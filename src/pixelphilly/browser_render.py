"""Drive render/index.html in headless Chromium from Python.

ES modules don't load from file:// URLs, so the repo is served over a local
HTTP server on a free port for the life of the context manager.
"""

from __future__ import annotations

import base64
import functools
import http.server
import io
import threading

from PIL import Image

from .projection import REPO_ROOT


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Renderer:
    """with Renderer(scene_rel_path, size) as r: img = r.frame(i) / r.view(frustum)"""

    def __init__(self, scene_rel: str, size: int):
        self.scene_rel = scene_rel
        self.size = size

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        handler = functools.partial(_QuietHandler, directory=str(REPO_ROOT))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(args=["--enable-gpu", "--ignore-gpu-blocklist"])
        self.page = self.browser.new_page(viewport={"width": self.size, "height": self.size})
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))
        self.page.goto(f"http://127.0.0.1:{self.httpd.server_port}/render/index.html?scene={self.scene_rel}")
        try:
            self.page.wait_for_function("window.sceneReady === true", timeout=300_000)
        except Exception:
            self.__exit__(None, None, None)
            raise SystemExit(f"scene failed to load: {errors}")
        self.info = self.page.evaluate("window.rendererInfo")
        return self

    def _decode(self, data_url: str) -> Image.Image:
        return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")

    def frame(self, index: int, mode: str = "color") -> Image.Image:
        return self._decode(self.page.evaluate("([i, m]) => window.renderFrame(i, m)", [index, mode]))

    def view(self, frustum: dict, mode: str = "color") -> Image.Image:
        return self._decode(self.page.evaluate("([f, m]) => window.renderView(f, m)", [frustum, mode]))

    def __exit__(self, *exc):
        try:
            self.browser.close()
            self._pw.stop()
        finally:
            self.httpd.shutdown()
