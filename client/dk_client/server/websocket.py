"""WebSocket handler for real-time Digital Key updates."""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from dk_client.ble import DkBleClient, scan

logger = logging.getLogger(__name__)

DK_SERVER_URL = os.environ.get("DK_SERVER_URL", "http://localhost:8100")


async def report_event(vehicle_addr: str, key_id: str, event: str, detail: str = ""):
    """Fire-and-forget event report to dk-server. Failures are silently ignored."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{DK_SERVER_URL}/api/events", json={
                "vehicle": vehicle_addr,
                "key_id": key_id,
                "event": event,
                "detail": detail,
            })
    except Exception:
        pass


async def fetch_registered_vehicles(owner: str = "", account: str = "") -> list[dict]:
    """Fetch registered vehicles from dk-server. Returns empty list on failure."""
    try:
        params = {}
        if owner:
            params["owner"] = owner
        if account:
            params["account"] = account
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{DK_SERVER_URL}/api/vehicles", params=params)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return []


def _find_key_for_vehicle(address: str, vehicles: list[dict],
                           account: str = "") -> tuple[str | None, str | None]:
    """Find a key_id bound to the vehicle for the given account.

    Returns (key_id, vehicle_id) or (None, None).
    If account is given, only keys belonging to that account are considered.
    Falls back to local PEM discovery if no account match.
    """
    from dk_client.crypto import get_key_dir

    key_dir = get_key_dir()
    addr_upper = address.upper()

    for v in vehicles:
        if v.get("ble_address", "").upper() == addr_upper:
            vid = v.get("id", "")
            # Prefer account-matched keys (cloud keys)
            if account:
                for k in v.get("keys", []):
                    kid = k.get("key_id", "")
                    if kid and k.get("account") == account:
                        return kid, vid
            # Fallback: local PEM keys
            for k in v.get("keys", []):
                kid = k.get("key_id", "")
                if kid and (key_dir / f"{kid}.pem").exists():
                    return kid, vid
    return None, None


def _get_device_pubkey(address: str, vehicles: list[dict]) -> str | None:
    """Look up stored device_public_key for a vehicle by BLE address."""
    addr_upper = address.upper()
    for v in vehicles:
        if v.get("ble_address", "").upper() == addr_upper:
            return v.get("device_public_key") or None
    return None


async def _store_device_pubkey(address: str, pubkey_hex: str,
                                vehicles: list[dict]) -> bool:
    """Store device pubkey via dk-server PATCH /api/vehicles/{id}."""
    addr_upper = address.upper()
    vehicle_id = None
    for v in vehicles:
        if v.get("ble_address", "").upper() == addr_upper:
            vehicle_id = v.get("id")
            break
    if not vehicle_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.patch(
                f"{DK_SERVER_URL}/api/vehicles/{vehicle_id}",
                json={"device_public_key": pubkey_hex},
            )
            return resp.status_code == 200
    except Exception:
        return False


from dk_client.crypto import (
    load_or_create_key, get_public_key_bytes, sign_challenge,
    verify_device_signature,
)


async def _fetch_private_key(vehicle_id: str, key_id: str):
    """Download private key PEM from dk-server and return a loaded EC private key."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{DK_SERVER_URL}/api/vehicles/{vehicle_id}/keys/{key_id}/private")
            if resp.status_code == 200:
                data = resp.json()
                pem = data.get("private_key", "")
                if pem:
                    return load_pem_private_key(pem.encode(), password=None)
    except Exception as e:
        logger.warning("Failed to fetch private key from server: %s", e)
    return None
from dk_client.protocol import (
    AUTH_NAMES,
    CHR_AUTH_STATE,
    CHR_CHALLENGE,
    CHR_DEVICE_AUTH,
    CHR_DEVICE_PUBKEY,
    CHR_KEY_MGMT,
    CHR_PROVISION,
    CHR_RESPONSE,
    CHR_SYSTEM_STATUS,
    KEY_MGMT_APPROVE,
    KEY_MGMT_DELETE,
    LOCK_NAMES,
    SystemStatus,
    ZONE_NAMES,
)

router = APIRouter()

# Connected WebSocket clients: client_id -> (WebSocket, owner_name)
clients: dict[str, tuple[WebSocket, str]] = {}

# Shared BLE state
ble_client: Optional[DkBleClient] = None
scanned_devices: list[dict] = []
last_status: Optional[SystemStatus] = None


async def broadcast(message: dict):
    """Broadcast message to all connected clients."""
    if not clients:
        return
    text = json.dumps(message)
    disconnected = []
    for client_id, (ws, _owner) in clients.items():
        try:
            await ws.send_text(text)
        except Exception:
            disconnected.append(client_id)
    for client_id in disconnected:
        clients.pop(client_id, None)


async def send_to_client(client_id: str, message: dict):
    entry = clients.get(client_id)
    if entry:
        try:
            await entry[0].send_text(json.dumps(message))
        except Exception:
            pass


def get_client_owner(client_id: str) -> str:
    entry = clients.get(client_id)
    return entry[1] if entry else ""


async def broadcast_log(level: str, message: str):
    getattr(logger, level.lower(), logger.info)(message)
    await broadcast({
        "type": "log",
        "data": {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
        },
    })


async def broadcast_status():
    """Broadcast current connection and system status."""
    connected = ble_client is not None and ble_client.connected
    data = {"connected": connected}

    if connected and last_status:
        data["auth_state"] = AUTH_NAMES.get(last_status.auth_state, "?")
        data["auth_state_raw"] = last_status.auth_state
        data["zone"] = ZONE_NAMES.get(last_status.zone_level, "?")
        data["rssi"] = last_status.rssi
        data["lock_state"] = LOCK_NAMES.get(last_status.lock_state, "?")
        data["lock_state_raw"] = last_status.lock_state
        data["registered_keys"] = last_status.registered_keys
        data["pending_keys"] = last_status.pending_keys

    await broadcast({"type": "status", "data": data})


async def status_update_loop():
    """Background task to periodically broadcast status."""
    while True:
        try:
            if ble_client and ble_client.connected:
                await broadcast_status()
                await asyncio.sleep(0.5)
            else:
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(1.0)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Check session cookie before accepting
    from dk_client.server.app import validate_session, get_session_name, SESSION_COOKIE

    token = websocket.cookies.get(SESSION_COOKIE)
    if not token or not validate_session(token):
        await websocket.accept()
        await websocket.close(code=4401, reason="unauthorized")
        return

    session_owner = get_session_name(token)

    await websocket.accept()

    client_id = str(uuid.uuid4())[:8]
    clients[client_id] = (websocket, session_owner)

    # Subscribe to status notifications if already connected
    await _ensure_status_subscription()

    try:
        # Send initial state (filtered by logged-in user's account)
        reg_vehicles = await fetch_registered_vehicles(account=session_owner)
        await send_to_client(client_id, {
            "type": "init",
            "data": {
                "client_id": client_id,
                "devices": scanned_devices,
                "scanning": _scanning,
                "registered_vehicles": reg_vehicles,
            },
        })
        await broadcast_status()

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                await handle_ws_message(client_id, msg)
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        clients.pop(client_id, None)


async def _ensure_status_subscription():
    """Subscribe to system status notifications if connected."""
    global last_status
    if ble_client and ble_client.connected:
        try:
            def on_status(data: bytes):
                global last_status
                try:
                    last_status = SystemStatus.from_bytes(data)
                except Exception:
                    pass
            await ble_client.subscribe(CHR_SYSTEM_STATUS, on_status)
        except Exception:
            pass


_scanning = False


async def do_scan():
    """Run BLE scan and broadcast results."""
    global scanned_devices, _scanning
    if _scanning:
        return
    _scanning = True
    await broadcast({"type": "scan_state", "data": {"scanning": True}})
    await broadcast_log("INFO", "Scanning for DK devices...")
    try:
        devices = await scan(timeout=5.0)
        scanned_devices = [
            {"name": d.name, "address": d.address, "rssi": d.rssi}
            for d in devices
        ]
        await broadcast({
            "type": "scan_result",
            "data": scanned_devices,
        })
        await broadcast_log("INFO", f"Scan complete: {len(devices)} device(s) found")
    except Exception as e:
        logger.exception("BLE scan failed")
        await broadcast_log("ERROR", f"Scan failed: {e}")
    finally:
        _scanning = False
        await broadcast({"type": "scan_state", "data": {"scanning": False}})


async def handle_ws_message(client_id: str, msg: dict):
    global ble_client, scanned_devices, last_status

    msg_type = msg.get("type")
    data = msg.get("data", {})

    if msg_type == "scan":
        await do_scan()

    elif msg_type == "connect":
        address = data.get("address")
        if not address:
            await send_to_client(client_id, {
                "type": "error",
                "data": {"message": "Address required"},
            })
            return

        await _connect_and_auth(client_id, address)

    elif msg_type == "fetch_vehicles":
        owner = get_client_owner(client_id)
        vehicles = await fetch_registered_vehicles(account=owner)
        await send_to_client(client_id, {
            "type": "registered_vehicles",
            "data": vehicles,
        })

    elif msg_type == "disconnect":
        if ble_client and ble_client.connected:
            await ble_client.disconnect()
        last_status = None
        await broadcast_log("INFO", "Disconnected")
        await broadcast_status()

    elif msg_type == "approve":
        await _key_mgmt_command(client_id, data, KEY_MGMT_APPROVE, "approve")

    elif msg_type == "delete":
        await _key_mgmt_command(client_id, data, KEY_MGMT_DELETE, "delete")


async def _on_ble_disconnect():
    """Called when the remote device terminates the BLE connection."""
    global last_status
    last_status = None
    await broadcast_log("WARNING", "Device disconnected (remote)")
    await broadcast_status()


async def _broadcast_progress(step: str, status: str, detail: str = ""):
    """Broadcast connect/auth progress to all clients."""
    await broadcast({
        "type": "connect_progress",
        "data": {"step": step, "status": status, "detail": detail},
    })


async def _connect_and_auth(client_id: str, address: str):
    """Connect → Pair → Provision (if needed) → Auth → Subscribe status."""
    global ble_client, last_status

    # Step 1: Connect
    await _broadcast_progress("connect", "in_progress", address)
    try:
        if ble_client and ble_client.connected:
            await ble_client.disconnect()

        ble_client = DkBleClient(address)
        ble_client.set_on_disconnect(
            lambda: asyncio.ensure_future(_on_ble_disconnect())
        )
        success = await ble_client.connect()
        if not success:
            await _broadcast_progress("connect", "failed")
            await broadcast_log("ERROR", "Connection failed")
            await broadcast_status()
            return
    except Exception as e:
        await _broadcast_progress("connect", "failed", str(e))
        await broadcast_log("ERROR", f"Connection error: {e}")
        await broadcast_status()
        return

    await _broadcast_progress("connect", "done")
    await broadcast_log("INFO", f"Connected to {address}")
    await broadcast_status()

    # Step 2: Provision — only allowed if key is bound in dk-server
    session_owner = get_client_owner(client_id)
    reg_vehicles = await fetch_registered_vehicles()
    bound_key_id, vehicle_id = _find_key_for_vehicle(
        address, reg_vehicles, account=session_owner) if reg_vehicles else (None, None)

    if not bound_key_id:
        await _broadcast_progress("provision", "failed", "Not authorized")
        await broadcast_log("ERROR",
            "Key not registered in dk-server. "
            "Register vehicle and bind key first.")
        await ble_client.disconnect()
        await broadcast_status()
        return

    # Try to load private key from dk-server (cloud key)
    pk = None
    if vehicle_id:
        pk = await _fetch_private_key(vehicle_id, bound_key_id)
        if pk:
            await broadcast_log("INFO", f"Using cloud key: {bound_key_id}")

    # Fallback to local PEM
    if pk is None:
        bound_key_id, pk = load_or_create_key(key_id=bound_key_id)
        await broadcast_log("INFO", f"Using local key: {bound_key_id}")

    key_id = bound_key_id
    pubkey = get_public_key_bytes(pk)

    await _broadcast_progress("provision", "in_progress", key_id)
    try:
        key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
        await ble_client.write(CHR_PROVISION, key_id_bytes + pubkey)
        await _broadcast_progress("provision", "done", key_id)
        await broadcast_log("INFO", f"Provisioned key: {key_id}")
    except Exception as e:
        # Provision may fail if key already registered — continue to auth
        detail = "Key already registered" if "NotPermitted" in str(e) else str(e)
        await _broadcast_progress("provision", "skipped", detail)
        await broadcast_log("INFO", f"Provision skipped: {detail}")

    # Step 3: Authenticate
    await _broadcast_progress("auth", "in_progress")
    try:
        challenge = await ble_client.read(CHR_CHALLENGE)
        sig = sign_challenge(pk, challenge)
        key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
        await ble_client.write(CHR_RESPONSE, key_id_bytes + sig)

        state_bytes = await ble_client.read(CHR_AUTH_STATE)
        state = state_bytes[0]
        auth_name = AUTH_NAMES.get(state, "?")
        success = state == 3  # AUTH_OK

        if success:
            await _broadcast_progress("auth", "done", auth_name)
            await broadcast_log("INFO", f"Authenticated ({auth_name})")
            asyncio.ensure_future(report_event(address, key_id, "auth", "ok"))
        else:
            await _broadcast_progress("auth", "failed", auth_name)
            await broadcast_log("WARNING", f"Auth state: {auth_name}")
            asyncio.ensure_future(report_event(address, key_id, "auth", f"failed: {auth_name}"))

        await broadcast({"type": "auth_result", "data": {
            "success": success, "state": auth_name, "state_raw": state,
        }})
    except Exception as e:
        await _broadcast_progress("auth", "failed", str(e))
        await broadcast_log("ERROR", f"Auth failed: {e}")
        await broadcast({"type": "auth_result", "data": {
            "success": False, "error": str(e),
        }})

    # Step 3.5: Device Auth (mutual authentication)
    await _broadcast_progress("device_auth", "in_progress")
    try:
        device_pubkey = await ble_client.read(CHR_DEVICE_PUBKEY)

        # TOFU: compare with stored pubkey from dk-server
        expected_hex = _get_device_pubkey(address, reg_vehicles)
        if expected_hex:
            if device_pubkey.hex() != expected_hex:
                await _broadcast_progress("device_auth", "failed",
                                          "Pubkey mismatch — possible rogue device!")
                await broadcast_log("WARNING",
                                    "Device pubkey mismatch! Expected vs actual differ.")
            else:
                await broadcast_log("INFO", "Device pubkey verified (TOFU)")
        else:
            # First connection: store pubkey via dk-server
            stored = await _store_device_pubkey(address, device_pubkey.hex(),
                                                 reg_vehicles)
            if stored:
                await broadcast_log("INFO", "Device pubkey captured (TOFU first-use)")
            else:
                await broadcast_log("INFO", "Device pubkey noted (dk-server unavailable)")

        # Challenge-response
        challenge = os.urandom(32)
        await ble_client.write(CHR_DEVICE_AUTH, challenge)
        sig = await ble_client.read(CHR_DEVICE_AUTH)

        if verify_device_signature(device_pubkey, challenge, sig):
            await _broadcast_progress("device_auth", "done", "Device verified")
            await broadcast_log("INFO", "Device identity verified")
        else:
            await _broadcast_progress("device_auth", "failed", "Invalid signature")
            await broadcast_log("WARNING", "Device signature verification failed")
    except Exception as e:
        detail = str(e)
        if "not found" in detail.lower() or "Not Found" in detail:
            detail = "Characteristic not found (old firmware?)"
        await _broadcast_progress("device_auth", "skipped", detail)
        await broadcast_log("INFO", f"Device auth skipped: {detail}")

    # Step 4: Subscribe to status notifications
    await _broadcast_progress("subscribe", "in_progress")
    await _ensure_status_subscription()
    await _broadcast_progress("subscribe", "done")

    await broadcast_status()


async def _key_mgmt_command(client_id: str, data: dict, cmd: int, action: str):
    if not ble_client or not ble_client.connected:
        await send_to_client(client_id, {
            "type": "command_result",
            "data": {"action": action, "success": False, "error": "Not connected"},
        })
        return

    target_key_id = data.get("key_id", "")
    if not target_key_id:
        await send_to_client(client_id, {
            "type": "command_result",
            "data": {"action": action, "success": False, "error": "key_id required"},
        })
        return

    try:
        # Authenticate as owner first
        key_id, pk = load_or_create_key()
        challenge = await ble_client.read(CHR_CHALLENGE)
        sig = sign_challenge(pk, challenge)
        key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
        await ble_client.write(CHR_RESPONSE, key_id_bytes + sig)

        state_bytes = await ble_client.read(CHR_AUTH_STATE)
        if state_bytes[0] != 3:
            await broadcast_log("ERROR", f"Auth failed — only owner can {action}")
            await send_to_client(client_id, {
                "type": "command_result",
                "data": {"action": action, "success": False, "error": "Not owner"},
            })
            return

        target_id_bytes = target_key_id.encode("ascii").ljust(16, b"\x00")[:16]
        await ble_client.write(CHR_KEY_MGMT, bytes([cmd]) + target_id_bytes)
        await broadcast_log("INFO", f"Key {action}d: {target_key_id}")
        await send_to_client(client_id, {
            "type": "command_result",
            "data": {"action": action, "success": True, "key_id": target_key_id},
        })
    except Exception as e:
        await broadcast_log("ERROR", f"Key {action} failed: {e}")
        await send_to_client(client_id, {
            "type": "command_result",
            "data": {"action": action, "success": False, "error": str(e)},
        })
