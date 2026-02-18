"""FastAPI application for dk-server (Key Management Server).

Internal backend — no auth middleware. PIN verification is exposed via
/api/login so that dk-web can proxy authentication here.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from dk_client.server.auth import (
    add_account,
    delete_account,
    get_accounts,
    verify_pin,
)


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


from dk_client.server.store import (
    _generate_keypair,
    add_key,
    add_vehicle,
    append_event,
    delete_key,
    delete_vehicle,
    get_events,
    get_key,
    get_keys_for_account,
    get_vehicle,
    list_local_keys,
    load_vehicles,
    update_vehicle,
)

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Digital Key Server", version="0.1.0")
app.add_middleware(NoCacheMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Pages ---

@app.get("/")
async def dashboard_page():
    return FileResponse(STATIC_DIR / "dashboard.html")


# --- Auth API (PIN verification only, no session) ---

@app.post("/api/login")
async def api_login(request: Request):
    body = await request.json()
    pin = body.get("pin", "")
    name = verify_pin(pin)
    if name is None:
        return JSONResponse({"error": "invalid PIN"}, status_code=403)
    return JSONResponse({"ok": True, "name": name})


# --- Account API ---

@app.get("/api/accounts")
async def api_accounts():
    return get_accounts()


@app.post("/api/accounts")
async def api_add_account(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    pin = body.get("pin", "").strip()
    if not name or not pin:
        return JSONResponse({"error": "name and pin required"}, status_code=400)
    add_account(pin, name)
    return {"ok": True}


@app.delete("/api/accounts/{name}")
async def api_delete_account(name: str):
    if not delete_account(name):
        return JSONResponse({"error": "account not found"}, status_code=404)
    return {"ok": True}


# --- Vehicles API ---

@app.get("/api/vehicles")
async def api_get_vehicles(owner: str = "", account: str = ""):
    vehicles = load_vehicles()
    if owner:
        vehicles = [v for v in vehicles if v.get("owner", "") == owner]
    if account:
        # Filter to vehicles where this account has at least one key
        vehicles = [v for v in vehicles
                    if any(k.get("account") == account for k in v.get("keys", []))]
    return vehicles


@app.post("/api/vehicles")
async def api_add_vehicle(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    ble_address = body.get("ble_address", "").strip()
    if not name or not ble_address:
        return JSONResponse({"error": "name and ble_address required"}, status_code=400)
    vehicle = add_vehicle(name, ble_address)
    return vehicle


@app.delete("/api/vehicles/{vehicle_id}")
async def api_delete_vehicle(vehicle_id: str):
    delete_vehicle(vehicle_id)
    return {"ok": True}


@app.patch("/api/vehicles/{vehicle_id}")
async def api_update_vehicle(vehicle_id: str, request: Request):
    body = await request.json()
    try:
        update_vehicle(vehicle_id, body)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return {"ok": True}


# --- Keys API ---

@app.post("/api/vehicles/{vehicle_id}/keys")
async def api_add_key(vehicle_id: str, request: Request):
    body = await request.json()
    account = body.get("account", "").strip()
    role = body.get("role", "user").strip()
    expires_at = body.get("expires_at", "").strip() or None
    if not account:
        return JSONResponse({"error": "account required"}, status_code=400)

    # Auto-generate keypair
    key_id, public_key, private_key = _generate_keypair()
    try:
        add_key(vehicle_id, key_id, public_key, role,
                account=account, private_key=private_key, expires_at=expires_at)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "key_id": key_id}


@app.get("/api/vehicles/{vehicle_id}/keys/{key_id}/private")
async def api_get_private_key(vehicle_id: str, key_id: str):
    """Return private key PEM for dk-web to download."""
    k = get_key(vehicle_id, key_id)
    if not k:
        return JSONResponse({"error": "key not found"}, status_code=404)
    pem = k.get("private_key", "")
    if not pem:
        return JSONResponse({"error": "no private key"}, status_code=404)
    return {"key_id": key_id, "private_key": pem, "public_key": k.get("public_key", "")}


@app.delete("/api/vehicles/{vehicle_id}/keys/{key_id}")
async def api_delete_key(vehicle_id: str, key_id: str):
    try:
        delete_key(vehicle_id, key_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True}


# --- Provision API (ESP32 calls this via WiFi) ---

@app.get("/api/provision/{ble_address}")
async def api_provision(ble_address: str):
    """Return approved public keys for a vehicle identified by BLE address."""
    addr_upper = ble_address.upper()
    for v in load_vehicles():
        if v.get("ble_address", "").upper() == addr_upper:
            keys = []
            for k in v.get("keys", []):
                keys.append({
                    "key_id": k["key_id"],
                    "public_key": k.get("public_key", ""),
                })
            return {"vehicle_id": v["id"], "keys": keys}
    return {"vehicle_id": None, "keys": []}


# --- Share API ---

@app.post("/api/vehicles/{vehicle_id}/share")
async def api_share_vehicle(vehicle_id: str, request: Request):
    """Share a vehicle by creating a new key for another account."""
    body = await request.json()
    account = body.get("account", "").strip()
    role = body.get("role", "family").strip()
    expires_at = body.get("expires_at", "").strip() or None
    if not account:
        return JSONResponse({"error": "account required"}, status_code=400)

    key_id, public_key, private_key = _generate_keypair()
    try:
        add_key(vehicle_id, key_id, public_key, role,
                account=account, private_key=private_key, expires_at=expires_at)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "key_id": key_id}


# --- Account keys API ---

@app.get("/api/accounts/{name}/keys")
async def api_account_keys(name: str):
    """Get all keys belonging to an account across all vehicles."""
    return get_keys_for_account(name)


# --- Events API ---

@app.get("/api/events")
async def api_get_events(limit: int = 50):
    return get_events(limit=limit)


@app.post("/api/events")
async def api_post_event(request: Request):
    body = await request.json()
    vehicle = body.get("vehicle", "")
    key_id = body.get("key_id", "")
    event = body.get("event", "")
    detail = body.get("detail", "")
    if not event:
        return JSONResponse({"error": "event required"}, status_code=400)
    append_event(vehicle, key_id, event, detail)
    return {"ok": True}


# --- Local keys API ---

@app.get("/api/local-keys")
async def api_local_keys():
    return list_local_keys()
