"""Track 3, experiment A: does a reference photo help Qwen-Image-Edit-2511
draw a landmark that looks like itself?

For each landmark frame (a 1,024 px crop of an atlas render centered on the
landmark, cut by hand into output/landmarks/experiment_a/<slug>_render.png),
at one seed, with the pixel philly style LoRA and Lightning 8-step:
  no_ref        render only, the training caption (the current method)
  r<k>_p<j>     image=[reference k, render], prompt variant j
The render is the LAST image: diffusers takes the output size from it, and
the prompt calls it "Picture 2".

Scores each output against the render:
  shift         registration_shift on the whole frame (global translation)
  shift_center  registration_shift on the central 512 px (the landmark)
  edge_corr     zero-shift correlation of edge maps on the central 512 px;
                compare with no_ref: a clear drop means the landmark's
                geometry moved or was replaced (e.g. by the photo's view)
and writes a comparison sheet:
  render | no_ref | with-reference variants | reference photos

Writes:
  output/landmarks/experiment_a/<slug>_<variant>.png
  output/landmarks/experiment_a/results.json
  output/landmarks/experiment_a.jpg
  output/gpu_runs.jsonl

Usage:
  uv run python scripts/20_landmark_experiment_a.py --dry-run
  uv run python scripts/20_landmark_experiment_a.py
  uv run python scripts/20_landmark_experiment_a.py --sheet-only
"""

import argparse
import io
import json
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw

from pixelphilly.projection import REPO_ROOT
from pixelphilly.qa import _edges, flat_share, registration_shift

OUT = REPO_ROOT / "output" / "landmarks" / "experiment_a"
SHEET = REPO_ROOT / "output" / "landmarks" / "experiment_a.jpg"
STYLE = {"path": "/runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors", "scale": 1.0}
SEED = 0
H100_PER_HOUR = 3.95  # Modal list price, Oct. 20, 2026 (https://modal.com/pricing); estimate only
BUDGET_USD = 1.00

# The LoRA's fixed training caption (scripts/14_train_lora.py CAPTION)
BASE_PROMPT = "Redraw this render as isometric pixel art in the pixel philly style."
PROMPTS = {
    "p1": ("Redraw Picture 2 as isometric pixel art in the pixel philly style. The {where} in Picture 2 is "
           "the building shown in Picture 1: match its facade, materials and details, but keep exactly the "
           "shapes and positions of Picture 2."),
    "p2": ("Redraw Picture 2 as isometric pixel art in the pixel philly style. Picture 1 is a photo of "
           "{name}, which is the {where} in Picture 2. Give it the stone color, windows, columns and roof "
           "detail seen in Picture 1. Do not change the viewpoint, layout or outline of anything in Picture 2, "
           "and do not add buildings."),
}

# slug: (name for the prompt, where it is in the frame). References are
# chosen by eye from data/landmarks/refs/<slug>/ and passed with --refs.
LANDMARKS = {
    "city_hall": ("Philadelphia City Hall", "tall tower with a clock and a pointed top in the center"),
    "art_museum": ("the Philadelphia Museum of Art", "large building with three wings in the center"),
}


def edge_corr(a, b):
    ea, eb = _edges(a), _edges(b)
    return float((ea * eb).mean())


def center(img, s=512):
    w, h = img.size
    return img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))


def load_refs(args):
    manifest = json.loads((REPO_ROOT / "data" / "landmarks" / "manifest.json").read_text())
    by_slug = {e["slug"]: e for e in manifest["landmarks"]}
    picks = {}
    for spec in args.refs:
        slug, idx = spec.split("=")
        refs = by_slug[slug]["references"]
        picks[slug] = [refs[int(i)] for i in idx.split(",")][:2]  # 2 references max per landmark
    return picks


def build_jobs(picks):
    jobs = []
    for slug, (name, where) in LANDMARKS.items():
        png = (OUT / f"{slug}_render.png").read_bytes()
        common = dict(image=png, steps=8, cfg=1.0, seed=SEED, lightning="8", style=STYLE, landmark=slug)
        jobs.append({**common, "variant": "no_ref", "prompt": BASE_PROMPT})
        for k, ref in enumerate(picks.get(slug, [])):
            ref_png = (REPO_ROOT / ref["local_path"]).read_bytes()
            for pk, tmpl in PROMPTS.items():
                jobs.append({**common, "variant": f"r{k}_{pk}", "prompt": tmpl.format(name=name, where=where),
                             "references": [ref_png], "reference": ref["local_path"]})
    return jobs


def score(slug, variant):
    render = Image.open(OUT / f"{slug}_render.png").convert("RGB")
    img = Image.open(OUT / f"{slug}_{variant}.png").convert("RGB")
    if img.size != render.size:
        img = img.resize(render.size, Image.LANCZOS)
    return {
        "shift": list(registration_shift(render, img)),
        "shift_center": list(registration_shift(center(render), center(img))),
        "edge_corr_center": round(edge_corr(center(render), center(img)), 3),
        "flat_share": round(flat_share(np.asarray(img)), 3),
    }


def verdict(results):
    """Accept an output only if it sits on the render: whole-frame AND
    central shift within 2 px, and central edge correlation at least half of
    the no-reference output's. The whole-frame shift alone is not enough: an
    output that pastes the photo into the middle but keeps the render's
    edges (trees, roads) still reads (0, 0) on the full frame."""
    base = {r["landmark"]: r["edge_corr_center"] for r in results if r["variant"] == "no_ref"}
    for r in results:
        ok = max(map(abs, r["shift"])) <= 2 and max(map(abs, r["shift_center"])) <= 2
        r["accepted"] = bool(ok and r["edge_corr_center"] >= 0.5 * base[r["landmark"]])
    return results


def sheet(rows, picks):
    tile, pad, label_h = 300, 6, 30
    cols = max(len(r["items"]) for r in rows)
    W = cols * (tile + pad) + pad
    H = len(rows) * (tile + label_h + pad) + pad + 24
    out = Image.new("RGB", (W, H), (245, 245, 242))
    d = ImageDraw.Draw(out)
    for i, r in enumerate(rows):
        y = pad + i * (tile + label_h + pad)
        for j, (label, img) in enumerate(r["items"]):
            x = pad + j * (tile + pad)
            im = img.copy()
            im.thumbnail((tile, tile), Image.LANCZOS)
            out.paste(im, (x + (tile - im.width) // 2, y + label_h + (tile - im.height) // 2))
            for k, line in enumerate(label.split("\n")[:2]):
                d.text((x + 2, y + 2 + k * 13), line, fill=(20, 20, 20))
    credits = "; ".join(f"ref {s}#{k}: {ref['credit'][:110]}" for s, refs in picks.items() for k, ref in enumerate(refs))
    d.text((pad, H - 20), ("Reference photos: " + credits)[:400], fill=(60, 60, 60))
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    out.save(SHEET, quality=88)


def make_sheet(results, picks):
    verdict(results)
    rows = []
    for slug in LANDMARKS:
        items = [("render", Image.open(OUT / f"{slug}_render.png").convert("RGB"))]
        for r in [r for r in results if r["landmark"] == slug]:
            label = (f"{r['variant']} {'ACCEPT' if r['accepted'] else 'REJECT'}  shift {r['shift'][0]},{r['shift'][1]}\n"
                     f"ctr {r['shift_center'][0]},{r['shift_center'][1]} edge {r['edge_corr_center']}")
            items.append((label, Image.open(OUT / f"{slug}_{r['variant']}.png").convert("RGB")))
        for k, ref in enumerate(picks.get(slug, [])):
            items.append((f"reference r{k}\n{ref['license'][:40]}", Image.open(REPO_ROOT / ref["local_path"]).convert("RGB")))
        rows.append({"items": items})
    sheet(rows, picks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", nargs="+", required=True,
                    help="slug=i,j: manifest reference indexes to use, e.g. city_hall=0,1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sheet-only", action="store_true")
    args = ap.parse_args()
    picks = load_refs(args)

    if args.sheet_only:
        make_sheet(json.loads((OUT / "results.json").read_text()), picks)
        print(f"wrote {SHEET}")
        return

    jobs = build_jobs(picks)
    # Spend so far on this experiment, so a rerun can't silently pass the cap
    spent = 0.0
    log = REPO_ROOT / "output" / "gpu_runs.jsonl"
    for line in log.read_text().splitlines():
        e = json.loads(line)
        if e.get("run", "").startswith("20_landmark_experiment_a"):
            spent += e.get("estimated_cost_usd", 0)
    est_s = 240 + 8 * 1.5 * len(jobs)  # cold start + weights ~4 min; 8 forwards per image, ~1.5 s with a reference
    est = est_s / 3600 * H100_PER_HOUR
    print(f"{len(jobs)} edits; estimate ~{est_s / 60:.0f} H100-min (~${est:.2f}); spent so far ${spent:.2f} "
          f"of ${BUDGET_USD:.2f}")
    for j in jobs:
        print(f"  {j['landmark']:11s} {j['variant']:7s} {j.get('reference', '')}")
    if args.dry_run:
        return
    if spent + est > BUDGET_USD:
        raise SystemExit("over the experiment A budget; not running")

    import modal

    print("environment:", modal.Function.from_name("pixel-philly", "check_env").remote())
    editor = modal.Cls.from_name("pixel-philly", "Editor")()
    t0 = time.time()
    res = editor.run.remote(jobs)
    wall = time.time() - t0
    cost = wall / 3600 * H100_PER_HOUR
    with log.open("a") as fh:
        fh.write(json.dumps({"run": "20_landmark_experiment_a", "gpu": "H100", "wall_seconds": round(wall, 1),
                             "images": len(res), "estimated_cost_usd": round(cost, 2),
                             "load_seconds": res[0].get("load_seconds") if res else None,
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")

    results = []
    for r in res:
        Image.open(io.BytesIO(r.pop("png"))).convert("RGB").save(OUT / f"{r['landmark']}_{r['variant']}.png")
        r.pop("style", None)
        results.append({**r, **score(r["landmark"], r["variant"])})
    order = {j["landmark"] + j["variant"]: i for i, j in enumerate(jobs)}
    results.sort(key=lambda r: order[r["landmark"] + r["variant"]])
    verdict(results)
    (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    make_sheet(results, picks)
    print(f"done in {wall / 60:.1f} min (~${cost:.2f}); wrote {SHEET}")
    for r in results:
        print(f"  {r['landmark']:11s} {r['variant']:7s} shift {r['shift']} center {r['shift_center']} "
              f"edge {r['edge_corr_center']} {r['seconds']} s peak {r['peak_gb']} GB")


if __name__ == "__main__":
    main()
