"""Download helpers for City of Philadelphia ArcGIS services.

Every download is recorded in data/raw/MANIFEST.json with its exact query URL
and fetch time, so anyone can re-fetch the same data or see how stale it is.
Raw files are written once and never edited; later steps write to
data/processed/.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

from .projection import REPO_ROOT

RAW = REPO_ROOT / "data" / "raw"
MANIFEST = RAW / "MANIFEST.json"

CITY_FEATURES = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
CITY_TILES = "https://tiles.arcgis.com/tiles/fLeGjb7u4uXqeF9q/arcgis/rest/services"

USER_AGENT = "pixel-philly (https://github.com/sstirling/pixel-philly; stephenstirling@gmail.com)"

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def record(key: str, entry: dict) -> None:
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    entry = {**entry, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    manifest[key] = entry
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


def get_with_retry(url: str, params=None, tries: int = 4, timeout: int = 60):
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
        except requests.RequestException:
            if attempt == tries - 1:
                raise
        time.sleep(2**attempt)
    r.raise_for_status()
    return r


def fetch_features(
    service: str,
    layer: int,
    bbox_wgs84,
    out_name: str,
    description: str,
    base_url: str = CITY_FEATURES,
    server_type: str = "FeatureServer",
    order_by: str | None = "objectid",
) -> Path:
    """Download every feature intersecting the bbox as GeoJSON (EPSG:4326).

    ArcGIS caps each response (2,000 records for these layers), so pages are
    requested with resultOffset until the server stops flagging
    exceededTransferLimit.
    """
    out = RAW / out_name
    if out.exists():
        # Raw files are immutable, but a file fetched for a different extent
        # (e.g. after a camera change) must not be reused silently.
        manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        prior = manifest.get(out_name, {}).get("bbox_wgs84")
        if prior is not None and [round(v, 7) for v in prior] != [round(v, 7) for v in bbox_wgs84]:
            raise SystemExit(
                f"{out_name} was fetched for bbox {prior}, not {list(bbox_wgs84)}. "
                "Delete it (and its manifest entry will be replaced) to re-fetch."
            )
        print(f"{out_name} already downloaded; raw files are immutable, skipping")
        return out

    url = f"{base_url}/{service}/{server_type}/{layer}/query"
    base = {
        "where": "1=1",
        "geometry": ",".join(str(v) for v in bbox_wgs84),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "outSR": 4326,
        "f": "geojson",
    }
    if order_by:
        base["orderByFields"] = order_by
    features, offset = [], 0
    while True:
        page = get_with_retry(url, {**base, "resultOffset": offset}).json()
        if "error" in page:
            raise RuntimeError(f"{service}: {page['error']}")
        batch = page.get("features", [])
        features.extend(batch)
        offset += len(batch)
        more = page.get("exceededTransferLimit") or page.get("properties", {}).get(
            "exceededTransferLimit"
        )
        if not batch or not more:
            break

    count = get_with_retry(url, {**base, "returnCountOnly": "true", "f": "json"}).json()["count"]
    if count != len(features):
        raise RuntimeError(f"{service}: server reports {count} features, downloaded {len(features)}")

    RAW.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    record(
        out_name,
        {
            "description": description,
            "query_url": f"{url}?{urlencode(base)}",
            "bbox_wgs84": list(bbox_wgs84),
            "feature_count": len(features),
        },
    )
    print(f"{out_name}: {len(features)} features")
    return out
