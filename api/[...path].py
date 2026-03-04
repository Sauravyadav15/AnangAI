from pathlib import Path
import sys
from typing import Any, Callable, Dict

# Ensure backend package is importable when running in Vercel's api/ runtime.
BACKEND_PATH = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from main import app as backend_app


class VercelPathCompatApp:
    """
    ASGI wrapper to tolerate Vercel path variations.

    Some deployments forward `/api/...` intact, while others can forward
    the catch-all function path without the `/api` prefix. Our backend routes
    are defined as `/api/*`, so if a request arrives as `/chat` this wrapper
    rewrites it to `/api/chat` before handing off to FastAPI.
    """

    def __init__(self, asgi_app: Callable[..., Any]):
        self.asgi_app = asgi_app

    async def __call__(self, scope: Dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]):
        if scope.get("type") in {"http", "websocket"}:
            path = scope.get("path") or "/"
            if not path.startswith("/api"):
                # Preserve root requests as `/api` for health-like checks.
                scope = dict(scope)
                scope["path"] = "/api" if path == "/" else f"/api{path}"
        await self.asgi_app(scope, receive, send)


app = VercelPathCompatApp(backend_app)
