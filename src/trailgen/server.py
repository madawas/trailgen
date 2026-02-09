from __future__ import annotations

import logging
import mimetypes
import os
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logger = logging.getLogger(__name__)


class RendererServer:
    def __init__(
        self,
        renderer_dir: Path,
        raster_upstream: str | None,
        terrain_upstream: str | None,
        cache_dir: Path,
    ):
        self._renderer_dir = renderer_dir
        self._raster_upstream = raster_upstream
        self._terrain_upstream = terrain_upstream
        self._cache_dir = cache_dir
        self._raster_ext = (
            self._infer_extension(raster_upstream) if raster_upstream else "png"
        )
        self._terrain_ext = (
            self._infer_extension(terrain_upstream) if terrain_upstream else "png"
        )
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise RuntimeError("Server not started")
        return f"http://127.0.0.1:{self.port}"

    @property
    def raster_url_template(self) -> str | None:
        if not self._raster_upstream:
            return None
        return f"{self.base_url}/tiles/raster/{{z}}/{{x}}/{{y}}.{self._raster_ext}"

    @property
    def terrain_url_template(self) -> str | None:
        if not self._terrain_upstream:
            return None
        return f"{self.base_url}/tiles/terrain/{{z}}/{{x}}/{{y}}.{self._terrain_ext}"

    def __enter__(self) -> "RendererServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        if self._httpd is not None:
            return

        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._httpd:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._httpd = None
        self._thread = None

    def _make_handler(self):
        renderer_dir = self._renderer_dir
        raster_upstream = self._raster_upstream
        terrain_upstream = self._terrain_upstream
        cache_dir = self._cache_dir
        cache_max_bytes = 2 * 1024 * 1024 * 1024

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path

                if path.startswith("/tiles/raster/"):
                    self._proxy_tile(raster_upstream, path, parsed.query)
                    return
                if path.startswith("/tiles/terrain/"):
                    self._proxy_tile(terrain_upstream, path, parsed.query)
                    return

                if path == "/":
                    path = "/index.html"
                file_path = (renderer_dir / path.lstrip("/")).resolve()
                if not file_path.is_file() or renderer_dir not in file_path.parents:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                    return

                content_type = (
                    mimetypes.guess_type(str(file_path))[0]
                    or "application/octet-stream"
                )
                try:
                    data = file_path.read_bytes()
                except OSError:
                    self.send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to read file"
                    )
                    return

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args) -> None:
                return

            def _proxy_tile(self, upstream: str | None, path: str, query: str) -> None:
                if not upstream:
                    self.send_error(
                        HTTPStatus.NOT_FOUND, "Tile upstream not configured"
                    )
                    return

                parts = path.strip("/").split("/")
                if len(parts) < 5:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid tile path")
                    return

                z, x, y_part = parts[2], parts[3], parts[4]
                y = y_part.split(".")[0]
                ext = y_part.split(".")[-1] if "." in y_part else "png"

                cache_path = cache_dir / parts[1] / z / x / f"{y}.{ext}"
                if cache_path.is_file():
                    try:
                        data = cache_path.read_bytes()
                        content_type = (
                            mimetypes.guess_type(str(cache_path))[0]
                            or "application/octet-stream"
                        )
                        now = time.time()
                        os.utime(cache_path, (now, now))
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    except OSError:
                        pass

                target = upstream.format(z=z, x=x, y=y)
                if query:
                    target = f"{target}?{query}"

                req = urllib.request.Request(
                    target, headers={"User-Agent": "trailgen/0.1"}
                )
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        payload = resp.read()
                        content_type = (
                            resp.headers.get("Content-Type")
                            or "application/octet-stream"
                        )
                        status = resp.status
                except urllib.error.HTTPError as exc:
                    logger.debug(
                        "[tile proxy] HTTP %s %s for %s",
                        exc.code,
                        exc.reason,
                        target,
                    )
                    self.send_error(exc.code, exc.reason)
                    return
                except Exception as exc:
                    logger.debug("[tile proxy] Failed to fetch %s: %s", target, exc)
                    self.send_error(HTTPStatus.BAD_GATEWAY, "Failed to fetch tile")
                    return

                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_bytes(payload)
                    RendererServer._enforce_cache_limit(cache_dir, cache_max_bytes)
                except OSError:
                    pass

                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler

    @staticmethod
    def _infer_extension(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        suffix = Path(parsed.path).suffix
        if suffix:
            return suffix.lstrip(".")
        return "png"

    @staticmethod
    def _enforce_cache_limit(cache_dir: Path, max_bytes: int) -> None:
        try:
            entries = []
            total = 0
            for path in cache_dir.rglob("*"):
                if not path.is_file():
                    continue
                stat = path.stat()
                total += stat.st_size
                entries.append((stat.st_mtime, stat.st_size, path))

            if total <= max_bytes:
                return

            entries.sort(key=lambda item: item[0])
            for _, size, path in entries:
                try:
                    path.unlink()
                    total -= size
                except OSError:
                    continue
                if total <= max_bytes:
                    break
        except OSError:
            return
