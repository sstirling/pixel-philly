"""Download OpenStreetMap piers and moored ships for the area.

Used by the water repaint's protection mask (config/vessels.json plus these
piers: pixelphilly.vessels): a pier deck inside the NHD river polygon whose
render color happens to match the river would otherwise be repainted as water
(the brick pier beside the USS New Jersey, Nov. 5). Fetches man_made=pier
(areas, and lines that are buffered by their width or 3 m) and
building=ship / historic=ship features for reference.

Writes data/raw/<area>_piers.json (Overpass JSON). License: ODbL 1.0; credit
"© OpenStreetMap contributors".

Usage: PP_AREA=south_lidar uv run python scripts/04o_fetch_piers.py
"""

from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_overpass

cfg = load_config()
w, s, e, n = render_extent_wgs84(cfg)
box = f"{s},{w},{n},{e}"
sel = [f'nwr["man_made"="pier"]({box});', f'nwr["building"="ship"]({box});', f'nwr["historic"="ship"]({box});']
query = f'[out:json][timeout:180];({"".join(sel)});out tags geom;'
fetch_overpass(query, [w, s, e, n], f"{cfg['name']}_piers.json",
               "OpenStreetMap piers (man_made=pier) and ships (building=ship, historic=ship) via Overpass")
