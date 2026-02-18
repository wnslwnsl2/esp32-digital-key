"""FastAPI application for dk-server (Key Management Server)."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from dk_client.server.auth import (
    create_session,
    remove_session,
    validate_session,
    verify_pin,
)
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

SESSION_COOKIE = "dk_session"

# Paths that don't require authentication
PUBLIC_PATHS = {"/login", "/api/login", "/api/events"}
PUBLIC_PREFIXES = ("/static/", "/api/vehicles/")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE)
        if not token or not validate_session(token):
            if path.startswith("/api/"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse("/login")

        return await call_next(request)


app = FastAPI(title="Digital Key Server", version="0.1.0")
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Pages ---

@app.get("/")
async def dashboard_page():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/login")
async def login_page():
    return FileResponse(STATIC_DIR / "login.html")


# --- Auth API ---

@app.post("/api/login")
async def api_login(request: Request):
    body = await request.json()
    pin = body.get("pin", "")
    if not verify_pin(pin):
        return JSONResponse({"error": "invalid PIN"}, status_code=403)
    token = create_session()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return resp


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        remove_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


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
