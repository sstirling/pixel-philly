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

Drawing next to an area already drawn (both configs share "projection_origin"):
  PP_AREA=north_lidar uv run python scripts/15_joint_sample.py --full --volume --name qwen_joint_light8 \
      --known-area south_lidar [--known-name qwen_joint_light8] [--known-stage water] ...
  Frames of this area at the same screen corner as a drawn frame of the
  known area (the "known band") are held at those drawn pixels; only the
  other frames are drawn and collected. Add --only-near-known N for a cheap
  boundary test: the frames within N of the new frame that borders the band
  nearest --center-lonlat (default: where Broad St crosses the boundary).

Landmark references (Track 3, off by default):
  PP_AREA=atlas_cityhall_lidar uv run python scripts/15_joint_sample.py --full --volume \
      --name qwen_joint_light8_landmarks --landmarks --landmark-baseline qwen_joint_light8 --style ... --prompt-text "..."
  Approved landmarks (data/landmarks/manifest.json, status "ok") whose point
  falls on the area get their primary photo as a second conditioning image
  in the windows that have them near the middle (pixelphilly.landmarks).
  On --collect, each landmark's frame is checked against the render and the
  --landmark-baseline drawing (experiment A's rule); a rejected frame is
  replaced by the baseline drawing and the rejection logged in result.json.
"""

import argparse
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.qa import seam_ratio_lines
from pixelphilly.windows import WIN, two_grids

H100_PER_HOUR = 3.95  # Modal list price, Oct. 20, 2026; estimate only
CROP = (4224, 2176, 1792)  # mosaic x, y, size: centered on the corner of frames (4,2)-(5,3)
# Where N Broad St crosses the North/South Philly boundary (lat 39.975),
# approximate: the default center of the --only-near-known boundary test
BROAD_ST_BOUNDARY = (-75.1600, 39.975)


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
    ap.add_argument("--volume", action="store_true",
                    help="--full only: large areas; frames go through the pp-runs Volume (implies --detach)")
    ap.add_argument("--known-area", help="--volume only: areas already drawn next to this one, comma list in "
                    "precedence order (e.g. south_lidar,north_lidar)")
    ap.add_argument("--plan-only", action="store_true",
                    help="with --known-area: print the known/new plan and exit (no Modal, no uploads)")
    ap.add_argument("--known-name", "--known-prompt", dest="known_name",
                    help="the known area's run name (default: --name)")
    ap.add_argument("--known-stage", default="water",
                    help="the known area's postprocessed stage: output/<known>/postprocessed/<run>/<stage>/")
    ap.add_argument("--known-ramp", type=int, default=0,
                    help="latent cells the known mask ramps over (default 0: a ramp of 8 smeared olive in the "
                    "boundary test)")
    ap.add_argument("--repair-width-px", type=int, default=200,
                    help="with --known-area: redraw this wide a strip of new frames along the known band after "
                    "the main pass, both sides held fixed (0 disables)")
    ap.add_argument("--repair-sigma", type=float, default=0.6,
                    help="noise level the repair strip restarts from (the schedule step nearest it)")
    ap.add_argument("--only-near-known", type=int, metavar="N",
                    help="boundary test: only the frames within N frames of a new frame bordering the known band")
    ap.add_argument("--landmarks", action="store_true",
                    help="--full --volume only: condition landmark windows on approved reference photos")
    ap.add_argument("--landmark-baseline", default="qwen_joint_light8",
                    help="with --landmarks: this area's existing drawing (no references), used for the safety "
                    "check and as the fallback for rejected frames")
    ap.add_argument("--redraw", help="with --known-area (including this area itself): redraw only these frames "
                    "(comma list), holding the frames around them at their finished pixels")
    ap.add_argument("--context", type=int, default=2, help="--redraw: known frames this many cells around")
    ap.add_argument("--center-lonlat", help="lon,lat: with --only-near-known, the bordering new frame nearest this "
                    f"point is the center (default {BROAD_ST_BOUNDARY[0]},{BROAD_ST_BOUNDARY[1]}, Broad St)")
    args = ap.parse_args()
    if (args.known_area or args.only_near_known is not None) and not (args.full and args.volume):
        ap.error("--known-area and --only-near-known need --full --volume")
    if args.only_near_known is not None and not args.known_area:
        ap.error("--only-near-known needs --known-area")
    if args.landmarks and not (args.full and args.volume):
        ap.error("--landmarks needs --full --volume")
    if args.landmarks and args.known_area:
        ap.error("--landmarks with --known-area is not supported yet")
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
    known = None
    if args.known_area:
        center = tuple(float(v) for v in args.center_lonlat.split(",")) if args.center_lonlat else BROAD_ST_BOUNDARY
        known = plan_known(cfg, args.known_area, args.known_name or args.name, args.known_stage,
                           args.only_near_known, center)
        if args.redraw:
            # Redraw a few frames of an area already drawn: list the area itself
            # among --known-area (after its neighbors, so band cells keep the
            # merged map's pixels); the frames within --context stay known
            from pixelphilly.regions import redraw_plan

            run, shared = redraw_plan(area_setup(cfg)[2], known["shared"],
                                      [f.strip() for f in args.redraw.split(",") if f.strip()], args.context)
            known.update(run=run, shared=shared, only_near=args.context,
                         sources={k: v for k, v in known["sources"].items() if k in shared})
            print(f"redraw: {len(run) - len(shared)} frames ({args.redraw}) with {len(shared)} known around them")
        if args.plan_only:
            missing = [f.name for f in known["run"] if not area_dir(cfg, "renders", f"{f.name}.png").exists()]
            print(f"renders missing: {len(missing)} of {len(known['run'])} (run 06_render.py before the GPU run)")
            return
    elif args.plan_only:
        ap.error("--plan-only needs --known-area")
    print("environment:", modal.Function.from_name("pixel-philly", "check_env").remote())
    if args.full and args.volume:
        start_volume_run(cfg, args.name, prompt, {k: v for k, v in common.items() if k != "prompt"}, known,
                         args.known_ramp, args.repair_width_px, args.repair_sigma,
                         landmark_baseline=args.landmark_baseline if args.landmarks else None)
        return
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


def override_areas(known_areas, prompt):
    """Areas whose water_band/ re-repaints can change known pixels: the known
    areas in order, then any other area with one (pixelphilly.regions
    .cell_sources; later wins)."""
    found = sorted(p.parts[-5] for p in (REPO_ROOT / "output").glob(f"*/postprocessed/{prompt}/water_band/report.json"))
    return list(known_areas) + [a for a in found if a not in known_areas]


def plan_known(cfg, known_areas, known_name, stage, only_near, center_lonlat):
    """Which of this area's frames are already drawn in the known areas
    (comma list in precedence order: a cell several have goes to the
    first), the merged-map PNG for each (overrides included, so known
    pixels == merged map), and (boundary test) which frames to run at all.
    Refuses areas that don't share one screen space."""
    from pixelphilly.regions import check_same_space, known_sources, lattice_distance, near_known

    if isinstance(known_areas, str):
        known_areas = [a.strip() for a in known_areas.split(",") if a.strip()]
    kcfgs = [load_config(a) for a in known_areas]
    try:
        check_same_space([cfg, *kcfgs])
    except ValueError as e:
        raise SystemExit(str(e))
    frame, cam, frames = area_setup(cfg)
    sources = known_sources(frames, [(k["name"], area_setup(k)[2]) for k in kcfgs], known_name, stage, REPO_ROOT,
                            override_from=override_areas(known_areas, known_name))
    if not sources:
        raise SystemExit(f"no frame of {cfg['name']} sits on a frame of {', '.join(known_areas)}")
    missing = [str(p) for _, _, p in sources.values() if not p.exists()]
    if missing:
        raise SystemExit(f"{len(missing)} drawn known frames missing, e.g. {missing[:3]}")
    # Known pixels must be final: no neighbor redraw merged but not yet
    # repainted, and no neighbor run still drawing (Nov. 4 seams)
    from pixelphilly.regions import in_flight_runs, stale_known

    stale = stale_known(sources, known_name, REPO_ROOT)
    if stale:
        raise SystemExit(f"{len(stale)} known frames are older than their drawings (repaint pending), "
                         f"e.g. {stale[:3]}; repaint those areas first")
    flying = [r for r in in_flight_runs(known_areas, REPO_ROOT) if r.split("/")[0] != cfg["name"]]
    if flying:
        raise SystemExit(f"known areas still drawing: {flying}; collect and repaint them first")
    shared = {n: kf for n, (_, kf, _) in sources.items()}
    per_area = {a: sum(1 for o, _, _ in sources.values() if o == a) for a in known_areas}
    run = frames
    if only_near is not None:
        e, n = frame.to_local([center_lonlat[0]], [center_lonlat[1]])
        sx, sy = cam.world_to_screen(e, n, 0.0)
        sx, sy = float(np.asarray(sx).ravel()[0]), float(np.asarray(sy).ravel()[0])
        # Center on a NEW frame that borders the band: seen at 45 degrees the
        # band is ~3 frames deep, so a known center gives a patch that is
        # almost all known (7 of 8 at Broad St)
        band = [f for f in frames if f.name in shared]
        edge = [f for f in frames if f.name not in shared and any(lattice_distance(f, k) <= 1 for k in band)]
        center = min(edge, key=lambda f: (f.x0 + f.size / 2 - sx) ** 2 + (f.y0 + f.size / 2 - sy) ** 2)
        run = near_known(frames, shared.keys(), only_near, center=center)
        print(f"boundary test around {center.name}: {len(run)} frames, {sum(f.name in shared for f in run)} known "
              f"({', '.join(f.name for f in run if f.name in shared)}), "
              f"{sum(f.name not in shared for f in run)} new ({', '.join(f.name for f in run if f.name not in shared)})")
    overridden = sum(1 for _, _, p in sources.values() if "water_band" in p.parts)
    print(f"{cfg['name']}: {len(frames)} frames, {len(sources)} known ({', '.join(f'{a} {c}' for a, c in per_area.items())}"
          f"; {overridden} from water_band re-repaints), {len(frames) - len(sources)} new; this run: {len(run)} frames")
    return {"areas": known_areas, "area": known_areas[0], "name": known_name, "stage": stage, "sources": sources,
            "shared": shared, "per_area": per_area, "run": run, "only_near": only_near}


def landmark_plan(cfg, payload, baseline):
    """pixelphilly.landmarks.plan for this run's frames, with the window
    grids computed exactly as AreaSampler.joint_volume computes them."""
    from pixelphilly.landmarks import PROMPT_P1, WHERE, plan
    from pixelphilly.windows import active_grids

    size = cfg["camera"]["frame_px"]
    cell = size // 8
    cols, rows = max(f["col"] for f in payload) + 1, max(f["row"] for f in payload) + 1
    active = np.zeros((rows * cell, cols * cell), bool)
    for f in payload:
        active[f["row"] * cell:(f["row"] + 1) * cell, f["col"] * cell:(f["col"] + 1) * cell] = True
    grids = active_grids(two_grids(*active.shape), active)
    scene_path = REPO_ROOT / "data" / "processed" / f"{cfg['name']}_scene.json"
    scene = json.loads(scene_path.read_text()) if scene_path.exists() else None
    p = plan(cfg, REPO_ROOT / "data" / "landmarks" / "manifest.json", scene, grids)
    missing = sorted({lm["frame"] for lm in p["landmarks"].values()
                      if not area_dir(cfg, "redraws", baseline, f"{lm['frame']}.png").exists()})
    if missing:
        raise SystemExit(f"--landmark-baseline {baseline} has no drawing for landmark frames {missing}")
    p["prompt"] = PROMPT_P1.format(where=WHERE)
    return p


def start_volume_run(cfg, name, prompt, settings, known=None, ramp=0, repair_width_px=200, repair_sigma=0.6,
                     landmark_baseline=None):
    """Upload the area's render frames to the pp-runs Volume and start
    AreaSampler.joint_volume detached (large areas: ~45 min). With `known`
    (plan_known), the known area's drawn frames go up too, under this
    area's frame names, and only the other frames are drawn."""
    import modal

    from pixelphilly.regions import rebase

    _, _, frames = area_setup(cfg)
    if known:
        frames = known["run"]
    payload = (rebase(frames) if known and known["only_near"] is not None
               else [{"name": f.name, "col": f.col, "row": f.row} for f in frames])
    missing = [f.name for f in frames if not area_dir(cfg, "renders", f"{f.name}.png").exists()]
    if missing:
        raise SystemExit(f"{len(missing)} renders missing in {area_dir(cfg, 'renders')} (run 06_render.py), "
                         f"e.g. {missing[:3]}")
    known_names = [f.name for f in frames if known and f.name in known["shared"]]
    lm = landmark_plan(cfg, payload, landmark_baseline) if landmark_baseline else None
    lm_arg = None
    if lm is not None:
        if not lm["landmarks"]:
            raise SystemExit("--landmarks: no approved landmark falls on this area's frames")
        refs = {s: f"/landmarks/refs/{s}{Path(v['local_path']).suffix}" for s, v in lm["landmarks"].items()}
        lm_arg = {"prompt": lm["prompt"], "refs": {s: "/runs" + r for s, r in refs.items()},
                  "windows": [[y, x, s] for (y, x), s in sorted(lm["windows"].items())]}
    vol = modal.Volume.from_name("pp-runs", create_if_missing=True)
    with vol.batch_upload(force=True) as batch:
        for f in frames:
            batch.put_file(str(area_dir(cfg, "renders", f"{f.name}.png")), f"/areas/{cfg['name']}/renders/{f.name}.png")
        for k in known_names:
            batch.put_file(str(known["sources"][k][2]), f"/areas/{cfg['name']}/joint/{name}/known/{k}.png")
        if lm is not None:
            for s, r in refs.items():
                batch.put_file(str(REPO_ROOT / lm["landmarks"][s]["local_path"]), r)
    sampler = modal.Cls.from_name("pixel-philly", "AreaSampler")()
    # landmarks is only passed when used, so the default call is unchanged
    call = sampler.joint_volume.spawn(cfg["name"], name, payload, cfg["camera"]["frame_px"], prompt,
                                      known_frames=known_names or None, known_ramp_cells=ramp,
                                      repair_width_px=repair_width_px, repair_sigma=repair_sigma,
                                      **({"landmarks": lm_arg} if lm_arg else {}), **settings)
    out_dir = area_dir(cfg, "joint", name)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = {"call_id": call.object_id, "volume": True, "prompt": prompt, "settings": settings,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if known:
        info["known"] = {"area": known["area"], "areas": known["areas"], "run": known["name"], "stage": known["stage"],
                         "per_area": {a: sum(1 for k in known_names if known["sources"][k][0] == a)
                                      for a in known["areas"]},
                         "frames": {k: known["shared"][k] for k in known_names},
                         "frame_sources": {k: [known["sources"][k][0], known["sources"][k][1],
                                               str(known["sources"][k][2].relative_to(REPO_ROOT))]
                                           for k in known_names},
                         "ramp_cells": ramp,
                         "repair_width_px": repair_width_px, "repair_sigma": repair_sigma,
                         "only_near_known": known["only_near"], "run_frames": [f.name for f in frames]}
    if lm is not None:
        info["landmarks"] = {"prompt": lm["prompt"], "baseline": landmark_baseline,
                             "windows": lm_arg["windows"],
                             "landmarks": {s: {k: v[k] for k in ("name", "frame", "windows", "height_m", "canvas_px",
                                                                 "local_path", "license", "credit", "source_url")}
                                           for s, v in lm["landmarks"].items()}}
    (out_dir / "call.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"uploaded {len(frames)} renders and {len(known_names)} known frames; "
          f"started {name} on Modal: call {call.object_id}")
    if lm is not None:
        print(f"landmarks: {len(lm['landmarks'])} ({', '.join(sorted(lm['landmarks']))}) in "
              f"{len(lm['windows'])} windows")


def collect(cfg, name):
    import modal

    info = json.loads((area_dir(cfg, "joint", name) / "call.json").read_text())
    try:
        res = modal.FunctionCall.from_id(info["call_id"]).get(timeout=0)
    except TimeoutError:
        print(f"{name} still running (started {info['started_at']})")
        return
    if info.get("volume"):
        # Frames were written to the Volume; download them into the redraws folder
        vol = modal.Volume.from_name("pp-runs")
        frame_dir = area_dir(cfg, "redraws", name)
        frame_dir.mkdir(parents=True, exist_ok=True)
        # Runs with a known band (or a boundary-test subset) return only the
        # frames they drew
        names = res.get("decoded_frames") or [f.name for f in area_setup(cfg)[2]]
        for n in names:
            with (frame_dir / f"{n}.png").open("wb") as fh:
                for chunk in vol.read_file(f"/areas/{cfg['name']}/joint/{name}/frames/{n}.png"):
                    fh.write(chunk)
        safety = landmark_safety(cfg, name, info["landmarks"]) if info.get("landmarks") else None
        (area_dir(cfg, "joint", name) / "result.json").write_text(json.dumps(
            {"area": cfg["name"], "settings": info["settings"], "prompt": info["prompt"],
             "known": info.get("known"), **res,
             **({"landmark_plan": info["landmarks"], "landmark_safety": safety} if safety is not None else {})},
            indent=2) + "\n")
        wall = res["total_seconds"]
        log_run({"run": f"15_joint_sample volume {cfg['name']}/{name}", "gpu": "H100", "wall_seconds": wall,
                 "estimated_cost_usd": round(wall / 3600 * H100_PER_HOUR, 2)})
        print(f"done in {wall / 60:.1f} min (~${wall / 3600 * H100_PER_HOUR:.2f}); {res['windows']} windows, "
              f"{res['forwards']} forwards, peak {res['peak_gb']} GB; {len(names)} frames in {frame_dir}")
        return
    # Server-side time; container start and weight loading add ~1-2 min
    finish_full(cfg, name, res, res["total_seconds"], info["prompt"], info["settings"])


def landmark_safety(cfg, name, lm_info):
    """Experiment A's check on each landmark's frame (pixelphilly.landmarks
    .check_frame): the drawing with references against the render and the
    baseline drawing. A frame with any rejected landmark is replaced by the
    baseline drawing; the drawing with references is kept in
    joint/<name>/rejected/ for inspection."""
    import shutil

    from pixelphilly.landmarks import center_box, check_frame

    _, _, frames = area_setup(cfg)
    by_name = {f.name: f for f in frames}
    frame_dir = area_dir(cfg, "redraws", name)
    base_dir = area_dir(cfg, "redraws", lm_info["baseline"])
    out = {"baseline": lm_info["baseline"], "landmarks": {}, "fallback_frames": []}
    for slug, lm in sorted(lm_info["landmarks"].items()):
        f = by_name[lm["frame"]]
        render = Image.open(area_dir(cfg, "renders", f"{f.name}.png")).convert("RGB")
        drawn = Image.open(frame_dir / f"{f.name}.png").convert("RGB")
        base = Image.open(base_dir / f"{f.name}.png").convert("RGB")
        m = check_frame(render, drawn, base, center_box(*lm["canvas_px"], f))
        out["landmarks"][slug] = {"frame": f.name, **m}
        print(f"  {slug:26s} {f.name} {'ACCEPT' if m['accepted'] else 'REJECT'} shift {m['shift']} center "
              f"{m['shift_center']} edge {m['edge_center']} (baseline {m['edge_center_baseline']}) {m['reason']}")
    for fname in sorted({v["frame"] for v in out["landmarks"].values() if not v["accepted"]}):
        rej = area_dir(cfg, "joint", name, "rejected")
        rej.mkdir(parents=True, exist_ok=True)
        shutil.copy(frame_dir / f"{fname}.png", rej / f"{fname}.png")
        shutil.copy(base_dir / f"{fname}.png", frame_dir / f"{fname}.png")
        out["fallback_frames"].append(fname)
        print(f"  {fname}: replaced by the {lm_info['baseline']} drawing (original in {rej})")
    return out


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
