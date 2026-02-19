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
    """
    from dk_client.crypto import get_key_dir

    key_dir = get_key_dir()
    addr_upper = address.upper()

    for v in vehicles:
        if v.get("ble_address", "").upper() == addr_upper:
            vid = v.get("id", "")
            if account:
                for k in v.get("keys", []):
                    kid = k.get("key_id", "")
                    if kid and k.get("account") == account:
                        return kid, vid
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



from dk_client.crypto import (
    get_public_key_bytes,
    load_or_create_key,
    sign_challenge,
    verify_device_signature,
)


async def _register_public_key(vehicle_id: str, key_id: str, pubkey_hex: str) -> bool:
    """Register a client-generated public key with dk-server (write-once)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(
                f"{DK_SERVER_URL}/api/vehicles/{vehicle_id}/keys/{key_id}/pubkey",
                json={"public_key": pubkey_hex})
            return resp.status_code == 200
    except Exception as e:
        logger.warning("Failed to register public key: %s", e)
    return False


async def _key_needs_registration(vehicle_id: str, key_id: str) -> bool:
    """Check if a key_id has no public_key registered on dk-server."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{DK_SERVER_URL}/api/vehicles")
            if resp.status_code == 200:
                for v in resp.json():
                    if v.get("id") == vehicle_id:
                        for k in v.get("keys", []):
                            if k.get("key_id") == key_id:
                                return not k.get("public_key")
    except Exception as e:
        logger.warning("Failed to check key registration: %s", e)
    return False

from dk_client.protocol import (
    AUTH_NAMES,
    CHR_AUTH_STATE,
    CHR_CHALLENGE,
    CHR_DEVICE_AUTH,
    CHR_DEVICE_PUBKEY,
    CHR_KEY_MGMT,
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
last_status: Optional[SystemStatus] = None

# Auto-scan task
_auto_scan_task: Optional[asyncio.Task] = None


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


# ---------------------------------------------------------------------------
# Auto-scan: continuously scan and auto-connect to registered vehicles
# ---------------------------------------------------------------------------

async def _start_auto_scan():
    """Start auto-scan background task if not already running."""
    global _auto_scan_task
    if _auto_scan_task and not _auto_scan_task.done():
        return
    _auto_scan_task = asyncio.create_task(_auto_scan_loop())


async def _stop_auto_scan():
    """Stop auto-scan background task."""
    global _auto_scan_task
    if _auto_scan_task and not _auto_scan_task.done():
        _auto_scan_task.cancel()
        try:
            await _auto_scan_task
        except asyncio.CancelledError:
            pass
    _auto_scan_task = None


async def _auto_scan_loop():
    """Continuously scan for registered vehicles and auto-connect."""
    while True:
        try:
            # Already connected — just wait
            if ble_client and ble_client.connected:
                await asyncio.sleep(5.0)
                continue

            # No WebSocket clients — wait
            if not clients:
                await asyncio.sleep(2.0)
                continue

            # Get first client's account
            first_client_id = None
            account = ""
            for cid, (_, owner) in clients.items():
                first_client_id = cid
                account = owner
                break

            # Fetch registered vehicles for this account
            reg_vehicles = await fetch_registered_vehicles(account=account)
            target_map: dict[str, dict] = {}
            for v in reg_vehicles:
                addr = (v.get("ble_address") or "").upper()
                if addr:
                    target_map[addr] = v

            if not target_map:
                await broadcast({"type": "auto_scan", "data": {
                    "state": "no_vehicles",
                }})
                return  # Stop scanning — no vehicles to look for

            # Broadcast scanning state with target vehicle names
            vehicle_names = [v.get("name", "?") for v in target_map.values()]
            await broadcast({"type": "auto_scan", "data": {
                "state": "scanning",
                "vehicles": vehicle_names,
            }})

            # BLE scan
            try:
                found = await scan(timeout=5.0)
            except Exception as e:
                await broadcast({"type": "auto_scan", "data": {
                    "state": "scan_error",
                    "error": str(e),
                }})
                await asyncio.sleep(5.0)
                continue

            # Check for matching device
            matched = None
            for d in found:
                if d.address.upper() in target_map:
                    matched = d
                    break

            if matched:
                v = target_map[matched.address.upper()]
                await broadcast({"type": "auto_scan", "data": {
                    "state": "found",
                    "vehicle": v.get("name", matched.address),
                    "rssi": matched.rssi,
                }})
                await _connect_and_auth(first_client_id, matched.address)
                # After connect (success or fail), loop continues
            else:
                await broadcast({"type": "auto_scan", "data": {
                    "state": "not_found",
                    "scan_count": len(found),
                }})
                await asyncio.sleep(3.0)

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Auto-scan error")
            await asyncio.sleep(5.0)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
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

    # Start auto-scan (idempotent — only one task runs)
    await _start_auto_scan()

    try:
        # Send initial state with vehicle info
        reg_vehicles = await fetch_registered_vehicles(account=session_owner)
        await send_to_client(client_id, {
            "type": "init",
            "data": {
                "client_id": client_id,
                "account": session_owner,
                "vehicles": reg_vehicles,
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

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        clients.pop(client_id, None)
        if not clients:
            await _stop_auto_scan()


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


async def handle_ws_message(client_id: str, msg: dict):
    global ble_client, last_status

    msg_type = msg.get("type")
    data = msg.get("data", {})

    if msg_type == "disconnect":
        if ble_client and ble_client.connected:
            await ble_client.disconnect()
        last_status = None
        await broadcast_log("INFO", "Disconnected")
        await broadcast_status()
        # Restart auto-scan
        await _start_auto_scan()

    elif msg_type == "approve":
        await _key_mgmt_command(client_id, data, KEY_MGMT_APPROVE, "approve")

    elif msg_type == "delete":
        await _key_mgmt_command(client_id, data, KEY_MGMT_DELETE, "delete")


async def _on_ble_disconnect():
    """Called when the remote device terminates the BLE connection."""
    global last_status
    last_status = None
    await broadcast_log("WARNING", "Device disconnected")
    await broadcast_status()
    # Restart auto-scan to reconnect
    await _start_auto_scan()


async def _broadcast_progress(step: str, status: str, detail: str = ""):
    """Broadcast connect/auth progress to all clients."""
    await broadcast({
        "type": "connect_progress",
        "data": {"step": step, "status": status, "detail": detail},
    })


async def _connect_and_auth(client_id: str, address: str):
    """Connect -> Load key -> Auth -> Subscribe status."""
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

    # Step 2: Load/create key locally
    session_owner = get_client_owner(client_id)
    reg_vehicles = await fetch_registered_vehicles()
    bound_key_id, vehicle_id = _find_key_for_vehicle(
        address, reg_vehicles, account=session_owner) if reg_vehicles else (None, None)

    if not bound_key_id:
        await _broadcast_progress("auth", "failed", "Not authorized")
        await broadcast_log("ERROR",
            "Key not registered in dk-server. "
            "Register vehicle and bind key first.")
        await ble_client.disconnect()
        await broadcast_status()
        return

    # Always use local key (generate if not exists)
    key_id, pk = load_or_create_key(key_id=bound_key_id)
    await broadcast_log("INFO", f"Using local key: {key_id}")

    # Register pubkey with server if needed
    just_registered = False
    if vehicle_id and await _key_needs_registration(vehicle_id, key_id):
        await _broadcast_progress("key_register", "in_progress")
        pubkey_hex = get_public_key_bytes(pk).hex()
        ok = await _register_public_key(vehicle_id, key_id, pubkey_hex)
        if ok:
            just_registered = True
            await _broadcast_progress("key_register", "done", "Public key registered")
            await broadcast_log("INFO", "Public key registered with server")
        else:
            await _broadcast_progress("key_register", "failed", "Registration failed")
            await broadcast_log("ERROR", "Failed to register public key")
            await ble_client.disconnect()
            await broadcast_status()
            return

    # Step 3: Authenticate (with retry for freshly registered keys)
    await _broadcast_progress("auth", "in_progress")
    max_attempts = 3 if just_registered else 1
    auth_success = False
    state = 0
    auth_name = "FAILED"

    for attempt in range(max_attempts):
        try:
            challenge = await ble_client.read(CHR_CHALLENGE)
            sig = sign_challenge(pk, challenge)
            key_id_bytes = key_id.encode("ascii").ljust(16, b"\x00")[:16]
            await ble_client.write(CHR_RESPONSE, key_id_bytes + sig)

            state_bytes = await ble_client.read(CHR_AUTH_STATE)
            state = state_bytes[0]
            auth_name = AUTH_NAMES.get(state, "?")
            auth_success = state == 3  # AUTH_OK

            if auth_success:
                await _broadcast_progress("auth", "done", auth_name)
                await broadcast_log("INFO", f"Authenticated ({auth_name})")
                asyncio.ensure_future(report_event(address, key_id, "auth", "ok"))
                break
            elif just_registered and attempt < max_attempts - 1:
                await broadcast_log("INFO",
                    f"Waiting for ESP32 key sync (attempt {attempt + 1}/{max_attempts})...")
                await asyncio.sleep(3.0)
            else:
                await _broadcast_progress("auth", "failed", auth_name)
                await broadcast_log("WARNING", f"Auth state: {auth_name}")
                asyncio.ensure_future(report_event(address, key_id, "auth", f"failed: {auth_name}"))
        except Exception as e:
            await _broadcast_progress("auth", "failed", str(e))
            await broadcast_log("ERROR", f"Auth failed: {e}")
            auth_success = False
            break

    await broadcast({"type": "auth_result", "data": {
        "success": auth_success,
        "state": auth_name,
        "state_raw": state,
    }})

    # Step 3.5: Device Auth (mutual authentication)
    # Device pubkey is pre-registered by ESP32 via WiFi (no TOFU)
    await _broadcast_progress("device_auth", "in_progress")
    try:
        expected_hex = _get_device_pubkey(address, reg_vehicles)
        if not expected_hex:
            await _broadcast_progress("device_auth", "skipped",
                                      "Device pubkey not registered on server")
            await broadcast_log("WARNING",
                                "Device pubkey not found on dk-server. "
                                "Is ESP32 WiFi connected?")
        else:
            device_pubkey = await ble_client.read(CHR_DEVICE_PUBKEY)

            if device_pubkey.hex() != expected_hex:
                await _broadcast_progress("device_auth", "failed",
                                          "Pubkey mismatch — possible rogue device!")
                await broadcast_log("WARNING",
                                    "Device pubkey mismatch! BLE key differs from server.")
            else:
                await broadcast_log("INFO", "Device pubkey verified")

                # Challenge-response
                challenge = os.urandom(32)
                await ble_client.write(CHR_DEVICE_AUTH, challenge)
                sig = await ble_client.read(CHR_DEVICE_AUTH)

                if verify_device_signature(bytes(device_pubkey), challenge, bytes(sig)):
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
