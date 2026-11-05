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

Usage:
  uv run python scripts/29_flyover.py preview              # full video
  uv run python scripts/29_flyover.py preview --seconds 10 # first 10 s only
Writes output/flyover/<name>[_<seconds>s].mp4
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
    """Yield (cx, cy, scale) for every frame."""
    out_w, out_h = cfg["size"]
    fps = cfg["fps"]
    fit_scale = max(pyr.w / out_w, pyr.h / out_h) * 1.04
    cur = (*pyr.to_px(*cfg["start"]["lonlat"], cfg["start"].get("z", 0.0)), cfg["start"]["scale"])
    for shot in cfg["shots"]:
        n = max(1, round(shot["seconds"] * fps))
        if shot.get("hold"):
            target = cur
        elif shot.get("fit"):
            target = (pyr.w / 2, pyr.h / 2, fit_scale)
        else:
            target = (*pyr.to_px(*shot["lonlat"], shot.get("z", 0.0)), shot.get("scale", cur[2]))
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
            yield ax + (bx - ax) * k, ay + (by - ay) * k, s
        cur = target


def credit_overlay(img, text):
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=max(14, img.height // 60))
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    pad = 8
    x, y = img.width - (r - l) - 2 * pad - 12, img.height - (b - t) - 2 * pad - 12
    d.rectangle([x, y, x + (r - l) + 2 * pad, y + (b - t) + 2 * pad], fill=(20, 24, 32))
    d.text((x + pad - l, y + pad - t), text, fill=(235, 238, 242), font=font)
    return img


def main():
    import imageio_ffmpeg

    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="config/flyover/<name>.json")
    ap.add_argument("--seconds", type=float, help="render only the first N seconds (a test cut)")
    args = ap.parse_args()
    cfg = json.loads((REPO_ROOT / "config" / "flyover" / f"{args.name}.json").read_text())
    pyr = Pyramid(REPO_ROOT / "output" / "philly" / "tiles" / cfg["version"])
    out_w, out_h = cfg["size"]
    frames = list(camera_path(cfg, pyr))
    if args.seconds:
        frames = frames[: round(args.seconds * cfg["fps"])]
    suffix = f"_{args.seconds:g}s" if args.seconds else ""
    out = REPO_ROOT / "output" / "flyover" / f"{args.name}{suffix}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    # yuv420p + faststart: plays in Keynote, PowerPoint, browsers and phones
    writer = imageio_ffmpeg.write_frames(
        str(out), (out_w, out_h), fps=cfg["fps"], codec="libx264", quality=None,
        output_params=["-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        macro_block_size=8)
    writer.send(None)
    for i, (cx, cy, s) in enumerate(frames):
        img = credit_overlay(pyr.window(cx, cy, s, out_w, out_h), cfg["credit"])
        writer.send(np.asarray(img).tobytes())
        if i % cfg["fps"] == 0:
            print(f"  {i / cfg['fps']:5.1f} s  scale {s:7.2f}", flush=True)
    writer.close()
    print(f"{len(frames)} frames -> {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
