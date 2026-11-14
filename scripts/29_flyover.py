"""Render a flyover video over a finished map's Deep Zoom tiles.

No GPU and no browser: each video frame is cut straight from the DZI pyramid
(output/<area>/tiles/<version>/map_files) and piped to ffmpeg (the static
binary bundled with the imageio-ffmpeg package, so nothing is installed
system-wide).

Camera path: config/flyover/<name>.json, a start point and a list of shots
(see that file's "about"). Two choices matter for pixel art:
- Close-ups use nearest-neighbor. Keep close-up scales at whole-number
  ratios (1, 0.5) and pan at a constant scale, so the drawn pixels stay
  square instead of blurring or shimmering.
- Zooms interpolate scale geometrically and move the center in proportion
  to the zoom, so a pull-back stays anchored on where it started instead of
  sliding sideways first.

Shot types (each runs from where the previous shot ended):
- "hold": stay still.
- "lonlat" (+ optional "z", "scale", and "offset": [dx, dy] in map px to
  aim beside the point, e.g. onto a bridge deck): move to a point, zooming if the scale
  changes. "fit": zoom out to the whole map.
- "by": [dx, dy]: pan by a fixed number of map pixels. Easier than lon/lat
  for a slow, short pan across one scene.
- "via": [point, ...]: one continuous sweep through several points (each a
  "lonlat" with optional "z", "offset", "scale", "caption"), on a smooth
  curve at a steady speed, easing in and out over the first and last "ramp"
  share of the time (default 0.25). Each point's caption takes over halfway
  to it.
- "cut": jump to a new scene ("lonlat"), crossfading from the old view over
  the shot's seconds. Both views stay still during the fade. A cut back to
  the start view at the end makes a clean loop for a GIF.
- "caption": text shown in the lower left from this shot on, until another
  shot sets a new one ("" clears it). The start can set one too.

Config options for the text on screen: "credit" (optional, always shown), "label"
(optional, always shown, e.g. the site address) and "safe" (optional margins
in px for TikTok/Reels, whose buttons and captions cover the frame's edges;
all text is then centered inside the safe box; see draw_overlays).

Usage:
  uv run python scripts/29_flyover.py preview              # full video
  uv run python scripts/29_flyover.py preview --seconds 10 # first 10 s only
  uv run python scripts/29_flyover.py promo --size 1080x1080   # square cut
  uv run python scripts/29_flyover.py promo_loop --gif 640     # also a GIF, 640 px wide
Writes output/flyover/<name>[_<W>x<H>][_<seconds>s].mp4 (and .gif)
"""

import argparse
import json
import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pixelphilly.projection import REPO_ROOT, IsoCamera, LocalFrame

TS = 512  # DZI tile size (map.dzi TileSize, Overlap 0)


def smoothstep(t):
    # Ease in and out: zero speed at both ends of every shot
    return t * t * (3 - 2 * t)


def ramp(t, r):
    """Share of a sweep's length covered at time t (0..1): speed up over the
    first r of the time, cruise at a steady speed, slow down over the last r.
    Peak speed is 1 / (1 - r) times the average, gentler than smoothstep's 1.5x."""
    if r <= 0:
        return t
    if t < r:
        return t * t / (2 * r * (1 - r))
    if t > 1 - r:
        return 1 - (1 - t) ** 2 / (2 * r * (1 - r))
    return (t - r / 2) / (1 - r)


def sweep_curve(points, samples=400):
    """A Catmull-Rom curve through `points` (it passes through every one),
    sampled densely. Returns the samples, the distance along the curve at each
    sample, and the distance at each point, so motion can be spaced by
    distance (steady speed) rather than by curve parameter."""
    P = np.asarray(points, float)
    ext = np.vstack([P[0], P, P[-1]])  # repeat the ends so the curve starts and stops on them
    t = np.linspace(0, 1, samples + 1)[1:, None]
    xy, knots = [P[0]], [0]
    for i in range(len(P) - 1):
        p0, p1, p2, p3 = ext[i:i + 4]
        seg = 0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                     + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3)
        xy.extend(seg)
        knots.append(len(xy) - 1)
    xy = np.array(xy)
    dist = np.r_[0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    return xy, dist, dist[knots]


class Pyramid:
    def __init__(self, tiles_dir):
        self.dir = tiles_dir
        meta = json.loads((tiles_dir / "map.json").read_text())
        self.w, self.h = meta["width"], meta["height"]
        self.ox, self.oy = meta["lattice_origin_px"]
        self.bg = tuple(int(meta["background"][i:i + 2], 16) for i in (1, 3, 5))
        self.max_level = max(int(p.name) for p in (tiles_dir / "map_files").iterdir() if p.name.isdigit())
        # All citywide regions share one camera and projection origin, so any
        # region config converts lon/lat to merged-map pixels
        cfg = json.loads((REPO_ROOT / "config" / "west_north.json").read_text())
        self.cam = IsoCamera.from_config(cfg)
        self.lf = LocalFrame(cfg["bbox_wgs84"], cfg["projection_origin"])
        self.tile = lru_cache(maxsize=800)(self._tile)

    def to_px(self, lon, lat, z=0.0):
        # z (meters above ground) aims at a height, e.g. a tower's top: in the
        # isometric view a tall building's base is hidden behind the towers
        # south of it, so aiming at the ground point can miss the landmark
        e, n = self.lf.to_local(np.asarray(lon), np.asarray(lat))
        sx, sy = self.cam.world_to_screen(e, n, float(z))
        return float(sx - self.ox), float(sy - self.oy)

    def _tile(self, level, tx, ty):
        f = self.dir / "map_files" / str(level) / f"{tx}_{ty}.webp"
        return Image.open(f).convert("RGB") if f.exists() else None

    def window(self, cx, cy, scale, out_w, out_h):
        """The out_w x out_h view centered on (cx, cy) in full-resolution map px,
        at `scale` map px per output px."""
        # Coarsest level that still has at least one level px per output px
        down = 2 ** max(0, min(self.max_level, int(math.floor(math.log2(max(scale, 1.0))))))
        level = self.max_level - int(math.log2(down))
        s = scale / down  # level px per output px
        x0, y0 = cx / down - out_w * s / 2, cy / down - out_h * s / 2
        x1, y1 = x0 + out_w * s, y0 + out_h * s
        ix0, iy0, ix1, iy1 = math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)
        canvas = Image.new("RGB", (ix1 - ix0, iy1 - iy0), self.bg)
        for ty in range(max(0, iy0 // TS), iy1 // TS + 1):
            for tx in range(max(0, ix0 // TS), ix1 // TS + 1):
                t = self.tile(level, tx, ty)
                if t is not None:
                    canvas.paste(t, (tx * TS - ix0, ty * TS - iy0))
        box = (x0 - ix0, y0 - iy0, x1 - ix0, y1 - iy0)
        # Magnifying: nearest keeps pixel art crisp. Shrinking: box filter
        # averages, which avoids shimmer on the zoom-out.
        resample = Image.NEAREST if s <= 1 else Image.BOX
        return canvas.resize((out_w, out_h), resample, box=box)


def camera_path(cfg, pyr):
    """Yield one dict per frame. "view" is (cx, cy, scale) and "caption" the
    text over it. During a cut, "prev" holds the view being faded out (as
    {"view", "caption"}) and "alpha" the new view's weight; otherwise prev is
    None and alpha 1."""
    out_w, out_h = cfg["size"]
    fps = cfg["fps"]
    fit_scale = max(pyr.w / out_w, pyr.h / out_h) * 1.04
    def point(spec, scale):
        x, y = pyr.to_px(*spec["lonlat"], spec.get("z", 0.0))
        dx, dy = spec.get("offset", (0, 0))
        return x + dx, y + dy, spec.get("scale", scale)

    start = cfg["start"]
    cur = point(start, start["scale"])
    caption = start.get("caption")
    for shot in cfg["shots"]:
        n = max(1, round(shot["seconds"] * fps))
        if shot.get("cut"):
            target = point(shot, cur[2])
            new_caption = shot.get("caption", caption)
            prev = {"view": cur, "caption": caption}
            for i in range(1, n + 1):
                yield {"view": target, "caption": new_caption, "prev": prev, "alpha": smoothstep(i / n)}
            cur, caption = target, new_caption
            continue
        if "via" in shot:
            # One continuous move through several points: no stop at each one
            pts = [cur] + [point(v, cur[2]) for v in shot["via"]]
            xy, dist, at = sweep_curve([q[:2] for q in pts])
            log_s = [math.log(q[2]) for q in pts]
            caps = [caption] + [v.get("caption", caption) for v in shot["via"]]
            switch = (at[:-1] + at[1:]) / 2  # a waypoint's caption takes over halfway to it
            for i in range(1, n + 1):
                d = ramp(i / n, shot.get("ramp", 0.25)) * dist[-1]
                caption = caps[int(np.searchsorted(switch, d, side="right"))]
                view = (float(np.interp(d, dist, xy[:, 0])), float(np.interp(d, dist, xy[:, 1])),
                        math.exp(float(np.interp(d, at, log_s))))
                yield {"view": view, "caption": caption, "prev": None, "alpha": 1.0}
            cur = pts[-1]
            continue
        caption = shot.get("caption", caption)
        if shot.get("hold"):
            target = cur
        elif shot.get("fit"):
            target = (pyr.w / 2, pyr.h / 2, fit_scale)
        elif "by" in shot:
            target = (cur[0] + shot["by"][0], cur[1] + shot["by"][1], shot.get("scale", cur[2]))
        else:
            target = point(shot, cur[2])
        (ax, ay, a_s), (bx, by, b_s) = cur, target
        for i in range(1, n + 1):
            u = smoothstep(i / n)
            s = math.exp(math.log(a_s) + (math.log(b_s) - math.log(a_s)) * u)
            if abs(b_s - a_s) > 1e-9 and max(a_s, b_s) / min(a_s, b_s) > 4:
                # Big zoom: move the center in step with the zoom so the
                # start point stays in view instead of sliding off first
                k = (s - a_s) / (b_s - a_s)
            else:
                k = u
            yield {"view": (ax + (bx - ax) * k, ay + (by - ay) * k, s), "caption": caption, "prev": None, "alpha": 1.0}
        cur = target


BOX, INK = (20, 24, 32), (235, 238, 242)


def _measure(text, size, pad):
    l, t, r, b = ImageFont.load_default(size=size).getbbox(text)
    return (r - l) + 2 * pad, (b - t) + 2 * pad


def _text_box(img, text, size, pad, x, y, align):
    """Light text on a dark box with its top at y; x is the box's left edge,
    right edge or center, per `align`."""
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=size)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    w, h = (r - l) + 2 * pad, (b - t) + 2 * pad
    x0 = round({"left": x, "right": x - w, "center": x - w / 2}[align])
    d.rectangle([x0, y, x0 + w - 1, y + h - 1], fill=BOX)
    d.text((x0 + pad - l, y + pad - t), text, fill=INK, font=font)


def credit_size(img):
    # From the short side, so a vertical frame's credit line still fits its width
    return max(14, min(img.width, img.height) // 60)


def draw_overlays(img, caption=None, label=None, credit="", safe=None):
    """Draw the scene caption, the always-on label (e.g. the site address) and
    the credit line. Empty or None parts are skipped.

    Without `safe`: credit lower right, caption lower left above it, label
    upper left. With `safe` ({"top", "right", "bottom", "left"} in px, the
    margins TikTok and Reels cover with their own buttons and captions):
    everything is centered in the safe box, label at its top, caption in a
    fixed slot under the label (so it never jumps), credit at its bottom."""
    W, H = img.size
    cs = credit_size(img)
    if safe is None:
        m = max(12, H // 40)
        cap = max(24, min(W, H) // 22)
        if credit:
            _text_box(img, credit, cs, 8, W - m, H - m - _measure(credit, cs, 8)[1], "right")
        if caption:
            lift = cs + 16 + m  # the credit line's height plus margin
            _text_box(img, caption, cap, cap // 3, m, H - m - lift - _measure(caption, cap, cap // 3)[1], "left")
        if label:
            _text_box(img, label, cap, cap // 3, m, m, "left")
        return img
    x0, x1 = safe["left"], W - safe["right"]
    y0, y1 = safe["top"], H - safe["bottom"]
    cx = (x0 + x1) / 2
    ls = min(W, H) // 20          # label: the largest text on screen
    cap = min(W, H) // 26
    slot = round(ls * 1.3) + 2 * (ls // 3) + ls // 3  # label box plus a gap, reserved even without a label
    if label:
        _text_box(img, label, ls, ls // 3, cx, y0, "center")
    if caption:
        _text_box(img, caption, cap, cap // 3, cx, y0 + slot, "center")
    if credit:
        _text_box(img, credit, cs, 8, cx, y1 - _measure(credit, cs, 8)[1], "center")
    return img


def parse_size(text):
    w, sep, h = text.partition("x")
    if not sep:
        raise ValueError(f"size must look like 1080x1920, not {text!r}")
    return int(w), int(h)


def render_frame(pyr, frame, out_w, out_h, cfg):
    safe = cfg.get("safe")

    def one(view, caption):
        return draw_overlays(pyr.window(*view, out_w, out_h), caption=caption, safe=safe)

    img = one(frame["view"], frame["caption"])
    if frame["prev"] is not None and frame["alpha"] < 1:
        # Captions fade with their scenes; the label and credit stay put
        img = Image.blend(one(frame["prev"]["view"], frame["prev"]["caption"]), img, frame["alpha"])
    return draw_overlays(img, label=cfg.get("label"), credit=cfg.get("credit", ""), safe=safe)


def write_gif(ffmpeg, mp4, gif, width, fps):
    """Two-pass GIF: build one 256-color palette for the whole clip, then map
    every frame to it. Area scaling averages whole pixels, which keeps the
    pixel art cleaner than a smoothing filter."""
    import subprocess

    vf = (f"fps={fps},scale={width}:-2:flags=area,split[a][b];"
          "[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp4), "-vf", vf, "-loop", "0", str(gif)],
                   check=True)


def main():
    import imageio_ffmpeg

    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="config/flyover/<name>.json")
    ap.add_argument("--seconds", type=float, help="render only the first N seconds (a test cut)")
    ap.add_argument("--size", type=parse_size, help="override the config's size, e.g. 1080x1080 or 1080x1920")
    ap.add_argument("--gif", type=int, metavar="WIDTH", help="also write a GIF this many pixels wide")
    ap.add_argument("--gif-fps", type=int, default=15, help="GIF frame rate (default 15)")
    args = ap.parse_args()
    cfg = json.loads((REPO_ROOT / "config" / "flyover" / f"{args.name}.json").read_text())
    if args.size:
        cfg["size"] = list(args.size)
    pyr = Pyramid(REPO_ROOT / "output" / "philly" / "tiles" / cfg["version"])
    out_w, out_h = cfg["size"]
    frames = list(camera_path(cfg, pyr))
    if args.seconds:
        frames = frames[: round(args.seconds * cfg["fps"])]
    suffix = (f"_{out_w}x{out_h}" if args.size else "") + (f"_{args.seconds:g}s" if args.seconds else "")
    out = REPO_ROOT / "output" / "flyover" / f"{args.name}{suffix}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    # yuv420p + faststart: plays in Keynote, PowerPoint, browsers and phones
    writer = imageio_ffmpeg.write_frames(
        str(out), (out_w, out_h), fps=cfg["fps"], codec="libx264", quality=None,
        output_params=["-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        macro_block_size=8)
    writer.send(None)
    for i, frame in enumerate(frames):
        img = render_frame(pyr, frame, out_w, out_h, cfg)
        writer.send(np.asarray(img).tobytes())
        if i % cfg["fps"] == 0:
            print(f"  {i / cfg['fps']:5.1f} s  scale {frame['view'][2]:7.2f}", flush=True)
    writer.close()
    print(f"{len(frames)} frames -> {out} ({out.stat().st_size / 1e6:.1f} MB)")
    if args.gif:
        gif = out.with_suffix(".gif")
        write_gif(imageio_ffmpeg.get_ffmpeg_exe(), out, gif, args.gif, args.gif_fps)
        print(f"GIF -> {gif} ({gif.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
