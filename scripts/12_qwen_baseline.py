"""Phase A: can Qwen-Image-Edit-2511 alone (no fine-tuning) redraw our renders?

Sends 6 varied render frames through the stock pipeline on a Modal H100 in
several settings, then scores every result and builds contact sheets next to
the render and the Gemini v3 redraw (Gemini is a visual benchmark only; none
of its output is used for training).

Settings per frame (48 images in total):
  base   40 steps, true CFG 4, prompts qwen_v1a and qwen_v1b, seeds 0 and 1
  light4 Lightning 4-step LoRA, CFG 1, both prompts, seed 0
  light8 Lightning 8-step LoRA, CFG 1, both prompts, seed 0

Writes:
  output/baseline_qwen/<setting>/<frame>.png
  output/baseline_qwen/qa.json          per-image registration shift, flat share
  output/baseline_qwen/sheet_<frame>.jpg contact sheets
  output/gpu_runs.jsonl                 wall time and estimated cost of the run

Usage:
  uv run python scripts/12_qwen_baseline.py --dry-run   # list jobs and cost, no GPU
  uv run python scripts/12_qwen_baseline.py
"""

import argparse
import io
import json
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw

from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.qa import flat_share, registration_shift
from pixelphilly.water import water_screen_geometry, water_sentence, water_share

# River, dense blocks (2), Independence Mall, an edge frame, Society Hill
FRAMES = ["frame_04_01", "frame_02_02", "frame_03_02", "frame_02_03", "frame_00_00", "frame_04_03"]
SETTINGS = [
    # name, prompt, steps, cfg, seed, lightning
    ("base_a_s0", "qwen_v1a", 40, 4.0, 0, None),
    ("base_a_s1", "qwen_v1a", 40, 4.0, 1, None),
    ("base_b_s0", "qwen_v1b", 40, 4.0, 0, None),
    ("base_b_s1", "qwen_v1b", 40, 4.0, 1, None),
    ("light4_a", "qwen_v1a", 4, 1.0, 0, "4"),
    ("light4_b", "qwen_v1b", 4, 1.0, 0, "4"),
    ("light8_a", "qwen_v1a", 8, 1.0, 0, "8"),
    ("light8_b", "qwen_v1b", 8, 1.0, 0, "8"),
]
# Modal H100 list price, checked Oct. 20, 2026 (https://modal.com/pricing).
# Used only to estimate spend; Modal's dashboard is the authority.
H100_PER_HOUR = 3.95
# Planning estimate: ~1 s per transformer forward at 1,024 px; CFG doubles it
EST_SECONDS_PER_FORWARD = 1.0

OUT = REPO_ROOT / "output" / "baseline_qwen"


def estimate_seconds():
    total = 0.0
    for _, _, steps, cfg, _, _ in SETTINGS:
        total += steps * (2 if cfg > 1 else 1) * EST_SECONDS_PER_FORWARD
    return total * len(FRAMES) + 240  # plus ~4 min container start and weight load


def contact_sheet(frame, render, gemini, results):
    tile, pad, label_h = 320, 6, 22
    items = [("render", render)] + ([("gemini v3 (benchmark)", gemini)] if gemini else []) + results
    cols = 5
    rows = -(-len(items) // cols)
    sheet = Image.new("RGB", (cols * (tile + pad) + pad, rows * (tile + label_h + pad) + pad), (245, 245, 242))
    d = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(items):
        x = pad + (i % cols) * (tile + pad)
        y = pad + (i // cols) * (tile + label_h + pad)
        sheet.paste(img.resize((tile, tile), Image.LANCZOS), (x, y + label_h))
        d.text((x + 2, y + 4), label, fill=(20, 20, 20))
    sheet.save(OUT / f"sheet_{frame}.jpg", quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    by_name = {f.name: f for f in frames}
    water = water_screen_geometry(cfg, frame, cam)
    prompts = {p: (REPO_ROOT / "prompts" / f"{p}.txt").read_text().strip() for p in {s[1] for s in SETTINGS}}
    render_dir = REPO_ROOT / "output" / "renders"

    jobs = []
    for name in FRAMES:
        f = by_name[name]
        sentence = water_sentence(water_share(water, f.x0, f.y0, size))
        png = (render_dir / f"{name}.png").read_bytes()
        for setting, prompt, steps, cfg_scale, seed, light in SETTINGS:
            jobs.append(
                {
                    "frame": name,
                    "setting": setting,
                    "prompt_version": prompt,
                    "prompt": prompts[prompt].replace("{water_sentence}", sentence),
                    "steps": steps,
                    "cfg": cfg_scale,
                    "seed": seed,
                    "lightning": light,
                    "image": png,
                }
            )

    est = estimate_seconds()
    print(f"{len(jobs)} edits on {len(FRAMES)} frames; estimated {est / 60:.0f} H100-minutes "
          f"(~${est / 3600 * H100_PER_HOUR:.2f} at ${H100_PER_HOUR}/h)")
    if args.dry_run:
        return

    import modal

    # Cheap CPU check first, so a broken environment fails for a fraction of
    # a cent instead of crash-looping an H100 container
    print("environment:", modal.Function.from_name("pixel-philly", "check_env").remote())
    editor = modal.Cls.from_name("pixel-philly", "Editor")()
    t0 = time.time()
    results = editor.run.remote(jobs)
    wall = time.time() - t0

    OUT.mkdir(parents=True, exist_ok=True)
    qa_rows = []
    for r in results:
        img = Image.open(io.BytesIO(r.pop("png"))).convert("RGB")
        d = OUT / r["setting"]
        d.mkdir(exist_ok=True)
        img.save(d / f"{r['frame']}.png")
        render = Image.open(render_dir / f"{r['frame']}.png").convert("RGB")
        if img.size != render.size:
            r["returned_size"] = list(img.size)
            img = img.resize(render.size, Image.LANCZOS)
        r.pop("prompt")
        r["registration_shift"] = registration_shift(render, img)
        r["flat_share"] = round(flat_share(np.asarray(img)), 3)
        qa_rows.append(r)
    (OUT / "qa.json").write_text(json.dumps(qa_rows, indent=2) + "\n")

    gemini_dir = REPO_ROOT / "output" / "redraws" / "redraw_v3"
    for name in FRAMES:
        render = Image.open(render_dir / f"{name}.png").convert("RGB")
        gem = gemini_dir / f"{name}.png"
        gemini = Image.open(gem).convert("RGB") if gem.exists() else None
        items = []
        for setting, *_ in SETTINGS:
            row = next(q for q in qa_rows if q["frame"] == name and q["setting"] == setting)
            dx, dy = row["registration_shift"]
            items.append((f"{setting}  shift {dx},{dy}  flat {row['flat_share']}",
                          Image.open(OUT / setting / f"{name}.png").convert("RGB")))
        contact_sheet(name, render, gemini, items)

    cost = wall / 3600 * H100_PER_HOUR
    with (REPO_ROOT / "output" / "gpu_runs.jsonl").open("a") as fh:
        fh.write(json.dumps({
            "run": "12_qwen_baseline",
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "gpu": "H100",
            "wall_seconds": round(wall, 1),
            "images": len(results),
            "estimated_cost_usd": round(cost, 2),
            "load_seconds": results[0].get("load_seconds") if results else None,
        }) + "\n")

    print(f"done in {wall / 60:.1f} min (~${cost:.2f}); load {results[0].get('load_seconds')} s")
    for setting, *_ in SETTINGS:
        rows = [q for q in qa_rows if q["setting"] == setting]
        ok = sum(1 for q in rows if max(abs(v) for v in q["registration_shift"]) <= 2)
        secs = np.mean([q["seconds"] for q in rows])
        peak = max(q["peak_gb"] for q in rows)
        print(f"  {setting:10s} aligned {ok}/{len(rows)}  flat median {np.median([q['flat_share'] for q in rows]):.3f}"
              f"  {secs:.1f} s/image  peak {peak} GB")


if __name__ == "__main__":
    main()
