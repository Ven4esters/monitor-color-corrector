import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from spectra.server import handler_for
from spectra.studio import Studio


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = Studio(demo=True, directory=self.tmp.name)

        class QuietHandler(handler_for(self.studio)):
            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None, headers=None):
        conn = HTTPConnection(*self.server.server_address, timeout=3)
        try:
            conn.request("GET" if body is None else "POST", path, body, headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def post(self, path, payload):
        return self.request(
            path,
            json.dumps(payload),
            {"X-Spectra-Request": "1", "Content-Type": "application/json"},
        )

    def test_state_and_assets_are_available_offline(self):
        code, data = self.request("/api/state")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(data)["demo"])
        for path in (
            "/",
            "/studio.css",
            "/studio.js",
            "/assets/icons.svg",
            "/assets/alpine-lake.jpg",
            "/assets/fonts/manrope-cyrillic-wght-normal.woff2",
        ):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request("/assets/")[0], 404)

    def test_valid_apply_and_undo_via_api(self):
        m = list(self.studio.monitors)[1]
        status, body = self.post("/api/apply", {"ids": [m], "profile": "cinema", "brightness": 45})
        self.assertEqual(status, 200)
        entry = json.loads(body)["undoId"]
        self.assertIsNotNone(entry)
        self.assertEqual(self.post("/api/undo", {"id": "stale"})[0], 409)
        self.assertEqual(self.post("/api/undo", {"id": entry})[0], 200)
        self.assertIsNone(self.studio.state()["undoId"])

    def test_origin_and_content_type_restrictions(self):
        self.assertEqual(self.request("/api/apply", "{}")[0], 403)
        self.assertEqual(
            self.request(
                "/api/scan",
                "{}",
                {
                    "X-Spectra-Request": "1",
                    "Content-Type": "application/json",
                    "Origin": "https://other.invalid",
                },
            )[0],
            403,
        )
        self.assertEqual(self.request("/api/state", headers={"Host": "unknown.invalid"})[0], 403)
        self.assertEqual(self.post("/api/scan", {})[0], 200)

    def test_invalid_body_and_route(self):
        self.assertEqual(self.post("/api/apply", [])[0], 400)
        self.assertEqual(self.post("/api/apply", {"profile": "cinema", "brightness": True})[0], 409)
        self.assertEqual(self.request("/api/undo")[0], 404)
        self.assertEqual(self.post("/api/invalid", {})[0], 404)
        self.assertEqual(
            self.request(
                "/api/apply", "{", {"X-Spectra-Request": "1", "Content-Type": "application/json"}
            )[0],
            400,
        )
        self.assertEqual(self.studio.state()["history"], [])

    def test_download_is_a_portable_app_without_local_state(self):
        self.studio.apply(list(self.studio.monitors), "warm", 50)
        status, body = self.request("/download/Spectra-Studio.pyz")
        self.assertEqual(status, 200)
        with ZipFile(BytesIO(body)) as archive:
            names = archive.namelist()
            self.assertIn("__main__.py", names)
            self.assertIn("spectra/web/index.html", names)
            self.assertIn("spectra/backends/windows.py", names)
            self.assertFalse(any(n.endswith((".json", ".pyc")) for n in names))
            self.assertIsNone(archive.testzip())
