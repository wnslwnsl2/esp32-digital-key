"""Digital Key Web UI server entry point."""

import logging
import os
import subprocess
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


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


def open_browser():
    time.sleep(1.5)
    url = f"http://{HOST}:{PORT}"
    if _is_wsl():
        # WSL2: open Windows default browser via cmd.exe
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

    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
