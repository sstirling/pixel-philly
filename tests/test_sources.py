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
