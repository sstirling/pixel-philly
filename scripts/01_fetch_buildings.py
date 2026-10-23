"""Download City of Philadelphia L&I building footprints for the render extent.

Source: OpenDataPhilly "Building Footprints" (LI_BUILDING_FOOTPRINTS), updated
weekly by the city. Heights (approx_hgt, max_hgt) are in feet, from LiDAR.
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(
    cfg,
    "LI_BUILDING_FOOTPRINTS",
    0,
    "buildings",
    "City of Philadelphia L&I building footprints with LiDAR-derived heights (feet)",
)
