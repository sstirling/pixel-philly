"""ArcGIS download retries."""

import json

from pixelphilly import sources


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_count_query_retries_an_error_body(tmp_path, monkeypatch):
    # Real case (Oct. 23, twice): the count query came back HTTP 200 with an
    # ArcGIS "error" body, and fetch_features crashed with KeyError: 'count'.
    # The feature pages already retried those; the count query didn't
    feature = {"type": "Feature", "geometry": None, "properties": {"objectid": 1}}
    replies = iter([
        {"type": "FeatureCollection", "features": [feature]},  # page 1
        {"error": {"code": 500, "message": "Unable to perform query"}},  # count, transient
        {"count": 1},  # count, retried
    ])
    monkeypatch.setattr(sources, "get_with_retry", lambda *a, **k: _Resp(next(replies)))
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    monkeypatch.setattr(sources, "RAW", tmp_path)
    monkeypatch.setattr(sources, "MANIFEST", tmp_path / "MANIFEST.json")
    out = sources.fetch_features("svc", 0, [-75.2, 39.9, -75.1, 40.0], "test.geojson", "test layer",
                                 base_url="https://example.test/arcgis/rest/services")
    assert len(json.loads(out.read_text())["features"]) == 1


def _carto_env(tmp_path, monkeypatch, pages):
    replies = iter(pages)
    monkeypatch.setattr(sources, "get_with_retry", lambda *a, **k: _Resp(next(replies)))
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    monkeypatch.setattr(sources, "RAW", tmp_path)
    monkeypatch.setattr(sources, "MANIFEST", tmp_path / "MANIFEST.json")


def test_carto_fetch_pages_and_records(tmp_path, monkeypatch):
    feat = lambda i: {"type": "Feature", "geometry": None, "properties": {"parcel_number": str(i)}}  # noqa: E731
    _carto_env(tmp_path, monkeypatch, [{"type": "FeatureCollection", "features": [feat(1), feat(2)]},
                                       {"type": "FeatureCollection", "features": [feat(3)]}])
    out = sources.fetch_carto("SELECT the_geom, parcel_number FROM t ORDER BY cartodb_id", [-75.2, 39.9, -75.1, 40.0],
                              "a_opa.geojson", "test", page=2)
    assert [f["properties"]["parcel_number"] for f in json.loads(out.read_text())["features"]] == ["1", "2", "3"]
    assert json.loads((tmp_path / "MANIFEST.json").read_text())["a_opa.geojson"]["feature_count"] == 3


def test_carto_fetch_refuses_pii_and_writes_nothing(tmp_path, monkeypatch):
    # If the service ever returned owner fields (a changed view, a typo in a
    # column list), nothing reaches data/raw
    import pytest

    bad = {"type": "Feature", "geometry": None, "properties": {"parcel_number": "1", "owner_1": "SMITH JOHN"}}
    _carto_env(tmp_path, monkeypatch, [{"type": "FeatureCollection", "features": [bad]}])
    with pytest.raises(ValueError, match="forbidden"):
        sources.fetch_carto("SELECT the_geom, parcel_number FROM t ORDER BY cartodb_id", [-75.2, 39.9, -75.1, 40.0],
                            "b_opa.geojson", "test")
    assert not (tmp_path / "b_opa.geojson").exists()


def test_overpass_fetch_records_the_odbl_credit(tmp_path, monkeypatch):
    body = {"elements": [{"type": "way", "id": 1, "tags": {"building": "yes", "building:colour": "#c8b89a"},
                          "geometry": [{"lat": 39.95, "lon": -75.16}]}]}
    _carto_env(tmp_path, monkeypatch, [body])
    out = sources.fetch_overpass("[out:json];way[building](39.9,-75.2,40.0,-75.1);out tags geom;",
                                 [-75.2, 39.9, -75.1, 40.0], "a_osm.json", "test")
    assert json.loads(out.read_text())["elements"][0]["id"] == 1
    entry = json.loads((tmp_path / "MANIFEST.json").read_text())["a_osm.json"]
    assert "ODbL" in entry["license"] and entry["credit"] == "© OpenStreetMap contributors"
