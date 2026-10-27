"""Download property records (OPA) and Water Department parcel ids for the area.

Used for façades (src/pixelphilly/facades.py): what each building is
(rowhouse, twin, warehouse, office tower), its stories and main material.

- data/raw/<area>_opa.geojson: opa_properties_public points with the
  facade columns only (pixelphilly.opa.OPA_COLUMNS)
- data/raw/<area>_pwd_parcels.json: pwd_parcels parcelid -> brt_id (OPA's
  parcel_number), no geometry; joins footprints' parcel_id_num to OPA

Owner, mailing, sale, tax and exemption fields and exterior_condition are
never requested, and the raw files are checked for them before writing
(pixelphilly.opa). City of Philadelphia License. The extent is the area's
render extent, like the footprints.

Usage: PP_AREA=atlas_indhall_fac uv run python scripts/04f_fetch_opa.py
"""

from pixelphilly.opa import opa_sql, pwd_sql
from pixelphilly.projection import load_config, render_extent_wgs84
from pixelphilly.sources import fetch_carto

cfg = load_config()
bbox = render_extent_wgs84(cfg)
fetch_carto(opa_sql(bbox), bbox, f"{cfg['name']}_opa.geojson",
            "OPA opa_properties_public: property points with building code, stories, construction, year "
            "(explicit columns; no owner, mailing, sale, tax or condition fields)")
fetch_carto(pwd_sql(bbox), bbox, f"{cfg['name']}_pwd_parcels.json",
            "Water Department pwd_parcels: parcelid and brt_id (OPA parcel_number) only", fmt="json")
