"""Download park polygons for the area, for the dormant-lawn correction.

The 2024 aerial is leaf-off (March): lawns render brown and the drawing
model draws dirt. With "lawn_correct": true, 05_build_scene.py shifts
dormant-grass pixels toward green inside these polygons only
(src/pixelphilly/lawns.py).

- data/raw/<area>_parks.geojson: Philadelphia Parks & Recreation properties
  (PPR_Properties, City of Philadelphia License)
- data/raw/<area>_nps_parks.geojson: National Park Service unit boundaries
  (Land Resources Division service; US federal data, public domain). The
  City layer lacks federal parkland, e.g. Independence National Historical
  Park (the Mall, Independence Square).

Usage: PP_AREA=atlas_indhall_fac uv run python scripts/04j_fetch_parks.py
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(cfg, "PPR_Properties", 0, "parks", "Philadelphia Parks & Recreation properties (polygons)")
fetch_area_features(cfg, "NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service", 2, "nps_parks",
                    "National Park Service unit boundaries (Land Resources Division)",
                    base_url="https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services",
                    order_by="OBJECTID")
