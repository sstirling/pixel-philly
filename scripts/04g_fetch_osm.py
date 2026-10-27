"""Download OpenStreetMap buildings and building parts for the area.

Used for façade colours and materials where mappers recorded them
(src/pixelphilly/facades.py: OSM colour or material wins over the property
record's material). Coverage is thin citywide (building:colour on 0.04% of
buildings, material on 1.4%), but the Center City skyline is well mapped,
often as coloured building:part shapes (One and Two Liberty, Three Logan,
Comcast Center, PSFS).

Writes data/raw/<area>_osm.json (Overpass JSON: ways and relations with a
building:colour or building:material tag, with all their tags and geometry). License: ODbL 1.0; credit "© OpenStreetMap
contributors" (recorded in the manifest and shown in map credits).

Usage: PP_AREA=atlas_cityhall_fac uv run python scripts/04g_fetch_osm.py
"""

from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_overpass

cfg = load_config()
w, s, e, n = render_extent_wgs84(cfg)
box = f"{s},{w},{n},{e}"
# Only shapes with a colour or material tag: the façade code uses nothing
# else, and all buildings of a whole region (South Philly, ~150,000) can
# exceed Overpass's time limit
sel = [f'{t}["{k}"]({box});' for t in ('way["building"]', 'way["building:part"]', 'relation["building"]',
                                         'relation["building:part"]') for k in ("building:colour", "building:material")]
query = f'[out:json][timeout:180];({"".join(sel)});out tags geom;'
fetch_overpass(query, [w, s, e, n], f"{cfg['name']}_osm.json",
               "OpenStreetMap buildings and building:part shapes (tags and geometry) via Overpass")
