"""Phase B: build LoRA training pairs (render -> pixel art) for Old City.

Targets come from Gemini 3 Pro Image with prompt redraw_v3. Stephen approved
training on Gemini outputs for INTERNAL use on Oct. 20, 2026, with legal
review required before publication (Gemini API terms bar using the service
"to develop models that compete with the Services"; see README). Every pair
records its source in the manifest so the model can be retrained on other
targets later.

Pairs, all from the TRAINING columns (lattice cols 0-3, mosaic x < 4,096 px);
cols 4-5 (riverfront and Society Hill) are held out for evaluation:
  lattice  the 20 existing v3 frames in cols 0-3 (already paid for)
  shift    1,024 px views every half frame, starting a quarter frame in
  zoom     the 4 quarters of each training frame rendered at 2x detail
           (tiny.london's trick: on a quarter the model redraws rather than
           copies)
Views that are more than 85% river (PWD layer) are skipped: water is
repainted afterwards anyway and the lattice frames already cover it.

Every target then has its water repainted (pixelphilly.waterpaint) so the
model learns one water style, and passes QA:
  registration shift <= 2 px vs. its render, flat share >= 0.30
A failing target is redrawn once more; a second failure is rejected and kept
in rejected/ with the reason.

Writes output/trainset/{control,target,raw,rejected}/<id>.png, manifest.jsonl
and contact sheets in sheets/. Resumable: finished ids are skipped.

Usage:
  uv run python scripts/13_build_trainset.py --dry-run
  uv run python scripts/13_build_trainset.py [--workers 4] [--max-calls 160]
"""

import argparse
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw

from pixelphilly import gemini, waterpaint
from pixelphilly.browser_render import Renderer
from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.qa import flat_share, registration_shift
from pixelphilly.water import water_screen_geometry, water_sentence, water_share

PROMPT = "redraw_v3"
TRAIN_COLS = range(0, 4)
HELDOUT_X = 4096  # mosaic px; nothing in the training set may reach past this
MAX_WATER = 0.85
MIN_FLAT = 0.30
MAX_SHIFT = 2
OUT = REPO_ROOT / "output" / "trainset"


def plan_views(cfg, frames):
    """Every training view as (id, kind, gx0, gy0, span) in mosaic px; span is
    the view's width in mosaic px (1,024 at 1x, 512 for a 2x quarter)."""
    size = cfg["camera"]["frame_px"]
    rows = max(f.row for f in frames) + 1
    views = []
    for f in frames:
        if f.col in TRAIN_COLS:
            views.append((f"lattice_{f.name}", "lattice", f.col * size, f.row * size, size))
    half = size // 2
    # Shifted views: a quarter frame in from the edge, every half frame, so
    # none coincides with a lattice frame and each street appears in several
    # different framings
    for gy in range(half // 2, rows * size - size + 1, half):
        for gx in range(half // 2, HELDOUT_X - size + 1, half):
            views.append((f"shift_{gx:05d}_{gy:05d}", "shift", gx, gy, size))
    for f in frames:
        if f.col not in TRAIN_COLS:
            continue
        for qy in (0, 1):
            for qx in (0, 1):
                views.append((f"zoom_{f.name}_q{qx}{qy}", "zoom",
                              f.col * size + qx * half, f.row * size + qy * half, half))
    for vid, _, gx, gy, span in views:
        assert gx + span <= HELDOUT_X, f"{vid} reaches into the held-out columns"
    return views


def frustum(gx, gy, span, x_origin, y_origin, mpp):
    sx, sy = x_origin + gx, y_origin + gy
    return {"left": sx * mpp, "right": (sx + span) * mpp, "top": -sy * mpp, "bottom": -(sy + span) * mpp}


def contact_sheets(rows_done, per_sheet=24):
    (OUT / "sheets").mkdir(exist_ok=True)
    tile = 256
    for s in range(0, len(rows_done), per_sheet):
        chunk = rows_done[s : s + per_sheet]
        sheet = Image.new("RGB", (6 * (2 * tile + 12), -(-len(chunk) // 6) * (tile + 22)), (245, 245, 242))
        d = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            x = (i % 6) * (2 * tile + 12)
            y = (i // 6) * (tile + 22)
            sheet.paste(Image.open(OUT / "control" / f"{r['id']}.png").resize((tile, tile)), (x, y + 20))
            sheet.paste(Image.open(OUT / "target" / f"{r['id']}.png").resize((tile, tile)), (x + tile, y + 20))
            d.text((x + 2, y + 4), f"{r['id']}  flat {r['flat_share']}", fill=(20, 20, 20))
        sheet.save(OUT / "sheets" / f"sheet_{s // per_sheet:02d}.jpg", quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=160)
    args = ap.parse_args()

    cfg = load_config()
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    mpp = cfg["camera"]["meters_per_pixel"]
    x_origin = min(f.x0 for f in frames)
    y_origin = min(f.y0 for f in frames)
    pwd_water = water_screen_geometry(cfg, frame, cam)
    views = plan_views(cfg, frames)

    # Skip mostly-river views (shares use the PWD layer, a lower bound)
    keep = []
    for v in views:
        vid, kind, gx, gy, span = v
        share = water_share(pwd_water, x_origin + gx, y_origin + gy, span)
        if kind != "lattice" and share > MAX_WATER:
            continue
        keep.append((*v, share))
    new_calls = sum(1 for v in keep if v[1] != "lattice")
    print(f"{len(keep)} pairs planned: "
          + ", ".join(f"{k} {sum(1 for v in keep if v[1] == k)}" for k in ("lattice", "shift", "zoom"))
          + f"; ~{new_calls} new Gemini calls (~${new_calls * gemini.PRICE_PER_IMAGE:.2f}, "
          f"plus retries for QA failures)")
    if args.dry_run:
        return

    for d in ("control", "target", "raw", "rejected"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.jsonl"
    # Finished = a passing target, or two QA rejections. Errored views (e.g.
    # rate limits) are retried on the next run.
    done = set()
    if manifest_path.exists():
        prior = [json.loads(line) for line in manifest_path.read_text().splitlines() if line]
        done = {r["id"] for r in prior if r["status"] == "ok"}
        rejected = [r["id"] for r in prior if r["status"] == "rejected"]
        done |= {v for v in rejected if rejected.count(v) >= 2}
    todo = [v for v in keep if v[0] not in done]

    # Water repaint inputs shared by every view
    report = json.loads((REPO_ROOT / "output" / "postprocessed" / PROMPT / "water" / "report.json").read_text())
    median, threshold = report["render_water_median_rgb"], report["color_threshold"]
    nhd_geom = waterpaint.nhd_geometry(cfg, frame, cam, x_origin, y_origin)
    template = (REPO_ROOT / "prompts" / f"{PROMPT}.txt").read_text()

    # 1. Render control images and building masks for every new view
    scene_rel = f"data/processed/{cfg['name']}_scene.json"
    renders, masks = {}, {}
    with Renderer(scene_rel, size) as r:
        for vid, kind, gx, gy, span, _ in todo:
            if kind == "lattice":
                name = vid.removeprefix("lattice_")
                renders[vid] = Image.open(REPO_ROOT / "output" / "renders" / f"{name}.png").convert("RGB")
                masks[vid] = np.asarray(Image.open(REPO_ROOT / "output" / "masks" / f"{name}.png").convert("L")) > 127
            else:
                fr = frustum(gx, gy, span, x_origin, y_origin, mpp)
                renders[vid] = r.view(fr, "color")
                masks[vid] = np.asarray(r.view(fr, "mask").convert("L")) > 127
    print(f"rendered {len(todo)} views")

    client = gemini.make_client()
    lock = threading.Lock()
    calls = {"n": 0, "ok": 0}
    stop = threading.Event()

    def log(row):
        with lock, manifest_path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")

    def target_qa(vid, render, raw, gx, gy, span):
        scale = span / size
        nhd = waterpaint.rasterize_view(nhd_geom, gx, gy, scale, size, size)
        water = waterpaint.water_mask(np.asarray(render), nhd, waterpaint.grow(masks[vid]), median, threshold)
        tgt = waterpaint.apply(np.asarray(raw).copy(), water, gx, gy, scale)
        shift = registration_shift(render, Image.fromarray(tgt))
        flat = round(flat_share(tgt), 3)
        return tgt, shift, flat, int(water.sum())

    def work(v):
        vid, kind, gx, gy, span, share = v
        render = renders[vid]
        render.save(OUT / "control" / f"{vid}.png")
        base = {"id": vid, "kind": kind, "mosaic_xywh": [gx, gy, span, span], "zoom": size / span,
                "water_share_pwd": round(share, 3), "target_source": gemini.MODEL, "prompt_version": PROMPT,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if kind == "lattice":
            # Existing v3 frame: target is the mosaic-level water repaint
            name = vid.removeprefix("lattice_")
            tgt = Image.open(REPO_ROOT / "output" / "postprocessed" / PROMPT / "water" / f"{name}.png").convert("RGB")
            tgt.save(OUT / "target" / f"{vid}.png")
            log({**base, "status": "ok", "origin": f"output/redraws/{PROMPT}/{name}.png",
                 "registration_shift": registration_shift(render, tgt), "flat_share": round(flat_share(np.asarray(tgt)), 3)})
            return
        prompt = template.replace("{water_sentence}", water_sentence(share))
        png = io.BytesIO()
        render.save(png, "PNG")
        for attempt in (1, 2):
            if stop.is_set():
                return
            with lock:
                if calls["n"] >= args.max_calls:
                    return
                calls["n"] += 1
            t0 = time.time()
            try:
                raw, returned = gemini.redraw(client, png.getvalue(), prompt, size)
            except Exception as exc:
                if gemini.is_quota_error(exc):
                    stop.set()
                log({**base, "status": "error", "attempt": attempt, "error": str(exc)[:300]})
                return
            with lock:
                calls["ok"] += 1
            raw.save(OUT / "raw" / f"{vid}_try{attempt}.png")
            tgt, shift, flat, wet = target_qa(vid, render, raw, gx, gy, span)
            row = {**base, "attempt": attempt, "seconds": round(time.time() - t0, 1),
                   "registration_shift": list(shift), "flat_share": flat, "water_px_repainted": wet,
                   "returned_size": returned}
            if max(abs(s) for s in shift) <= MAX_SHIFT and flat >= MIN_FLAT:
                Image.fromarray(tgt).save(OUT / "target" / f"{vid}.png")
                log({**row, "status": "ok", "origin": f"output/trainset/raw/{vid}_try{attempt}.png"})
                print(f"{vid}: ok (try {attempt}, shift {shift}, flat {flat})")
                return
            reason = f"shift {shift}" if max(abs(s) for s in shift) > MAX_SHIFT else f"flat {flat} < {MIN_FLAT}"
            Image.fromarray(tgt).save(OUT / "rejected" / f"{vid}_try{attempt}.png")
            log({**row, "status": "rejected", "reason": reason})
            print(f"{vid}: rejected try {attempt} ({reason})")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, todo))

    rows = [json.loads(line) for line in manifest_path.read_text().splitlines() if line]
    ok = [r for r in rows if r["status"] == "ok"]
    contact_sheets(ok)
    print(f"{calls['n']} Gemini calls this run, {calls['ok']} images (~${calls['ok'] * gemini.PRICE_PER_IMAGE:.2f}); "
          f"{len(ok)} pairs ok in total; "
          f"{sum(1 for r in rows if r['status'] == 'rejected')} rejected tries; "
          f"{sum(1 for r in rows if r['status'] == 'error')} errors"
          + ("; STOPPED on quota error" if stop.is_set() else ""))


if __name__ == "__main__":
    main()
