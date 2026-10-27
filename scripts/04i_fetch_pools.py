"""Download the City's swimming pools (Parks & Recreation) for the area.

Used to keep real pools when looking for water the drawing model invents on
land (src/pixelphilly/invented_water.py): a water-colored blob near a City
pool is left alone.

Writes data/raw/<area>_pools.geojson (points; recorded in MANIFEST.json).
Usage: PP_AREA=south_lidar uv run python scripts/04i_fetch_pools.py
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(cfg, "PPR_Swimming_Pools", 0, "pools", "Philadelphia Parks & Recreation swimming pools (points)")
