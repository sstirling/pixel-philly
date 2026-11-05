"""Freeze a merged map version (e.g. the talk map): write
output/<name>/FROZEN_<version>.json with the tile counts, a SHA-256 over the
sorted list of (relative path, file SHA-256) lines, the regions, the drawing
run (prompt, LoRA) and the date. Rerun with --verify to check that nothing in
the version folder changed since.

    uv run python scripts/26_freeze_map.py --name philly --version v14
    uv run python scripts/26_freeze_map.py --name philly --version v14 --verify
"""

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_digest(root: Path) -> tuple[str, dict]:
    """(SHA-256 of "relpath  sha256\\n" lines in sorted path order, counts).
    The manifest itself lives outside the folder, so it isn't hashed."""
    files = sorted(p for p in root.rglob("*") if p.is_file())
    h = hashlib.sha256()
    counts = {"files": 0, "bytes": 0, "tiles": {}}
    for p in files:
        rel = p.relative_to(root).as_posix()
        h.update(f"{rel}  {file_sha(p)}\n".encode())
        counts["files"] += 1
        counts["bytes"] += p.stat().st_size
        top = rel.split("/")[0]
        if top.endswith("_files") and rel.endswith(".webp"):
            counts["tiles"][top] = counts["tiles"].get(top, 0) + 1
    return h.hexdigest(), counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="philly")
    ap.add_argument("--version", required=True)
    ap.add_argument("--run", default="qwen_joint_light8_fac", help="the drawing run the map was built from")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    root = REPO_ROOT / "output" / args.name / "tiles" / args.version
    manifest_path = REPO_ROOT / "output" / args.name / f"FROZEN_{args.version}.json"
    digest, counts = tree_digest(root)
    if args.verify:
        m = json.loads(manifest_path.read_text())
        ok = m["tree_sha256"] == digest
        print(f"{'OK' if ok else 'CHANGED'}: {digest} (manifest {m['tree_sha256']}), {counts['files']} files")
        sys.exit(0 if ok else 1)
    meta = json.loads((root / "map.json").read_text())
    regions = [a["area"] for a in meta["areas"]]
    # The run's settings as recorded by the GPU job of the first region
    style = prompt = None
    for a in regions:
        res = REPO_ROOT / "output" / a / "joint" / args.run / "result.json"
        if res.exists():
            r = json.loads(res.read_text())
            style = (r.get("settings", {}).get("style") or {}).get("path")
            prompt = r.get("prompt")
            break
    manifest = {
        "map": f"output/{args.name}/tiles/{args.version}/",
        "frozen": datetime.date.today().isoformat(),
        "purpose": "talk map: do not rebuild or edit this version; build a new version instead",
        "tree_sha256": digest,
        "tree_sha256_method": "SHA-256 over 'relative/path  <file sha256>\\n' lines, sorted by path, "
                              "every file under the version folder (scripts/26_freeze_map.py)",
        "files": counts["files"],
        "bytes": counts["bytes"],
        "tiles_per_layer": counts["tiles"],
        "regions_in_precedence_order": regions,
        "cells_per_region": {a["area"]: a.get("cells") for a in meta["areas"]},
        "drawing_run": args.run,
        "prompt": prompt,
        "style_lora": style,
        "lightning": "8-step",
        # Frames redrawn later (trees, golf, borders) were merged into the
        # run's folder; their source runs, same prompt and LoRA
        "redraw_runs_merged": {a: sorted(p.name for p in (REPO_ROOT / "output" / a / "redraws").glob(f"{args.run}_*")
                                         if not p.name.startswith(f"{args.run}_pre_")
                                         and not p.name.endswith("_forest"))  # forest redraws were reverted
                               for a in regions},
        "band_overrides": meta.get("band_overrides"),
        "built": meta.get("built"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"-> {manifest_path}: {counts['files']} files, {counts['bytes'] / 1e9:.2f} GB, {digest}")


if __name__ == "__main__":
    main()
