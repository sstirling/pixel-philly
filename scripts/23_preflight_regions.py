"""Pre-flight for the citywide regions: sizes, overlaps, LiDAR, viewer fit,
and gaps inside the city line. No downloads (it needs only
data/raw/city_limits.geojson and the PASDA tile index in
data/raw/lidar/index/, both already fetched).

For each region, in draw order (earlier regions own shared cells):
  frames       lattice frames after clipping (clip_to_city)
  shared       frames at the same global cell as an earlier region's frame
               (these become the known band when the region is drawn)
  new          frames only this region draws
  $, GPU min   the run's estimate: ALL its frames x $0.011 and x 0.17 min
               (South Philly's pace, Oct. 27). Known-band frames aren't
               decoded but still go through the sampler, so they cost GPU
               time; this is the figure the runner's budget gate uses
  LiDAR        tiles the region's box (+100 m) needs, how many are on disk,
               how many would be downloaded and their estimated size (from
               the manifest's recorded sizes; mean size when unknown)
  fit          the viewer's lon/lat -> px cubic: worst error in px (limit 0.5)
Then the coverage check: every global lattice cell that shows city ground
(pixelphilly.coverage.city_cells) must belong to some region.

Writes output/preflight_regions.json.
Usage: uv run python scripts/23_preflight_regions.py [--order south_lidar,north_lidar,...]
"""

import argparse
import json
import time

import numpy as np

from pixelphilly.coverage import city_cells, frames_by_cell, uncovered_cells
from pixelphilly.lidar_tiles import tiles_in_index
from pixelphilly.projection import REPO_ROOT, area_setup, city_polygon, load_config
from pixelphilly.region_runner import CITY_REGIONS, GPU_MIN_PER_FRAME, USD_PER_FRAME
from pixelphilly.sources import MANIFEST, RAW

EXISTING = CITY_REGIONS[:4]
NEW = CITY_REGIONS[4:]
SPLIT_OVER = 700  # new frames: one region must fit the GPU job's 4-hour cap with margin


def fit_error(cfg) -> float:
    from pixelphilly.viewer_geo import fit_lonlat_to_px

    try:
        return fit_lonlat_to_px(cfg)["max_error_px"]
    except RuntimeError as e:  # over 0.5 px
        return float(str(e).split("off by ")[1].split(" px")[0])


def union_fit_error(cfgs) -> float:
    from pixelphilly.regions import union_lattice
    from pixelphilly.viewer_geo import fit_lonlat_to_px_union

    u = union_lattice([(c["name"], area_setup(c)[2]) for c in cfgs])
    try:
        return fit_lonlat_to_px_union(cfgs, u["x0"], u["y0"])["max_error_px"]
    except RuntimeError as e:
        return float(str(e).split("off by ")[1].split(" px")[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", default=",".join(EXISTING + NEW), help="regions in draw order")
    args = ap.parse_args()
    order = [a.strip() for a in args.order.split(",") if a.strip()]
    cfgs = {a: load_config(a) for a in order}
    manifest = json.loads(MANIFEST.read_text())
    sizes = {k.removeprefix("lidar/"): v["bytes"] for k, v in manifest.items() if k.startswith("lidar/") and "bytes" in v}
    mean_bytes = float(np.mean(list(sizes.values())))
    lidar_dir = RAW / "lidar"

    rows, cells_of, owner = [], {}, {}
    planned_tiles = set()
    for a in order:
        t0 = time.monotonic()
        cfg = cfgs[a]
        _, _, frames = area_setup(cfg)
        setup_s = time.monotonic() - t0
        cells = frames_by_cell(frames)
        cells_of[a] = cells
        shared = {}
        for c in cells:
            if c in owner:
                shared[owner[c]] = shared.get(owner[c], 0) + 1
        new = [c for c in cells if c not in owner]
        for c in new:
            owner[c] = a
        tiles = tiles_in_index(cfg, lidar_dir / "index")
        on_disk = [t for t in tiles if (lidar_dir / t).exists()]
        # "new" = neither on disk nor already counted for an earlier region in this plan
        fetch = [t for t in tiles if t not in on_disk and t not in planned_tiles]
        planned_tiles |= set(tiles)
        rows.append({"region": a, "frames": len(frames), "shared": shared, "new": len(new),
                     "est_usd": round(len(frames) * USD_PER_FRAME, 2),
                     "est_gpu_min": round(len(frames) * GPU_MIN_PER_FRAME, 1),
                     "lidar_tiles": len(tiles), "lidar_on_disk": len(on_disk), "lidar_new": len(fetch),
                     "lidar_new_gb": round(sum(sizes.get(t, mean_bytes) for t in fetch) / 1e9, 1),
                     "fit_error_px": fit_error(cfg), "split": len(new) > SPLIT_OVER,
                     "area_setup_s": round(setup_s, 2), "existing": a in EXISTING})

    # Same-cell overlaps between every pair (not just earlier -> later):
    # regions drawn in parallel must not share cells
    pairs = {}
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            n = len(set(cells_of[a]) & set(cells_of[b]))
            if n:
                pairs[f"{a}|{b}"] = n

    ref = cfgs[order[0]]
    frame, cam, _ = area_setup(ref)
    size = ref["camera"]["frame_px"]
    city = city_polygon()
    cells = city_cells(cam, frame, city, size)
    gaps = uncovered_cells(cells, {a: area_setup(cfgs[a])[2] for a in order})
    gap_rows = []
    for (gx, gy), share in sorted(gaps.items(), key=lambda kv: -kv[1]):
        e, n = cam.screen_to_ground((gx + 0.5) * size, (gy + 0.5) * size, 0.0)
        lon, lat = frame.to_wgs84(float(e), float(n))
        gap_rows.append({"cell": [gx, gy], "city_share": round(share, 4), "center_lonlat": [round(lon, 5), round(lat, 5)]})
    # City ground in no region's bbox (bboxes decide LiDAR shapes and fetches)
    from shapely.geometry import box
    from shapely.ops import unary_union

    outside = city.difference(unary_union([box(*cfgs[a]["bbox_wgs84"]) for a in order]))
    lat0 = 40.0
    km2 = outside.area * (111.32 * np.cos(np.radians(lat0))) * 110.57

    report = {"order": order, "regions": rows, "pair_overlaps": pairs, "city_cells": len(cells),
              "uncovered_cells": gap_rows, "city_km2_outside_all_bboxes": round(float(km2), 3),
              "union_fit_error_px": union_fit_error([cfgs[a] for a in order]),
              "mean_tile_gb": round(mean_bytes / 1e9, 2)}
    out = REPO_ROOT / "output" / "preflight_regions.json"
    out.write_text(json.dumps(report, indent=1) + "\n")

    print(f"{'region':18s} {'frames':>6s} {'new':>5s} {'$':>6s} {'GPU min':>7s} {'tiles':>5s} {'disk':>4s} "
          f"{'fetch':>5s} {'GB':>5s} {'fit px':>8s}  shared with earlier")
    for r in rows:
        print(f"{r['region']:18s} {r['frames']:6d} {r['new']:5d} {r['est_usd']:6.2f} {r['est_gpu_min']:7.1f} "
              f"{r['lidar_tiles']:5d} {r['lidar_on_disk']:4d} {r['lidar_new']:5d} {r['lidar_new_gb']:5.1f} "
              f"{r['fit_error_px']:8.1e}  {', '.join(f'{k} {v}' for k, v in r['shared'].items()) or '-'}"
              f"{'  SPLIT (> %d new)' % SPLIT_OVER if r['split'] else ''}")
    new_rows = [r for r in rows if not r["existing"]]
    print(f"new regions: {sum(r['frames'] for r in new_rows)} run frames ({sum(r['new'] for r in new_rows)} new), "
          f"~${sum(r['est_usd'] for r in new_rows):.2f}, "
          f"~{sum(r['est_gpu_min'] for r in new_rows) / 60:.1f} GPU h; "
          f"{sum(r['lidar_new'] for r in new_rows)} LiDAR tiles to fetch, ~{sum(r['lidar_new_gb'] for r in new_rows):.0f} GB")
    print("pairs sharing cells:", ", ".join(f"{k} {v}" for k, v in pairs.items()))
    print(f"union viewer fit: {report['union_fit_error_px']:.2e} px")
    print(f"coverage: {len(cells)} lattice cells show city ground; {len(gaps)} not covered by any region"
          + (f" (largest city share {gap_rows[0]['city_share']:.3f})" if gap_rows else ""))
    for g in gap_rows[:40]:
        print(f"  gap cell {g['cell']} city share {g['city_share']:.4f} near {g['center_lonlat']}")
    print(f"city ground outside every region bbox: {report['city_km2_outside_all_bboxes']} km²")
    print(f"-> {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
