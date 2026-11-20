"""Short promo video of the live transit layer: hard cuts between spots where
live SEPTA vehicles are moving, with the site address and a caption.

The vehicles are drawn by the real viewer (viewer/transit.js) in headless
Chromium, from the live feed, so the clips show the layer exactly as visitors
see it. Only live vehicles are filmed (buses, trolleys, Regional Rail); El
trains are timetable positions, so they are not used to illustrate "live."

How the recording works:
1. Open the local viewer (the repo served on 127.0.0.1:8000, with
   scripts/38_live_feed.py writing output/live/vehicles.json) and wait for
   two SEPTA updates, so vehicles are mid-glide between reports.
2. Take over the transit layer's clock (performance.now, Date and
   requestAnimationFrame) and stop further feed updates. Each video frame then
   advances the layer exactly 1/fps seconds, so motion is smooth and real-time
   however long a screenshot takes. OpenSeadragon keeps its own clock; the
   view is still during a clip.
3. Score candidate spots (one per neighborhood with a live vehicle) by how
   far the visible vehicles near the middle of the frame glide, in meters. A
   moving Regional Rail train is required and opens the cut; if none is in
   view, the script waits for fresh feed updates and tries again (3 tries).
   Then the best trolley and bus spots, filmed a few seconds each.
4. Draw the address and caption with scripts/29_flyover.py draw_overlays and
   encode with the ffmpeg binary bundled with imageio-ffmpeg.

--vertical makes the TikTok/Reels cut (1080 x 1920): text sits in the same
safe box as config/flyover/promo_vertical.json (the apps cover the frame's
edges with their own buttons and captions), and scenes are scored and framed
in the open part of that box, under the caption.

Output: output/flyover/promo_transit.mp4, or promo_transit_vertical.mp4 (not tracked).
--cuts sets the number of scenes (default 4: the train, a trolley, a bus and
the next best); --caption replaces the caption. scripts/43_feature_promo.py
uses a 2-cut version.

Usage: uv run python scripts/39_transit_promo.py [--vertical] [--seconds 10] [--zoom 3] [--cuts 4]
"""

import argparse
import importlib.util
import json
import shutil
import subprocess
import time

import io

import imageio_ffmpeg
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

from pixelphilly.projection import REPO_ROOT
from pixelphilly.viewer_geo import lonlat_to_px

_spec = importlib.util.spec_from_file_location("flyover", REPO_ROOT / "scripts" / "29_flyover.py")
fly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fly)

URL = "http://127.0.0.1:8000/viewer/index.html"
LIVE = REPO_ROOT / "output" / "live" / "vehicles.json"
MAP_JSON = REPO_ROOT / "output" / "philly" / "tiles" / "v18" / "map.json"
VERTICAL = REPO_ROOT / "config" / "flyover" / "promo_vertical.json"
CAPTION, LABEL = "Now with live SEPTA vehicles", "pixelphilly.sstirling.com"
OUT = REPO_ROOT / "output" / "flyover"
ATTEMPTS = 3

CLOCK = """(() => {
  let vt = performance.now();
  const dateBase = Date.now() - vt;
  const RealDate = Date;
  performance.now = () => vt;
  class FakeDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(dateBase + vt); }
    static now() { return dateBase + vt; }
  }
  window.Date = FakeDate;
  let queue = [];
  window.requestAnimationFrame = (cb) => { queue.push(cb); return queue.length; };
  window.cancelAnimationFrame = () => {};
  window.__step = (ms) => { vt += ms; const run = queue; queue = []; run.forEach((cb) => cb(vt)); };
})()"""

# Put map point (x, y) at screen offset (dx, dy) from the frame's center, at zoom z
GOTO = """([x, y, z, dx = 0, dy = 0]) => { const v = OpenSeadragon.getViewer(document.getElementById('map'));
  const item = v.world.getItemAt(0);
  v.viewport.zoomTo(item.imageToViewportZoom(z), null, true);
  v.viewport.panTo(item.imageToViewportCoordinates(x - dx / z, y - dy / z), true); }"""

# Visible vehicles in the scoring box (their pixel on the transit canvas isn't
# erased by a building) and how far they glide in this update, in meters
# box: [left, top, right, bottom] of the frame to count, in CSS px
SCORE = """([bx0, by0, bx1, by1]) => { const c = document.querySelector('canvas.transit-layer'); const g = c.getContext('2d');
  const dpr = devicePixelRatio; const seen = new Map();
  for (const it of c.transitItems || []) {
    if (it.v.kind === 'el') continue;
    if (it.sx < bx0 || it.sx > bx1 || it.sy < by0 || it.sy > by1) continue;
    const a = g.getImageData(Math.round(it.sx * dpr), Math.round(it.sy * dpr), 1, 1).data[3];
    if (!a) continue;
    const m = it.v.motion; const meters = m && m.kind === 'along' ? Math.max(0, m.m1 - m.m0) : 0;
    seen.set(it.v.kind + it.v.id, { kind: it.v.kind, meters });
  }
  const vs = [...seen.values()];
  const moving = vs.filter((v) => v.meters > 15);
  return { visible: vs.length, moving: moving.length, meters: Math.round(moving.reduce((t, v) => t + Math.min(v.meters, 150), 0)),
           kinds: moving.map((v) => v.kind) }; }"""


# Do two different vehicles overlap anywhere in the frame (e.g. buses stacked at a
# loop, trains on side-by-side tracks)? Any two of their cars closer than d CSS px
OVERLAP = """(d) => { const c = document.querySelector('canvas.transit-layer'); const W = c.clientWidth, H = c.clientHeight;
  const its = (c.transitItems || []).filter((it) => it.sx > -d && it.sx < W + d && it.sy > -d && it.sy < H + d);
  for (let i = 0; i < its.length; i++) for (let j = i + 1; j < its.length; j++) {
    const a = its[i], b = its[j];
    if (a.v.kind + a.v.id === b.v.kind + b.v.id) continue;
    if (Math.hypot(a.sx - b.sx, a.sy - b.sy) < d) return true;
  }
  return false; }"""


# Screen centers of the visible (not behind a building) cars in the frame
VISIBLE = """() => { const c = document.querySelector('canvas.transit-layer'); const g = c.getContext('2d');
  const dpr = devicePixelRatio, W = c.clientWidth, H = c.clientHeight;
  return (c.transitItems || []).filter((it) => it.sx >= 0 && it.sx < W && it.sy >= 0 && it.sy < H
    && g.getImageData(Math.round(it.sx * dpr), Math.round(it.sy * dpr), 1, 1).data[3]).map((it) => [it.sx, it.sy]); }"""


# The scene's subject: the visible vehicle of `kind` (any kind if null) that glides
# farthest in this update. Returns its key, or null.
SUBJECT = """(kind) => { const c = document.querySelector('canvas.transit-layer'); const g = c.getContext('2d');
  const dpr = devicePixelRatio; let best = null, bestM = -1;
  for (const it of c.transitItems || []) {
    if (it.v.kind === 'el' || (kind && it.v.kind !== kind)) continue;
    if (!g.getImageData(Math.round(it.sx * dpr), Math.round(it.sy * dpr), 1, 1).data[3]) continue;
    const m = it.v.motion; const meters = m && m.kind === 'along' ? m.m1 - m.m0 : 0;
    if (meters > bestM) { bestM = meters; best = it.v.kind + it.v.id; }
  }
  return best; }"""

# Middle of all of a vehicle's cars, in map px (null if it's out of view)
CENTROID = """(key) => { const its = (document.querySelector('canvas.transit-layer').transitItems || [])
  .filter((it) => it.v.kind + it.v.id === key);
  if (!its.length) return null;
  return [its.reduce((t, it) => t + it.mx, 0) / its.length, its.reduce((t, it) => t + it.my, 0) / its.length]; }"""


def candidates():
    fit = json.loads(MAP_JSON.read_text())["fit"]
    data = json.loads(LIVE.read_text())
    out = []
    for src, route, vid, lon, lat, *_ in data["vehicles"]:
        x, y = lonlat_to_px(fit, lon, lat)
        kind = "rail" if src == "rr" else ("trolley" if route[:1] in "TGD" and route[1:2].isdigit() else "bus")
        # One spot per neighborhood: a frame at zoom 3 is about 640 x 360 map px
        if all(abs(x - q[1]) > 300 or abs(y - q[2]) > 200 for q in out):
            out.append((kind, float(x), float(y)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--vertical", action="store_true", help="TikTok/Reels cut, 1080 x 1920, text in the safe box")
    # A bus is about 125 px long at zoom 3; vertical frames are 1080 px wide, so
    # they default a little wider (2.5) to keep a four-car train in the safe box
    ap.add_argument("--zoom", type=float)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--cuts", type=int, default=4, help="number of scenes (the first is always a moving train)")
    ap.add_argument("--caption", default=CAPTION)
    ap.add_argument("--size")
    ap.add_argument("--name")
    args = ap.parse_args()
    w, h = fly.parse_size(args.size or ("1080x1920" if args.vertical else "1920x1080"))
    args.zoom = args.zoom or (2.5 if args.vertical else 3.0)
    args.name = args.name or ("promo_transit_vertical" if args.vertical else "promo_transit")
    safe = json.loads(VERTICAL.read_text())["safe"] if args.vertical else None
    if safe:
        # The open part of the safe box: under the address and caption, above the
        # bottom margin (same layout as fly.draw_overlays)
        ls, cap = min(w, h) // 20, min(w, h) // 26
        slot = round(ls * 1.3) + 2 * (ls // 3) + ls // 3
        top = safe["top"] + slot + fly._measure(args.caption, cap, cap // 3)[1] + 20
        box = [safe["left"], top, w - safe["right"], h - safe["bottom"]]
    else:
        box = [w * 0.2, h * 0.2, w * 0.8, h * 0.8]  # the middle 60%
    # Subjects are framed at the box's center, not the frame's
    off = [(box[0] + box[2]) / 2 - w / 2, (box[1] + box[3]) / 2 - h / 2]
    clip_ms = args.seconds / args.cuts * 1000
    # Two vehicles' cars with ground centers under ~10 m apart are drawn on top of
    # each other (the shortest, a bus, is 12.2 m long). A meter is 2.44-3.39 map px
    # depending on direction; about 3 x zoom screen px
    gap_px = 10 * 3 * args.zoom
    print(f"{w} x {h}, zoom {args.zoom}, subject box {[round(v) for v in box]}")
    frames_dir = OUT / f"{args.name}_frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        def score(page, spots):
            out = []
            for kind, x, y in spots:
                page.evaluate(GOTO, [x, y, args.zoom, *off])
                for _ in range(3):
                    time.sleep(0.2)  # tiles and building masks load in real time
                    page.evaluate("__step(0)")
                s = page.evaluate(SCORE, box)
                # Skip spots where vehicles overlap now, mid-clip or at the end
                # (Stephen, Nov. 16: stacked buses and trains looked like a glitch)
                hits = []
                for ms in (0, clip_ms / 2, clip_ms):
                    page.evaluate(f"__step({ms})")
                    hits.append(page.evaluate(OVERLAP, gap_px))
                    page.evaluate(f"__step({-ms})")
                if any(hits):
                    continue
                bonus = 1.5 if any(k in ("trolley", "rail") for k in s["kinds"]) else 1.0
                out.append((s["meters"] * bonus, kind, x, y, s))
            return sorted(out, key=lambda r: -r[0])

        far = lambda r, picks: all(abs(r[2] - q[2]) + abs(r[3] - q[3]) > 1500 for q in picks)

        per = max(1, round(args.seconds * args.fps / args.cuts))
        half_ms = per / args.fps * 500

        def settle():
            for _ in range(6):
                time.sleep(0.3)  # tiles and masks for the new view
                page.evaluate("__step(0)")

        def frame(r, train):
            """Frame a scene as it will be filmed: the subject (the train, for the
            opener) centered where it will be halfway through the clip. Returns the
            view center, or None when the framed clip shows a vehicle drawn over
            trees or grass, or two vehicles overlapping, at any of 9 moments."""
            page.evaluate(GOTO, [r[2], r[3], args.zoom, *off])
            settle()
            center = (r[2], r[3])
            key = page.evaluate(SUBJECT, "rail" if train else None)
            if key:
                page.evaluate(f"__step({half_ms})")
                mid = page.evaluate(CENTROID, key)
                page.evaluate(f"__step({-half_ms})")
                if mid:
                    center = tuple(mid)
                    page.evaluate(GOTO, [*center, args.zoom, *off])
                    settle()
            clip = per * 1000 / args.fps
            ok = True
            for k in range(9):
                t = clip * k / 8
                page.evaluate(f"__step({t})")
                if page.evaluate(OVERLAP, gap_px):
                    ok, why = False, "vehicles overlap"
                elif on_green(page):
                    ok, why = False, "a vehicle is over trees or grass"
                page.evaluate(f"__step({-t})")
                if not ok:
                    break
            print(f"  {r[1]} at {round(r[2])}, {round(r[3])}: {'ok' if ok else 'rejected: ' + why} at {t / 1000:.1f} s")
            return center if ok else None

        def on_green(page):
            # The map under each visible car, with the transit layer hidden. Tree
            # canopy and grass are green; roads, track and pavement aren't. The
            # building masks hide vehicles behind buildings, not trees, so a bus in
            # a curb lane under street trees is drawn on top of them (Stephen,
            # Nov. 16). Reject when over a quarter of the pixels within ~2 m of a
            # car's center are green
            cars = page.evaluate(VISIBLE)
            if not cars:
                return False
            page.evaluate("document.querySelector('canvas.transit-layer').style.visibility = 'hidden'")
            shot = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB")).astype(int)
            page.evaluate("document.querySelector('canvas.transit-layer').style.visibility = ''")
            rad = max(4, round(2 * 3 * args.zoom))
            for sx, sy in cars:
                x, y = round(sx), round(sy)
                patch = shot[max(0, y - rad):y + rad + 1, max(0, x - rad):x + rad + 1]
                r_, g_, b_ = patch[..., 0], patch[..., 1], patch[..., 2]
                if ((g_ > r_ + 10) & (g_ > b_ + 10)).mean() > 0.25:
                    return True
            return False

        # Frame each pick in turn; a rejected one is replaced by the next of its kind.
        # The train opener is framed inside the retry loop below
        def take(pool, train=False):
            for r in pool:
                if id(r) in tried or not far(r, [q for q, _ in framed]):
                    continue
                tried.add(id(r))
                c = frame(r, train)
                if c:
                    framed.append((r, c))
                    return True
            return False

        # Every cut must show a moving train (Stephen, Nov. 14). Regional Rail
        # positions update less often than buses, so if no train is moving in
        # view, wait for fresh feed updates and try again.
        for attempt in range(1, ATTEMPTS + 1):
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{URL}#x=50000&y=58000&z=0.3")
            # Only the map and vehicles: no bar, buttons or credits, and no weather
            # badge or animation (the real temperature would clash with the simulated
            # storm in scripts/43_feature_promo.py, and the badge sits in the vertical
            # cut's unsafe corner)
            page.add_style_tag(content=".bar, .controls, .credits, #temp, .weather-layer { display: none !important; }")
            # Two feed updates after the first: vehicles that reported since are gliding
            for _ in range(3):
                with page.expect_response(lambda r: "vehicles.json" in r.url, timeout=40000):
                    pass
            time.sleep(1.5)  # let the update's route shapes load and apply
            page.route("**/live/vehicles.json", lambda route: route.abort())
            page.evaluate(CLOCK)  # from here the layer's time moves only with __step
            page.evaluate("__step(0)")
            spots = candidates()
            trains = [r for r in score(page, [c for c in spots if c[0] == "rail"]) if "rail" in r[4]["kinds"]]
            framed, tried = [], set()
            if trains and take(trains, train=True):
                break
            print(f"attempt {attempt}: no moving train in a clean view; waiting for fresh updates")
            page.close()
        else:
            raise SystemExit(f"no moving Regional Rail train in a clean view after {ATTEMPTS} attempts; try again later")

        # Then the best trolley and bus spots, then the next best overall
        scored = score(page, [c for c in spots if c[0] != "rail"])
        for want in ("trolley", "bus")[:max(0, args.cuts - 1)]:
            take([r for r in scored if want in r[4]["kinds"]])
        while len(framed) < args.cuts and take([r for r in scored + trains if r[4]["moving"]]):
            pass
        print("scenes:", [(r[1], round(c[0]), round(c[1]), r[4]) for r, c in framed])

        n = 0
        for r, center in framed:
            page.evaluate(GOTO, [*center, args.zoom, *off])
            settle()
            for _ in range(per):
                page.evaluate(f"__step({1000 / args.fps})")
                page.screenshot(path=str(frames_dir / f"{n:05d}.png"))
                n += 1
        browser.close()

    # Address and caption on every frame (the source line was dropped from promos, Nov. 13)
    for f in sorted(frames_dir.glob("*.png")):
        img = Image.open(f).convert("RGB")
        fly.draw_overlays(img, caption=args.caption, label=LABEL, credit="", safe=safe)
        img.save(f)
    out = OUT / f"{args.name}.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", str(args.fps),
                    "-i", str(frames_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-movflags", "+faststart", str(out)], check=True)
    print(f"{out}: {n} frames, {n / args.fps:.1f} s, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
