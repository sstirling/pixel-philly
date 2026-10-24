"""Download the City's expressway and ramp centerlines for the area.

Used to keep elevated highways out of LiDAR structures
(pixelphilly.lidar.structures): I-95's decks are mostly LAS class 1, not
bridge class 17 (one ramp at the I-95/I-76 interchange: 186,515 class-1
points vs. 12 class-17), so the class filter alone let viaducts through as
"ships and containers". The street centerline CLASS field: 1 = expressway
mainline ("NB DELAWARE EXPY", "WB SCHUYLKILL EXPY"), 9 and 10 = ramps
("PACKER AVE RAMP", "DELAWARE EXPY RAMP H").

SEPTA's elevated rail (the Market-Frankford El) isn't a street, so it isn't
here; North Philly will need a rail layer for it.

Writes data/raw/<area>_highways.geojson (recorded in MANIFEST.json).
Usage: PP_AREA=atlas_i95_lidar uv run python scripts/04d_fetch_highways.py
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(
    cfg,
    "Street_Centerline",
    0,
    "highways",
    "City of Philadelphia street centerlines, expressways (class 1) and ramps (class 9, 10)",
    where="class IN (1,9,10)",
)
