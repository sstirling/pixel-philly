"""Download all street centerlines for the area (every class).

Used to find each building's street-facing walls, where porch and
storefront bands are painted (facades.front_dirs). 04d fetches only
expressways and ramps; this takes every class (local streets included).

Writes data/raw/<area>_streets.geojson (recorded in MANIFEST.json).
Usage: PP_AREA=atlas_porch_fac uv run python scripts/04h_fetch_streets.py
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(cfg, "Street_Centerline", 0, "streets",
                    "City of Philadelphia street centerlines, all classes", where="1=1")
