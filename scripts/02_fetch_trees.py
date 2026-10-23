"""Download the Philadelphia Parks & Recreation 2025 tree inventory.

The inventory covers street and park trees the city maintains, not trees on
private land, so it undercounts canopy in courtyards and backyards.
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(
    cfg,
    "ppr_tree_inventory_2025",
    0,
    "trees",
    "Philadelphia Parks & Recreation tree inventory, 2025 (street and park trees)",
)
