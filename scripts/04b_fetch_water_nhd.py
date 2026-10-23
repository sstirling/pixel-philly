"""Download USGS National Hydrography Dataset water areas for the render extent.

The PWD layer (04_fetch_water.py) stops at the state line in the middle of
the Delaware. NHD's large-scale "Area" layer covers both banks, so it is the
water mask for the post-redraw water repaint (10_postprocess.py). The PWD
layer stays as the source of the per-frame water sentence, so redraw prompts
remain identical to the ones already sent.

NHD is a U.S. federal dataset (public domain).
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

cfg = load_config()
fetch_area_features(
    cfg,
    "nhd",
    9,
    "water_nhd",
    "USGS National Hydrography Dataset, Area - Large Scale (both banks of the Delaware)",
    base_url="https://hydro.nationalmap.gov/arcgis/rest/services",
    server_type="MapServer",
    order_by=None,
)
