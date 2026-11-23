"""Audit OPA year_built for the map's buildings (investigation only; draws nothing).

Question (Nov. 22, 2026): could building styles use the year each building was
built? This measures how good that field is, using only the raw files the map
already has, unchanged:

- data/raw/<region>_opa.geojson: opa_properties_public points with
  year_built and year_built_estimate (scripts/04f_fetch_opa.py, fetched
  Oct. 25, 2026; City of Philadelphia License)
- data/raw/<region>_buildings.geojson: L&I building footprints (no year field)
- data/raw/<region>_pwd_parcels.json: footprint parcel id -> OPA parcel_number

Two levels:
1. Parcels: every OPA record in the 12 regions, deduplicated by
   parcel_number (regions overlap). Coverage, estimate flag, impossible
   values and round-number heaping, overall and by OPA style code.
2. Footprints: the 12 regions' footprints, deduplicated by objectid, joined to
   OPA with the map's own join (pixelphilly.facades.join: parcel, then
   address, then point in footprint), so the numbers describe what the
   renderer would actually see. Each footprint is placed in a neighborhood
   (data/raw/philadelphia-neighborhoods.geojson, CC BY 4.0, by an interior point) to
   help pick a pilot area.

"Plausible" year = 1682 (Penn's founding of the city) to 2026. OPA's
year_built_estimate "Y" marks a year the assessor estimated; "N" is
almost never set, and most other records leave the flag empty, so an empty
flag means "not flagged," not "verified." The audit reports Y / N / empty
separately, with round-number heaping for each.

Writes output/building_age/year_built_audit.json and prints a summary.

Usage: uv run python scripts/44_year_built_audit.py
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from shapely import STRtree
from shapely.geometry import Point, shape

from pixelphilly import facades

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "output" / "building_age"
REGIONS = ["south_lidar", "north_lidar", "upper_north_lidar", "west_lidar", "west_north", "southwest",
           "germantown", "east_riverfront", "roxborough", "lower_northeast", "northwest", "upper_northeast"]
MIN_YEAR, MAX_YEAR = 1682, 2026
VACANT = ("VACANT LAND",)
# Eras used in docs/building_age_styles.md (approximate; see the report's sources)
ERAS = [(1682, 1839, "pre1840"), (1840, 1879, "1840_1879"), (1880, 1904, "1880_1904"),
        (1905, 1929, "1905_1929"), (1930, 1944, "1930_1944"), (1945, 1974, "1945_1974"),
        (1975, 1999, "1975_1999"), (2000, 2026, "2000_2026")]


def year_of(rec):
    """(year or None, reason): reason is ok, missing, zero, or out_of_range."""
    raw = rec.get("year_built")
    if raw in (None, ""):
        return None, "missing"
    try:
        y = int(str(raw).strip())
    except ValueError:
        return None, "out_of_range"
    if y == 0:
        return None, "zero"
    if not MIN_YEAR <= y <= MAX_YEAR:
        return None, "out_of_range"
    return y, "ok"


def era(y):
    return next(name for lo, hi, name in ERAS if lo <= y <= hi)


def is_estimate(rec):
    return str(rec.get("year_built_estimate") or "").strip().upper() == "Y"


def style_code(rec):
    return rec.get("building_code_description_new") or f"(none) {rec.get('building_code_description') or ''}".strip()


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def summarize_years(recs):
    """Coverage, estimate share and heaping for a list of OPA records."""
    n = len(recs)
    reasons = Counter()
    years, est = [], 0
    for r in recs:
        y, why = year_of(r)
        reasons[why] += 1
        if y is not None:
            years.append(y)
            est += is_estimate(r)
    top = Counter(years).most_common(8)
    flags = defaultdict(list)
    for r in recs:
        y, _ = year_of(r)
        if y is not None:
            f = str(r.get("year_built_estimate") or "").strip().upper() or "empty"
            flags[f].append(y)
    by_flag = {f: {"n": len(v), "ends_in_0_or_5_pct": pct(sum(y % 5 == 0 for y in v), len(v)),
                   "top_years": [[y, c] for y, c in Counter(v).most_common(5)]} for f, v in flags.items()}
    return {
        "records": n,
        "plausible_year": len(years), "plausible_pct": pct(len(years), n),
        "missing": reasons["missing"], "zero": reasons["zero"], "out_of_range": reasons["out_of_range"],
        "estimate_flag_y_of_plausible": est, "estimate_pct_of_plausible": pct(est, len(years)),
        "ends_in_0_or_5_pct": pct(sum(y % 5 == 0 for y in years), len(years)),
        "by_estimate_flag": by_flag,
        "top_years": [[y, c, pct(c, len(years))] for y, c in top],
        "median_year": statistics.median(years) if years else None,
        "era_counts": dict(Counter(era(y) for y in years)),
    }


def load_opa():
    by_parcel, rows_by_region = {}, {}
    for reg in REGIONS:
        feats = json.loads((RAW / f"{reg}_opa.geojson").read_text())["features"]
        rows = []
        for f in feats:
            p = dict(f["properties"])
            if f.get("geometry"):
                p["_pt"] = shape(f["geometry"])
                rows.append(p)
            by_parcel.setdefault(str(p.get("parcel_number")), p)
        rows_by_region[reg] = rows
    return by_parcel, rows_by_region


def load_neighborhoods():
    path = RAW / "philadelphia-neighborhoods.geojson"
    if not path.exists():
        return None, []
    feats = json.loads(path.read_text())["features"]
    geoms = [shape(f["geometry"]) for f in feats]
    names = [f["properties"].get("LISTNAME") or f["properties"].get("MAPNAME") for f in feats]
    return STRtree(geoms), list(zip(geoms, names))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    by_parcel, rows_by_region = load_opa()
    parcels = list(by_parcel.values())
    built = [r for r in parcels if not str(r.get("category_code_description") or "").upper().startswith(VACANT)]

    report = {"parcels_all": summarize_years(parcels), "parcels_excluding_vacant_land": summarize_years(built)}

    by_style = defaultdict(list)
    for r in built:
        by_style[style_code(r)].append(r)
    report["parcels_by_opa_style"] = {
        k: {kk: v[kk] for kk in ("records", "plausible_pct", "estimate_pct_of_plausible", "median_year",
                                  "top_years", "era_counts")}
        for k, v in sorted(((k, summarize_years(v)) for k, v in by_style.items()), key=lambda kv: -kv[1]["records"])
        if v["records"] >= 200
    }

    # Footprints, with the map's own join
    nb_tree, nb = load_neighborhoods()
    seen = set()
    fp_rows = []  # (objectid, record or None, how, neighborhood, height_m, area_m2)
    for reg in REGIONS:
        feats = json.loads((RAW / f"{reg}_buildings.geojson").read_text())["features"]
        pwd_rows = json.loads((RAW / f"{reg}_pwd_parcels.json").read_text())["rows"]
        pwd = {str(r["parcelid"]): r["brt_id"] for r in pwd_rows}
        fps = []
        for f in feats:
            oid = f["properties"]["objectid"]
            if oid in seen or not f.get("geometry"):
                continue
            seen.add(oid)
            p = f["properties"]
            fps.append({"id": oid, "parcel_id_num": p.get("parcel_id_num"), "address": p.get("address"),
                        "geom": shape(f["geometry"]), "h": (p.get("approx_hgt") or 0) * 0.3048,
                        "area": p.get("Shape__Area") or 0})
        matches = facades.join(fps, rows_by_region[reg], pwd)
        for fp in fps:
            rec, how = matches[fp["id"]]
            name = None
            if nb_tree is not None:
                c = fp["geom"].representative_point()
                for i in nb_tree.query(c, predicate="within"):
                    name = nb[i][1]
                    break
            fp_rows.append((fp["id"], rec, how, name, fp["h"], fp["area"]))
        print(f"  {reg}: {len(fps):,} new footprints")

    n = len(fp_rows)
    matched = [(r, h, nm, ht, a) for _, r, h, nm, ht, a in fp_rows if r]
    with_year = [(r, nm) for r, _, nm, _, _ in matched if year_of(r)[0] is not None]
    recorded = [(r, nm) for r, nm in with_year if not is_estimate(r)]
    report["footprints"] = {
        "footprints": n,
        "matched_to_opa": len(matched), "matched_pct": pct(len(matched), n),
        "join_method": dict(Counter(h for _, h, _, _, _ in matched)),
        "with_plausible_year": len(with_year), "with_plausible_year_pct": pct(len(with_year), n),
        "with_year_not_flagged_estimate": len(recorded), "not_flagged_pct": pct(len(recorded), n),
        "summary_of_matched_records": summarize_years([r for r, _, _, _, _ in matched]),
        "map_style_counts": dict(Counter(facades.style_of(r, ht) for r, _, _, ht, _ in matched).most_common()),
    }
    # Era x map style, footprints with a plausible year
    cross = defaultdict(Counter)
    for r, _, _, ht, _ in matched:
        y = year_of(r)[0]
        if y is not None:
            cross[facades.style_of(r, ht)][era(y)] += 1
    # The OPA style code each map style collapses (era words: OLD STYLE, POST WAR, MODERN, RANCH ...)
    codes = defaultdict(Counter)
    for r, _, _, ht, _ in matched:
        codes[facades.style_of(r, ht)][style_code(r)] += 1
    report["footprints_opa_codes_by_map_style"] = {k: dict(v.most_common(12)) for k, v in codes.items()}
    report["footprints_era_by_map_style"] = {k: dict(v) for k, v in cross.items()}

    # Neighborhoods: candidates for a pilot (era mix, data quality)
    hood = defaultdict(list)
    for r, _, nm, _, _ in matched:
        hood[nm].append(r)
    hood_n = Counter(nm for _, _, _, nm, _, _ in fp_rows)
    hoods = {}
    for nm, recs in hood.items():
        s = summarize_years(recs)
        hoods[nm or "(none)"] = {"footprints": hood_n[nm], "matched": len(recs),
                                 "plausible_pct": s["plausible_pct"],
                                 "estimate_pct_of_plausible": s["estimate_pct_of_plausible"],
                                 "median_year": s["median_year"], "top_years": s["top_years"][:3],
                                 "era_counts": s["era_counts"]}
    report["neighborhoods"] = dict(sorted(hoods.items(), key=lambda kv: -kv[1]["footprints"]))
    report["notes"] = {
        "plausible_range": [MIN_YEAR, MAX_YEAR],
        "eras": ERAS,
        "sources": "data/raw/<region>_opa.geojson, _buildings.geojson, _pwd_parcels.json (MANIFEST.json); "
                   "data/raw/philadelphia-neighborhoods.geojson",
        "dedupe": "OPA by parcel_number, footprints by objectid (regions overlap)",
    }
    path = OUT / "year_built_audit.json"
    path.write_text(json.dumps(report, indent=1, default=str))

    p, f = report["parcels_excluding_vacant_land"], report["footprints"]
    print(f"\nParcels (excl. vacant land): {p['records']:,}; plausible year {p['plausible_pct']}%; "
          f"estimated {p['estimate_pct_of_plausible']}% of those; ends in 0/5 {p['ends_in_0_or_5_pct']}%; "
          f"missing {p['missing']:,}, zero {p['zero']:,}, out of range {p['out_of_range']:,}")
    print(f"  top years: {p['top_years']}")
    print(f"Footprints: {f['footprints']:,}; matched {f['matched_pct']}%; plausible year {f['with_plausible_year_pct']}%; "
          f"not flagged as estimate {f['not_flagged_pct']}%")
    print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
