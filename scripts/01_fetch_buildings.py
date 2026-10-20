"""Download City of Philadelphia L&I building footprints for the render extent.

Source: OpenDataPhilly "Building Footprints" (LI_BUILDING_FOOTPRINTS), updated
weekly by the city. Heights (approx_hgt, max_hgt) are in feet, from LiDAR.
"""

from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_features

cfg = load_config()
fetch_features(
    "LI_BUILDING_FOOTPRINTS",
    0,
    render_extent_wgs84(cfg),
    f"{cfg['name']}_buildings.geojson",
    "City of Philadelphia L&I building footprints with LiDAR-derived heights (feet)",
)
