"""Download National Wetlands Inventory polygons for the area.

Used to keep possibly-real water when looking for water the drawing model
invented on land (src/pixelphilly/invented_water.py): a blob 20% or more
inside a mapped wetland, pond or lake is left alone (lower South Philly
basins and mudflats are missing from NHD and PWD).

Source: U.S. Fish and Wildlife Service, National Wetlands Inventory,
fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0
(public domain, U.S. federal data). Writes data/raw/<area>_wetlands.geojson.

Usage: PP_AREA=south_lidar uv run python scripts/04k_fetch_wetlands.py
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(cfg, "Wetlands", 0, "wetlands", "USFWS National Wetlands Inventory polygons",
                    base_url="https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services",
                    server_type="MapServer", order_by="OBJECTID")
