"""Download City of Philadelphia 2022 LiDAR tiles for an area.

Source: PASDA dataset 7154, classified LAS 1.4, 3,000 x 3,000 ft tiles
(~0.7-1.7 GB each, uncompressed). Only tiles intersecting the area's box
plus LIDAR_MARGIN_M (src/pixelphilly/lidar.py) are fetched, selected with the official tile index.
Buildings farther out keep their single footprint height: the shape test is
about the landmark or stadium at each spot's center, and covering everything
the frames see would mean ~30 tiles instead of ~24 for the nine atlas spots
(~1 GB each). The files carry no CRS record: they are PA State Plane South, US survey feet
(EPSG:6565), NAVD88 feet (see src/pixelphilly/lidar.py).

License: PASDA metadata lists "Use_Constraints: None". Credit "City of
Philadelphia via PASDA".

Writes data/raw/lidar/Philadelphia_<Id>.las (git-ignored) and records each
tile in data/raw/MANIFEST.json. Downloads stream to a .part file and are
renamed when complete, so an interrupted run resumes cleanly.

Skips the download when the area's height grid is already cached
(data/processed/<area>_lidar_grid.npz with "struct"), since raw tiles may
have been pruned (scripts/04m_prune_lidar.py).

Usage: PP_AREA=atlas_cityhall uv run python scripts/04c_fetch_lidar.py
"""

from pixelphilly.lidar import LAS_CRS
from pixelphilly.lidar_tiles import INDEX_FILES, grid_valid, index_url, las_url, tiles_in_index
from pixelphilly.projection import REPO_ROOT, load_config
from pixelphilly.sources import RAW, record, session

LIDAR = RAW / "lidar"


def fetch(url, dest):
    if dest.exists():
        return False
    tmp = dest.with_suffix(dest.suffix + ".part")
    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=8 << 20):
                fh.write(chunk)
    tmp.rename(dest)
    return True


def tiles_for(cfg):
    """Tile file names whose footprint intersects the LiDAR region (the
    official index is downloaded on first use)."""
    idx_dir = LIDAR / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    for name in INDEX_FILES:
        fetch(index_url(name), idx_dir / name)
    return tiles_in_index(cfg, idx_dir)


def main():
    cfg = load_config()
    names = tiles_for(cfg)
    print(f"{cfg['name']}: {len(names)} LiDAR tiles: {', '.join(names)}")
    tile_list = LIDAR / f"{cfg['name']}_tiles.txt"
    # Raw tiles are pruned once gridded (scripts/04m_prune_lidar.py); with a
    # valid grid cached, 05_build_scene.py never reads them, so don't fetch
    # them again. Delete the grid to force a regrid.
    if grid_valid(REPO_ROOT / "data" / "processed" / f"{cfg['name']}_lidar_grid.npz"):
        print("  height grid already cached: not downloading LAS tiles")
        if not tile_list.exists():
            tile_list.write_text("\n".join(names) + "\n")
        return
    for name in names:
        dest = LIDAR / name
        if fetch(las_url(name), dest):
            record(f"lidar/{name}", {
                "description": "City of Philadelphia 2022 classified LiDAR (LAS 1.4), PASDA dataset 7154",
                "url": las_url(name),
                "crs": f"{LAS_CRS} (PA State Plane South, US ft; NAVD88 ft) - not stored in the file",
                "bytes": dest.stat().st_size,
            })
            print(f"  downloaded {name} ({dest.stat().st_size / 1e9:.2f} GB)")
        else:
            print(f"  {name} already downloaded")
    tile_list.write_text("\n".join(names) + "\n")


if __name__ == "__main__":
    main()
