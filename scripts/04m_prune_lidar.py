"""Delete raw LiDAR tiles that no area needs any more. DRY RUN by default.

After scripts/05_build_scene.py has gridded an area, its cached grid
(data/processed/<area>_lidar_grid.npz, with the class-1 "struct" grid) is
all a rebuild reads, so the raw LAS tiles (0.7-1.7 GB each) can go. A tile
is deleted only when EVERY config that lists it
(data/raw/lidar/<area>_tiles.txt) uses "building_shapes": "lidar" and has a
valid grid. Tiles are kept when they are in no list, when a listing area has
no config, isn't a LiDAR config or has no valid grid, and when a LiDAR
config that hasn't fetched yet (no list, no grid: a new region or atlas
spot) will need them by the PASDA tile index. Rules and tests:
src/pixelphilly/lidar_tiles.py, tests/test_lidar_prune.py.

With --apply, each deleted tile is marked in data/raw/MANIFEST.json (path,
bytes, deleted_at, the PASDA re-download URL, the grids that replaced it).
To get a tile back, delete the area's grid and run 04c_fetch_lidar.py, or
download the URL.

Writes output/lidar_prune.json (the full plan: every tile, why it's kept).

Usage:
  uv run python scripts/04m_prune_lidar.py            # dry run: what would be freed
  uv run python scripts/04m_prune_lidar.py --apply    # delete
"""

import argparse
import json
from collections import Counter

from pixelphilly.lidar_tiles import apply_prune, plan_prune, read_tile_lists, tiles_in_index
from pixelphilly.projection import REPO_ROOT
from pixelphilly.sources import MANIFEST, RAW

LIDAR = RAW / "lidar"
PROCESSED = REPO_ROOT / "data" / "processed"


def load_configs() -> dict:
    out = {}
    for p in sorted((REPO_ROOT / "config").glob("*.json")):
        cfg = json.loads(p.read_text())
        if isinstance(cfg, dict) and "bbox_wgs84" in cfg and "name" in cfg:
            out[cfg["name"]] = cfg
    return out


def extra_needs(configs: dict) -> dict:
    """Tiles each LiDAR config without a tile list (not fetched yet) will
    need, from the tile index already on disk (04c downloads it)."""
    from pixelphilly.lidar_tiles import grid_valid

    lists = read_tile_lists(LIDAR)
    todo = {a: c for a, c in configs.items() if c.get("building_shapes") == "lidar" and a not in lists
            and not grid_valid(PROCESSED / f"{a}_lidar_grid.npz")}
    if todo and not (LIDAR / "index" / "Philadelphia_Tiles.shp").exists():
        raise SystemExit(f"tile index missing ({LIDAR / 'index'}): can't tell which tiles "
                         f"{', '.join(sorted(todo))} will need. Run 04c_fetch_lidar.py for any area first.")
    return {a: tiles_in_index(c, LIDAR / "index") for a, c in todo.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="delete (default: dry run)")
    args = ap.parse_args()

    configs = load_configs()
    needs = extra_needs(configs)
    plan = plan_prune(LIDAR, PROCESSED, configs, needs)
    result = apply_prune(plan, LIDAR, MANIFEST, dry_run=not args.apply)

    on_disk = sum(p["bytes"] for p in plan)
    keep = [p for p in plan if not p["delete"]]
    reasons = Counter()
    by_area = Counter()
    for p in keep:
        for b in p["blockers"]:
            reasons[b["reason"]] += 1
            by_area[(b["area"], b["reason"])] += 1
    print(f"{len(plan)} LAS tiles on disk, {on_disk / 1e9:.1f} GB")
    print(f"{'DRY RUN: would delete' if not args.apply else 'deleted'} "
          f"{len(result['would_delete'] if not args.apply else result['deleted'])} tiles, "
          f"{(result['would_free_bytes'] if not args.apply else result['freed_bytes']) / 1e9:.1f} GB")
    if result["skipped"]:
        print(f"skipped (grid changed since planning): {', '.join(result['skipped'])}")
    print(f"kept {len(keep)} tiles, {sum(p['bytes'] for p in keep) / 1e9:.1f} GB; blockers (a tile can have several):")
    for (area, reason), n in sorted(by_area.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"  {n:4d} tiles  {area or '-'}: {reason}")
    if needs:
        print("not fetched yet (tiles kept for them): "
              + ", ".join(f"{a} {len(t)} tiles ({sum(1 for x in t if (LIDAR / x).exists())} on disk)"
                          for a, t in sorted(needs.items())))
    out = REPO_ROOT / "output" / "lidar_prune.json"
    out.write_text(json.dumps({"result": result, "on_disk_bytes": on_disk, "reasons": dict(reasons),
                               "extra_needs": needs, "plan": plan}, indent=1) + "\n")
    print(f"-> {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
