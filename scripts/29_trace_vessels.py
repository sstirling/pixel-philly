"""Trace vessel outlines from the 2024 aerial for review (pixelphilly.vessels).

For each seed group in config/vessels.json ("groups": a bbox around a berth),
loads the cached z19 City aerial tiles, marks river pixels (NHD and PWD
water polygons) minus OSM piers, and traces hull candidates (vessels.trace).
Writes data/processed/vessels_draft.json (WGS84 polygons, area, mean deck
color) and a review sheet per group in output/review/vessels/trace_<group>.jpg
with numbered outlines. A person then accepts, rejects or edits each trace
into config/vessels.json "vessels" (status "accepted"/"rejected").

    uv run python scripts/29_trace_vessels.py [--groups N1,P1]
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pixelphilly import vessels  # noqa: E402
from pixelphilly.sources import RAW  # noqa: E402

Z = 19
TILE = 256
MARGIN_DEG = 0.0006  # ~50 m around the seed box


def merc_px(lon, lat, z=Z):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    s = TILE * 2 ** z
    r = np.radians(lat)
    return (lon + 180) / 360 * s, (1 - np.log(np.tan(r) + 1 / np.cos(r)) / math.pi) / 2 * s


def px_lonlat(x, y, z=Z):
    s = TILE * 2 ** z
    lon = np.asarray(x) / s * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * np.asarray(y) / s))))
    return lon, lat


def aerial(w, s, e, n):
    x0, y1 = merc_px(w, s)
    x1, y0 = merc_px(e, n)
    X0, Y0, X1, Y1 = int(x0), int(y0), int(np.ceil(x1)), int(np.ceil(y1))
    img = Image.new("RGB", (X1 - X0, Y1 - Y0))
    for tx in range(X0 // TILE, (X1 - 1) // TILE + 1):
        for ty in range(Y0 // TILE, (Y1 - 1) // TILE + 1):
            p = RAW / "imagery" / "CityImagery_2024_3in" / str(Z) / f"{ty}_{tx}.jpg"
            if p.exists():
                img.paste(Image.open(p).convert("RGB"), (tx * TILE - X0, ty * TILE - Y0))
    return np.asarray(img), (X0, Y0)


def raster(geoms, origin, shape):
    from rasterio.features import rasterize
    from shapely.affinity import affine_transform  # noqa: F401
    import shapely

    if not geoms:
        return np.zeros(shape, bool)

    def to_px(c):
        x, y = merc_px(c[:, 0], c[:, 1])
        return np.column_stack([x - origin[0], y - origin[1]])

    g = [shapely.transform(x, to_px) for x in geoms]
    return rasterize([(x, 1) for x in g if not x.is_empty], out_shape=shape, fill=0, dtype="uint8").astype(bool)


def water_geoms(area):
    from shapely.geometry import shape

    out = []
    for suffix in ("water_nhd", "water"):
        p = RAW / f"{area}_{suffix}.geojson"
        if p.exists():
            out += [shape(f["geometry"]).buffer(0) for f in json.loads(p.read_text())["features"] if f.get("geometry")]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups")
    args = ap.parse_args()
    cfg = json.loads((REPO_ROOT / "config" / "vessels.json").read_text())
    groups = cfg["groups"]
    only = set(args.groups.split(",")) if args.groups else None
    out_dir = REPO_ROOT / "output" / "review" / "vessels"
    out_dir.mkdir(parents=True, exist_ok=True)
    draft_path = REPO_ROOT / "data" / "processed" / "vessels_draft.json"
    draft = json.loads(draft_path.read_text()) if draft_path.exists() and only else {}
    font = ImageFont.load_default(size=20)
    from shapely.geometry import Polygon

    for gid, g in groups.items():
        if only and gid not in only:
            continue
        w, s, e, n = g["bbox"]
        w, s, e, n = w - MARGIN_DEG, s - MARGIN_DEG, e + MARGIN_DEG, n + MARGIN_DEG
        rgb, origin = aerial(w, s, e, n)
        water = raster(water_geoms(g["area"]), origin, rgb.shape[:2])
        pp = RAW / f"{g['area']}_piers.json"
        piers = vessels.pier_polygons(json.loads(pp.read_text())["elements"]) if pp.exists() else []
        pier = raster(piers, origin, rgb.shape[:2])
        mpp = 156543.03 * math.cos(math.radians((s + n) / 2)) / 2 ** Z
        comps = vessels.trace(rgb, water, pier, mpp, deck_v=g.get("deck_v", vessels.DECK_V))
        sheet = Image.fromarray(rgb.copy())
        d = ImageDraw.Draw(sheet)
        for py in vessels.pier_polygons(json.loads(pp.read_text())["elements"]) if pp.exists() else []:
            for pg in getattr(py, "geoms", [py]):
                x, y = merc_px(*np.asarray(pg.exterior.coords).T)
                d.line(list(zip(x - origin[0], y - origin[1])), fill=(0, 200, 255), width=2)
        traces = []
        for k, m in enumerate(comps):
            from rasterio.features import shapes
            from shapely.geometry import shape

            polys = [shape(geom) for geom, _ in shapes(m.astype(np.uint8), mask=m, connectivity=8)]
            poly = max(polys, key=lambda p: p.area)
            # Close notches around deck fittings per hull (vector closing, ~2.5 m),
            # so nested hulls, traced apart, stay apart
            close_px = 2.5 / mpp
            poly = Polygon(poly.exterior).buffer(close_px, join_style=1).buffer(-close_px, join_style=1)
            poly = max(getattr(poly, 'geoms', [poly]), key=lambda p: p.area)
            poly = Polygon(poly.exterior).simplify(2.0)  # ~0.5 m
            c = np.asarray(poly.exterior.coords)
            lon, lat = px_lonlat(c[:, 0] + origin[0], c[:, 1] + origin[1])
            color = np.median(rgb[m], axis=0).round().astype(int).tolist()
            area_m2 = poly.area * mpp * mpp
            tid = f"{gid}-{k + 1}"
            traces.append({"id": tid, "group": gid, "area_m2": round(area_m2), "deck_rgb": color,
                           "geometry": {"type": "Polygon",
                                        "coordinates": [[[round(float(a), 7), round(float(b), 7)] for a, b in zip(lon, lat)]]}})
            d.line([tuple(p) for p in c], fill=(255, 0, 255), width=3)
            cx, cy = poly.representative_point().coords[0]
            d.text((cx, cy), str(k + 1), fill=(255, 255, 0), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
        sheet.thumbnail((2000, 2000))
        ImageDraw.Draw(sheet).text((8, 8), f"{gid} {g['label']}: {len(traces)} traces (magenta), OSM piers (cyan). "
                                           "2024 City aerial; (c) OpenStreetMap contributors", fill=(255, 255, 255),
                                   font=font, stroke_width=2, stroke_fill=(0, 0, 0))
        sheet.save(out_dir / f"trace_{gid}.jpg", quality=85)
        draft[gid] = traces
        print(gid, len(traces), [t["area_m2"] for t in traces])
    draft_path.write_text(json.dumps(draft, indent=1))


if __name__ == "__main__":
    main()
