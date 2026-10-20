"""Render every frame of the lattice with headless Chromium.

Serves the repo over a local HTTP server (ES modules don't load from
file:// URLs), opens render/index.html, and calls window.renderFrame for each
frame. Writes:

  output/renders/<frame>.png         1024 x 1024 render frames
  output/renders/mosaic.png          all frames pasted on the lattice
  output/renders/mosaic_preview.jpg  the mosaic at 1/4 size for a quick look

Usage: uv run python scripts/06_render.py [--mode mask] [--only frame_02_01]
"""

import argparse
import base64
import functools
import http.server
import io
import json
import threading

from PIL import Image
from playwright.sync_api import sync_playwright

from pixelphilly.projection import REPO_ROOT, load_config


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve_repo():
    handler = functools.partial(QuietHandler, directory=str(REPO_ROOT))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="color", choices=["color", "mask"])
    ap.add_argument("--only", help="render just this frame name")
    args = ap.parse_args()

    cfg = load_config()
    scene_rel = f"data/processed/{cfg['name']}_scene.json"
    scene = json.loads((REPO_ROOT / scene_rel).read_text())
    size = scene["frame_px"]
    out_dir = REPO_ROOT / "output" / ("renders" if args.mode == "color" else "masks")
    out_dir.mkdir(parents=True, exist_ok=True)

    httpd = serve_repo()
    url = f"http://127.0.0.1:{httpd.server_port}/render/index.html?scene={scene_rel}"
    images = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--enable-gpu", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": size, "height": size})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        try:
            page.wait_for_function("window.sceneReady === true", timeout=300_000)
        except Exception:
            raise SystemExit(f"scene failed to load: {errors}")
        print("renderer:", page.evaluate("window.rendererInfo"))

        for i, f in enumerate(scene["frames"]):
            if args.only and f["name"] != args.only:
                continue
            data_url = page.evaluate("([i, m]) => window.renderFrame(i, m)", [i, args.mode])
            img = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")
            img.save(out_dir / f"{f['name']}.png")
            images[(f["col"], f["row"])] = img
            print(f"  {f['name']}")
        browser.close()
    httpd.shutdown()

    if args.only or args.mode != "color":
        return
    cols = max(c for c, _ in images) + 1
    rows = max(r for _, r in images) + 1
    mosaic = Image.new("RGB", (cols * size, rows * size))
    for (c, r), img in images.items():
        mosaic.paste(img, (c * size, r * size))
    mosaic.save(out_dir / "mosaic.png")
    mosaic.resize((mosaic.width // 4, mosaic.height // 4), Image.LANCZOS).save(
        out_dir / "mosaic_preview.jpg", quality=88
    )
    print(f"mosaic {mosaic.size} -> {out_dir / 'mosaic.png'}")


if __name__ == "__main__":
    main()
