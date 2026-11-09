"""Bridge inventory and crops (Nov. 5, Stephen: water bleeding onto roads).

--inventory: every City street, expressway or rail line crossing mapped water
(NHD and PWD) for 20 m or more, grouped by name within 150 m, with its area
and lon/lat; trails and the city-boundary line are left out. Written to
output/review/bridges/inventory.json.

Crops: for each bridge, at --scale (default 2): the drawing in map version
--before, the render (its photo layer), the raw drawing before the water
repaint (the owning area's redraws), and the drawing in --after (a map
version, or "areas" for the areas' finished frames before a map is built).
Plus a contact sheet.

    uv run python scripts/33_bridge_crops.py --inventory
    uv run python scripts/33_bridge_crops.py --before v15 --after v16 --label v16
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pixelphilly.projection import area_setup, load_config  # noqa: E402

AREAS = ["south_lidar", "north_lidar", "upper_north_lidar", "west_lidar", "west_north", "southwest", "germantown",
         "east_riverfront", "roxborough", "lower_northeast", "northwest", "upper_northeast"]
OUT = REPO_ROOT / "output" / "review" / "bridges"
MIN_LEN_M = 20.0
SKIP = ("TRL", "PATH", "CITY BOUNDARY", "LOOP")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def inventory():
    from shapely.geometry import shape
    from shapely.ops import unary_union

    found = []
    for a in AREAS:
        wg = []
        for s in ("water_nhd", "water"):
            p = REPO_ROOT / "data" / "raw" / f"{a}_{s}.geojson"
            if p.exists():
                wg += [shape(f["geometry"]).buffer(0) for f in json.loads(p.read_text())["features"] if f.get("geometry")]
        W = unary_union(wg)
        for src in ("streets", "highways", "rail"):
            p = REPO_ROOT / "data" / "raw" / f"{a}_{src}.geojson"
            if not p.exists():
                continue
            for f in json.loads(p.read_text())["features"]:
                if not f.get("geometry"):
                    continue
                g = shape(f["geometry"])
                if not g.intersects(W):
                    continue
                part = g.intersection(W)
                L = part.length * 85000
                if L < MIN_LEN_M:
                    continue
                pr = f["properties"]
                nm = "RAIL" if src == "rail" else (pr.get("stname") or pr.get("streetlabe") or "?")
                if any(s in nm for s in SKIP):
                    continue
                c = part.centroid
                found.append({"name": nm, "lon": c.x, "lat": c.y, "area": a, "len_m": round(L)})
    groups = []
    for x in sorted(found, key=lambda x: -x["len_m"]):
        hit = next((g for g in groups if g["name"] == x["name"]
                    and np.hypot((g["lon"] - x["lon"]) * 85000, (g["lat"] - x["lat"]) * 111000) < 150), None)
        if hit:
            hit["len_m"] = max(hit["len_m"], x["len_m"])
            continue
        groups.append(dict(x))
    # Owner of each place: the first area in the merge order whose frames cover it
    for g in groups:
        g["id"] = f"{g['name'].replace(' ', '_').lower()}_{abs(int(g['lon'] * 1000)) % 1000}_{int(g['lat'] * 1000) % 1000}"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inventory.json").write_text(json.dumps(groups, indent=1))
    print(len(groups), "bridges ->", OUT / "inventory.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--label")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--half-m", type=float, default=70.0)
    args = ap.parse_args()
    if args.inventory:
        return inventory()
    vc = _load("31_vessel_crops")
    st = _load("32_stage_crops")
    inv = json.loads((OUT / "inventory.json").read_text())
    before = vc.MapSource(args.before)
    after = vc.AreaSource(st.RUN) if args.after == "areas" else vc.MapSource(args.after)
    photo = None
    out_dir = OUT / f"crops_{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=20)
    thumbs = []
    for b in inv:
        x0, y0, x1, y1 = st.box_for(b["area"], b["lon"], b["lat"], args.half_m)
        bd = before.crop(x0, y0, x1, y1, area=b["area"])
        if photo is None or photo[0] != args.before:
            photo = (args.before, before)
        ph = _photo(before, x0, y0, x1, y1)
        raw = st.stitch(b["area"], REPO_ROOT / "output" / b["area"] / "redraws" / st.RUN, (x0, y0, x1, y1))
        af = after.crop(x0, y0, x1, y1, area=b["area"])
        ims = [(f"{args.before} drawing", bd), ("render", ph), ("raw drawing (before repaint)", raw),
               (f"{args.after} drawing", af)]
        w, h = (x1 - x0) * args.scale, (y1 - y0) * args.scale
        sheet = Image.new("RGB", (4 * w + 30, h + 30), "white")
        d = ImageDraw.Draw(sheet)
        for i, (lab, im) in enumerate(ims):
            sheet.paste(im.resize((w, h), Image.NEAREST), (i * (w + 10), 30))
            d.text((i * (w + 10) + 4, 4), f"{b['name']} ({b['area']}): {lab}", fill="black", font=font)
        p = out_dir / f"{b['id']}.jpg"
        sheet.save(p, quality=86)
        t = sheet.copy()
        t.thumbnail((1200, 320))
        thumbs.append(t)
    cols = 2
    rows = (len(thumbs) + cols - 1) // cols
    for k in range(0, rows, 12):
        part = thumbs[k * cols:(k + 12) * cols]
        cs = Image.new("RGB", (cols * 1200, ((len(part) + 1) // 2) * 320), "white")
        for i, t in enumerate(part):
            cs.paste(t, ((i % cols) * 1200, (i // cols) * 320))
        cs.save(out_dir / f"contact_sheet_{k // 12 + 1}.jpg", quality=82)
    print(out_dir, len(inv))


def _photo(src, x0, y0, x1, y1):
    """The render from a map version's photo layer."""
    ox, oy = src.ox, src.oy
    X0, Y0, X1, Y1 = int(x0 - ox), int(y0 - oy), int(x1 - ox), int(y1 - oy)
    out = Image.new("RGB", (X1 - X0, Y1 - Y0), (204, 214, 227))
    for ty in range(Y0 // 512, (Y1 - 1) // 512 + 1):
        for tx in range(X0 // 512, (X1 - 1) // 512 + 1):
            f = src.v / f"photo_files/{src.level}/{tx}_{ty}.webp"
            if f.exists():
                out.paste(Image.open(f).convert("RGB"), (tx * 512 - X0, ty * 512 - Y0))
    return out


if __name__ == "__main__":
    main()
