"""The region runner (scripts/22_run_region.py, pixelphilly.region_runner):
step planning, resumability, the stop gates before GPU spend and the run
loop. No network, no GPU, no subprocess: steps run through a fake executor."""

import json
import os
import time

import pytest

from pixelphilly import region_runner as rr

CFG = {"name": "testarea", "building_shapes": "lidar", "facades": "opa", "render_tile_frames": 4,
       "clip_to_city": True}
FRAMES = ["frame_00_00", "frame_01_00", "frame_00_01"]


def _opts(**kw):
    base = dict(run_name="run1", known=["south_lidar", "north_lidar"], known_run=None, style="/runs/lora/x.safetensors",
                prompt_text="Redraw this render as isometric pixel art.", lightning="8", budget_usd=15.0,
                stop_before_gpu=False, no_wait=False, poll_s=0.0, max_wait_s=10.0)
    base.update(kw)
    return rr.Options(**base)


def _touch(path, t=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    if t is not None:
        os.utime(path, (t, t))


def _names(steps):
    return [s.name for s in steps]


# ---------------------------------------------------------------- planning


def test_step_order_and_scripts(tmp_path):
    steps = rr.plan(CFG, tmp_path, FRAMES, _opts())
    names = _names(steps)
    fetch = ["04l", "01", "02", "03", "04", "04b", "04c", "04d", "04e", "04f", "04g", "04h", "04i", "04j", "04k"]
    assert names[:len(fetch)] == fetch
    assert names[len(fetch):] == ["05", "06_color", "06_mask", "09", "18", "15_launch", "15_collect", "10", "10b"]
    # City limits first: clipping needs it before any area extent is known
    by = {s.name: s for s in steps}
    assert by["04l"].cmd == ["scripts/04l_fetch_city_limits.py"] and by["04l"].area_env is False
    assert all(s.area_env for s in steps if s.name != "04l")
    assert by["04b"].retries >= 10  # the USGS NHD server stalls for minutes (North, Oct. 24)
    assert by["06_mask"].cmd == ["scripts/06_render.py", "--mode", "mask"]
    assert by["09"].ok_codes == (0, 1)  # FAILED exits 1; the gate reads the report
    assert [s.phase for s in steps].index("gpu") > _names(steps).index("18")


def test_gpu_command_carries_known_areas_style_and_prompt(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    cmd = by["15_launch"].cmd
    assert cmd[:5] == ["scripts/15_joint_sample.py", "--full", "--volume", "--detach", "--name"]
    assert cmd[5] == "run1"
    assert cmd[cmd.index("--known-area") + 1] == "south_lidar,north_lidar"
    assert cmd[cmd.index("--known-name") + 1] == "run1"  # known_run defaults to the run name
    assert cmd[cmd.index("--style") + 1] == "/runs/lora/x.safetensors"
    assert cmd[cmd.index("--prompt-text") + 1] == "Redraw this render as isometric pixel art."
    assert cmd[cmd.index("--lightning") + 1] == "8"
    assert by["15_collect"].cmd == ["scripts/15_joint_sample.py", "--collect", "--name", "run1"]
    ten = by["10"].cmd
    assert ten[:3] == ["scripts/10_repaint_water.py", "--prompt", "run1"]
    assert ten[ten.index("--invented-water") + 1] == "fix"
    assert ten[ten.index("--known-area") + 1] == "south_lidar,north_lidar"
    b = by["10b"].cmd
    assert b[b.index("--areas") + 1] == "testarea" and b[b.index("--prompt") + 1] == "run1"


def test_no_style_and_no_known_leave_flags_out(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts(known=[], style=None, known_run="other"))}
    for name in ("15_launch", "10"):
        assert "--known-area" not in by[name].cmd and "--style" not in by[name].cmd


def test_known_run_can_differ(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts(known_run="qwen_joint_light8_fac"))}
    cmd = by["15_launch"].cmd
    assert cmd[cmd.index("--known-name") + 1] == "qwen_joint_light8_fac"
    assert by["10"].cmd[by["10"].cmd.index("--known-prompt") + 1] == "qwen_joint_light8_fac"


def test_untiled_area_outputs_one_scene(tmp_path):
    by = {s.name: s for s in rr.plan({**CFG, "render_tile_frames": None}, tmp_path, FRAMES, _opts())}
    outs = {p.name for p in by["05"].outputs}
    assert "testarea_scene.json" in outs and "testarea_qa.json" in outs


# ---------------------------------------------------------------- resumability


def test_fetch_step_is_done_when_its_raw_files_exist(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    assert not rr.fresh(by["01"])[0]
    _touch(tmp_path / "data" / "raw" / "testarea_buildings.geojson")
    assert rr.fresh(by["01"])[0]
    # 04j writes two files; both are needed
    _touch(tmp_path / "data" / "raw" / "testarea_parks.geojson")
    assert not rr.fresh(by["04j"])[0]
    _touch(tmp_path / "data" / "raw" / "testarea_nps_parks.geojson")
    assert rr.fresh(by["04j"])[0]


def test_imagery_is_done_when_the_manifest_records_it(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    m = tmp_path / "data" / "raw" / "MANIFEST.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({}))
    assert not rr.fresh(by["03"])[0]
    m.write_text(json.dumps({"imagery/testarea/CityImagery_2024_3in/19": {}}))
    assert rr.fresh(by["03"])[0]


def test_lidar_fetch_skipped_once_the_grid_is_cached(tmp_path):
    # Raw tiles may have been pruned: a valid grid means 05 never reads them
    import numpy as np

    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    assert not rr.fresh(by["04c"])[0]
    grid = tmp_path / "data" / "processed" / "testarea_lidar_grid.npz"
    grid.parent.mkdir(parents=True)
    np.savez(grid, dsm=0, ground=0, origin=0, struct=0)
    assert rr.fresh(by["04c"])[0]


def test_lidar_fetch_needs_every_listed_tile(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    lidar = tmp_path / "data" / "raw" / "lidar"
    lidar.mkdir(parents=True)
    (lidar / "testarea_tiles.txt").write_text("Philadelphia_1.las\nPhiladelphia_2.las\n")
    _touch(lidar / "Philadelphia_1.las")
    assert not rr.fresh(by["04c"])[0]
    _touch(lidar / "Philadelphia_2.las")
    assert rr.fresh(by["04c"])[0]


def test_build_step_reruns_when_an_input_is_newer(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    s = by["18"]
    now = time.time()
    for p in s.inputs:
        _touch(p, now - 100)
    for p in s.outputs:
        _touch(p, now - 50)
    assert rr.fresh(s)[0]
    _touch(s.inputs[0], now)
    ok, why = rr.fresh(s)
    assert not ok and "newer" in why


def test_render_step_needs_every_frame(tmp_path):
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    outs = {p.name for p in by["06_color"].outputs}
    assert {f"{f}.png" for f in FRAMES} <= outs and "mosaic.png" in outs
    assert {p.name for p in by["06_mask"].outputs} == {f"{f}.png" for f in FRAMES}


def test_gpu_launch_is_never_repeated(tmp_path):
    # Once call.json exists the launch counts as done even if renders are
    # newer: a second launch would pay twice. The runner warns instead.
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    s = by["15_launch"]
    now = time.time()
    _touch(s.outputs[0], now - 100)
    for p in s.inputs:
        _touch(p, now)
    assert rr.fresh(s)[0]


# ---------------------------------------------------------------- gates

EXC = {"match_m": 3.0, "match_h_m": 2.0,
       "needles": [{"id": "310603-9", "areas": ["south_lidar"], "lonlat": [-75.156289, 39.948598], "h_m": 51.29},
                   {"id": "s1459-0", "areas": ["south_lidar"], "lonlat": [-75.126297, 39.916283], "h_m": 40.86}],
       "alignment": [{"area": "testarea", "frame": "frame_09_09"}]}


def _ident(xy):
    """local_xy -> lon/lat stand-in: 1 local m = 1e-5 degrees."""
    return (xy[0] * 1e-5, xy[1] * 1e-5)


def _gates(**kw):
    base = dict(area="testarea", alignment_rows=[], needles=[], scene_qa={"facade_match_rate": 0.99},
                exceptions=EXC, to_lonlat=_ident, run_frames=100, new_frames=80, budget_usd=15.0,
                facades_required=True)
    base.update(kw)
    return rr.evaluate_gates(**base)


def _row(frame, iou=1.0, shift=(0, 0), px=10000):
    return {"frame": frame, "iou": iou, "iou_1px": iou, "best_shift_px": list(shift), "building_px": px}


def test_clean_area_passes():
    g = _gates()
    assert g["pass"] and g["failures"] == []
    assert g["estimated_usd"] == pytest.approx(100 * rr.USD_PER_FRAME)


def test_alignment_fail_stops():
    g = _gates(alignment_rows=[_row("frame_01_01", iou=0.95), _row("frame_02_02", iou=0.95, px=100)])
    assert not g["pass"]
    assert [f["gate"] for f in g["failures"]] == ["alignment"]
    assert "frame_01_01" in g["failures"][0]["message"] and "frame_02_02" not in g["failures"][0]["message"]


def test_alignment_shift_stops_and_reviewed_frame_passes():
    assert not _gates(alignment_rows=[_row("frame_01_01", iou=0.985, shift=(4, 0))])["pass"]
    assert _gates(alignment_rows=[_row("frame_09_09", iou=0.95)])["pass"]


def test_missing_alignment_report_stops():
    g = _gates(alignment_rows=None)
    assert not g["pass"] and g["failures"][0]["gate"] == "alignment"


def test_unreviewed_needle_stops():
    n = {"id": "777-1", "h_m": 60.0, "local_xy": [100.0, 100.0], "area_m2": 9.0, "neighbor_max_m": 10.0}
    g = _gates(needles=[n])
    assert not g["pass"] and g["failures"][0]["gate"] == "needles" and "777-1" in g["failures"][0]["message"]


def test_reviewed_needle_by_id_only_in_its_areas():
    n = {"id": "310603-9", "h_m": 51.29, "local_xy": [0.0, 0.0]}
    assert _gates(area="south_lidar", needles=[n])["pass"]
    # Same id in another area is a different part (ids aren't global)
    assert not _gates(area="testarea", needles=[n])["pass"]


def test_reviewed_needle_by_position_and_height_in_any_area():
    # Structure ids are renumbered per area: the crane seen from a new
    # region has another id but the same place and height
    lon, lat = -75.126297, 39.916283
    n = {"id": "s12-0", "h_m": 41.5, "local_xy": [0.0, 0.0]}
    about_1m_east = lambda xy: (lon + 1e-5, lat)  # noqa: E731
    about_85m_east = lambda xy: (lon + 1e-3, lat)  # noqa: E731
    assert _gates(needles=[n], to_lonlat=about_1m_east)["pass"]
    assert not _gates(needles=[dict(n, h_m=48.0)], to_lonlat=about_1m_east)["pass"]  # not the same height
    assert not _gates(needles=[n], to_lonlat=about_85m_east)["pass"]


def test_facade_match_rate_gate():
    assert not _gates(scene_qa={"facade_match_rate": 0.94})["pass"]
    assert _gates(scene_qa={"facade_match_rate": 0.95})["pass"]
    # Facades configured but the rate missing: the build didn't apply them
    assert not _gates(scene_qa={})["pass"]
    assert _gates(scene_qa={}, facades_required=False)["pass"]


def test_budget_gate_counts_every_frame_in_the_run():
    # Known-band frames are not decoded but still go through the sampler, so
    # GPU time follows the whole canvas (South 672 frames 120 min; West 158
    # frames 28 min = 0.18 min/frame either way)
    g = _gates(run_frames=1400, new_frames=100, budget_usd=15.0)
    assert not g["pass"] and g["failures"][0]["gate"] == "budget"
    assert _gates(run_frames=1300, budget_usd=15.0)["pass"]


def test_every_failing_gate_is_reported():
    g = _gates(alignment_rows=[_row("frame_01_01", iou=0.9)], scene_qa={"facade_match_rate": 0.5}, run_frames=5000,
               needles=[{"id": "x", "h_m": 60.0, "local_xy": [0.0, 0.0]}])
    assert {f["gate"] for f in g["failures"]} == {"alignment", "needles", "facades", "budget"}


# ---------------------------------------------------------------- run loop


class FakeExec:
    """Records commands; each step 'creates' its outputs unless told to fail."""

    def __init__(self, root=None, fail=(), codes=None):
        self.root, self.calls, self.fail, self.codes = root, [], set(fail), codes or {}

    def root_manifest(self, step):
        m = self.root / "data" / "raw" / "MANIFEST.json"
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({"imagery/testarea/CityImagery_2024_3in/19": {}}))

    def __call__(self, step):
        self.calls.append(step.name)
        if step.name in self.fail:
            return 3
        for p in step.outputs:
            _touch(p)
        if step.name == "03":  # 03 and 04c are judged by the manifest and the tile list
            self.root_manifest(step)
        if step.name == "04c":
            lst = self.root / "data" / "raw" / "lidar" / "testarea_tiles.txt"
            lst.parent.mkdir(parents=True, exist_ok=True)
            lst.write_text("")
        if step.name == "15_collect":
            return 0
        return self.codes.get(step.name, 0)


def test_run_steps_skips_fresh_and_retries(tmp_path):
    steps = rr.plan(CFG, tmp_path, FRAMES, _opts())[:3]
    for p in steps[0].outputs:
        _touch(p)
    ex = FakeExec(tmp_path)
    log = rr.run_steps(steps, ex, sleep=lambda s: None)
    assert ex.calls == [s.name for s in steps[1:]]
    assert [r["status"] for r in log] == ["skipped", "ran", "ran"]

    flaky = rr.Step(name="flaky", cmd=["x"], outputs=[tmp_path / "f"], retries=2, retry_wait_s=0, phase="fetch")
    attempts = []

    def ex2(step):
        attempts.append(1)
        return 1 if len(attempts) < 3 else (_touch(tmp_path / "f") or 0)

    assert rr.run_steps([flaky], ex2, sleep=lambda s: None)[0]["attempts"] == 3
    with pytest.raises(rr.StepFailed):
        rr.run_steps([rr.Step(name="bad", cmd=["x"], outputs=[tmp_path / "g"], retries=1, phase="fetch")],
                     lambda s: 1, sleep=lambda s: None)


def _write_checks(root, step, frames=FRAMES, needles=(), rate=0.99, align=None):
    """What 05 (scene QA), 09 (alignment) and 18 (needles) would write."""
    out = root / "output" / "testarea"
    if step == "05":
        proc = root / "data" / "processed"
        proc.mkdir(parents=True, exist_ok=True)
        (proc / "testarea_qa.json").write_text(json.dumps({"facade_match_rate": rate}))
    if step == "09":
        (out / "masks").mkdir(parents=True, exist_ok=True)
        (out / "masks" / "alignment_report.json").write_text(
            json.dumps(align if align is not None else [_row(f) for f in frames]))
    if step == "18":
        (out / "qa_scan.json").write_text(json.dumps({"needles": list(needles)}))


class CheckExec(FakeExec):
    """FakeExec whose check steps write the given reports, and whose
    collect step finishes the run on its second call."""

    def __init__(self, root, collect_after=2, **checks):
        super().__init__(root)
        self.checks, self.collect_after, self.collects = checks, collect_after, 0

    def __call__(self, step):
        code = super().__call__(step)
        _write_checks(self.root, step.name, **self.checks)
        if step.name == "15_collect":
            self.collects += 1
            res = self.root / "output" / "testarea" / "joint" / "run1" / "result.json"
            if self.collects >= self.collect_after:
                _touch(res)
                res.write_text(json.dumps({"total_seconds": 3600}))
            elif res.exists():
                res.unlink()
        if step.name == "10":
            p = self.root / "output" / "testarea" / "postprocessed" / "run1" / "water" / "report.json"
            p.write_text(json.dumps({"invented_water": {"repaired": 2, "held": 1}}))
        if step.name == "10b":
            step.outputs[0].write_text(json.dumps([{"area_px": 50, "exempt": None}, {"area_px": 9, "exempt": "held"}]))
        return code


def _run(tmp_path, ex, **kw):
    return rr.run_region(CFG, tmp_path, FRAMES, new_frames=2, opts=_opts(**kw), execute=ex, sleep=lambda s: None,
                         to_lonlat=_ident, exceptions=EXC)


def test_gate_failure_stops_before_any_gpu_step(tmp_path):
    ex = CheckExec(tmp_path, rate=0.5)
    rep = _run(tmp_path, ex)
    assert rep["status"] == "stopped_at_gates"
    assert "15_launch" not in ex.calls and "15_collect" not in ex.calls
    assert rep["gates"]["failures"][0]["gate"] == "facades"
    saved = json.loads((tmp_path / "output" / "testarea" / "region_report.json").read_text())
    assert saved["status"] == "stopped_at_gates"


def test_stop_before_gpu(tmp_path):
    ex = CheckExec(tmp_path)
    rep = _run(tmp_path, ex, stop_before_gpu=True)
    assert rep["status"] == "ready_for_gpu" and rep["gates"]["pass"]
    assert "15_launch" not in ex.calls


def test_full_run_collects_until_done_then_postprocesses(tmp_path):
    ex = CheckExec(tmp_path, collect_after=3)
    rep = _run(tmp_path, ex)
    assert rep["status"] == "done"
    assert ex.calls.count("15_launch") == 1 and ex.calls.count("15_collect") == 3
    assert ex.calls[-2:] == ["10", "10b"]
    assert rep["gpu"]["estimated_cost_usd"] == pytest.approx(3.95, abs=0.01)
    assert rep["invented_water"] == {"repaired": 2, "held": 1}
    assert rep["invented_water_scan"]["flagged_blobs"] == 1 and rep["invented_water_scan"]["flagged_px"] == 50
    # Resume: everything is fresh, nothing runs again
    ex2 = CheckExec(tmp_path)
    rep2 = _run(tmp_path, ex2)
    assert rep2["status"] == "done" and ex2.calls == []


def test_no_wait_leaves_the_drawing_running(tmp_path):
    ex = CheckExec(tmp_path, collect_after=99)
    rep = _run(tmp_path, ex, no_wait=True)
    assert rep["status"] == "drawing" and ex.calls.count("15_collect") == 1 and "10" not in ex.calls


def test_wait_gives_up_after_max_wait(tmp_path):
    ex = CheckExec(tmp_path, collect_after=10**6)
    clock = iter(range(0, 10**6, 5))
    rep = rr.run_region(CFG, tmp_path, FRAMES, new_frames=2, opts=_opts(poll_s=5.0, max_wait_s=20.0), execute=ex,
                        sleep=lambda s: None, to_lonlat=_ident, exceptions=EXC, clock=lambda: next(clock))
    assert rep["status"] == "drawing" and "10" not in ex.calls


def test_needs_run_name_and_prompt_for_gpu(tmp_path):
    with pytest.raises(ValueError, match="run-name"):
        rr.plan(CFG, tmp_path, FRAMES, _opts(run_name=None))
    with pytest.raises(ValueError, match="prompt"):
        rr.plan(CFG, tmp_path, FRAMES, _opts(prompt_text=None))
    # Fine when stopping before the GPU
    rr.plan(CFG, tmp_path, FRAMES, _opts(run_name=None, prompt_text=None, stop_before_gpu=True))


def test_scene_rebuilds_when_reviewed_corrections_change(tmp_path):
    # Height overrides and stadium exclusions change scenes, so the scene
    # build depends on them like on the raw data
    by = {s.name: s for s in rr.plan(CFG, tmp_path, FRAMES, _opts())}
    names = {p.name for p in by["05"].inputs}
    assert {"height_overrides.json", "stadium_exclusions.json"} <= names


def test_golf_fetch_and_review_list_feed_the_scene():
    by = {s.name: s for s in rr.plan({**CFG, "golf_correct": True}, tmp_path_factory_dir(), FRAMES, _opts())}
    assert by["04n"].cmd == ["scripts/04n_fetch_golf.py"]
    assert {p.name for p in by["04n"].outputs} == {"testarea_golf.json"}
    assert "golf.json" in {p.name for p in by["05"].inputs}
    assert "testarea_golf.json" in {p.name for p in by["05"].inputs}
    # Without the option there's no golf fetch
    assert "04n" not in {s.name for s in rr.plan(CFG, tmp_path_factory_dir(), FRAMES, _opts())}


def test_vessel_piers_fetch_and_review_list_feed_the_scene():
    by = {s.name: s for s in rr.plan({**CFG, "vessels": True}, tmp_path_factory_dir(), FRAMES, _opts())}
    assert by["04o"].cmd == ["scripts/04o_fetch_piers.py"]
    assert {p.name for p in by["04o"].outputs} == {"testarea_piers.json"}
    assert "vessels.json" in {p.name for p in by["05"].inputs}
    assert "04o" not in {s.name for s in rr.plan(CFG, tmp_path_factory_dir(), FRAMES, _opts())}


def tmp_path_factory_dir():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
