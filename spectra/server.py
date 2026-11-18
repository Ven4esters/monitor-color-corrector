"""Small same-origin HTTP boundary. Only demo mode may bind a non-loopback host."""

import json
import logging
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from .backends.base import DisplayError
from .portable import FILENAME, archive_bytes

WEB = Path(__file__).parent / "web"
logger = logging.getLogger(__name__)


def handler_for(studio, local_only=True, web_root=WEB):
    class Handler(SimpleHTTPRequestHandler):
        server_version = "Spectra/1.0"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_root), **kwargs)

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header(
                "Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache"
            )
            super().end_headers()

        def json(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def allowed_host(self):
            if not local_only:
                return True
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
            if host not in ("127.0.0.1", "localhost", "::1"):
                self.json({"error": "Аппаратное управление доступно только локально."}, 403)
                return False
            return True

        def do_GET(self):
            if not self.allowed_host():
                return
            path = urlsplit(self.path).path
            if path == "/api/state":
                self.json(studio.state())
            elif path == f"/download/{FILENAME}":
                body = archive_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{FILENAME}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path.startswith("/api/"):
                self.json({"error": "Метод не найден."}, 404)
            else:
                super().do_GET()

        def list_directory(self, path):
            self.send_error(404)

        def do_POST(self):
            if not self.allowed_host():
                return
            origin = self.headers.get("Origin")
            if (
                self.headers.get("X-Spectra-Request") != "1"
                or self.headers.get_content_type() != "application/json"
                or (local_only and origin and urlsplit(origin).netloc != self.headers.get("Host"))
            ):
                return self.json({"error": "Операция доступна только из интерфейса Spectra."}, 403)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 <= length <= 16384:
                    return self.json({"error": "Слишком большой запрос."}, 413)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    return self.json({"error": "Ожидается JSON-объект."}, 400)
            except ValueError:
                return self.json({"error": "Некорректный JSON."}, 400)
            try:
                if self.path == "/api/apply":
                    result = studio.apply(
                        payload.get("ids"), payload.get("profile"), payload.get("brightness")
                    )
                elif self.path == "/api/undo":
                    result = studio.undo(payload.get("id"))
                elif self.path == "/api/scan":
                    with studio.lock:
                        studio.refresh()
                        result = studio.state()
                else:
                    return self.json({"error": "Метод не найден."}, 404)
                self.json(result)
            except DisplayError as exc:
                self.json({"error": str(exc)}, 409)
            except OSError:
                logger.exception("Display I/O failed")
                self.json(
                    {
                        "error": "Системная ошибка устройства. Проверьте подключение и повторите операцию."
                    },
                    503,
                )

    return Handler
