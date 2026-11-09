"""Download OpenStreetMap bridges for the area: ways tagged bridge=* (not
"no") that carry a highway or railway, with full geometry.

Used by the water repaint's bridge bands (pixelphilly.bridges) alongside the
City street and rail centerlines: the City layers stop at the city line, so
the New Jersey halves of the Delaware bridges (Ben Franklin, Walt Whitman,
Betsy Ross, Tacony-Palmyra) come only from OSM, as do footbridges.

Writes data/raw/<area>_bridges.json (Overpass JSON). License: ODbL 1.0;
credit "© OpenStreetMap contributors".

Usage: PP_AREA=south_lidar uv run python scripts/04p_fetch_bridges.py
"""

from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_overpass

cfg = load_config()
w, s, e, n = render_extent_wgs84(cfg)
box = f"{s},{w},{n},{e}"
sel = [f'way["bridge"]["bridge"!="no"]["highway"]({box});', f'way["bridge"]["bridge"!="no"]["railway"]({box});']
query = f'[out:json][timeout:180];({"".join(sel)});out tags geom;'
fetch_overpass(query, [w, s, e, n], f"{cfg['name']}_bridges.json",
               "OpenStreetMap bridges (ways with bridge=* carrying a highway or railway) via Overpass")
