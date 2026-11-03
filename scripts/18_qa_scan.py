"""QA gate before the GPU drawing: needles, stadiums, LiDAR fallbacks,
LiDAR structures.

Reads the area's scene(s) and QA file, runs the needle scan
(pixelphilly.qa_scan) and lists the footprints treated as stadiums. Every hit
should be checked against the 2024 aerial before paying for a drawing
(structures too: the 20 largest are listed, since sheds, trailer rows and
billboards are the likely false positives); the
known downtown exception is 905-11 Walnut St (a 6.5 m², 51 m part kept
because it matches the footprint's typical City height).

Writes output/<area>/qa_scan.json.
Usage: PP_AREA=south_lidar uv run python scripts/18_qa_scan.py
"""

import json

from shapely.geometry import Polygon

from pixelphilly.projection import REPO_ROOT, area_dir, load_config
from pixelphilly.qa_scan import find_needles, footprint_id
from pixelphilly.scenes import scene_paths


def main():
    cfg = load_config()
    name = cfg["name"]
    # Render tiles overlap, so the same part appears in several scenes
    parts = {}
    for rel in scene_paths(cfg):
        for b in json.loads((REPO_ROOT / rel).read_text())["buildings"]:
            parts[str(b["id"])] = b
    raw = json.loads((REPO_ROOT / "data" / "raw" / f"{name}_buildings.geojson").read_text())
    props = {str(f["properties"]["objectid"]): f["properties"] for f in raw["features"]}
    qa = json.loads((REPO_ROOT / "data" / "processed" / f"{name}_qa.json").read_text())

    def describe(building_id):
        p = props.get(str(building_id), {})
        return {"address": p.get("address"), "approx_hgt_ft": p.get("approx_hgt"), "max_hgt_ft": p.get("max_hgt")}

    needles = find_needles(list(parts.values()))
    for n in needles:
        n.update(describe(footprint_id(n["id"])))
    # Structures (s<region>-<part>): one entry per region, its tallest part's
    # height, total area and center in local m
    regions = {}
    for pid, b in parts.items():
        if not pid.startswith("s"):
            continue
        polys = [Polygon(p[0], p[1:]) for p in b["polys"]]
        r = regions.setdefault(pid.rsplit("-", 1)[0], {"h_m": 0.0, "area_m2": 0.0, "_x": 0.0, "_y": 0.0})
        for g in polys:
            r["area_m2"] += g.area
            r["_x"] += g.centroid.x * g.area
            r["_y"] += g.centroid.y * g.area
        r["h_m"] = max(r["h_m"], b["h"])
    top = sorted(regions.items(), key=lambda kv: -kv[1]["area_m2"])[:20]
    structures = {"count": len(regions), "top_by_area": [
        {"id": k, "h_m": round(v["h_m"], 1), "area_m2": round(v["area_m2"], 1),
         "local_xy": [round(v["_x"] / v["area_m2"], 1), round(v["_y"] / v["area_m2"], 1)]}
        for k, v in top]}
    report = {
        "area": name,
        "parts": len(parts),
        "needles": needles,
        "stadiums": [{"id": i, **describe(i)} for i in qa.get("lidar_stadiums", [])],
        "lidar_fallback_single_height": qa.get("lidar_fallback_single_height"),
        "lidar_terrace_parts": qa.get("lidar_terrace_parts"),
        "structures": structures,
    }
    out = area_dir(cfg, "qa_scan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{len(parts):,} parts; {len(needles)} needle(s); stadiums: "
          f"{', '.join(str(s['address']) for s in report['stadiums']) or 'none'}; "
          f"{report['lidar_fallback_single_height']} LiDAR fallbacks")
    for n in needles:
        print(f"  needle {n['id']} {n['address']}: {n['h_m']:.1f} m beside {n['neighbor_max_m']:.1f} m, {n['area_m2']} m²")
    print(f"{structures['count']} structure(s); largest:")
    for t in structures["top_by_area"]:
        print(f"  {t['id']}: {t['h_m']} m, {t['area_m2']} m² at {t['local_xy']}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
