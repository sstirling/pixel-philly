"""Queries for the City's property records (OPA), with a PII guard.

Source: Office of Property Assessment, `opa_properties_public` (one row per
property; nightly) and the Water Department's `pwd_parcels` (parcel polygons,
whose `brt_id` is OPA's `parcel_number`), both on the City's Carto SQL API
(https://phl.carto.com/api/v2/sql). City of Philadelphia License.

The OPA table also holds owner names, mailing addresses, sale and tax
figures. None of that is needed to draw a building, so every query lists its
columns explicitly (never SELECT *) and check_columns / assert_no_pii refuse
anything on the forbidden list, at query time and again on the raw file.
`exterior_condition` is excluded too, by editorial rule: the map does not
encode vacancy or condition, which would stigmatize blocks.
"""

from __future__ import annotations

from fnmatch import fnmatch

CARTO_SQL = "https://phl.carto.com/api/v2/sql"

# What the facade spec uses (pixelphilly.facades); the_geom is the property point
OPA_COLUMNS = [
    "parcel_number",
    "location",
    "category_code_description",
    "building_code_description",
    "building_code_new",
    "building_code_description_new",
    "general_construction",
    "number_stories",
    "year_built",
    "year_built_estimate",
    "quality_grade",
]
PWD_COLUMNS = ["parcelid", "brt_id"]

FORBIDDEN_PATTERNS = [
    "owner*",
    "mailing*",
    "sale*",
    "taxable*",
    "exempt*",
    "market_value",
    "homestead*",
    "exterior_condition",
    "book_and_page",
    "registry_number",
    "cross_reference",
    "recording_date",
]


def check_columns(columns) -> None:
    """Raise ValueError if any column is on the forbidden list."""
    bad = [c for c in columns if any(fnmatch(str(c).lower(), p) for p in FORBIDDEN_PATTERNS)]
    if bad:
        raise ValueError(f"forbidden OPA columns (PII or condition): {bad}")


def assert_no_pii(data) -> None:
    """Check a fetched GeoJSON FeatureCollection or Carto JSON ({"rows": [...]})."""
    rows = [f.get("properties") or {} for f in data.get("features", [])] + list(data.get("rows", []))
    keys = set()
    for r in rows:
        keys.update(r)
    check_columns(sorted(keys))


def _envelope(bbox) -> str:
    w, s, e, n = (float(v) for v in bbox)
    return f"ST_MakeEnvelope({w}, {s}, {e}, {n}, 4326)"


def opa_sql(bbox) -> str:
    """Property points (the_geom) and the facade columns inside a WGS84 bbox."""
    check_columns(OPA_COLUMNS)
    return (f"SELECT the_geom, {', '.join(OPA_COLUMNS)} FROM opa_properties_public "
            f"WHERE the_geom && {_envelope(bbox)} ORDER BY cartodb_id")


def pwd_sql(bbox) -> str:
    """Parcel id -> OPA parcel number for Water Department parcels touching the bbox (no geometry)."""
    check_columns(PWD_COLUMNS)
    return (f"SELECT {', '.join(PWD_COLUMNS)} FROM pwd_parcels "
            f"WHERE the_geom && {_envelope(bbox)} ORDER BY parcelid")
