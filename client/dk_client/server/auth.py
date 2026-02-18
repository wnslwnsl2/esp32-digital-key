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


def _load_accounts() -> list[dict]:
    """Load accounts list (handles legacy single-object format)."""
    if not PIN_FILE.exists():
        return []
    raw = json.loads(PIN_FILE.read_text())
    if isinstance(raw, dict):
        return [raw]
    return raw


def _save_accounts(accounts: list[dict]):
    _ensure_dir()
    PIN_FILE.write_text(json.dumps(accounts, indent=2, ensure_ascii=False))


def is_pin_configured() -> bool:
    return len(_load_accounts()) > 0


def add_account(pin: str, name: str):
    """Add a new account with PIN and name."""
    accounts = _load_accounts()
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + pin).encode()).hexdigest()
    accounts.append({"salt": salt, "hash": h, "name": name})
    _save_accounts(accounts)


def setup_pin(pin: str, name: str = ""):
    """Reset all accounts and create a single account."""
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + pin).encode()).hexdigest()
    _save_accounts([{"salt": salt, "hash": h, "name": name}])


def verify_pin(pin: str) -> str | None:
    """Verify PIN against all accounts. Returns name on success, None on failure."""
    for account in _load_accounts():
        h = hashlib.sha256((account["salt"] + pin).encode()).hexdigest()
        if secrets.compare_digest(h, account["hash"]):
            return account.get("name", "")
    return None


def get_accounts() -> list[dict]:
    """Return account list (name only, no secrets)."""
    return [{"name": a.get("name", "")} for a in _load_accounts()]


def delete_account(name: str) -> bool:
    """Delete account by name. Returns True if found and deleted."""
    accounts = _load_accounts()
    filtered = [a for a in accounts if a.get("name", "") != name]
    if len(filtered) == len(accounts):
        return False
    _save_accounts(filtered)
    return True


def create_session() -> str:
    token = secrets.token_hex(32)
    _sessions.add(token)
    return token


def validate_session(token: str) -> bool:
    return token in _sessions


def remove_session(token: str):
    _sessions.discard(token)
