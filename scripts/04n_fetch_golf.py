"""Download OpenStreetMap golf courses and golf features for the area.

Used by the golf lawn correction ("golf_correct": true; src/pixelphilly/golf.py,
lawns.correct_golf) and the water repaint (water hazards). Fetches
leisure=golf_course (plus disused:/was: courses, so they can be excluded)
and golf=fairway/green/tee/bunker/rough/water_hazard/lateral_water_hazard,
with full geometry including relation members (`out geom`).

Writes data/raw/<area>_golf.json (Overpass JSON). License: ODbL 1.0; credit
"© OpenStreetMap contributors" (recorded in the manifest).

Usage: PP_AREA=germantown uv run python scripts/04n_fetch_golf.py
"""

from pixelphilly.golf import FEATURE_KINDS
from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_overpass

cfg = load_config()
w, s, e, n = render_extent_wgs84(cfg)
box = f"{s},{w},{n},{e}"
sel = [f'nwr["{k}"="golf_course"]({box});' for k in ("leisure", "disused:leisure", "was:leisure")]
sel += [f'nwr["golf"="{k}"]({box});' for k in FEATURE_KINDS]
query = f'[out:json][timeout:180];({"".join(sel)});out tags geom;'
fetch_overpass(query, [w, s, e, n], f"{cfg['name']}_golf.json",
               "OpenStreetMap golf courses and golf features (fairway, green, tee, bunker, rough, water hazards) via Overpass")
