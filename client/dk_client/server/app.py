"""FastAPI application."""

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from dk_client.server.websocket import router as ws_router, status_update_loop, do_scan

logger = logging.getLogger(__name__)

DK_SERVER_URL = os.environ.get("DK_SERVER_URL", "http://localhost:8100")

SESSION_COOKIE = "dk_web_session"

# In-memory session store: token -> account name
_sessions: dict[str, str] = {}

# Paths that don't require authentication
PUBLIC_PATHS = {"/login", "/api/login"}
PUBLIC_PREFIXES = ("/static/",)


def validate_session(token: str) -> bool:
    return token in _sessions


def get_session_name(token: str) -> str:
    """Return account name for a session token, or empty string."""
    return _sessions.get(token, "")


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to /login."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE)
        if not token or not validate_session(token):
            if path.startswith("/api/") or path == "/ws":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse("/login")

        return await call_next(request)


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Disable caching for static files during development."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


STATIC_DIR = Path(__file__).parent.parent / "static"

_status_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _status_task

    print("Digital Key Web UI starting...")
    _status_task = asyncio.create_task(status_update_loop())
    asyncio.create_task(do_scan())

    yield

    print("Digital Key Web UI shutting down...")
    if _status_task:
        _status_task.cancel()
        try:
            await _status_task
        except asyncio.CancelledError:
            pass

    # Disconnect BLE on shutdown
    from dk_client.server.websocket import ble_client
    if ble_client and ble_client.connected:
        await ble_client.disconnect()


app = FastAPI(
    title="Digital Key",
    description="ESP32-S3 Digital Key Web UI",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(NoCacheMiddleware)
app.add_middleware(AuthMiddleware)
app.include_router(ws_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login")
async def login_page():
    return FileResponse(STATIC_DIR / "login-web.html")


@app.post("/api/login")
async def api_login(request: Request):
    body = await request.json()
    pin = body.get("pin", "")
    if not pin:
        return JSONResponse({"error": "PIN required"}, status_code=400)

    # Proxy to dk-server
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{DK_SERVER_URL}/api/login",
                json={"pin": pin},
            )
        if resp.status_code == 200:
            token = secrets.token_hex(32)
            name = resp.json().get("name", "")
            _sessions[token] = name
            response = JSONResponse({"ok": True, "name": name})
            response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
            return response
        else:
            return JSONResponse({"error": "invalid PIN"}, status_code=403)
    except httpx.ConnectError:
        logger.warning("dk-server unavailable at %s", DK_SERVER_URL)
        return JSONResponse({"error": "Server unavailable"}, status_code=502)
    except Exception as e:
        logger.exception("Login proxy error")
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/logout")
async def api_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _sessions.pop(token, None)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp
