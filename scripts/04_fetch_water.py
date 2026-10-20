"""Download Philadelphia Water Department hydrographic polygons.

Used only as a QA overlay: it marks where the Delaware River is, so redraws
that invent objects on open water can be spotted (the failure tiny.london hit
most often).
"""

from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_features

cfg = load_config()
fetch_features(
    "Hydrographic_Features_Poly",
    1,
    render_extent_wgs84(cfg),
    f"{cfg['name']}_water.geojson",
    "Philadelphia Water Department hydrographic features (polygons)",
)
