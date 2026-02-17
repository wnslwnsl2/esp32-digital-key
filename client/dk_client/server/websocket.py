"""WebSocket handler for real-time Digital Key updates."""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from dk_client.ble import DkBleClient, scan

logger = logging.getLogger(__name__)
from dk_client.crypto import load_or_create_key, get_public_key_bytes, sign_challenge
from dk_client.protocol import (
    AUTH_NAMES,
    CHR_AUTH_STATE,
    CHR_CHALLENGE,
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

# Connected WebSocket clients: client_id -> WebSocket
clients: dict[str, WebSocket] = {}

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
    for client_id, ws in clients.items():
        try:
            await ws.send_text(text)
        except Exception:
            disconnected.append(client_id)
    for client_id in disconnected:
        clients.pop(client_id, None)


async def send_to_client(client_id: str, message: dict):
    ws = clients.get(client_id)
    if ws:
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            pass


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
    await websocket.accept()

    client_id = str(uuid.uuid4())[:8]
    clients[client_id] = websocket

    # Subscribe to status notifications if already connected
    await _ensure_status_subscription()

    try:
        # Send initial state
        await send_to_client(client_id, {
            "type": "init",
            "data": {
                "client_id": client_id,
                "devices": scanned_devices,
                "scanning": _scanning,
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

    # Step 2: Provision (if no local key exists)
    key_id, pk = load_or_create_key()
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
        else:
            await _broadcast_progress("auth", "failed", auth_name)
            await broadcast_log("WARNING", f"Auth state: {auth_name}")

        await broadcast({"type": "auth_result", "data": {
            "success": success, "state": auth_name, "state_raw": state,
        }})
    except Exception as e:
        await _broadcast_progress("auth", "failed", str(e))
        await broadcast_log("ERROR", f"Auth failed: {e}")
        await broadcast({"type": "auth_result", "data": {
            "success": False, "error": str(e),
        }})

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
