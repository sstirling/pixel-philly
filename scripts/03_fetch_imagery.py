"""Download City of Philadelphia 2024 3-inch aerial imagery tiles.

Source: the city's CityImagery_2024_3in tile service (Web Mercator, 256 px
JPEG tiles). The same imagery is downloadable as TIFFs from PASDA (dataset
7001); the tile service is used because the pilot needs only a small area.

Zoom 19 is ~0.30 m per Web Mercator pixel, ~0.23 m on the ground at this
latitude. The render samples the ground at ~0.29 x 0.41 m, so z19 is enough.
Tiles are cached under data/raw/imagery/ and never re-downloaded.
"""

import math
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

from pixelphilly.projection import load_config, render_extent_wgs84, render_ground_polygon
from pixelphilly.sources import CITY_TILES, RAW, get_with_retry, record

SERVICE = "CityImagery_2024_3in"


def lon_to_tile_x(lon, z):
    return (lon + 180.0) / 360.0 * 2**z


def lat_to_tile_y(lat, z):
    r = math.radians(lat)
    return (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * 2**z


def main():
    cfg = load_config()
    z = cfg["imagery_zoom"]
    west, south, east, north = render_extent_wgs84(cfg)
    x0, x1 = int(lon_to_tile_x(west, z)), int(lon_to_tile_x(east, z))
    y0, y1 = int(lat_to_tile_y(north, z)), int(lat_to_tile_y(south, z))
    out_dir = RAW / "imagery" / SERVICE / str(z)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    if cfg.get("clip_frames_to_area"):
        # Large clipped areas: only tiles the kept frames actually see
        from shapely.geometry import box
        from shapely.prepared import prep

        poly = prep(render_ground_polygon(cfg))

        def tile_box(x, y):
            n = 2**z
            lon0, lon1 = x / n * 360 - 180, (x + 1) / n * 360 - 180
            lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
            lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
            return box(lon0, lat0, lon1, lat1)

        jobs = [(x, y) for x, y in jobs if poly.intersects(tile_box(x, y))]
    # A ".none" marker means the server has no imagery there (HTTP 404, e.g.
    # across the river outside the city's coverage); don't ask again
    todo = [(x, y) for x, y in jobs
            if not (out_dir / f"{y}_{x}.jpg").exists() and not (out_dir / f"{y}_{x}.none").exists()]
    print(f"{len(jobs)} tiles at z{z}; {len(todo)} to download")

    def get(xy):
        x, y = xy
        try:
            r = get_with_retry(f"{CITY_TILES}/{SERVICE}/MapServer/tile/{z}/{y}/{x}")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                (out_dir / f"{y}_{x}.none").touch()
                return
            raise
        if not r.headers.get("Content-Type", "").startswith("image/"):
            raise RuntimeError(f"tile {z}/{y}/{x}: not an image ({r.headers.get('Content-Type')})")
        # Write to a temp name and rename, so an interrupted run never leaves
        # a truncated tile that a rerun would mistake for a finished one.
        tmp = out_dir / f"{y}_{x}.jpg.part"
        tmp.write_bytes(r.content)
        tmp.rename(out_dir / f"{y}_{x}.jpg")

    # A handful of parallel requests keeps this to a couple of minutes without
    # hammering the city's tile server.
    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for _ in pool.map(get, todo):
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(todo)}", file=sys.stderr)

    record(
        # One manifest entry per area (tiles are cached in one shared folder,
        # but each area's scene needs its own tile range)
        f"imagery/{cfg['name']}/{SERVICE}/{z}",
        {
            "description": "City of Philadelphia 2024 3-inch aerial imagery, Web Mercator tiles",
            "tile_url_template": f"{CITY_TILES}/{SERVICE}/MapServer/tile/{{z}}/{{y}}/{{x}}",
            "zoom": z,
            "tile_x_range": [x0, x1],
            "tile_y_range": [y0, y1],
            "tile_count": len(jobs),
            "tiles_without_coverage": sum(1 for x, y in jobs if (out_dir / f"{y}_{x}.none").exists()),
        },
    )


if __name__ == "__main__":
    main()
