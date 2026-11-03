"""One command per region: fetch, build, render, check, gate, draw, collect,
repaint, report (scripts/22_run_region.py).

The runner calls the existing scripts as they are; this module plans the
steps, decides which are already done, applies the stop gates before any
GPU spend and runs the loop. Everything here takes its I/O as arguments
(paths, an `execute` function, a clock), so tests/test_region_runner.py
covers it without network, GPU or subprocesses.

Resumable: a step is skipped when its outputs exist and are newer than its
inputs (fetches: when their raw files exist, since raw files are immutable
and the fetchers refuse a changed extent themselves). The GPU launch is
never repeated once its call.json exists; collecting is repeated until the
result arrives.

Gates (all reported together; any one stops the run before the GPU):
  alignment  a frame failing the 09 rule (pixelphilly.qa.alignment_failed)
             that isn't a reviewed exception, or no alignment report
  needles    a needle (18_qa_scan.py) not in config/qa_exceptions.json
  facades    facade match rate under FACADE_MIN_MATCH (configs with facades)
  budget     run frames x USD_PER_FRAME over --budget-usd
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# GPU cost per frame drawn in one joint run, Oct. 27: South 672 frames in
# 113 min for $7.42 = $0.011 and 0.17 min a frame. Known-band frames are not
# decoded but still go through every denoising window, so time follows the
# whole canvas (West: 158 frames, 132 new, 28.1 min = 0.18 min per canvas
# frame), and the budget counts every frame in the run. An estimate.
USD_PER_FRAME = 0.011
GPU_MIN_PER_FRAME = 0.17
H100_PER_HOUR = 3.95  # Modal list price, as in 15_joint_sample.py
FACADE_MIN_MATCH = 0.95

# Every citywide region in draw order (earlier-drawn first: the precedence
# for known bands and for the merged map). The first four are drawn; the
# rest are the Phase 2 regions (config/<name>.json, "clip_to_city": true).
CITY_REGIONS = ["south_lidar", "north_lidar", "upper_north_lidar", "west_lidar",
                "east_riverfront", "west_north", "southwest", "germantown",
                "roxborough", "lower_northeast", "northwest", "upper_northeast"]
IMAGERY_SERVICE = "CityImagery_2024_3in"


class StepFailed(RuntimeError):
    pass


@dataclass
class Options:
    run_name: str | None
    known: list[str]
    known_run: str | None = None
    style: str | None = None
    prompt_text: str | None = None
    lightning: str = "8"
    budget_usd: float = 15.0
    stop_before_gpu: bool = False
    no_wait: bool = False
    poll_s: float = 120.0
    max_wait_s: float = 5 * 3600.0  # the GPU job's own cap is 4 h


@dataclass
class Step:
    name: str
    cmd: list[str]  # arguments after `uv run python`
    outputs: list[Path]
    inputs: list[Path] = field(default_factory=list)
    phase: str = "build"  # fetch | build | check | gpu | collect | post
    area_env: bool = True  # run with PP_AREA=<area>
    retries: int = 0
    retry_wait_s: float = 0.0
    ok_codes: tuple = (0,)
    done: Callable[[], bool] | None = None  # replaces the outputs check
    launch_once: bool = False  # never rerun once outputs exist


def fresh(step: Step) -> tuple[bool, str]:
    """(done?, why) for a step. Done means: its own check passes, or every
    output exists and (unless launch_once) none is older than any input."""
    if step.done is not None:
        ok = step.done()
        return ok, "done" if ok else "not done"
    missing = [p for p in step.outputs if not Path(p).exists()]
    if missing:
        return False, f"{len(missing)} output(s) missing, e.g. {missing[0]}"
    if step.launch_once or not step.inputs:
        return True, "outputs exist"
    oldest = min(Path(p).stat().st_mtime for p in step.outputs)
    newer = [p for p in step.inputs if Path(p).exists() and Path(p).stat().st_mtime > oldest]
    if newer:
        return False, f"input newer than outputs: {newer[0]}"
    return True, "outputs newer than inputs"


def _raw(root: Path, *names: str) -> list[Path]:
    return [root / "data" / "raw" / n for n in names]


def _manifest_has(root: Path, key: str) -> Callable[[], bool]:
    def check():
        m = root / "data" / "raw" / "MANIFEST.json"
        return m.exists() and key in json.loads(m.read_text())

    return check


def _lidar_done(root: Path, area: str) -> Callable[[], bool]:
    """04c is done when the grid is cached (raw tiles may be pruned after
    gridding) or when every tile in the area's list is on disk."""
    from .lidar_tiles import grid_valid

    def check():
        if grid_valid(root / "data" / "processed" / f"{area}_lidar_grid.npz"):
            return True
        lst = root / "data" / "raw" / "lidar" / f"{area}_tiles.txt"
        return lst.exists() and all((lst.parent / t).exists() for t in lst.read_text().split())

    return check


def fetch_steps(cfg: dict, root: Path) -> list[Step]:
    a = cfg["name"]
    s = []

    def add(name, script, outputs, **kw):
        s.append(Step(name=name, cmd=[f"scripts/{script}.py"], outputs=outputs, phase="fetch",
                      retries=kw.pop("retries", 3), retry_wait_s=kw.pop("retry_wait_s", 30.0), **kw))

    # City limits first: with clip_to_city every extent depends on it
    add("04l", "04l_fetch_city_limits", _raw(root, "city_limits.geojson"), area_env=False)
    add("01", "01_fetch_buildings", _raw(root, f"{a}_buildings.geojson"))
    add("02", "02_fetch_trees", _raw(root, f"{a}_trees.geojson"))
    add("03", "03_fetch_imagery", [], done=_manifest_has(root, f"imagery/{a}/{IMAGERY_SERVICE}/{cfg.get('imagery_zoom', 19)}"))
    add("04", "04_fetch_water", _raw(root, f"{a}_water.geojson"))
    # The USGS NHD server answers 504 for minutes at a time (North, Oct. 24:
    # 12 one-minute retries)
    add("04b", "04b_fetch_water_nhd", _raw(root, f"{a}_water_nhd.geojson"), retries=12, retry_wait_s=60.0)
    if cfg.get("building_shapes") == "lidar":
        add("04c", "04c_fetch_lidar", [], done=_lidar_done(root, a))
    add("04d", "04d_fetch_highways", _raw(root, f"{a}_highways.geojson"))
    add("04e", "04e_fetch_rail", _raw(root, f"{a}_rail_el.geojson", f"{a}_rail.geojson"))
    add("04f", "04f_fetch_opa", _raw(root, f"{a}_opa.geojson", f"{a}_pwd_parcels.json"))
    add("04g", "04g_fetch_osm", _raw(root, f"{a}_osm.json"))
    add("04h", "04h_fetch_streets", _raw(root, f"{a}_streets.geojson"))
    add("04i", "04i_fetch_pools", _raw(root, f"{a}_pools.geojson"))
    add("04j", "04j_fetch_parks", _raw(root, f"{a}_parks.geojson", f"{a}_nps_parks.geojson"))
    add("04k", "04k_fetch_wetlands", _raw(root, f"{a}_wetlands.geojson"))
    return s


def _run_dirs(root: Path, area: str, run: str | None):
    out = root / "output" / area
    return out / "joint" / str(run), out / "postprocessed" / str(run) / "water"


def plan(cfg: dict, root: Path, frames: list[str], opts: Options) -> list[Step]:
    """Every step for one region, in order. `frames`: the area's frame
    names (projection.area_setup)."""
    if not opts.stop_before_gpu:
        if not opts.run_name:
            raise ValueError("--run-name is needed to draw (or use --stop-before-gpu)")
        if not opts.prompt_text:
            raise ValueError("--prompt-text is needed to draw (or use --stop-before-gpu)")
    root = Path(root)
    a = cfg["name"]
    proc = root / "data" / "processed"
    out = root / "output" / a
    steps = fetch_steps(cfg, root)
    raw_inputs = [p for s in steps if s.name != "04l" for p in s.outputs]
    config_path = root / "config" / f"{a}.json"

    scene_index = [proc / f"{a}_tiles.json"] if cfg.get("render_tile_frames") else [proc / f"{a}_scene.json"]
    qa = proc / f"{a}_qa.json"
    grid = [proc / f"{a}_lidar_grid.npz"] if cfg.get("building_shapes") == "lidar" else []
    steps.append(Step(name="05", cmd=["scripts/05_build_scene.py"], outputs=scene_index + [qa],
                      inputs=[config_path, *raw_inputs, *grid,
                              # reviewed corrections (pixelphilly.reviewed)
                              root / "config" / "height_overrides.json",
                              root / "config" / "stadium_exclusions.json"]))
    renders = [out / "renders" / f"{f}.png" for f in frames]
    masks = [out / "masks" / f"{f}.png" for f in frames]
    steps.append(Step(name="06_color", cmd=["scripts/06_render.py"], outputs=renders + [out / "renders" / "mosaic.png"],
                      inputs=scene_index))
    steps.append(Step(name="06_mask", cmd=["scripts/06_render.py", "--mode", "mask"], outputs=masks,
                      inputs=scene_index))
    align = out / "masks" / "alignment_report.json"
    steps.append(Step(name="09", cmd=["scripts/09_check_alignment.py"], outputs=[align], inputs=scene_index + masks,
                      phase="check", ok_codes=(0, 1)))
    steps.append(Step(name="18", cmd=["scripts/18_qa_scan.py"], outputs=[out / "qa_scan.json"],
                      inputs=scene_index + [qa], phase="check"))

    run = opts.run_name
    known_run = opts.known_run or run
    joint, water = _run_dirs(root, a, run)
    known = ",".join(opts.known)
    draw = ["scripts/15_joint_sample.py", "--full", "--volume", "--detach", "--name", str(run),
            "--lightning", opts.lightning]
    if opts.known:
        draw += ["--known-area", known, "--known-name", str(known_run)]
    if opts.style:
        draw += ["--style", opts.style]
    if opts.prompt_text:
        draw += ["--prompt-text", opts.prompt_text]
    steps.append(Step(name="15_launch", cmd=draw, outputs=[joint / "call.json"], inputs=renders, phase="gpu",
                      launch_once=True))
    steps.append(Step(name="15_collect", cmd=["scripts/15_joint_sample.py", "--collect", "--name", str(run)],
                      outputs=[joint / "result.json"], phase="collect", launch_once=True))
    repaint = ["scripts/10_repaint_water.py", "--prompt", str(run), "--invented-water", "fix"]
    if opts.known:
        repaint += ["--known-area", known, "--known-prompt", str(known_run)]
    steps.append(Step(name="10", cmd=repaint, outputs=[water / "report.json"], inputs=[joint / "result.json"],
                      phase="post"))
    scan = out / "invented_water_scan" / str(run)
    steps.append(Step(name="10b", cmd=["scripts/10b_scan_invented_water.py", "--areas", a, "--prompt", str(run),
                                       "--out", str(scan)],
                      outputs=[scan / "blobs.json"], inputs=[water / "report.json"], phase="post"))
    return steps


def run_steps(steps: list[Step], execute: Callable[[Step], int], sleep=time.sleep, log=print) -> list[dict]:
    """Run each step that isn't fresh, retrying failures. Raises StepFailed
    when a step's last attempt fails or it leaves outputs missing."""
    records = []
    for step in steps:
        ok, why = fresh(step)
        if ok:
            log(f"[{step.name}] skip ({why})")
            records.append({"step": step.name, "status": "skipped", "why": why})
            continue
        log(f"[{step.name}] run ({why})")
        t0 = time.monotonic()
        for attempt in range(1, step.retries + 2):
            code = execute(step)
            if code in step.ok_codes:
                break
            if attempt <= step.retries:
                log(f"[{step.name}] exit {code}; retry {attempt}/{step.retries} in {step.retry_wait_s:.0f} s")
                sleep(step.retry_wait_s)
        else:
            raise StepFailed(f"step {step.name} failed (exit {code}) after {step.retries + 1} attempt(s): "
                             f"{' '.join(step.cmd)}")
        if step.phase != "collect" and not fresh(step)[0]:
            raise StepFailed(f"step {step.name} finished but {fresh(step)[1]}")
        records.append({"step": step.name, "status": "ran", "attempts": attempt, "exit": code,
                        "seconds": round(time.monotonic() - t0, 1)})
    return records


def _meters(lonlat_a, lonlat_b) -> float:
    """Distance between two nearby lon/lat points (equirectangular)."""
    lat = math.radians((lonlat_a[1] + lonlat_b[1]) / 2)
    dx = (lonlat_a[0] - lonlat_b[0]) * 111_320.0 * math.cos(lat)
    dy = (lonlat_a[1] - lonlat_b[1]) * 110_574.0
    return math.hypot(dx, dy)


def needle_reviewed(needle: dict, area: str, lonlat, exceptions: dict) -> dict | None:
    """The exceptions entry that covers this needle, or None: the same id
    in one of the entry's areas, or (any area) within match_m meters and
    match_h_m of height."""
    match_m = exceptions.get("match_m", 3.0)
    match_h = exceptions.get("match_h_m", 2.0)
    for e in exceptions.get("needles", []):
        if e.get("id") == str(needle["id"]) and area in e.get("areas", []):
            return e
        if (e.get("lonlat") and lonlat is not None and _meters(e["lonlat"], lonlat) <= match_m
                and abs(e.get("h_m", -1e9) - needle["h_m"]) <= match_h):
            return e
    return None


def evaluate_gates(area: str, alignment_rows, needles, scene_qa: dict, exceptions: dict, to_lonlat,
                   run_frames: int, new_frames: int, budget_usd: float, facades_required: bool) -> dict:
    """Every stop gate before GPU spend. alignment_rows: the alignment
    report's rows (None if missing); needles: qa_scan.json's; to_lonlat:
    local_xy -> (lon, lat) in this area's frame."""
    from .qa import alignment_failed

    failures, details = [], {}
    if alignment_rows is None:
        failures.append({"gate": "alignment", "message": "no alignment report (09_check_alignment.py didn't run)"})
    else:
        reviewed = {e["frame"] for e in exceptions.get("alignment", []) if e.get("area") == area}
        bad = [r for r in alignment_rows if alignment_failed(r)]
        details["alignment_failed_frames"] = [r["frame"] for r in bad]
        unreviewed = [r for r in bad if r["frame"] not in reviewed]
        if unreviewed:
            failures.append({"gate": "alignment", "message": f"{len(unreviewed)} frame(s) FAIL alignment: " + ", ".join(
                f"{r['frame']} (IoU 1px {r['iou_1px']}, shift {r['best_shift_px']})" for r in unreviewed[:10])})
    hits = []
    for n in needles or []:
        ll = to_lonlat(n["local_xy"]) if n.get("local_xy") is not None else None
        entry = needle_reviewed(n, area, ll, exceptions)
        hits.append({"id": n["id"], "h_m": n["h_m"], "lonlat": ll, "reviewed": entry.get("id") if entry else None})
    details["needles"] = hits
    new_needles = [h for h in hits if h["reviewed"] is None]
    if new_needles:
        failures.append({"gate": "needles", "message": f"{len(new_needles)} needle(s) not in config/qa_exceptions.json "
                         "(check each on the 2024 aerial): " + ", ".join(
                             f"{h['id']} {h['h_m']:.1f} m at {tuple(round(v, 6) for v in h['lonlat'] or ())}"
                             for h in new_needles[:10])})
    rate = scene_qa.get("facade_match_rate") if scene_qa else None
    details["facade_match_rate"] = rate
    if facades_required and (rate is None or rate < FACADE_MIN_MATCH):
        failures.append({"gate": "facades", "message": f"facade match rate {rate} under {FACADE_MIN_MATCH}"
                         if rate is not None else "no facade match rate in the scene QA (facades not applied?)"})
    est = round(run_frames * USD_PER_FRAME, 2)
    if est > budget_usd:
        failures.append({"gate": "budget", "message": f"{run_frames} frames x ${USD_PER_FRAME} = ${est:.2f} "
                         f"exceeds the ${budget_usd:.2f} budget"})
    return {"pass": not failures, "failures": failures, "run_frames": run_frames, "new_frames": new_frames,
            "estimated_usd": est, "estimated_gpu_min": round(run_frames * GPU_MIN_PER_FRAME, 1),
            "budget_usd": budget_usd, **details}


def _load(path: Path):
    return json.loads(Path(path).read_text()) if Path(path).exists() else None


def run_region(cfg: dict, root: Path, frames: list[str], new_frames: int, opts: Options, execute, to_lonlat,
               exceptions: dict, sleep=time.sleep, clock=time.monotonic, log=print) -> dict:
    """The whole region run. Returns (and writes) output/<area>/region_report.json;
    status is one of stopped_at_gates, ready_for_gpu, drawing, done."""
    root = Path(root)
    a = cfg["name"]
    steps = plan(cfg, root, frames, opts)
    by = {s.name: s for s in steps}
    report = {"area": a, "run": opts.run_name, "known": opts.known, "known_run": opts.known_run or opts.run_name,
              "frames": len(frames), "new_frames": new_frames, "steps": [],
              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out_path = root / "output" / a / "region_report.json"

    def finish(status, **extra):
        report.update(status=status, finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n")
        log(f"{a}: {status} -> {out_path}")
        return report

    pre = [s for s in steps if s.phase in ("fetch", "build", "check")]
    report["steps"] += run_steps(pre, execute, sleep, log)

    scan = _load(root / "output" / a / "qa_scan.json") or {}
    gates = evaluate_gates(a, _load(by["09"].outputs[0]), scan.get("needles", []),
                           _load(root / "data" / "processed" / f"{a}_qa.json") or {}, exceptions, to_lonlat,
                           run_frames=len(frames), new_frames=new_frames, budget_usd=opts.budget_usd,
                           facades_required=bool(cfg.get("facades")))
    report["gates"] = gates
    if not gates["pass"]:
        for f in gates["failures"]:
            log(f"STOP [{f['gate']}] {f['message']}")
        return finish("stopped_at_gates")
    log(f"gates pass: {len(frames)} frames ({new_frames} new), est. ${gates['estimated_usd']:.2f} "
        f"(~{gates['estimated_gpu_min']:.0f} GPU min)")
    if opts.stop_before_gpu:
        return finish("ready_for_gpu")

    launch, collect = by["15_launch"], by["15_collect"]
    renders_newer = fresh(Step(name="x", cmd=[], outputs=launch.outputs, inputs=launch.inputs))
    if launch.outputs[0].exists() and not renders_newer[0]:
        log(f"WARNING: renders changed after {launch.name} started ({renders_newer[1]}); not relaunching")
    report["steps"] += run_steps([launch], execute, sleep, log)

    t0 = clock()
    while not fresh(collect)[0]:
        report["steps"] += run_steps([collect], execute, sleep, log)
        if fresh(collect)[0]:
            break
        if opts.no_wait or clock() - t0 >= opts.max_wait_s:
            return finish("drawing", note="drawing still running on Modal; rerun the same command to collect")
        sleep(opts.poll_s)
    result = _load(collect.outputs[0]) or {}
    secs = result.get("total_seconds") or result.get("wall_seconds")
    report["gpu"] = {"total_seconds": secs,
                     "estimated_cost_usd": round(secs / 3600 * H100_PER_HOUR, 2) if secs else None}

    report["steps"] += run_steps([by["10"], by["10b"]], execute, sleep, log)
    water = _load(by["10"].outputs[0]) or {}
    report["invented_water"] = water.get("invented_water")
    blobs = _load(by["10b"].outputs[0])
    if blobs is not None:
        flagged = [b for b in blobs if not b.get("exempt")]
        report["invented_water_scan"] = {"flagged_blobs": len(flagged),
                                         "flagged_px": sum(b.get("area_px", 0) for b in flagged),
                                         "review": str(by["10b"].outputs[0].parent)}
    return finish("done")
