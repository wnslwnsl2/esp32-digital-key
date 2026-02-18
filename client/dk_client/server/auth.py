"""PIN authentication and session management for dk-server."""

import hashlib
import json
import os
import secrets
from pathlib import Path


PIN_FILE = Path.home() / ".dk-client" / "pin.json"

# In-memory session store
_sessions: set[str] = set()


def _ensure_dir():
    PIN_FILE.parent.mkdir(parents=True, exist_ok=True)


def is_pin_configured() -> bool:
    return PIN_FILE.exists()


def setup_pin(pin: str):
    """Hash PIN with random salt and save to file."""
    _ensure_dir()
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + pin).encode()).hexdigest()
    PIN_FILE.write_text(json.dumps({"salt": salt, "hash": h}))


def verify_pin(pin: str) -> bool:
    if not PIN_FILE.exists():
        return False
    data = json.loads(PIN_FILE.read_text())
    h = hashlib.sha256((data["salt"] + pin).encode()).hexdigest()
    return secrets.compare_digest(h, data["hash"])


def create_session() -> str:
    token = secrets.token_hex(32)
    _sessions.add(token)
    return token


def validate_session(token: str) -> bool:
    return token in _sessions


def remove_session(token: str):
    _sessions.discard(token)
