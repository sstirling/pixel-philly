"""Measure roof forms from the 2022 LiDAR (investigation only; draws nothing).

Question (Nov. 23, 2026; docs/building_age_styles.md): how many buildings
have pitched roofs, and how many flat-roofed rows have a shingled slope
across the front (the interwar and postwar Northeast pattern seen in dated
Evening Bulletin photos)? That decides whether roof work is worth planning.

Inputs, all already on disk and unchanged:
- data/processed/<area>_lidar_grid.npz: the cached 0.5 m surface grid that
  05_build_scene.py builds from the City's 2022 LiDAR (PASDA 7154; leaf-off,
  flown March 29, 2022). "dsm" is the highest return per cell, "ground" the
  ground surface, origin = (west, north) in the area's local meters.
- data/raw/<area>_buildings.geojson (L&I footprints), _opa.geojson and
  _pwd_parcels.json (OPA style code and year, joined with the map's own
  join), _streets.geojson (street centerlines, for the street-facing side).

Per footprint:
- Pitch: a plane is fit to every 5 x 5 cell (2.5 m) patch of the DSM over the
  footprint shrunk by EDGE_M. Patches that fit a plane well (residual under
  PLANE_RESID_M) are "flat" (under FLAT_DEG) or "sloped" (STEEP_DEG to
  MAX_DEG); patches that don't fit are steps between roof levels, parapets,
  party walls or HVAC units and are left out. A first version counted steep
  cells directly, and the steps between a rowhouse's main roof and its rear
  ell made flat rows look half pitched. steep_share = sloped / (sloped +
  flat). Classes: pitched (steep_share >= PITCHED_SHARE), flat
  (<= FLAT_SHARE), mixed in between, unclear (too few planar patches),
  too_small, low (roof under MIN_HEIGHT_M).
- Front: for non-pitched roofs with a street-facing side
  (pixelphilly.facades.front_dirs), compare a band along the front wall
  (FRONT_BAND_M deep) with the roof behind it (BACK_BAND_M); drop = how
  much lower the front band is. front_type:
    front_slope: drop FRONT_DROP_M to SLOPE_MAX_DROP_M, front band steep
      (median 3x3 angle >= STEEP_DEG), roof behind flat (< FLAT_DEG); a
      shingled slope rising from a low eave to the flat roof
    lower_front: drop PORCH_DROP_M or more; a story-high step at the front,
      usually a porch roof (checked against OPA's porch-front code)
    level / raised (front band higher: cornice or parapet) / other

Thresholds are first guesses checked by eye on examples (see the report);
these are measurements of the 2022 surface, not a survey, and every class
has errors (trees over roofs, rooftop additions, roofs under 2022
construction, footprints that don't match the LiDAR).

Writes output/building_age/roof_forms_<area>.csv (one row per footprint:
object id, OPA style code, year, estimate flag, map style, measurements,
class; no addresses) and roof_forms_summary.json.

Usage:
  uv run python scripts/45_roof_forms.py                      # the facade atlas spots
  uv run python scripts/45_roof_forms.py --areas lower_northeast south_lidar
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from rasterio.features import geometry_mask
from shapely import STRtree
from shapely.geometry import LineString, shape

from pixelphilly import facades
from pixelphilly.projection import load_config, local_frame

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "output" / "building_age"

ATLAS = ["atlas_indhall_fac", "atlas_cityhall_fac", "atlas_passyunk_fac", "atlas_porch_fac", "atlas_twin_fac",
         "atlas_northeast_fac", "atlas_wissahickon_fac"]
# Pitch thresholds live with the shared pitch test (pixelphilly.roofs); the
# front-band ones are this script's
from pixelphilly.roofs import (EDGE_M, FLAT_DEG, FLAT_SHARE, MAX_DEG, MIN_HEIGHT_M,  # noqa: E402
                               PITCHED_SHARE, PLANE_RESID_M, STEEP_DEG, roof_pitch, roof_window)
from pixelphilly.roofs import PITCH_RES_M as RES  # noqa: E402

SLOPE_MAX_DROP_M = 1.6
PORCH_DROP_M = 2.0
FRONT_BAND_M = (0.25, 1.75)   # depth from the front wall line
BACK_BAND_M = (2.75, 6.0)
FRONT_DROP_M = 0.3
ERAS = [(1682, 1879, "pre1880"), (1880, 1904, "1880_1904"), (1905, 1929, "1905_1929"),
        (1930, 1944, "1930_1944"), (1945, 1974, "1945_1974"), (1975, 1999, "1975_1999"),
        (2000, 2026, "2000_2026")]


def era(y):
    return next((n for lo, hi, n in ERAS if y is not None and lo <= y <= hi), "unknown")


def year_of(rec):
    try:
        y = int(str(rec.get("year_built") or "").strip())
    except ValueError:
        return None
    return y if 1682 <= y <= 2026 else None


def load_grid(name):
    for cand in (f"{name}_lidar_grid.npz", f"{name}_lidar_lidar_grid.npz"):
        p = PROCESSED / cand
        if p.exists():
            z = np.load(p)
            return z["dsm"], z["ground"], tuple(float(v) for v in z["origin"]), p.name
    raise FileNotFoundError(f"no LiDAR grid for {name}")


def slope_deg(win):
    gy, gx = np.gradient(win, RES)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def measure(fp, dsm, ground, origin, front):
    """Measurements for one footprint (local-m polygon), or None outside the grid."""
    w = roof_window(fp, dsm, ground, origin, RES)
    if w is None:
        return None
    out = roof_pitch(fp, dsm, ground, origin, RES, window=w)
    cls = out["cls"]
    if cls in ("too_small", "low"):
        return out
    win, tf, c0, r0 = w["win"], w["tf"], w["c0"], w["r0"]
    ang = slope_deg(win)
    if cls in ("flat", "mixed", "unclear") and front:
        d = np.array(front[0])
        rows, cols = np.indices(win.shape)
        e = origin[0] + (c0 + cols + 0.5) * RES
        n = origin[1] - (r0 + rows + 0.5) * RES
        s = e * d[0] + n * d[1]
        poly = fp if fp.geom_type == "Polygon" else max(fp.geoms, key=lambda g: g.area)
        xs, ys = poly.exterior.coords.xy
        front_s = max(x * d[0] + y * d[1] for x, y in zip(xs, ys))
        dist = front_s - s
        body = geometry_mask([fp.buffer(-0.25)], out_shape=win.shape, transform=tf, invert=True)
        fb = body & (dist >= FRONT_BAND_M[0]) & (dist <= FRONT_BAND_M[1])
        bb = body & (dist >= BACK_BAND_M[0]) & (dist <= BACK_BAND_M[1])
        if fb.sum() >= 4 and bb.sum() >= 4:
            drop = float(np.median(win[bb]) - np.median(win[fb]))
            fdeg, bdeg = float(np.median(ang[fb])), float(np.median(ang[bb]))
            if FRONT_DROP_M <= drop <= SLOPE_MAX_DROP_M and fdeg >= STEEP_DEG and bdeg < FLAT_DEG:
                ft = "front_slope"
            elif drop >= PORCH_DROP_M:
                ft = "lower_front"
            elif abs(drop) < FRONT_DROP_M:
                ft = "level"
            elif drop <= -FRONT_DROP_M:
                ft = "raised"
            else:
                ft = "other"
            out.update(front_drop_m=round(drop, 2), front_deg=round(fdeg, 1), back_deg=round(bdeg, 1),
                       front_type=ft)
    return out


def run_area(name):
    cfg = load_config(name)
    fr = local_frame(cfg)
    dsm, ground, origin, grid_file = load_grid(name)
    import shapely

    def to_local(g):
        return shapely.transform(g, lambda xy: np.column_stack(fr.to_local(xy[:, 0], xy[:, 1])))

    feats = json.loads((RAW / f"{name}_buildings.geojson").read_text())["features"]
    opa = json.loads((RAW / f"{name}_opa.geojson").read_text())["features"]
    rows = [dict(f["properties"], _pt=shape(f["geometry"])) for f in opa if f.get("geometry")]
    pwd = {str(r["parcelid"]): r["brt_id"] for r in json.loads((RAW / f"{name}_pwd_parcels.json").read_text())["rows"]}
    fps = []
    for f in feats:
        if not f.get("geometry"):
            continue
        p = f["properties"]
        g = shape(f["geometry"])
        fps.append({"id": p["objectid"], "parcel_id_num": p.get("parcel_id_num"), "address": p.get("address"),
                    "geom": g, "local": to_local(g), "h": (p.get("approx_hgt") or 0) * 0.3048})
    matches = facades.join(fps, rows, pwd)
    streets = []
    sp = RAW / f"{name}_streets.geojson"
    if sp.exists():
        for f in json.loads(sp.read_text())["features"]:
            if f.get("geometry"):
                streets.append(to_local(shape(f["geometry"])))
    streets = [s for s in streets if isinstance(s, LineString) or s.geom_type == "MultiLineString"]
    tree = STRtree(streets) if streets else None

    out = []
    for i, fp in enumerate(fps):
        rec, _ = matches[fp["id"]]
        g = fp["local"]
        if g.is_empty or not g.is_valid:
            g = g.buffer(0)
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda x: x.area)
        front = []
        if tree is not None:
            near = [streets[j] for j in tree.query(g.buffer(facades.FRONT_RAY_M + 5))]
            front = facades.front_dirs(g, near)
        mres = measure(g, dsm, ground, origin, front)
        if mres is None:
            continue
        y = year_of(rec) if rec else None
        out.append({"area": name, "objectid": fp["id"],
                    "opa_style": (rec or {}).get("building_code_description_new") or (rec or {}).get("building_code_description"),
                    "year": y, "era": era(y), "year_est": (rec or {}).get("year_built_estimate"),
                    "map_style": facades.style_of(rec, fp["h"]) if rec else "unmatched",
                    "footprint_m2": round(g.area, 1), **mres})
        if i and i % 20000 == 0:
            print(f"    {i:,}/{len(fps):,}")
    return out, grid_file, len(fps)


def summarize(rows):
    def block(rs):
        c = Counter(r["cls"] for r in rs)
        measured = sum(c[k] for k in ("flat", "mixed", "pitched"))
        fs = [r for r in rs if r.get("front_type")]
        ft = Counter(r["front_type"] for r in fs)
        pc = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
        return {"footprints": len(rs), "classes": dict(c),
                "pitched_pct_of_measured": pc(c["pitched"], measured),
                "mixed_pct_of_measured": pc(c["mixed"], measured),
                "flat_pct_of_measured": pc(c["flat"], measured),
                "front_checked": len(fs), "front_types": dict(ft),
                "front_slope_pct_of_checked": pc(ft["front_slope"], len(fs)),
                "lower_front_pct_of_checked": pc(ft["lower_front"], len(fs))}
    s = {"all": block(rows)}
    for key in ("area", "map_style", "era", "opa_style"):
        g = defaultdict(list)
        for r in rows:
            g[r[key]].append(r)
        s[f"by_{key}"] = {k: block(v) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])) if len(v) >= 30}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--areas", nargs="+", default=ATLAS)
    ap.add_argument("--tag", default=None, help="summary file suffix (default: atlas, or the area names)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    allrows, grids = [], {}
    for name in args.areas:
        print(f"  {name} ...")
        rows, grid_file, n = run_area(name)
        grids[name] = {"grid": grid_file, "footprints": n, "measured_in_grid": len(rows)}
        allrows += rows
        with open(OUT / f"roof_forms_{name}.csv", "w", newline="") as f:
            keys = ["area", "objectid", "opa_style", "year", "era", "year_est", "map_style", "footprint_m2", "cls",
                    "cells", "planar_share", "roof_h_m", "steep_share", "front_drop_m", "front_deg", "back_deg",
                    "front_type"]
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in keys})
        b = summarize(rows)["all"]
        print(f"    {len(rows):,} in grid: {b['classes']}; pitched {b['pitched_pct_of_measured']}% "
              f"mixed {b['mixed_pct_of_measured']}%; front {b['front_types']}")
    tag = args.tag or ("atlas" if args.areas == ATLAS else "_".join(args.areas))
    summary = {"grids": grids, "thresholds": {"EDGE_M": EDGE_M, "STEEP_DEG": STEEP_DEG,
                                              "PITCHED_SHARE": PITCHED_SHARE, "FLAT_SHARE": FLAT_SHARE,
                                              "FRONT_BAND_M": FRONT_BAND_M, "BACK_BAND_M": BACK_BAND_M,
                                              "FRONT_DROP_M": FRONT_DROP_M, "MIN_HEIGHT_M": MIN_HEIGHT_M,
                                              "FLAT_DEG": FLAT_DEG, "MAX_DEG": MAX_DEG, "PLANE_RESID_M": PLANE_RESID_M,
                                              "SLOPE_MAX_DROP_M": SLOPE_MAX_DROP_M, "PORCH_DROP_M": PORCH_DROP_M},
               **summarize(allrows)}
    (OUT / f"roof_forms_summary_{tag}.json").write_text(json.dumps(summary, indent=1))
    print(f"Wrote output/building_age/roof_forms_summary_{tag}.json")


if __name__ == "__main__":
    main()
