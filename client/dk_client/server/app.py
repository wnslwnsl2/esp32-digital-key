"""FastAPI application."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from dk_client.server.websocket import router as ws_router, status_update_loop, do_scan


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
app.include_router(ws_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
