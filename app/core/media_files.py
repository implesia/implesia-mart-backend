"""Serve `/media` from disk, or redirect to the public object-storage URL.

The database stores `/media/<folder>/<name>` either way. When R2 is
configured, a browser that asks the API for that path is sent to
`MEDIA_PUBLIC_BASE_URL/<folder>/<name>`, which is the object key.
"""

from pathlib import Path

from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from app.core.config import settings
from app.services.image_storage import safe_object_key

_SAFE_QUERY = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~%&=+")


class MediaFiles:
    def __init__(self) -> None:
        self._static: StaticFiles | None = None
        self._root: Path | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await _lifespan(receive, send)
            return
        if scope["type"] != "http":
            return
        if settings.object_storage_enabled:
            await self._redirect(scope, receive, send)
            return
        await self._local()(scope, receive, send)

    def _local(self) -> StaticFiles:
        root = Path(settings.media_root).resolve()
        if self._static is None or self._root != root:
            root.mkdir(parents=True, exist_ok=True)
            self._static = StaticFiles(directory=root)
            self._root = root
        return self._static

    async def _redirect(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] not in {"GET", "HEAD"}:
            await Response(status_code=405)(scope, receive, send)
            return
        # Starlette keeps the full path on the scope and records the mount
        # prefix in root_path. The object key is the part after `/media`.
        key = safe_object_key(_mounted_path(scope))
        if key is None:
            await Response(status_code=404)(scope, receive, send)
            return
        base = settings.media_public_base_url.strip().rstrip("/")
        url = f"{base}/{key}"
        query = scope.get("query_string", b"")
        if isinstance(query, bytes) and query:
            text = query.decode("ascii", errors="ignore")
            if text and all(char in _SAFE_QUERY for char in text):
                url = f"{url}?{text}"
        await RedirectResponse(url, status_code=307)(scope, receive, send)


def _mounted_path(scope: Scope) -> str:
    path = str(scope.get("path", ""))
    root = str(scope.get("root_path", ""))
    if not root or not path.startswith(root):
        return path
    if path == root:
        return ""
    if path[len(root)] == "/":
        return path[len(root) :]
    return path


async def _lifespan(receive: Receive, send: Send) -> None:
    message = await receive()
    if message["type"] == "lifespan.startup":
        await send({"type": "lifespan.startup.complete"})
    message = await receive()
    if message["type"] == "lifespan.shutdown":
        await send({"type": "lifespan.shutdown.complete"})
