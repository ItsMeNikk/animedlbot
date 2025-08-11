import subprocess
import time
import sys
import shutil
import os

# No longer need to modify sys.path

# The import is now simpler because bot.py is in the same directory
from bot import main as start_bot

def main():
    """
    A launcher script that starts the aria2c daemon and then the Telegram bot.
    It ensures aria2c is terminated when the bot script is stopped.
    """
    if not shutil.which("aria2c"):
        print("Error: aria2c is not installed or not in your system's PATH.")
        print("Please install it from https://aria2.github.io/ and try again.")
        sys.exit(1)

    # Corrected the download directory path
    aria_command = [
        "aria2c",
        "--enable-rpc",
        "--rpc-listen-all=true",
        "--rpc-allow-origin-all",
        "--dir=downloads", # Corrected path
        "--continue=true",
        "--log=aria2.log", # Corrected path
        "--log-level=warn"
    ]

    print("Starting aria2c daemon in the background...")
    
    aria_process = subprocess.Popen(
        aria_command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE
    )
    
    time.sleep(2)

    if aria_process.poll() is not None:
        print("Error: aria2c failed to start. It might already be running, or the configuration is wrong.")
        stderr_output = aria_process.stderr.read().decode('utf-8')
        if stderr_output:
            print(f"Aria2c error output:\n{stderr_output}")
        print("Check the 'aria2.log' file for more details.")
        sys.exit(1)

    print(f"✅ Aria2c daemon is running with PID: {aria_process.pid}")

    try:
        print("Starting Telegram bot...")
        start_bot()
    except Exception as e:
        print(f"An error occurred with the Telegram bot: {e}")
    finally:
        print("\nStopping Telegram bot and aria2c daemon...")
        aria_process.terminate()
        aria_process.wait()
        print("✅ All processes have been stopped gracefully.")

if __name__ == "__main__":
    main()