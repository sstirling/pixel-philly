"""Download rail centerlines for the area, to mask elevated rail decks out
of LiDAR structures (pixelphilly.lidar.structures), as 04d does for
expressways.

- SEPTA Highspeed Lines, route L (the Market-Frankford El), from SEPTA's
  ArcGIS open data. Elevated along Front St and Kensington Ave; the line also
  runs underground under Market St downtown, where masking does nothing
  harmful (no LiDAR structure there). Route B (Broad Street Line) is
  underground in North Philly and is not fetched. No formal license on the
  item; OpenDataPhilly lists SEPTA data as "Public Use; Free". Credit: SEPTA.
- City of Philadelphia Railroad Lines (traced from aerials, updated 2004),
  fcode 1700. The fcode values are undocumented; 1700 matched surface track
  (it overlays the El and Regional Rail) and 1701 the underground Broad
  Street Line, by comparison with SEPTA's lines (Oct. 23, 2026).

Writes data/raw/<area>_rail_el.geojson and data/raw/<area>_rail.geojson.
Usage: PP_AREA=north_lidar uv run python scripts/04e_fetch_rail.py
"""

from pixelphilly.projection import load_config
from pixelphilly.sources import fetch_area_features

SEPTA = "https://services2.arcgis.com/9U43PSoL47wawX5S/arcgis/rest/services"

cfg = load_config()
fetch_area_features(
    cfg, "SEPTA_-_Highspeed_Lines", 0, "rail_el",
    "SEPTA Highspeed Lines, route L (Market-Frankford Line)",
    base_url=SEPTA, where="Route='L'", order_by="FID",
)
fetch_area_features(
    cfg, "Rail", 0, "rail",
    "City of Philadelphia Railroad Lines, fcode 1700 (surface track)",
    where="fcode=1700",
)
