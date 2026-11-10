"""Download OpenStreetMap outlines of the Delaware River suspension-bridge
towers (Ben Franklin and Walt Whitman).

The 2024 aerial shows each tower only from above, and the 2022 LiDAR shapes
on the decks were removed (pixelphilly.bridges.drop_deck_parts), so without
these the model drew the bridges with one tower or none (Nov. 9 redraw,
output/review/bridges/nj/gpu_test/). The outlines give each tower's
position and leg footprint; heights come from config/bridge_towers.json,
which cites published sources. Fetches man_made=tower, bridge:support and
building=* features with "tower" in a tag, within ~200 m of the four tower
points found by the Nov. 9 research.

Writes data/raw/<area>_bridge_towers.json (Overpass JSON). License: ODbL
1.0; credit "© OpenStreetMap contributors".

Usage: PP_AREA=south_lidar uv run python scripts/04q_fetch_bridge_towers.py
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_overpass

# Tower points (OSM ways 754832342 and 755034376 for the PA towers; the NJ
# points from the same mapping), used only to scope the query
POINTS = [(-75.1376656, 39.9534928), (-75.1316924, 39.9524523),
          (-75.1327797, 39.9057984), (-75.1258158, 39.9045817)]

cfg = load_config()
sel = []
for lon, lat in POINTS:
    a = f"around:200,{lat},{lon}"
    sel += [f'nwr["man_made"="tower"]({a});', f'nwr["bridge:support"]({a});',
            f'nwr["bridge:structure"]({a});', f'way(754832342);', f'way(755034376);']
query = f'[out:json][timeout:180];({"".join(sel)});out tags geom;'
w = min(p[0] for p in POINTS) - 0.003; e = max(p[0] for p in POINTS) + 0.003
s = min(p[1] for p in POINTS) - 0.003; n = max(p[1] for p in POINTS) + 0.003
fetch_overpass(query, [w, s, e, n], f"{cfg['name']}_bridge_towers.json",
               "OpenStreetMap suspension-bridge tower outlines (man_made=tower, bridge:support) via Overpass")
