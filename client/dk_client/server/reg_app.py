"""FastAPI application for dk-server (Key Management Server).

Internal backend — no auth middleware. PIN verification is exposed via
/api/login so that dk-web can proxy authentication here.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dk_client.server.auth import verify_pin
from dk_client.server.store import (
    add_key,
    add_vehicle,
    append_event,
    delete_key,
    delete_vehicle,
    get_events,
    list_local_keys,
    load_vehicles,
    update_vehicle,
)

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Digital Key Server", version="0.1.0")
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
    if not verify_pin(pin):
        return JSONResponse({"error": "invalid PIN"}, status_code=403)
    return JSONResponse({"ok": True})


# --- Vehicles API ---

@app.get("/api/vehicles")
async def api_get_vehicles():
    return load_vehicles()


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
    key_id = body.get("key_id", "").strip()
    public_key = body.get("public_key", "").strip()
    role = body.get("role", "user").strip()
    if not key_id:
        return JSONResponse({"error": "key_id required"}, status_code=400)
    try:
        add_key(vehicle_id, key_id, public_key, role)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True}


@app.delete("/api/vehicles/{vehicle_id}/keys/{key_id}")
async def api_delete_key(vehicle_id: str, key_id: str):
    try:
        delete_key(vehicle_id, key_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True}


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
