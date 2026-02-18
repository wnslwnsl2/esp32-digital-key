"""Digital Key Web UI server entry point."""

import getpass
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000

REG_HOST = "0.0.0.0"
REG_PORT = 8100


def _is_wsl() -> bool:
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


def _open_url(url: str):
    time.sleep(1.5)
    if _is_wsl():
        subprocess.Popen(
            ["cmd.exe", "/c", "start", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        webbrowser.open(url)


def main():
    """Entry point for dk-web command."""
    setup_logging()

    from dk_client.server.app import app

    threading.Thread(
        target=_open_url, args=(f"http://{HOST}:{PORT}",), daemon=True,
    ).start()

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
    )


def start_reg_server():
    """Entry point for dk-server command."""
    from dk_client.server.auth import is_pin_configured, setup_pin

    # Handle --reset-pin flag
    if "--reset-pin" in sys.argv:
        pin = getpass.getpass("New PIN: ")
        confirm = getpass.getpass("Confirm PIN: ")
        if pin != confirm:
            print("PINs do not match.")
            sys.exit(1)
        setup_pin(pin)
        print("PIN reset successfully.")
        sys.argv.remove("--reset-pin")

    # First-run PIN setup
    if not is_pin_configured():
        print("First run — set up a PIN for dk-server.")
        pin = getpass.getpass("Enter PIN: ")
        confirm = getpass.getpass("Confirm PIN: ")
        if pin != confirm:
            print("PINs do not match.")
            sys.exit(1)
        setup_pin(pin)
        print("PIN configured.")

    setup_logging()

    from dk_client.server.reg_app import app

    print(f"Digital Key Server running on http://{REG_HOST}:{REG_PORT}")
    uvicorn.run(
        app,
        host=REG_HOST,
        port=REG_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
