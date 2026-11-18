"""Local stand-in for the live transit Worker (worker/septa-live.js), for
working on the viewer without deploying anything.

Polls SEPTA's TransitViewAll and TrainView feeds every 15 s and writes the
same file the Worker writes to R2, at output/live/vehicles.json. Start the
local server too (uv run python -m http.server 8000) and open
http://localhost:8000/viewer/?live=local

normalize() must give exactly what the Worker's normalize() gives;
tests/test_live_feed.py checks both against saved SEPTA responses.

Usage: uv run python scripts/38_live_feed.py [--once] [--save-fixture DIR]
"""

import argparse
import json
import math
import time

from pixelphilly.projection import REPO_ROOT
from pixelphilly.sources import session

TRANSITVIEW = "https://www3.septa.org/api/TransitViewAll/index.php"
TRAINVIEW = "https://www3.septa.org/api/TrainView/index.php"
BOUNDS = [-75.28399636541867, 39.86480815125875, -74.94781362117637, 40.141246179090835]
MAX_REPORT_AGE_S = 300
OUT = REPO_ROOT / "output" / "live" / "vehicles.json"


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _js_number(x):
    """Whole floats as ints, as JSON.stringify writes them."""
    return int(x) if x is not None and float(x).is_integer() else x


def _round6(x):
    # Math.round(x * 1e6) / 1e6, including JavaScript's round-half-up
    return math.floor(x * 1e6 + 0.5) / 1e6


def _late(v):
    x = _num(v)
    return None if x is None or abs(x) > 600 else _js_number(x)


def _inside(lon, lat, b):
    return b[0] <= lon <= b[2] and b[1] <= lat <= b[3]


# TrainView reports trains it can't locate at one fixed point in Suburban Station,
# even when their current stop is miles away (observed, not documented; 7 of 24
# trains in tests/fixtures/septa/trainview.json). Same test as worker/septa-live.js:
# equal at 5 decimal places (about 1 m), rounding half up like JavaScript's Math.round
PLACEHOLDER = (-75.1677778, 39.9538889)


def _is_placeholder(lon, lat):
    return all(math.floor(v * 1e5 + 0.5) == math.floor(p * 1e5 + 0.5) for v, p in zip((lon, lat), PLACEHOLDER))


def normalize(transit_view, train_view, now_s, bounds=BOUNDS):
    vehicles = []
    for group in (transit_view or {}).get("routes", []):
        for route, items in group.items():
            for v in items or []:
                lon, lat, ts = _num(v.get("lng")), _num(v.get("lat")), _num(v.get("timestamp"))
                if lon is None or lat is None or not _inside(lon, lat, bounds):
                    continue
                if ts is not None and now_s - ts > MAX_REPORT_AGE_S:
                    continue
                vid = v.get("VehicleID") if v.get("VehicleID") is not None else v.get("label", "")
                vehicles.append(["tv", str(v.get("route_id") or route), str(vid if vid is not None else ""),
                                 _js_number(_round6(lon)), _js_number(_round6(lat)), _js_number(_num(v.get("heading"))),
                                 _late(v.get("late")), str(v.get("destination") or ""),
                                 _js_number(ts if ts is not None else now_s), None])
    for t in train_view if isinstance(train_view, list) else []:
        lon, lat = _num(t.get("lon")), _num(t.get("lat"))
        if lon is None or lat is None or not _inside(lon, lat, bounds) or _is_placeholder(lon, lat):
            continue
        consist = len([c for c in str(t.get("consist") or "").split(",") if c.strip()])
        vehicles.append(["rr", str(t.get("line") or ""), str(t.get("trainno") or ""),
                         _js_number(_round6(lon)), _js_number(_round6(lat)), None, _late(t.get("late")),
                         str(t.get("dest") or ""), now_s, consist or None])
    vehicles.sort(key=lambda v: v[0] + v[2])
    return {"fetched": now_s, "vehicles": vehicles}


def poll(save_fixture=None):
    tv = session.get(TRANSITVIEW, timeout=30).json()
    rr = session.get(TRAINVIEW, timeout=30).json()
    now = int(time.time())
    if save_fixture:
        save_fixture.mkdir(parents=True, exist_ok=True)
        (save_fixture / "transitview.json").write_text(json.dumps(tv))
        (save_fixture / "trainview.json").write_text(json.dumps(rr))
        (save_fixture / "fetched.txt").write_text(f"{now}\n")
    out = normalize(tv, rr, now)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, separators=(",", ":")))
    tmp.replace(OUT)  # atomic: the viewer never reads a half-written file
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--save-fixture", type=lambda p: REPO_ROOT / p)
    args = ap.parse_args()
    while True:
        started = time.time()
        try:
            out = poll(args.save_fixture)
            kinds = {}
            for v in out["vehicles"]:
                kinds[v[0]] = kinds.get(v[0], 0) + 1
            print(f"{time.strftime('%H:%M:%S')} {len(out['vehicles'])} vehicles {kinds}", flush=True)
        except Exception as e:  # keep the last good file, like the Worker
            print(f"{time.strftime('%H:%M:%S')} poll failed: {e}", flush=True)
        if args.once:
            break
        time.sleep(max(0.0, 15 - (time.time() - started)))


if __name__ == "__main__":
    main()
