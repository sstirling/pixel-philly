"""Check that an offline copy (scripts/27_offline_copy.py) works with no
network: serve it on 127.0.0.1, open the viewer in headless Chromium with
every host except 127.0.0.1 unresolvable, zoom and pan so tiles load, try an
address search, and log every request. Fails if any request leaves
127.0.0.1, if a request fails, or if no tiles load.

    uv run python scripts/28_check_offline.py output/philly_offline_v14 [--shot out.png]
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--shot")
    ap.add_argument("--log", help="write the request log (JSON) here")
    args = ap.parse_args()
    folder = Path(args.folder).resolve()
    meta = json.loads(next((folder / "output").glob("*/tiles/*/map.json")).read_text())
    area, version = meta["area"], meta["version"]

    from playwright.sync_api import sync_playwright

    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port), "--bind", "127.0.0.1"],
                              cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    origin = f"http://127.0.0.1:{args.port}"
    requests, failed = [], []
    try:
        time.sleep(1.0)
        with sync_playwright() as p:
            # No DNS for anything but 127.0.0.1: an external request can't
            # succeed, and it would still show in the log
            browser = p.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"])
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.on("request", lambda r: requests.append(r.url))
            page.on("requestfailed", lambda r: failed.append(r.url))
            page.goto(f"{origin}/viewer/?area={area}&v={version}", wait_until="networkidle")
            for _ in range(4):
                page.click("#zoom-in")
                page.wait_for_timeout(700)
            page.mouse.move(700, 450)
            page.mouse.down()
            page.mouse.move(500, 350, steps=10)
            page.mouse.up()
            page.wait_for_load_state("networkidle")
            if page.locator("#layer-toggle").is_visible():
                page.click("#layer-toggle")
                page.wait_for_load_state("networkidle")
                page.click("#layer-toggle")
            page.fill("#q", "1400 JFK Blvd")
            page.click("#search button")
            page.wait_for_timeout(500)
            status = page.locator("#status").inner_text()
            page.wait_for_load_state("networkidle")
            if args.shot:
                page.screenshot(path=args.shot)
            browser.close()
    finally:
        server.terminate()

    external = [u for u in requests if not u.startswith(origin)]
    tiles = [u for u in requests if u.endswith(".webp")]
    report = {"requests": len(requests), "tiles": len(tiles), "external": external, "failed": failed,
              "search_status": status}
    if args.log:
        Path(args.log).write_text(json.dumps({**report, "urls": requests}, indent=1))
    print(json.dumps(report, indent=1))
    ok = not external and not failed and tiles
    print("OK: no request left 127.0.0.1" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
