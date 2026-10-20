"""Download the Philadelphia Parks & Recreation 2025 tree inventory.

The inventory covers street and park trees the city maintains, not trees on
private land, so it undercounts canopy in courtyards and backyards.
"""

from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_features

cfg = load_config()
fetch_features(
    "ppr_tree_inventory_2025",
    0,
    render_extent_wgs84(cfg),
    f"{cfg['name']}_trees.geojson",
    "Philadelphia Parks & Recreation tree inventory, 2025 (street and park trees)",
)
