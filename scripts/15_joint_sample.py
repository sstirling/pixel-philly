"""Phase D: draw Old City as ONE image with joint denoising (no frame seams).

Modes:
  --test-crop  a 1,792 px HELD-OUT crop centered where four held-out frames
               meet (exactly 2 x 2 windows). Runs the joint sampler and, as a
               control, the same model on independent 896 px tiles. Pass:
               joint seam ratio within +0.15 of the render's on the same
               lines; the independent control must score clearly higher,
               which shows the metric can see a seam.
  --full       the whole 6,144 x 5,120 render; the result is sliced back into
               lattice frames in output/redraws/<name>/ so 10_repaint_water.py
               and 08_compare_page.py work unchanged.

Model settings: --lightning 8 (Phase A's best: aligned on 6/6 frames) or
none; --style points at a trained LoRA in the pp-runs Volume.

Usage:
  uv run python scripts/15_joint_sample.py --test-crop --name test_light8
  PP_AREA=fishtown uv run python scripts/15_joint_sample.py --full --detach --name qwen_joint_light8 \\
      --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors --prompt-text "..."
  PP_AREA=fishtown uv run python scripts/15_joint_sample.py --collect --name qwen_joint_light8
"""

import argparse
import io
import json
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image

from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.qa import seam_ratio_lines
from pixelphilly.windows import WIN, two_grids

H100_PER_HOUR = 3.95  # Modal list price, Oct. 20, 2026; estimate only
CROP = (4224, 2176, 1792)  # mosaic x, y, size: centered on the corner of frames (4,2)-(5,3)


def log_run(entry):
    with (REPO_ROOT / "output" / "gpu_runs.jsonl").open("a") as fh:
        fh.write(json.dumps({**entry, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-crop", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--name", required=True)
    ap.add_argument("--prompt", default="qwen_v1b")
    ap.add_argument("--prompt-text", help="literal prompt (e.g. the LoRA training caption)")
    ap.add_argument("--lightning", default="8", choices=["4", "8", "none"])
    ap.add_argument("--steps", type=int)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--style", help="LoRA path inside the pp-runs Volume (/runs/...)")
    ap.add_argument("--style-scale", type=float, default=1.0)
    ap.add_argument("--detach", action="store_true",
                    help="--full only: start the run on Modal and return; fetch it later with --collect")
    ap.add_argument("--collect", action="store_true", help="fetch a run started with --detach")
    args = ap.parse_args()
    if not args.collect and args.test_crop == args.full:
        ap.error("choose exactly one of --test-crop / --full (or --collect)")

    light = None if args.lightning == "none" else args.lightning
    steps = args.steps or (int(light) if light else 40)
    prompt = args.prompt_text or (REPO_ROOT / "prompts" / f"{args.prompt}.txt").read_text().strip()
    style = {"path": args.style, "scale": args.style_scale} if args.style else None
    common = dict(prompt=prompt, steps=steps, cfg=args.cfg, seed=args.seed, lightning=light, style=style)

    import modal

    cfg = load_config()
    if args.collect:
        collect(cfg, args.name)
        return
    print("environment:", modal.Function.from_name("pixel-philly", "check_env").remote())
    editor = modal.Cls.from_name("pixel-philly", "Editor")()
    mosaic = Image.open(area_dir(cfg, "renders", "mosaic.png")).convert("RGB")
    out_dir = area_dir(cfg, "joint", args.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.test_crop:
        x, y, s = CROP
        crop = mosaic.crop((x, y, x + s, y + s))
        crop.save(out_dir / "render.png")
        buf = io.BytesIO()
        crop.save(buf, "PNG")
        t0 = time.time()
        joint = editor.joint.remote(buf.getvalue(), mode="joint", check_tiling=True, **common)
        indep = editor.joint.remote(buf.getvalue(), mode="independent", tile=112, **common)
        wall = time.time() - t0
        results = {}
        lat = s // 8
        edges_px = sorted({p * 8 for g in two_grids(lat, lat) for yy, xx in g for p in (yy, yy + WIN, xx, xx + WIN)} - {0, s})
        tile_px = [896]
        render_arr = np.asarray(crop)
        untiled = joint.pop("png_untiled", None)
        indep.pop("png_untiled", None)
        if untiled:
            # Same joint latents decoded without VAE tiling: isolates VAE seams
            uimg = Image.open(io.BytesIO(untiled)).convert("RGB")
            uimg.save(out_dir / "joint_untiled.png")
            joint["seam_ratio_untiled_decode"] = round(seam_ratio_lines(np.asarray(uimg), edges_px, edges_px), 3)
        for label, res, lines in (("joint", joint, edges_px), ("independent", indep, tile_px)):
            img = Image.open(io.BytesIO(res.pop("png"))).convert("RGB")
            img.save(out_dir / f"{label}.png")
            arr = np.asarray(img)
            results[label] = {
                **res,
                "seam_ratio": round(seam_ratio_lines(arr, lines, lines), 3),
                "render_seam_ratio_same_lines": round(seam_ratio_lines(render_arr, lines, lines), 3),
            }
        side = Image.new("RGB", (3 * s, s))
        for i, n in enumerate(("render", "independent", "joint")):
            side.paste(Image.open(out_dir / f"{n}.png"), (i * s, 0))
        side.resize((3 * s // 2, s // 2), Image.LANCZOS).save(out_dir / "side_by_side.jpg", quality=88)
        j, ind = results["joint"], results["independent"]
        verdict = (j["seam_ratio"] <= j["render_seam_ratio_same_lines"] + 0.15
                   and ind["seam_ratio"] > ind["render_seam_ratio_same_lines"] + 0.3)
        summary = {"settings": {k: v for k, v in common.items() if k != "prompt"}, **results,
                   "pass": bool(verdict), "wall_seconds": round(wall, 1)}
        (out_dir / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
        log_run({"run": f"15_joint_sample test {args.name}", "gpu": "H100", "wall_seconds": round(wall, 1),
                 "estimated_cost_usd": round(wall / 3600 * H100_PER_HOUR, 2)})
        print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "sigmas"})
                          for k, v in summary.items()}, indent=2))
        return

    # --full
    buf = io.BytesIO()
    mosaic.save(buf, "PNG")
    if args.detach:
        # The run continues on Modal even if this process stops (a local
        # command held open past ~10 min was cancelled once, killing a run)
        call = editor.joint.spawn(buf.getvalue(), mode="joint", **common)
        (out_dir / "call.json").write_text(json.dumps({
            "call_id": call.object_id, "prompt": prompt,
            "settings": {k: v for k, v in common.items() if k != "prompt"},
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2) + "\n")
        print(f"started {args.name} on Modal: call {call.object_id}; collect with --collect --name {args.name}")
        return
    t0 = time.time()
    res = editor.joint.remote(buf.getvalue(), mode="joint", **common)
    finish_full(cfg, args.name, res, time.time() - t0, prompt, {k: v for k, v in common.items() if k != "prompt"})


def collect(cfg, name):
    import modal

    info = json.loads((area_dir(cfg, "joint", name) / "call.json").read_text())
    try:
        res = modal.FunctionCall.from_id(info["call_id"]).get(timeout=0)
    except TimeoutError:
        print(f"{name} still running (started {info['started_at']})")
        return
    # Server-side time; container start and weight loading add ~1-2 min
    finish_full(cfg, name, res, res["total_seconds"], info["prompt"], info["settings"])


def finish_full(cfg, name, res, wall, prompt, settings):
    """Save the canvas and slice it into lattice frames for 10_repaint_water.py."""
    _, _, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    out_dir = area_dir(cfg, "joint", name)
    img = Image.open(io.BytesIO(res.pop("png"))).convert("RGB")
    res.pop("png_untiled", None)
    img.save(out_dir / "mosaic.png")
    frame_dir = area_dir(cfg, "redraws", name)
    frame_dir.mkdir(parents=True, exist_ok=True)
    for f in frames:
        img.crop((f.col * size, f.row * size, (f.col + 1) * size, (f.row + 1) * size)).save(frame_dir / f"{f.name}.png")
    (out_dir / "result.json").write_text(json.dumps({"area": cfg["name"], "settings": settings,
                                                     "prompt": prompt, **res, "wall_seconds": round(wall, 1)}, indent=2) + "\n")
    log_run({"run": f"15_joint_sample full {cfg['name']}/{name}", "gpu": "H100", "wall_seconds": round(wall, 1),
             "estimated_cost_usd": round(wall / 3600 * H100_PER_HOUR, 2)})
    print(f"done in {wall / 60:.1f} min (~${wall / 3600 * H100_PER_HOUR:.2f}); "
          f"{res['windows']} windows, {res['forwards']} forwards, peak {res['peak_gb']} GB; frames in {frame_dir}")


if __name__ == "__main__":
    main()
