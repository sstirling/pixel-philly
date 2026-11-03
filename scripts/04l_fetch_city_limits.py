"""Download the City of Philadelphia city-limits polygon.

Configs with "clip_to_city": true keep only the frames that see the part of
their bbox inside the city line (pixelphilly.projection.city_ground), so
regions along the city edge don't draw Upper Darby, Cheltenham or New Jersey
and the citywide map ends at the city line. scripts/22_run_region.py also
uses it for the coverage-gap check across all regions.

Source: City of Philadelphia, "City_Limits" (Department of Planning and
Development), ArcGIS feature service
services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/City_Limits/FeatureServer/0
(one polygon; metadata: https://metadata.phila.gov/#home/datasetdetails/5543868820583086178c4f89/).
License: City of Philadelphia open data terms, credit "City of Philadelphia".

Writes data/raw/city_limits.geojson (one file for every area, not per
area) and records the query in data/raw/MANIFEST.json. Like every raw file
it is written once; delete it to re-fetch.

Usage: uv run python scripts/04l_fetch_city_limits.py
"""

from pixelphilly.projection import CITY_FETCH_BBOX
from pixelphilly.sources import fetch_features

fetch_features("City_Limits", 0, CITY_FETCH_BBOX, "city_limits.geojson",
               "City of Philadelphia city limits (Department of Planning and Development), one polygon")
