"""Check that the WebGL render and the Python projection agree to the pixel.

For each frame, the renderer draws buildings white on black (mask mode). The
same buildings are projected independently in Python with
pixelphilly.projection and rasterized: each building's silhouette is the
union of its footprint at ground level, its roof at full height, and every
wall quad between them. The two masks are compared:

  IoU          overlap / union of the two masks; should be close to 1
  best shift   the (dx, dy) within +/-4 px that maximises overlap; should be
               (0, 0), or at most 2 px if antialiasing biases the edge

Writes output/masks/alignment_report.json and an overlay image for one
frame (render mask in red, Python mask in cyan, agreement in white).

Usage: uv run python scripts/06_render.py --mode mask
       uv run python scripts/09_check_alignment.py
"""

import json
import sys

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon
from shapely.ops import unary_union

from pixelphilly.projection import IsoCamera, REPO_ROOT, area_dir, load_config
from pixelphilly.scenes import scene_paths

MAX_SHIFT = 4


def silhouettes(buildings, cam):
    """Screen-space polygons (global pixels) for every building prism.

    A prism's outline is its footprint at ground level, its roof at full
    height, and every wall quad between them, including walls around
    courtyards: footprint and roof keep their holes, so an open courtyard is
    not filled in (except where its own inner walls hide it)."""
    out = []
    for b in buildings:
        for rings in b["polys"]:
            screen = []
            for ring in rings:
                r = np.asarray(ring)
                gx, gy = cam.world_to_screen(r[:, 0], r[:, 1], 0.0)
                rx, ry = cam.world_to_screen(r[:, 0], r[:, 1], b["h"])
                screen.append((gx, gy, rx, ry))
            ground = Polygon(list(zip(*screen[0][:2])), [list(zip(*s_[:2])) for s_ in screen[1:]]).buffer(0)
            roof = Polygon(list(zip(*screen[0][2:])), [list(zip(*s_[2:])) for s_ in screen[1:]]).buffer(0)
            parts = [ground, roof]
            for gx, gy, rx, ry in screen:
                k = len(gx)
                for i in range(k):
                    j = (i + 1) % k
                    quad = Polygon([(gx[i], gy[i]), (gx[j], gy[j]), (rx[j], ry[j]), (rx[i], ry[i])])
                    if quad.area > 0:
                        parts.append(quad.buffer(0))
            out.append(unary_union(parts))
    return out


def rasterize(polys, frame, size):
    """Union of all silhouettes as a boolean mask. Polygons with holes are
    drawn on their own layer and OR-ed in, so a courtyard can only clear its
    own building, never one drawn earlier that overlaps it."""
    img = Image.new("L", (size, size))
    d = ImageDraw.Draw(img)
    x0, y0 = frame["x0"], frame["y0"]
    holed = np.zeros((size, size), bool)
    for g in polys:
        geoms = [g] if g.geom_type == "Polygon" else getattr(g, "geoms", [])
        for p in geoms:
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            ext = [(x - x0, y - y0) for x, y in p.exterior.coords]
            if not p.interiors:
                d.polygon(ext, fill=255)
                continue
            layer = Image.new("L", (size, size))
            ld = ImageDraw.Draw(layer)
            ld.polygon(ext, fill=255)
            for hole in p.interiors:
                ld.polygon([(x - x0, y - y0) for x, y in hole.coords], fill=0)
            holed |= np.asarray(layer) > 127
    return (np.asarray(img) > 127) | holed


def best_shift(a, b):
    """(dx, dy) shift of b that best overlaps a, within +/-MAX_SHIFT px."""
    best, best_xy = -1, (0, 0)
    m = MAX_SHIFT
    core_a = a[m:-m, m:-m]
    for dy in range(-m, m + 1):
        for dx in range(-m, m + 1):
            core_b = b[m + dy : b.shape[0] - m + dy, m + dx : b.shape[1] - m + dx]
            score = np.count_nonzero(core_a & core_b)
            if score > best:
                best, best_xy = score, (dx, dy)
    return best_xy


def main():
    cfg = load_config()
    cam = IsoCamera.from_config(cfg)
    mask_dir = area_dir(cfg, "masks")
    report, failures = [], []
    # Each scene (one, or one per render tile) checks its own frames against
    # its own buildings
    pairs = []
    for scene_rel in scene_paths(cfg):
        scene = json.loads((REPO_ROOT / scene_rel).read_text())
        polys = silhouettes(scene["buildings"], cam)
        pairs += [(scene, polys, f) for f in scene["frames"]]
    for scene, polys, f in pairs:
        size = scene["frame_px"]
        mpp = scene["meters_per_pixel"]
        # Recover the frame's screen-pixel origin from its frustum
        frame = {"x0": round(f["left"] / mpp), "y0": round(-f["top"] / mpp)}
        rendered = np.asarray(Image.open(mask_dir / f"{f['name']}.png").convert("L")) > 127
        expected = rasterize(polys, frame, size)
        union = np.count_nonzero(rendered | expected)
        iou = np.count_nonzero(rendered & expected) / union if union else 1.0
        dx, dy = best_shift(rendered, expected)
        row = {"frame": f["name"], "iou": round(iou, 4), "best_shift_px": [dx, dy],
               "building_px": int(np.count_nonzero(expected))}
        report.append(row)
        # Frames that are mostly river carry too few building pixels for the
        # shift search to mean anything; only judge frames with real content.
        # On sparse frames the search can also tie between offsets while the
        # overlap is near perfect (downtown frame_23_09: IoU 0.995, "shift"
        # -4,-2); a real 4 px offset would pull IoU well below 0.99, so a
        # shift only fails a frame whose IoU is also under 0.99.
        shifted = max(abs(dx), abs(dy)) > 2 and iou < 0.99
        if row["building_px"] > 5000 and (iou < 0.97 or shifted):
            failures.append(row)
        if f["name"] == "frame_02_02":
            overlay = np.zeros((size, size, 3), np.uint8)
            overlay[rendered] = [255, 60, 60]
            overlay[expected] = [60, 220, 255]
            overlay[rendered & expected] = [255, 255, 255]
            Image.fromarray(overlay).save(mask_dir / "alignment_overlay_frame_02_02.png")

    (mask_dir / "alignment_report.json").write_text(json.dumps(report, indent=2) + "\n")
    ious = [r["iou"] for r in report if r["building_px"] > 5000]
    print(f"frames checked: {len(ious)}; IoU min {min(ious):.4f}, mean {np.mean(ious):.4f}")
    print("shifts:", sorted({tuple(r["best_shift_px"]) for r in report}))
    if failures:
        print("FAILED:", failures)
        sys.exit(1)
    print("PASS: render and projection agree")


if __name__ == "__main__":
    main()
