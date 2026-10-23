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

Usage: PP_AREA=atlas_cityhall uv run python scripts/04c_fetch_lidar.py
"""

import shapefile
from pyproj import Transformer
from shapely.geometry import shape

from pixelphilly.lidar import LAS_CRS, lidar_region_local
from pixelphilly.projection import load_config
from pixelphilly.sources import RAW, record, session

BASE = "https://www.pasda.psu.edu/download/phillyLiDAR/2022"
INDEX_FILES = ["Philadelphia_Tiles.shp", "Philadelphia_Tiles.shx", "Philadelphia_Tiles.dbf", "Philadelphia_Tiles.prj"]
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
    """Tile ids whose footprint intersects the LiDAR region."""
    import numpy as np
    import shapely

    idx_dir = LIDAR / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    for name in INDEX_FILES:
        fetch(f"{BASE}/Metadata_and_Reports/ESRI_shapefiles/{name}", idx_dir / name)
    to_sp = Transformer.from_crs("EPSG:4326", LAS_CRS, always_xy=True)
    fr, region = lidar_region_local(cfg)

    def local_to_sp(c):
        lon, lat = fr.to_wgs84(c[:, 0], c[:, 1])
        return np.column_stack(to_sp.transform(lon, lat))

    area = shapely.transform(region, local_to_sp)
    reader = shapefile.Reader(str(idx_dir / "Philadelphia_Tiles.shp"))
    fields = [f[0] for f in reader.fields[1:]]
    out = []
    for sr in reader.iterShapeRecords():
        if shape(sr.shape.__geo_interface__).intersects(area):
            rec = dict(zip(fields, sr.record))
            out.append(rec)
    return out, fields


def main():
    cfg = load_config()
    tiles, fields = tiles_for(cfg)
    # The tile name field is "Id" in the index (files are Philadelphia_<Id>.las)
    key = next(f for f in fields if f.lower() == "id")
    names = [f"Philadelphia_{int(t[key])}.las" for t in tiles]
    print(f"{cfg['name']}: {len(names)} LiDAR tiles: {', '.join(names)}")
    for name in names:
        dest = LIDAR / name
        if fetch(f"{BASE}/LAS/Classified_LAS/{name}", dest):
            record(f"lidar/{name}", {
                "description": "City of Philadelphia 2022 classified LiDAR (LAS 1.4), PASDA dataset 7154",
                "url": f"{BASE}/LAS/Classified_LAS/{name}",
                "crs": f"{LAS_CRS} (PA State Plane South, US ft; NAVD88 ft) - not stored in the file",
                "bytes": dest.stat().st_size,
            })
            print(f"  downloaded {name} ({dest.stat().st_size / 1e9:.2f} GB)")
        else:
            print(f"  {name} already downloaded")
    (LIDAR / f"{cfg['name']}_tiles.txt").write_text("\n".join(names) + "\n")


if __name__ == "__main__":
    main()
