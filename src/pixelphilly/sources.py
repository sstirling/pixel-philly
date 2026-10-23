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


def get_with_retry(url: str, params=None, tries: int = 6, timeout: int = 60, post: bool = False):
    """GET (or POST, for long polygon queries that would overflow a URL)
    with exponential backoff on network errors, 5xx and 429. Six tries wait
    ~30 s in all: the USGS NHD server answers 504 for minutes at a time when
    busy (Oct. 22), which four tries (~7 s) didn't ride out."""
    for attempt in range(tries):
        try:
            r = session.post(url, data=params, timeout=timeout) if post else session.get(url, params=params, timeout=timeout)
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
    polygon=None,
) -> Path:
    """Download every feature intersecting the bbox as GeoJSON (EPSG:4326).

    With `polygon` (a shapely WGS84 polygon), only features intersecting it
    are fetched, which for a large area seen at ~45 degrees halves the
    download. The query is then sent by POST, since the polygon would
    overflow a URL; bbox_wgs84 should be the polygon's bounds.

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
    if polygon is not None:
        # ~10 m tolerance keeps the query small without losing coverage (the
        # polygon already has a 50 m margin)
        simple = polygon.simplify(0.0001)
        rings = [list(map(list, simple.exterior.coords))] + [list(map(list, r.coords)) for r in simple.interiors]
        base["geometry"] = json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}})
        base["geometryType"] = "esriGeometryPolygon"
    if order_by:
        base["orderByFields"] = order_by
    post = polygon is not None
    features, offset = [], 0
    while True:
        # ArcGIS sometimes reports a transient failure as HTTP 200 with an
        # "error" body ("Unable to perform query"); retry those too
        for attempt in range(4):
            page = get_with_retry(url, {**base, "resultOffset": offset}, post=post).json()
            if "error" not in page:
                break
            time.sleep(2**attempt)
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

    count = get_with_retry(url, {**base, "returnCountOnly": "true", "f": "json"}, post=post).json()["count"]
    if count != len(features):
        raise RuntimeError(f"{service}: server reports {count} features, downloaded {len(features)}")

    RAW.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    record(
        out_name,
        {
            "description": description,
            "query_url": f"{url}?{urlencode({k: v for k, v in base.items() if k != 'geometry'})}",
            "query_geometry": base["geometry"] if polygon is not None else None,
            "bbox_wgs84": list(bbox_wgs84),
            "feature_count": len(features),
        },
    )
    print(f"{out_name}: {len(features)} features")
    return out


def fetch_area_features(cfg: dict, service: str, layer: int, suffix: str, description: str, **kwargs) -> Path:
    """fetch_features for an area config: by polygon for clipped areas
    (only the ground the kept frames see), by bounding box otherwise (the
    original behavior, so existing areas' queries are unchanged)."""
    from .projection import render_extent_wgs84, render_ground_polygon

    out_name = f"{cfg['name']}_{suffix}.geojson"
    if cfg.get("clip_frames_to_area"):
        poly = render_ground_polygon(cfg)
        return fetch_features(service, layer, list(poly.bounds), out_name, description, polygon=poly, **kwargs)
    return fetch_features(service, layer, render_extent_wgs84(cfg), out_name, description, **kwargs)
