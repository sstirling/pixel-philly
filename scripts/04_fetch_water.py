"""Download Philadelphia Water Department hydrographic polygons.

Used only as a QA overlay: it marks where the Delaware River is, so redraws
that invent objects on open water can be spotted (the failure tiny.london hit
most often).
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(
    cfg,
    "Hydrographic_Features_Poly",
    1,
    "water",
    "Philadelphia Water Department hydrographic features (polygons)",
)
