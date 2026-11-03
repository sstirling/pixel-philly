"""Run one region end to end: fetch, build, render, check, gate, draw,
collect, repaint, report. Resumable: rerun the same command after any stop
and finished steps are skipped (pixelphilly.region_runner).

Steps (each is the existing script, run with PP_AREA=<area>):
  fetch    04l (city limits, shared), 01, 02, 03, 04, 04b (12 retries, a
           minute apart), 04c (skipped once the LiDAR grid is cached), 04d-04k
  build    05 scene, 06 color render, 06 mask render
  check    09 alignment, 18 QA scan
  gates    stop before any GPU spend on: alignment FAIL, a needle not in
           config/qa_exceptions.json, facade match rate < 0.95, or
           frames x $0.011 over --budget-usd (every frame in the run counts,
           known band included: GPU time follows the whole canvas)
  draw     15_joint_sample.py --full --volume --detach (with --known areas),
           then --collect every --poll-s seconds until the result is in
  post     10_repaint_water.py --invented-water fix, then the
           10b_scan_invented_water.py dry-run report for review
Writes output/<area>/region_report.json at every stop.

Usage:
  uv run python scripts/22_run_region.py germantown --known upper_north_lidar --stop-before-gpu
  uv run python scripts/22_run_region.py germantown --known upper_north_lidar --run-name <run> \\
      --prompt-text "Redraw this render as isometric pixel art." [--style /runs/lora/...safetensors] \\
      [--known-run <known areas' run>] [--budget-usd 15] [--no-wait]
  uv run python scripts/22_run_region.py germantown --plan     # list steps and what's done; runs nothing
"""

import argparse
import json
import os
import subprocess
import sys

from pixelphilly.projection import REPO_ROOT, area_setup, load_config, local_frame
from pixelphilly.region_runner import CITY_REGIONS, Options, fresh, plan, run_region, run_steps


def execute(step) -> int:
    env = dict(os.environ)
    if step.area_env:
        env["PP_AREA"] = AREA[0]
    else:
        env.pop("PP_AREA", None)
    print(f"$ {'PP_AREA=' + AREA[0] + ' ' if step.area_env else ''}uv run python {' '.join(step.cmd)}", flush=True)
    return subprocess.run(["uv", "run", "python", *step.cmd], cwd=REPO_ROOT, env=env).returncode


AREA = [""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("--known", default="", help="areas already drawn next to this one, comma list in precedence "
                    "order (earlier-drawn first)")
    ap.add_argument("--known-run", help="the known areas' run name (default: --run-name)")
    ap.add_argument("--run-name", help="this drawing's run name (output/<area>/redraws/<run>/)")
    ap.add_argument("--style", help="LoRA path inside the pp-runs Volume (omit for no style LoRA)")
    ap.add_argument("--prompt-text")
    ap.add_argument("--lightning", default="8", choices=["4", "8", "none"])
    ap.add_argument("--budget-usd", type=float, default=15.0)
    ap.add_argument("--stop-before-gpu", action="store_true")
    ap.add_argument("--no-wait", action="store_true", help="start the drawing, collect once, and exit")
    ap.add_argument("--poll-s", type=float, default=120.0)
    ap.add_argument("--plan", action="store_true", help="print the steps and which are done; run nothing")
    args = ap.parse_args()

    AREA[0] = args.area
    cfg = load_config(args.area)
    known = [k.strip() for k in args.known.split(",") if k.strip()]
    opts = Options(run_name=args.run_name, known=known, known_run=args.known_run, style=args.style,
                   prompt_text=args.prompt_text, lightning=args.lightning, budget_usd=args.budget_usd,
                   stop_before_gpu=args.stop_before_gpu or args.plan, no_wait=args.no_wait, poll_s=args.poll_s)

    # The city limits come first: frames of a clip_to_city area depend on them
    city = plan(cfg, REPO_ROOT, [], opts)[0]
    if not args.plan:
        run_steps([city], execute)
    _, _, frames = area_setup(cfg)
    names = [f.name for f in frames]
    from pixelphilly.regions import shared_frames

    shared = {}
    for k in known:
        for name in shared_frames(frames, area_setup(load_config(k))[2]):
            shared.setdefault(name, k)
    # Areas sharing cells with this one but not given as known: they'd be
    # drawn over twice. Warn (the merge gives a cell to the first-listed area).
    xy = {(f.x0, f.y0) for f in frames}
    for other in CITY_REGIONS:
        if other in (args.area, *known) or not (REPO_ROOT / "config" / f"{other}.json").exists():
            continue
        n = sum((f.x0, f.y0) in xy for f in area_setup(load_config(other))[2])
        drawn = args.run_name and (REPO_ROOT / "output" / other / "redraws" / args.run_name).exists()
        if n and drawn:
            print(f"WARNING: {other} already has run {args.run_name} and shares {n} frames with {args.area}, "
                  "but isn't in --known", flush=True)
    print(f"{args.area}: {len(names)} frames, {len(shared)} known "
          f"({', '.join(f'{k} {sum(v == k for v in shared.values())}' for k in known) or 'none'}), "
          f"{len(names) - len(shared)} new", flush=True)

    if args.plan:
        for s in plan(cfg, REPO_ROOT, names, opts):
            ok, why = fresh(s)
            print(f"  {'done' if ok else 'todo'}  {s.name:11s} {s.phase:7s} {' '.join(s.cmd)[:110]}  ({why[:80]})")
        return

    lf = local_frame(cfg)
    exceptions = json.loads((REPO_ROOT / "config" / "qa_exceptions.json").read_text())
    report = run_region(cfg, REPO_ROOT, names, new_frames=len(names) - len(shared), opts=opts, execute=execute,
                        to_lonlat=lambda xy: tuple(float(v) for v in lf.to_wgs84(*xy)), exceptions=exceptions)
    sys.exit(0 if report["status"] in ("done", "ready_for_gpu", "drawing") else 2)


if __name__ == "__main__":
    main()
