"""QA gate before the GPU drawing: needles, stadiums, LiDAR fallbacks.

Reads the area's scene(s) and QA file, runs the needle scan
(pixelphilly.qa_scan) and lists the footprints treated as stadiums. Every hit
should be checked against the 2024 aerial before paying for a drawing; the
known downtown exception is 905-11 Walnut St (a 6.5 m², 51 m part kept
because it matches the footprint's typical City height).

Writes output/<area>/qa_scan.json.
Usage: PP_AREA=south_lidar uv run python scripts/18_qa_scan.py
"""

import json

from pixelphilly.projection import REPO_ROOT, area_dir, load_config
from pixelphilly.qa_scan import find_needles
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
        n.update(describe(n["id"].rsplit("-", 1)[0]))
    report = {
        "area": name,
        "parts": len(parts),
        "needles": needles,
        "stadiums": [{"id": i, **describe(i)} for i in qa.get("lidar_stadiums", [])],
        "lidar_fallback_single_height": qa.get("lidar_fallback_single_height"),
        "lidar_terrace_parts": qa.get("lidar_terrace_parts"),
    }
    out = area_dir(cfg, "qa_scan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{len(parts):,} parts; {len(needles)} needle(s); stadiums: "
          f"{', '.join(str(s['address']) for s in report['stadiums']) or 'none'}; "
          f"{report['lidar_fallback_single_height']} LiDAR fallbacks")
    for n in needles:
        print(f"  needle {n['id']} {n['address']}: {n['h_m']:.1f} m beside {n['neighbor_max_m']:.1f} m, {n['area_m2']} m²")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
