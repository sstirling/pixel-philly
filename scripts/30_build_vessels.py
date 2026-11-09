"""Build reviewed vessel outlines (config/vessels.json "vessels") from the
traces (data/processed/vessels_draft.json, scripts/29_trace_vessels.py) and
the reviewer's reading of each sheet (config/vessels.json "review").

Per listed hull: the union of its traces, then the shape ops (in the 2024
aerial's pixel space, meters converted at the tile scale):
- open:<m>: drop parts thinner than 2 x m (pier strips, a sailing ship's
  yards, a submarine alongside);
- hull: convex hull (container ships cut apart by crane booms);
- rect: minimum rotated rectangle (a shaded deck edge the trace missed);
- split=k: a nest of k hulls side by side, cut along the long axis at the
  k-1 darkest lines across the beam (the gap between hulls), nearest the
  even spacing.
Rejected traces are dropped; traces neither listed nor rejected stay as
"protect" entries (the repaint leaves them alone; no 3D). Each vessel gets
its kind's default height (kind_defaults_m, an assumption); the scene build
replaces it with LiDAR heights where the 2022 LiDAR saw the same hull.

    uv run python scripts/30_build_vessels.py
"""

import datetime
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("trace29", REPO_ROOT / "scripts" / "29_trace_vessels.py")
trace29 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trace29)


def to_px(g, origin):
    import shapely

    def f(c):
        x, y = trace29.merc_px(c[:, 0], c[:, 1])
        return np.column_stack([x - origin[0], y - origin[1]])

    return shapely.transform(g, f)


def to_lonlat(g, origin):
    import shapely

    def f(c):
        lon, lat = trace29.px_lonlat(c[:, 0] + origin[0], c[:, 1] + origin[1])
        return np.column_stack([lon, lat])

    return shapely.transform(g, f)


def largest(g):
    return max(getattr(g, "geoms", [g]), key=lambda p: p.area)


def parts_of(g):
    return sorted([p for p in getattr(g, "geoms", [g]) if p.area > 0], key=lambda p: -p.area)


def split_nest(poly, k, rgb):
    """Cut a nest of k side-by-side hulls along their long axis at the
    darkest across-beam lines near i/k of the beam."""
    from rasterio.features import rasterize
    from shapely.geometry import Polygon, box
    from shapely.affinity import rotate

    rect = poly.minimum_rotated_rectangle
    c = np.asarray(rect.exterior.coords)[:4]
    e = [np.hypot(*(c[(i + 1) % 4] - c[i])) for i in range(4)]
    i = int(np.argmax(e[:2]))
    long_vec = c[i + 1] - c[i]
    ang = math.degrees(math.atan2(long_vec[1], long_vec[0]))
    # Rotate so the long axis is horizontal; rows are across the beam
    rp = rotate(poly, -ang, origin=(0, 0))
    minx, miny, maxx, maxy = rp.bounds
    mask = rasterize([(poly, 1)], out_shape=rgb.shape[:2], fill=0, dtype="uint8").astype(bool)
    ys, xs = np.nonzero(mask)
    v = rgb[ys, xs].max(axis=1).astype(float)
    a = math.radians(-ang)
    yr = xs * math.sin(a) + ys * math.cos(a)  # across-beam coordinate after rotation
    bins = np.arange(miny, maxy + 2, 2.0)
    idx = np.clip(np.digitize(yr, bins) - 1, 0, len(bins) - 2)
    prof = np.array([v[idx == b].mean() if (idx == b).sum() > 20 else np.nan for b in range(len(bins) - 1)])
    width = maxy - miny
    cuts = []
    for j in range(1, k):
        target = miny + width * j / k
        lo, hi = target - width / (4 * k), target + width / (4 * k)
        sel = [b for b in range(len(prof)) if lo <= bins[b] <= hi and np.isfinite(prof[b])]
        b = min(sel, key=lambda b: prof[b]) if sel else int((target - miny) / 2)
        cuts.append(bins[b] + 1.0)
    edges = [miny - 1] + cuts + [maxy + 1]
    out = []
    for y0, y1 in zip(edges[:-1], edges[1:]):
        strip = rotate(box(minx - 1, y0, maxx + 1, y1), ang, origin=(0, 0))
        piece = poly.intersection(strip)
        if not piece.is_empty:
            out.append(piece)
    return out


def apply_ops(poly, ops, mpp):
    for op in ops or []:
        if op.startswith("open:"):
            r = float(op.split(":")[1]) / mpp
            opened = poly.buffer(-r, join_style=2).buffer(r, join_style=2)
            if not opened.is_empty:  # keep every substantial piece (a hull cut by a boom stays whole)
                big = largest(opened).area
                from shapely.ops import unary_union as _uu
                poly = _uu([p for p in getattr(opened, 'geoms', [opened]) if p.area >= 0.1 * big])
        elif op == "hull":
            poly = poly.convex_hull
        elif op == "rect":
            poly = poly.minimum_rotated_rectangle
    return poly


def main():
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    cfg_path = REPO_ROOT / "config" / "vessels.json"
    cfg = json.loads(cfg_path.read_text())
    draft = json.loads((REPO_ROOT / "data" / "processed" / "vessels_draft.json").read_text())
    review, defaults = cfg["review"], cfg["kind_defaults_m"]
    today = datetime.date.today().isoformat()
    out = []
    for gid, g in cfg["groups"].items():
        traces = {int(t["id"].split("-")[1]): t for t in draft.get(gid, [])}
        rv = review.get(gid, {})
        used = set()
        w, s, e, n = g["bbox"]
        m = trace29.MARGIN_DEG
        rgb, origin = trace29.aerial(w - m, s - m, e + m, n + m)
        mpp = 156543.03 * math.cos(math.radians((s + n) / 2)) / 2 ** trace29.Z
        k_hull = 0
        for h in rv.get("hulls", []):
            missing = [t for t in h["traces"] if t not in traces]
            if missing:
                raise SystemExit(f"{gid}: traces {missing} not in the draft (re-run 29 and re-review)")
            used |= set(h["traces"])
            close = 3.0 / mpp  # join a hull's stern and bow pieces the deck trace split
            U = unary_union([to_px(shape(traces[t]["geometry"]), origin) for t in h["traces"]]).buffer(close).buffer(-close)
            if "clip" in h:
                from shapely.geometry import box as _box
                U = U.intersection(to_px(_box(*h["clip"]), origin))
            ops = h.get("shape", [])
            comps = parts_of(apply_ops(U, [o for o in ops if o.startswith("open:")], mpp)) if h.get("components") == "each" \
                else [apply_ops(U, [o for o in ops if o.startswith("open:")], mpp)]
            splits = h.get("split_each") or [h.get("split", 1)] * len(comps)
            for comp, kk in zip(comps, splits):
                comp = apply_ops(comp, [o for o in ops if not o.startswith("open:")], mpp)
                # Each hull of a nest is its strip's convex hull: hulls are convex
                # in plan apart from the bow, and strips can come out in pieces
                opens = [o for o in ops if o.startswith("open:")]
                pieces = [apply_ops(p, opens, mpp).convex_hull for p in split_nest(comp, kk, rgb)] if kk > 1 else [comp]
                for piece in pieces:
                    k_hull += 1
                    ll = to_lonlat(piece.simplify(1.5), origin)
                    px_mask_color = None
                    out.append({
                        "id": f"{gid}-h{k_hull}", "group": gid, "area": g["area"], "status": "accepted",
                        "kind": h["kind"], **({"name": h["name"]} if "name" in h else {}),
                        "flat": bool(h.get("flat", False)), "base": h.get("base", "water"),
                        "h": float(defaults[h["kind"]]), "h_source": "default",
                        "from_traces": h["traces"], "area_m2": round(piece.area * mpp * mpp),
                        **({"note": h["note"]} if "note" in h else {}),
                        "reviewed": today, "source": "City of Philadelphia 2024 3-inch aerial (z19 tiles)",
                        "geometry": mapping(ll)})
        for t, tr in traces.items():
            if t in used:
                continue
            status = "rejected" if t in set(rv.get("reject", [])) else "protect"
            out.append({"id": tr["id"], "group": gid, "area": g["area"], "status": status, "kind": "unclassified",
                        "flat": True, "h": 4.0, "h_source": "default", "area_m2": tr["area_m2"],
                        "reviewed": today, "source": "City of Philadelphia 2024 3-inch aerial (z19 tiles)",
                        "geometry": tr["geometry"]})
        print(gid, k_hull, "hulls;", sum(1 for v in out if v["group"] == gid and v["status"] == "protect"), "protect-only;",
              sum(1 for v in out if v["group"] == gid and v["status"] == "rejected"), "rejected")
    cfg["vessels"] = out
    cfg_path.write_text(json.dumps(cfg, indent=1) + "\n")
    review_sheets(cfg, out)


def review_sheets(cfg, vessels_out):
    """output/review/vessels/hulls_<group>.jpg: hulls (magenta, with ids),
    protect-only traces (cyan), rejected (red), on the 2024 aerial."""
    from PIL import Image, ImageDraw, ImageFont
    from shapely.geometry import shape

    font = ImageFont.load_default(size=22)
    out_dir = REPO_ROOT / "output" / "review" / "vessels"
    for gid, g in cfg["groups"].items():
        w, s, e, n = g["bbox"]
        m = trace29.MARGIN_DEG
        rgb, origin = trace29.aerial(w - m, s - m, e + m, n + m)
        im = Image.fromarray(rgb.copy())
        d = ImageDraw.Draw(im)
        for v in [v for v in vessels_out if v["group"] == gid]:
            col = {"accepted": (255, 0, 255), "protect": (0, 220, 255), "rejected": (255, 40, 40)}[v["status"]]
            p = to_px(shape(v["geometry"]), origin)
            for pg in getattr(p, "geoms", [p]):
                d.line([tuple(c) for c in np.asarray(pg.exterior.coords)], fill=col, width=4)
            if v["status"] == "accepted":
                x, y = p.representative_point().coords[0]
                d.text((x, y), v["id"].split("-")[1] + (" flat" if v["flat"] else ""), fill=(255, 255, 0), font=font,
                       stroke_width=2, stroke_fill=(0, 0, 0))
        im.thumbnail((1800, 1800))
        ImageDraw.Draw(im).text((8, 8), f"{gid}: hulls (magenta), protect only (cyan), rejected (red). 2024 City aerial",
                                fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
        im.save(out_dir / f"hulls_{gid}.jpg", quality=85)


if __name__ == "__main__":
    main()
