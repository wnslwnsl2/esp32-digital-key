"""JSON file storage for vehicles, key bindings, and event logs."""

import json
import uuid
from datetime import datetime
from pathlib import Path

DATA_DIR = Path.home() / ".dk-client"
VEHICLES_FILE = DATA_DIR / "vehicles.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# --- Vehicles ---

def load_vehicles() -> list[dict]:
    if not VEHICLES_FILE.exists():
        return []
    return json.loads(VEHICLES_FILE.read_text())


def save_vehicles(vehicles: list[dict]):
    _ensure_dir()
    VEHICLES_FILE.write_text(json.dumps(vehicles, indent=2, ensure_ascii=False))


def add_vehicle(name: str, ble_address: str) -> dict:
    vehicles = load_vehicles()
    vehicle = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "ble_address": ble_address,
        "created_at": datetime.now().isoformat(),
        "keys": [],
    }
    vehicles.append(vehicle)
    save_vehicles(vehicles)
    return vehicle


def delete_vehicle(vehicle_id: str):
    vehicles = load_vehicles()
    vehicles = [v for v in vehicles if v["id"] != vehicle_id]
    save_vehicles(vehicles)


def get_vehicle(vehicle_id: str) -> dict | None:
    for v in load_vehicles():
        if v["id"] == vehicle_id:
            return v
    return None


def update_vehicle(vehicle_id: str, fields: dict):
    """Partially update a vehicle record (e.g. device_public_key)."""
    vehicles = load_vehicles()
    for v in vehicles:
        if v["id"] == vehicle_id:
            v.update(fields)
            save_vehicles(vehicles)
            return
    raise ValueError(f"Vehicle {vehicle_id} not found")


# --- Keys ---

def add_key(vehicle_id: str, key_id: str, public_key: str, role: str):
    vehicles = load_vehicles()
    for v in vehicles:
        if v["id"] == vehicle_id:
            # Avoid duplicate key_id
            if any(k["key_id"] == key_id for k in v["keys"]):
                raise ValueError(f"Key {key_id} already bound to this vehicle")
            v["keys"].append({
                "key_id": key_id,
                "public_key": public_key,
                "role": role,
                "created_at": datetime.now().isoformat(),
            })
            save_vehicles(vehicles)
            return
    raise ValueError(f"Vehicle {vehicle_id} not found")


def delete_key(vehicle_id: str, key_id: str):
    vehicles = load_vehicles()
    for v in vehicles:
        if v["id"] == vehicle_id:
            v["keys"] = [k for k in v["keys"] if k["key_id"] != key_id]
            save_vehicles(vehicles)
            return
    raise ValueError(f"Vehicle {vehicle_id} not found")


# --- Events ---

def append_event(vehicle_addr: str, key_id: str, event: str, detail: str = ""):
    _ensure_dir()
    entry = {
        "ts": datetime.now().isoformat(),
        "vehicle": vehicle_addr,
        "key_id": key_id,
        "event": event,
        "detail": detail,
    }
    with open(EVENTS_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_events(limit: int = 50) -> list[dict]:
    """Read the last `limit` events (most recent first)."""
    if not EVENTS_FILE.exists():
        return []
    lines = EVENTS_FILE.read_text().strip().splitlines()
    tail = lines[-limit:] if len(lines) > limit else lines
    events = []
    for line in reversed(tail):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


# --- Local keys discovery ---

def list_local_keys() -> list[dict]:
    """List key files in ~/.dk-client/ for easy binding."""
    keys = []
    for pem in sorted(DATA_DIR.glob("*.pem")):
        keys.append({"key_id": pem.stem, "path": str(pem)})
    return keys
