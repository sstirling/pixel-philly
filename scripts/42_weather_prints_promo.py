"""Short promo video of live weather and the neighborhood prints page: snow
and then rain falling on the map with the temperature badge, then the prints
page's grid and its larger preview.

Everything is filmed from the real local site (the repo served on
127.0.0.1:8000) in headless Chromium, so the clips show the viewer and page
exactly as visitors see them.

The weather is simulated. Philadelphia's real weather rarely suits a promo, so
the viewer is fed made-up live/weather.json records (snow at 30°F, rain at
48°F) and every weather frame says "Weather simulated for this preview."

How the recording works:
1. Map scenes: load the viewer with the weather file replaced by a simulated
   record (DEMO below), hide the bar, zoom buttons and credits, and keep the
   temperature badge. Then take over the page's clock (performance.now, Date
   and requestAnimationFrame, as scripts/39_transit_promo.py does): each video
   frame advances the weather animation and OpenSeadragon exactly 1/fps
   seconds, so motion is smooth however long a screenshot takes. The view
   pans slowly; tiles for the whole pan are loaded before filming.
2. Prints scenes: scroll the grid of neighborhoods, then open one larger
   preview (a click on its thumbnail, as a visitor would).
3. Draw the address and captions with scripts/29_flyover.py draw_overlays and
   encode with the ffmpeg binary bundled with imageio-ffmpeg.

Pages are rendered at 2 device pixels per CSS pixel, so the pixel art, the
badge and the page text are large enough to read in a phone feed.

--vertical makes the TikTok/Reels cut (1080 x 1920), with text in the safe box
from config/flyover/promo_vertical.json and the badge moved inside it.

--parts picks and orders the scenes, each optionally with its own length in
seconds: snow, rain, storm (map scenes); grid, preview (the prints page);
prints (a short grid scroll into a preview, one caption, for a single slot in
a longer promo). Default "snow,rain,grid,preview". The storm scene times a
lightning strike into the clip (the weather layer's scheduleStrike hook).
scripts/43_feature_promo.py uses "storm=3,prints=3".

Output: output/flyover/promo_weather_prints.mp4, or promo_weather_prints_vertical.mp4
(not tracked).
Usage: uv run python scripts/42_weather_prints_promo.py [--vertical] [--parts storm=3,prints=3] [--name NAME]
"""

import argparse
import importlib.util
import json
import shutil
import subprocess
import time

import imageio_ffmpeg
from PIL import Image
from playwright.sync_api import sync_playwright

from pixelphilly.projection import REPO_ROOT
from pixelphilly.viewer_geo import lonlat_to_px

_spec = importlib.util.spec_from_file_location("flyover", REPO_ROOT / "scripts" / "29_flyover.py")
fly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fly)
_spec = importlib.util.spec_from_file_location("transit_promo", REPO_ROOT / "scripts" / "39_transit_promo.py")
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)

SITE = "http://127.0.0.1:8000/viewer/"
MAP_JSON = REPO_ROOT / "output" / "philly" / "tiles" / "v18" / "map.json"
VERTICAL = REPO_ROOT / "config" / "flyover" / "promo_vertical.json"
LABEL = "pixelphilly.sstirling.com"
SIMULATED = "Weather simulated for this preview"
OUT = REPO_ROOT / "output" / "flyover"
DPR = 2

# Simulated weather records, in the Worker's live/weather.json format
# (worker/septa-live.js weatherRecord); "observed" is filled in at run time
DEMO = {
    "snow": {"station": "KPHL", "kind": "snow", "intensity": "heavy", "text": "Heavy Snow", "temp_c": -1.1, "night": False},
    "rain": {"station": "KPHL", "kind": "rain", "intensity": "heavy", "text": "Heavy Rain", "temp_c": 8.9, "night": False},
    "storm": {"station": "KPHL", "kind": "rain", "intensity": "heavy", "text": "Thunderstorm, Heavy Rain", "temp_c": 24.4,
              "night": False, "thunder": True},
}

# Map scenes: where (lon, lat), zoom (map px per CSS px), and a pan in CSS px over
# the clip. "strike": seconds into the clip for a lightning strike.
SCENES = {
    "snow": {"seconds": 4.0, "lonlat": [-75.1645, 39.9535], "z": 0.6, "pan": [140, -40],
             "caption": "When it snows in Philly, it snows on the map"},
    "rain": {"seconds": 3.5, "lonlat": [-75.1370, 39.9525], "z": 0.6, "pan": [-120, -30],
             "caption": "Rain too, with the airport's temperature"},
    "storm": {"seconds": 3.0, "lonlat": [-75.1645, 39.9535], "z": 0.6, "pan": [120, -35], "strike": 1.1,
              "caption": "Live weather, thunderstorms included"},
}
GRID_SECONDS, GRID_SCROLL = 3.0, 520  # CSS px scrolled while filming the grid
GRID_CAPTION = "New: every neighborhood, ready to print"
PREVIEW_SECONDS, PREVIEW_NAME = 3.5, "Rittenhouse"
PREVIEW_CAPTION = "Free to download for your wall or phone"
# "prints": the grid for PRINTS_GRID_S, then the preview, under one caption
PRINTS_SECONDS, PRINTS_GRID_S, PRINTS_SCROLL = 3.0, 0.9, 160
PRINTS_CAPTION = "Every neighborhood, free to download"
DEFAULT_PARTS = "snow,rain,grid,preview"


def parse_parts(text):
    """"storm=3,prints" -> [("storm", 3.0), ("prints", None)]"""
    out = []
    for item in text.split(","):
        key, _, sec = item.strip().partition("=")
        if key not in (*SCENES, "grid", "preview", "prints"):
            raise SystemExit(f"unknown part {key!r}")
        out.append((key, float(sec) if sec else None))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vertical", action="store_true", help="TikTok/Reels cut, 1080 x 1920, text in the safe box")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--name")
    ap.add_argument("--parts", default=DEFAULT_PARTS, help=f"scenes in order, e.g. storm=3,prints=3 (default {DEFAULT_PARTS})")
    args = ap.parse_args()
    parts = parse_parts(args.parts)
    w, h = (1080, 1920) if args.vertical else (1920, 1080)
    cw, ch = w // DPR, h // DPR  # CSS viewport
    name = args.name or ("promo_weather_prints_vertical" if args.vertical else "promo_weather_prints")
    safe = json.loads(VERTICAL.read_text())["safe"] if args.vertical else None
    fit = json.loads(MAP_JSON.read_text())["fit"]
    frames_dir = OUT / f"{name}_frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    captions = []  # (caption, credit) per frame

    # The badge: top right in the horizontal cut (the viewer's own spot). In the
    # vertical cut the viewer would move it into the hidden bar, so it's put back
    # on the page, inside the safe box above the bottom margin.
    badge_css = ".bar, .controls, .credits { display: none !important; }"
    if safe:
        badge_css += (f" #temp {{ top: auto !important; bottom: {safe['bottom'] // DPR + 16}px !important;"
                      f" right: {safe['right'] // DPR + 8}px !important; }}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        n = 0

        def shoot(page, caption, credit=""):
            nonlocal n
            page.screenshot(path=str(frames_dir / f"{n:05d}.png"))
            captions.append((caption, credit))
            n += 1

        def film_weather(key, seconds):
            sc = SCENES[key]
            page = browser.new_page(viewport={"width": cw, "height": ch}, device_scale_factor=DPR)
            rec = {**DEMO[key], "fetched": int(time.time()), "observed": int(time.time()) - 600}
            page.route("**/output/live/weather.json",
                       lambda route, _req=None, rec=rec: route.fulfill(body=json.dumps(rec), content_type="application/json"))
            page.goto(f"{SITE}index.html?live=off#x=50000&y=58000&z=0.3")
            page.wait_for_selector("#temp:not([hidden])")
            page.evaluate("document.getElementById('map').before(document.getElementById('temp'))")
            page.add_style_tag(content=badge_css)
            page.evaluate(tp.CLOCK)
            x, y = lonlat_to_px(fit, *sc["lonlat"])
            z, (px, py) = sc["z"], sc["pan"]
            # Load tiles for both ends of the pan first
            for fx in (1, 0):
                page.evaluate(tp.GOTO, [x + px * fx / z, y + py * fx / z, z])
                for _ in range(10):
                    time.sleep(0.3)
                    page.evaluate("__step(0)")
            # Let the particles spread over the frame before filming
            for _ in range(30):
                page.evaluate(f"__step({1000 / args.fps})")
            if "strike" in sc:
                page.evaluate(f"document.querySelector('canvas.weather-layer').scheduleStrike(performance.now() + {sc['strike'] * 1000})")
            frames = round(seconds * args.fps)
            for k in range(frames):
                f = k / max(1, frames - 1)
                f = f * f * (3 - 2 * f)  # ease in and out
                page.evaluate(tp.GOTO, [x + px * f / z, y + py * f / z, z])
                page.evaluate(f"__step({1000 / args.fps})")
                shoot(page, sc["caption"], SIMULATED)
            print(f"{key}: {frames} frames")
            page.close()

        prints = {}  # the prints page, opened once and shared by grid, preview and prints

        def prints_page():
            if "page" not in prints:
                page = browser.new_page(viewport={"width": cw, "height": ch}, device_scale_factor=DPR)
                page.goto(f"{SITE}neighborhoods.html")
                page.add_style_tag(content="html { scrollbar-width: none; } ::-webkit-scrollbar { display: none; }")
                page.wait_for_selector("#grid li")
                top = page.evaluate("document.querySelector('.finder').getBoundingClientRect().top + scrollY - 12")
                # Load every thumbnail the scroll will pass over
                page.evaluate(f"scrollTo(0, {top + GRID_SCROLL})")
                page.wait_for_load_state("networkidle")
                page.evaluate(f"scrollTo(0, {top})")
                page.wait_for_function("[...document.querySelectorAll('#grid img')].filter(i => i.getBoundingClientRect().top < innerHeight)"
                                       ".every(i => i.complete && i.naturalWidth)")
                prints.update(page=page, top=top)
            return prints["page"], prints["top"]

        def film_grid(seconds, scroll, caption):
            page, top = prints_page()
            frames = round(seconds * args.fps)
            for k in range(frames):
                f = k / max(1, frames - 1)
                f = f * f * (3 - 2 * f)
                page.evaluate(f"scrollTo(0, {top + scroll * f})")
                shoot(page, caption)
            print(f"grid: {frames} frames")

        def film_preview(seconds, caption):
            page, _ = prints_page()
            page.get_by_role("button", name=f"Larger preview of {PREVIEW_NAME}", exact=True).click()
            page.wait_for_function("(() => { const i = document.getElementById('preview-img'); return i.complete && i.naturalWidth > 0; })()")
            page.mouse.move(0, 0)  # no hover outline on the downloads
            frames = round(seconds * args.fps)
            for _ in range(frames):
                shoot(page, caption)
            print(f"preview: {frames} frames")

        for key, sec in parts:
            if key in SCENES:
                film_weather(key, sec or SCENES[key]["seconds"])
            elif key == "grid":
                film_grid(sec or GRID_SECONDS, GRID_SCROLL, GRID_CAPTION)
            elif key == "preview":
                film_preview(sec or PREVIEW_SECONDS, PREVIEW_CAPTION)
            else:  # prints
                total = sec or PRINTS_SECONDS
                film_grid(PRINTS_GRID_S, PRINTS_SCROLL, PRINTS_CAPTION)
                film_preview(total - PRINTS_GRID_S, PRINTS_CAPTION)
        browser.close()

    for f, (caption, credit) in zip(sorted(frames_dir.glob("*.png")), captions):
        img = Image.open(f).convert("RGB")
        fly.draw_overlays(img, caption=caption, label=LABEL, credit=credit, safe=safe)
        img.save(f)
    out = OUT / f"{name}.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", str(args.fps),
                    "-i", str(frames_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-movflags", "+faststart", str(out)], check=True)
    print(f"{out}: {n} frames, {n / args.fps:.1f} s, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
