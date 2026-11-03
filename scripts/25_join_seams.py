"""Seam ratios across region joins in a merged map.

For every frame border between cells owned by different regions (the same
ownership 16_build_tiles.py uses: first-listed area wins, water_band/
overrides applied), the two finished frames are put side by side and the
mean color jump across the border is divided by the mean jump between
neighboring pixels everywhere else in the pair (pixelphilly.qa
.seam_ratio_lines, tiny.london's measure). 1.0 = invisible. Reported per
region pair: count, median, 90th percentile, max and the worst edges.
Earlier joins measured this way: medians 2.27-2.45 (CHANGELOG Oct. 24).

Writes output/<name>/join_seams_<version>.json.
Usage: uv run python scripts/25_join_seams.py --areas south_lidar,...,germantown \\
           --prompt qwen_joint_light8_fac --name philly --version v8 [--only-new east_riverfront,...]
"""

import argparse
import json

import numpy as np
from PIL import Image

from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.qa import seam_ratio_lines
from pixelphilly.regions import cell_sources, owner_edges, union_lattice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--areas", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--stage", default="water")
    ap.add_argument("--name", default="philly")
    ap.add_argument("--version", required=True)
    ap.add_argument("--only-new", help="comma list: report only pairs involving these areas")
    args = ap.parse_args()
    names = [a.strip() for a in args.areas.split(",") if a.strip()]
    only = {a.strip() for a in (args.only_new or "").split(",") if a.strip()}
    cfgs = [load_config(n) for n in names]
    u = union_lattice([(c["name"], area_setup(c)[2]) for c in cfgs])
    size = cfgs[0]["camera"]["frame_px"]
    sources, _ = cell_sources(u, names, args.prompt, args.stage, REPO_ROOT)
    edges = [e for e in owner_edges(u["cells"], names) if not only or set(e["pair"].split("|")) & only]
    cache = {}

    def img(cell):
        if cell not in cache:
            if len(cache) > 64:
                cache.clear()
            cache[cell] = np.asarray(Image.open(sources[cell]).convert("RGB"))
        return cache[cell]

    rows = []
    for e in sorted(edges, key=lambda e: (e["a"], e["b"])):
        a, b = img(e["a"]), img(e["b"])
        if e["axis"] == "x":
            r = seam_ratio_lines(np.concatenate([a, b], axis=1), [size], [])
        else:
            r = seam_ratio_lines(np.concatenate([a, b], axis=0), [], [size])
        rows.append({**e, "ratio": round(r, 3), "frames": [u["cells"][e["a"]][1].name, u["cells"][e["b"]][1].name]})
    pairs = {}
    for r in rows:
        pairs.setdefault(r["pair"], []).append(r)
    summary = {}
    print(f"{'pair':40s} {'edges':>5s} {'median':>7s} {'p90':>6s} {'max':>6s}")
    for p, rs in sorted(pairs.items()):
        v = np.array([r["ratio"] for r in rs])
        worst = sorted(rs, key=lambda r: -r["ratio"])[:3]
        summary[p] = {"edges": len(rs), "median": round(float(np.median(v)), 2),
                      "p90": round(float(np.percentile(v, 90)), 2), "max": round(float(v.max()), 2),
                      "worst": [{"frames": w["frames"], "owners": p, "ratio": w["ratio"]} for w in worst]}
        print(f"{p:40s} {len(rs):5d} {summary[p]['median']:7.2f} {summary[p]['p90']:6.2f} {summary[p]['max']:6.2f}")
    out = REPO_ROOT / "output" / args.name / f"join_seams_{args.version}.json"
    out.write_text(json.dumps({"areas": names, "prompt": args.prompt, "pairs": summary, "edges": [
        {k: (list(v) if isinstance(v, tuple) else v) for k, v in r.items()} for r in rows]}, indent=1) + "\n")
    print(f"-> {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
