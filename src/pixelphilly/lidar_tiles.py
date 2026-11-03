"""Which raw LiDAR tiles an area needs, and which can be deleted.

The City's 2022 LAS tiles (PASDA dataset 7154) are 0.7-1.7 GB each; the
four drawn regions alone hold ~153 GB. scripts/05_build_scene.py reads them
once to build data/processed/<area>_lidar_grid.npz and afterwards uses only
that grid, provided the grid holds the class-1 "struct" grid (older grids
without it are rebuilt from the LAS files; see lidar_shaped in 05). So a
tile can go once every area that needs it has such a grid.

A tile is deleted only when every area listing it
(data/raw/lidar/<area>_tiles.txt, written by scripts/04c_fetch_lidar.py) has
a config with "building_shapes": "lidar" and a valid grid. It is kept when
any listing area has no config, isn't a LiDAR config (its list may be from
an earlier experiment; we don't guess), or has no valid grid, when no list
names it, and when a LiDAR area that hasn't fetched yet (no list, no grid)
will need it (extra_needs, from the tile index). Deleted tiles can be
re-downloaded from PASDA (las_url); each deletion is recorded in
data/raw/MANIFEST.json.

Pure apart from the file system paths it is given; tested in
tests/test_lidar_prune.py.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PASDA_BASE = "https://www.pasda.psu.edu/download/phillyLiDAR/2022"
INDEX_FILES = ["Philadelphia_Tiles.shp", "Philadelphia_Tiles.shx", "Philadelphia_Tiles.dbf", "Philadelphia_Tiles.prj"]


def las_url(name: str) -> str:
    """Where scripts/04c_fetch_lidar.py downloads tile `name` from."""
    return f"{PASDA_BASE}/LAS/Classified_LAS/{name}"


def index_url(name: str) -> str:
    return f"{PASDA_BASE}/Metadata_and_Reports/ESRI_shapefiles/{name}"


def tiles_in_index(cfg: dict, index_dir: Path) -> list[str]:
    """Tile file names (Philadelphia_<Id>.las) whose index footprint meets
    the area's LiDAR region (bbox + lidar.LIDAR_MARGIN_M), in index order.
    The index (INDEX_FILES) must already be in index_dir."""
    import numpy as np
    import shapefile
    import shapely
    from pyproj import Transformer
    from shapely.geometry import shape

    from .lidar import LAS_CRS, lidar_region_local

    to_sp = Transformer.from_crs("EPSG:4326", LAS_CRS, always_xy=True)
    fr, region = lidar_region_local(cfg)

    def local_to_sp(c):
        lon, lat = fr.to_wgs84(c[:, 0], c[:, 1])
        return np.column_stack(to_sp.transform(lon, lat))

    area = shapely.transform(region, local_to_sp)
    reader = shapefile.Reader(str(Path(index_dir) / "Philadelphia_Tiles.shp"))
    fields = [f[0] for f in reader.fields[1:]]
    # The tile name field is "Id" in the index (files are Philadelphia_<Id>.las)
    key = next(f for f in fields if f.lower() == "id")
    return [f"Philadelphia_{int(dict(zip(fields, sr.record))[key])}.las" for sr in reader.iterShapeRecords()
            if shape(sr.shape.__geo_interface__).intersects(area)]


def grid_valid(path: Path) -> bool:
    """True if the cached grid would be used as-is by 05_build_scene.py
    (an .npz holding "struct"); a missing, unreadable or pre-structure grid
    makes 05 regrid from the LAS files."""
    try:
        with zipfile.ZipFile(path) as z:
            names = {n.removesuffix(".npy") for n in z.namelist()}
    except (OSError, zipfile.BadZipFile):
        return False
    return {"dsm", "ground", "origin", "struct"} <= names


def read_tile_lists(lidar_dir: Path) -> dict[str, list[str]]:
    """{area: tiles} from every data/raw/lidar/<area>_tiles.txt."""
    return {p.name.removesuffix("_tiles.txt"): p.read_text().split()
            for p in sorted(Path(lidar_dir).glob("*_tiles.txt"))}


def plan_prune(lidar_dir: Path, processed_dir: Path, configs: dict, extra_needs: dict) -> list[dict]:
    """One entry per .las tile on disk: {"tile", "bytes", "areas" (listing
    it), "grids" (their grid paths), "delete", "blockers": [{"area",
    "reason"}]}.

    configs: {area: config dict} for every config in config/ (an area with
    a tile list but no entry has "no config"). extra_needs: {area: tiles}
    for LiDAR areas without a tile list or grid yet."""
    lidar_dir, processed_dir = Path(lidar_dir), Path(processed_dir)
    lists = read_tile_lists(lidar_dir)
    plan = []
    for tile in sorted(lidar_dir.glob("*.las")):
        name = tile.name
        areas = sorted(a for a, ts in lists.items() if name in ts)
        blockers = []
        if not areas:
            blockers.append({"area": None, "reason": "in no tile list"})
        for a in areas:
            cfg = configs.get(a)
            if cfg is None:
                blockers.append({"area": a, "reason": "no config"})
            elif cfg.get("building_shapes") != "lidar":
                blockers.append({"area": a, "reason": "not a LiDAR config"})
            elif not grid_valid(processed_dir / f"{a}_lidar_grid.npz"):
                blockers.append({"area": a, "reason": "no valid grid"})
        for a, need in sorted(extra_needs.items()):
            if a not in lists and name in need and not grid_valid(processed_dir / f"{a}_lidar_grid.npz"):
                blockers.append({"area": a, "reason": "needed, no grid yet (no tile list)"})
        plan.append({"tile": name, "bytes": tile.stat().st_size, "areas": areas,
                     "grids": [str(processed_dir / f"{a}_lidar_grid.npz") for a in areas],
                     "delete": not blockers, "blockers": blockers})
    return plan


def _record_deletion(manifest: Path, name: str, nbytes: int, areas: list[str]) -> None:
    """Mark the tile's manifest entry deleted (re-read each time so other
    writers' entries survive). 04c re-downloading the tile replaces the
    entry with a fresh one."""
    m = json.loads(manifest.read_text()) if manifest.exists() else {}
    key = f"lidar/{name}"
    m[key] = {**m.get(key, {}), "path": f"data/raw/lidar/{name}", "bytes": nbytes, "url": las_url(name),
              "deleted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "deleted_reason": "raw LAS pruned after gridding (scripts/04m_prune_lidar.py); re-download from url",
              "grids": areas}
    manifest.write_text(json.dumps(m, indent=2) + "\n")


def apply_prune(plan: list[dict], lidar_dir: Path, manifest: Path, dry_run: bool = True) -> dict:
    """Delete the tiles the plan marks (dry_run: only report). Each grid is
    re-checked just before its tiles go, in case it changed since
    planning."""
    lidar_dir = Path(lidar_dir)
    todo = [p for p in plan if p["delete"]]
    out = {"dry_run": dry_run, "would_delete": [p["tile"] for p in todo],
           "would_free_bytes": sum(p["bytes"] for p in todo), "deleted": [], "freed_bytes": 0, "skipped": []}
    if dry_run:
        return out
    for p in todo:
        if not all(grid_valid(Path(g)) for g in p["grids"]):
            out["skipped"].append(p["tile"])
            continue
        path = lidar_dir / p["tile"]
        nbytes = path.stat().st_size
        path.unlink()
        _record_deletion(Path(manifest), p["tile"], nbytes, p["areas"])
        out["deleted"].append(p["tile"])
        out["freed_bytes"] += nbytes
    return out
