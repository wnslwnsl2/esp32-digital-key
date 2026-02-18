"""Digital Key Web UI server entry point."""

import logging
import socket
import subprocess
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


MDNS_SERVICE_NAME = "dk-server"
MDNS_SERVICE_TYPE = "_dk._tcp.local."


def _start_mdns():
    """Advertise dk-server via mDNS so ESP32 can find it as dk-server.local."""
    try:
        from zeroconf import ServiceInfo, Zeroconf

        ip = _get_local_ip()
        info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            f"{MDNS_SERVICE_NAME}.{MDNS_SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=REG_PORT,
            properties={"path": "/api/"},
            server=f"{MDNS_SERVICE_NAME}.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        logging.getLogger(__name__).info(
            "mDNS: advertising %s.local → %s:%d", MDNS_SERVICE_NAME, ip, REG_PORT)
        return zc, info
    except Exception as e:
        logging.getLogger(__name__).warning("mDNS failed: %s", e)
        return None, None


def _get_local_ip() -> str:
    """Best-effort local IP detection."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


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
    setup_logging()

    # Advertise via mDNS (dk-server.local)
    _start_mdns()

    from dk_client.server.reg_app import app

    local_ip = _get_local_ip()
    print(f"Digital Key Server running on http://{REG_HOST}:{REG_PORT}")
    print(f"  LAN:  http://{local_ip}:{REG_PORT}")
    print(f"  mDNS: http://dk-server.local:{REG_PORT}")
    uvicorn.run(
        app,
        host=REG_HOST,
        port=REG_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
