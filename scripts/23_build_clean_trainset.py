"""Candidate B: build a clean, self-distilled training set (no Gemini).

Targets are Qwen-Image-Edit-2511 + Lightning-8 redraws with NO style LoRA
(Candidate A: the neutral prompt below) of our own renders of City open
data, filtered with the pipeline's QA (pixelphilly.trainset_clean). Every
pair's provenance is written to output/trainset_clean/manifest.jsonl.

Sources: the four drawn regions' renders (south, north, upper_north, west;
facades, LiDAR shapes and lawn correction, i.e. today's renderer). Frames
within EVAL_MARGIN_PX of any of the 8 comparison atlas spots are excluded,
so the comparison is on ground the LoRA never saw.

Views:
  full  a region lattice frame, its existing 1,024 px render
  zoom  one quarter of a frame RE-RENDERED at 2x (512 screen px -> 1,024 px)
        from the frame's own render-tile scene. Re-rendering, not cropping
        and upscaling: geometry edges, facade windows and tree canopies are
        drawn at full resolution, so the input looks like a real 2x render
        rather than a blurred one. (The aerial texture is z19, ~0.23 m on
        the ground, so ground detail is about the same either way.)

Subcommands (run in order; each is resumable):
  plan      features, terrain classes, held-out exclusion, stratified pick;
            writes plan.json and control/<id>.png (renders zooms)
  generate  Editor.run on Modal for planned views without a raw/ image
            (--limit N for a pilot); logs cost to output/gpu_runs.jsonl
  filter    water repaint + QA scores + decisions; writes target/, the
            manifest, rejected.jsonl and contact sheets

Usage:
  uv run python scripts/23_build_clean_trainset.py plan
  uv run python scripts/23_build_clean_trainset.py generate --limit 40
  uv run python scripts/23_build_clean_trainset.py filter
"""

import argparse
import io
import json
import math
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon
from shapely.ops import unary_union

from pixelphilly import invented_water as iw
from pixelphilly import trainset_clean as tc
from pixelphilly import waterpaint
from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config, render_ground_polygon
from pixelphilly.qa import flat_share, registration_shift
from pixelphilly.scenes import scene_paths

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("repaint", REPO_ROOT / "scripts" / "10_repaint_water.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

OUT = REPO_ROOT / "output" / "trainset_clean"
REGIONS = ["south_lidar", "north_lidar", "upper_north_lidar", "west_lidar"]
EVAL_SPOTS = ["atlas_passyunk_fac", "atlas_porch_fac", "atlas_twin_fac", "atlas_cityhall_fac", "atlas_indhall_fac",
              "atlas_wissahickon_fac", "atlas_airport_fac", "atlas_northeast_fac"]
EVAL_MARGIN_PX = 512  # ~150 m beyond each comparison spot's rendered ground

PROMPT = "Redraw this render as isometric pixel art."  # Candidate A's caption
MODEL_ID = "Qwen/Qwen-Image-Edit-2511@6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9"
LIGHTNING_ID = ("lightx2v/Qwen-Image-Edit-2511-Lightning@107d238d68b8387e32843d0b4a2e24ceb0d3ad86 "
                "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors")
H100_PER_HOUR = 3.95

# Stratified quotas: full frames and 2x quarters per terrain class. Rowhouses
# are most of the city but are capped so other terrain is not drowned out
QUOTA_FULL = {"rowhouse": 60, "tower": 30, "park": 25, "woods": 25, "river": 30, "stadium": 20, "industrial": 35,
              "port": 20, "open": 10}
QUOTA_ZOOM = {"rowhouse": 30, "tower": 20, "park": 10, "woods": 10, "river": 15, "stadium": 15, "industrial": 15,
              "port": 10, "open": 5}

# Known places used as terrain tags (lon, lat, radius m)
TAGS = {
    "stadium": [(-75.1675, 39.9008, 260), (-75.1665, 39.9057, 260), (-75.1720, 39.9012, 160),
                (-75.1903, 39.9502, 160)],  # Linc, CBP, Wells Fargo Center, Franklin Field
    "port": [(-75.1370, 39.9040, 600), (-75.1780, 39.8890, 600), (-75.1450, 39.9150, 350)],
    # Packer Ave terminal, Navy Yard reserve basin, Tioga-less south piers (Pier 82/84)
}

# Filters, from current drawings (see the README section "Candidate B"):
# flat share of renders p5-p95 0.19-0.41; prompt-only joint drawings
# 0.23-0.50; old style 0.27-0.53. 0.26 keeps photo-like redraws out (a
# render's median is 0.265). The pilot (40 views) set the top: woods drawn
# as flat camouflage blobs scored 0.75-0.82, good park and lawn drawings
# 0.68-0.70. Measured on non-water pixels, since the water repaint is flat
# by construction.
FLAT_RANGE = (0.26, 0.72)
# Invented saturated color: old style p95 0.0012, prompt-only median 0.012
# and p95 0.038 (5 atlas spots, 50 frames). Keeping targets at or below
# prompt-only's median selects the cleaner half
MAX_COLOR = 0.012
TONE_K = 3.5
# Near-copies: kept pairs below ~13 levels of mean absolute difference from
# the render (land pixels) were, by eye, the photo with light edits (rail
# yards, parking lots, towers); from ~13 up they are redrawn. Copies also
# invent the least color, so without this the color filter favors them
MIN_DIFF = 13.0


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lonlat_of(frame, cam, sx, sy):
    e, n = cam.screen_to_ground(np.asarray([sx], float), np.asarray([sy], float))
    lon, lat = frame.to_wgs84(e, n)
    return float(np.ravel(lon)[0]), float(np.ravel(lat)[0])


def dist_m(lon0, lat0, lon1, lat1):
    kx = 111320 * math.cos(math.radians(lat0))
    return math.hypot((lon1 - lon0) * kx, (lat1 - lat0) * 110540)


def eval_polys(frame, cam, x_origin, y_origin):
    """The comparison spots' rendered ground, in this region's mosaic px."""
    out = []
    for name in EVAL_SPOTS:
        g = render_ground_polygon(load_config(name))
        lon, lat = np.asarray(g.exterior.coords).T[:2]
        e, n = frame.to_local(lon, lat)
        sx, sy = cam.world_to_screen(e, n, 0.0)
        out.append(Polygon(np.column_stack([sx - x_origin, sy - y_origin])))
    return out


def footprints_screen(cfg, frame, cam, x_origin, y_origin):
    """(x, y, area_m2, height_m) per footprint centroid, mosaic px."""
    from shapely.geometry import shape

    data = json.loads((REPO_ROOT / "data" / "raw" / f"{cfg['name']}_buildings.geojson").read_text())
    lon, lat, area, hgt = [], [], [], []
    for f in data["features"]:
        if not f.get("geometry"):
            continue
        c = shape(f["geometry"]).centroid
        p = f["properties"]
        lon.append(c.x)
        lat.append(c.y)
        # Shape__Area is Web Mercator m²; scale by cos²(lat) to ground m²
        area.append((p.get("Shape__Area") or 0) * math.cos(math.radians(c.y)) ** 2)
        hgt.append(max(p.get("approx_hgt") or 0, 0) * 0.3048)
    e, n = frame.to_local(np.asarray(lon), np.asarray(lat))
    sx, sy = cam.world_to_screen(e, n, 0.0)
    return np.asarray(sx) - x_origin, np.asarray(sy) - y_origin, np.asarray(area), np.asarray(hgt)


def green_share(render):
    h, s, v = iw._hsv(render)
    g = iw.GREEN_RING
    return float(((h >= g["h"][0]) & (h <= g["h"][1]) & (s >= g["s_min"]) & (v >= g["v"][0]) & (v <= g["v"][1])).mean())


def plan():
    from pixelphilly.browser_render import Renderer

    items = []
    for region in REGIONS:
        cfg = load_config(region)
        frame, cam, frames = area_setup(cfg)
        size = cfg["camera"]["frame_px"]
        x_origin = min(f.x0 - f.col * size for f in frames)
        y_origin = min(f.y0 - f.row * size for f in frames)
        evals = eval_polys(frame, cam, x_origin, y_origin)
        water = unary_union([waterpaint.water_geometry(cfg, frame, cam, x_origin, y_origin, s)
                             for s in ("water_nhd", "water")])
        parks = waterpaint.water_geometry(cfg, frame, cam, x_origin, y_origin, "parks")
        fx, fy, farea, fh = footprints_screen(cfg, frame, cam, x_origin, y_origin)
        n_ex = 0
        for f in frames:
            gx, gy = f.col * size, f.row * size
            rpath = area_dir(cfg, "renders", f"{f.name}.png")
            mpath = area_dir(cfg, "masks", f"{f.name}.png")
            if not rpath.exists() or not mpath.exists():
                continue
            if tc.near_eval((gx, gy, size), evals, EVAL_MARGIN_PX):
                n_ex += 1
                continue
            render = np.asarray(Image.open(rpath).convert("RGB"))[::4, ::4]
            sel = (fx >= gx) & (fx < gx + size) & (fy >= gy) & (fy < gy + size)
            lon, lat = lonlat_of(frame, cam, f.x0 + size / 2, f.y0 + size / 2)
            tags = [t for t, pts in TAGS.items() if any(dist_m(lon, lat, a, b) <= r for a, b, r in pts)]
            feats = {
                "building_share": float((np.asarray(Image.open(mpath).convert("L"))[::4, ::4] > 127).mean()),
                "water_share": float(waterpaint.rasterize_view(water, gx, gy, 4.0, size // 4, size // 4).mean())
                if not water.is_empty else 0.0,
                "park_share": float(waterpaint.rasterize_view(parks, gx, gy, 4.0, size // 4, size // 4).mean())
                if not parks.is_empty else 0.0,
                "green_share": green_share(render),
                "median_footprint_m2": float(np.median(farea[sel])) if sel.any() else 0.0,
                "max_height_m": float(fh[sel].max()) if sel.any() else 0.0,
                "tags": tags,
            }
            items.append({"region": region, "frame": f.name, "col": f.col, "row": f.row,
                          "center_lonlat": [round(lon, 5), round(lat, 5)], "features": feats,
                          "terrain": tc.classify_terrain(feats), "id": f"{region}__{f.name}"})
        print(f"{region}: {len(frames)} frames, {n_ex} excluded near comparison spots", flush=True)
    counts = {}
    for it in items:
        counts[it["terrain"]] = counts.get(it["terrain"], 0) + 1
    print("available by terrain:", dict(sorted(counts.items())))

    full = tc.stratified_pick(items, QUOTA_FULL, seed=1)
    full_ids = {x["id"] for x in full}
    # Zoom quarters come from frames not already used whole where possible
    rest = [x for x in items if x["id"] not in full_ids]
    zoom_src = tc.stratified_pick(rest, QUOTA_ZOOM, seed=2)
    short = {k: v - sum(1 for z in zoom_src if z["terrain"] == k) for k, v in QUOTA_ZOOM.items()}
    zoom_src += tc.stratified_pick([x for x in full if x["id"] not in {z["id"] for z in zoom_src}],
                                   {k: v for k, v in short.items() if v > 0}, seed=3)
    rng = np.random.default_rng(4)
    views = [{**x, "kind": "full", "view_id": f"full__{x['id']}", "quarter": None} for x in full]
    for x in zoom_src:
        qx, qy = (int(v) for v in rng.integers(0, 2, 2))
        views.append({**x, "kind": "zoom", "view_id": f"zoom__{x['id']}_q{qx}{qy}", "quarter": [qx, qy]})

    (OUT / "control").mkdir(parents=True, exist_ok=True)
    # Controls: full frames are the existing renders; zooms are re-rendered
    # from the render tile that contains the frame
    by_region = {}
    for v in views:
        by_region.setdefault(v["region"], []).append(v)
    for region, vs in by_region.items():
        cfg = load_config(region)
        need = [v for v in vs if not (OUT / "control" / f"{v['view_id']}.png").exists()]
        for v in need:
            if v["kind"] == "full":
                Image.open(area_dir(cfg, "renders", f"{v['frame']}.png")).convert("RGB").save(
                    OUT / "control" / f"{v['view_id']}.png")
        zooms = [v for v in need if v["kind"] == "zoom"]
        if not zooms:
            continue
        scenes = {}
        for rel in scene_paths(cfg):
            sc = json.loads((REPO_ROOT / rel).read_text())
            for i, f in enumerate(sc["frames"]):
                scenes.setdefault(f["name"], (rel, f))
        for rel in sorted({scenes[v["frame"]][0] for v in zooms}):
            mine = [v for v in zooms if scenes[v["frame"]][0] == rel]
            with Renderer(rel, cfg["camera"]["frame_px"]) as r:
                for v in mine:
                    f = scenes[v["frame"]][1]
                    qx, qy = v["quarter"]
                    w, h = (f["right"] - f["left"]) / 2, (f["top"] - f["bottom"]) / 2
                    fr = {"left": f["left"] + qx * w, "right": f["left"] + (qx + 1) * w,
                          "top": f["top"] - qy * h, "bottom": f["top"] - (qy + 1) * h}
                    v["scene"] = rel
                    r.view(fr, "color").save(OUT / "control" / f"{v['view_id']}.png")
                    r.view(fr, "mask").convert("L").save(OUT / "control" / f"{v['view_id']}__mask.png")
            print(f"  rendered {len(mine)} zoom views from {rel}", flush=True)
    (OUT / "plan.json").write_text(json.dumps({"made_at": now(), "prompt": PROMPT, "views": views,
                                               "eval_spots": EVAL_SPOTS, "eval_margin_px": EVAL_MARGIN_PX,
                                               "available": counts}, indent=1) + "\n")
    print(f"planned {len(views)} views: {sum(v['kind'] == 'full' for v in views)} full, "
          f"{sum(v['kind'] == 'zoom' for v in views)} zoom -> {OUT / 'plan.json'}")


def raw_path(view_id, seed):
    return OUT / "raw" / f"{view_id}.seed{seed}.png"


def generate(limit, chunk, workers, seed, only_rejected=False, terrains=None):
    import modal

    views = json.loads((OUT / "plan.json").read_text())["views"]
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    todo = [v for v in views if not raw_path(v["view_id"], seed).exists()]
    if only_rejected:
        # Another seed only for views with no passing try yet
        kept = {json.loads(x)["id"] for x in (OUT / "manifest.jsonl").read_text().splitlines()}
        tried = {v["view_id"] for v in views if raw_path(v["view_id"], 0).exists()}
        todo = [v for v in todo if v["view_id"] in tried and v["view_id"] not in kept]
    if terrains:
        todo = [v for v in todo if v["terrain"] in terrains]
    if limit:
        # A pilot takes views spread across terrain classes, not the first N
        import zlib

        todo = sorted(todo, key=lambda v: zlib.crc32(v["view_id"].encode()))[:limit]
    est = len(todo) * 5.5 + 60 * workers
    print(f"{len(todo)} edits; estimated ~{est / 60:.0f} H100-min (~${est / 3600 * H100_PER_HOUR:.2f})")
    if not todo:
        return
    print("environment:", modal.Function.from_name("pixel-philly", "check_env").remote())
    editor = modal.Cls.from_name("pixel-philly", "Editor")()
    chunks = [todo[i:i + chunk] for i in range(0, len(todo), chunk)]
    lock = threading.Lock()
    stats = {"gpu_seconds": 0.0, "images": 0, "load": []}
    log = (OUT / "generate_log.jsonl").open("a")

    def work(ch):
        jobs = [{"image": (OUT / "control" / f"{v['view_id']}.png").read_bytes(), "prompt": PROMPT, "steps": 8,
                 "cfg": 1.0, "seed": seed, "lightning": "8", "view_id": v["view_id"]} for v in ch]
        res = editor.run.remote(jobs)
        with lock:
            for r in res:
                Image.open(io.BytesIO(r.pop("png"))).convert("RGB").save(raw_path(r["view_id"], r["seed"]))
                r.pop("prompt", None)
                log.write(json.dumps({**r, "at": now()}) + "\n")
                stats["gpu_seconds"] += r["seconds"]
                stats["images"] += 1
            stats["load"].append(res[0].get("load_seconds"))
            log.flush()
            print(f"  {stats['images']}/{len(todo)} done", flush=True)

    t0 = time.time()
    # A few chunks at a time on separate containers; each chunk is one call
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, chunks))
    wall = time.time() - t0
    # Billing estimate: per-image GPU time plus each container's weight load
    # and start (~load_seconds + 30 s); the local wall clock also includes
    # transfers, so log the larger of the two estimates per container
    loads = sorted({round(x or 60, 1) for x in stats["load"]})
    billed = max(stats["gpu_seconds"] + workers * (max(loads) + 30), wall * min(workers, len(chunks)))
    entry = {"run": f"23_build_clean_trainset generate seed {seed}", "gpu": "H100", "wall_seconds": round(wall, 1),
             "images": stats["images"], "gpu_seconds_images": round(stats["gpu_seconds"], 1),
             "containers": min(workers, len(chunks)), "estimated_cost_usd": round(billed / 3600 * H100_PER_HOUR, 2),
             "note": "estimate = max(image seconds + per-container load, local wall x containers)", "at": now()}
    with (REPO_ROOT / "output" / "gpu_runs.jsonl").open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(json.dumps(entry))


class RegionCtx:
    """Per-region geometry for the water repaint and invented-water check."""

    def __init__(self, region):
        cfg = load_config(region)
        self.cfg = cfg
        frame, cam, frames = area_setup(cfg)
        self.frames = {f.name: f for f in frames}
        self.size = size = cfg["camera"]["frame_px"]
        xo = min(f.x0 - f.col * size for f in frames)
        yo = min(f.y0 - f.row * size for f in frames)
        self.nhd = waterpaint.nhd_geometry(cfg, frame, cam, xo, yo)
        self.water_ok, self.pools, self.wetlands = rp.invented_water_context(cfg, frame, cam, xo, yo)
        self.median = self.threshold = None

    def color_model(self, views):
        """Open-water color of the render (median and threshold, as in
        10_repaint_water.py), from this region's planned full frames with
        enough NHD water; None if there are none (no repaint needed)."""
        samples = []
        for v in views:
            if v["kind"] != "full":
                continue
            f = self.frames[v["frame"]]
            gx, gy = f.col * self.size, f.row * self.size
            nhd = waterpaint.rasterize_view(self.nhd, gx, gy, 1.0, self.size, self.size)
            if nhd.sum() < 5000:
                continue
            m = np.asarray(Image.open(area_dir(self.cfg, "masks", f"{f.name}.png")).convert("L")) > 127
            r = np.asarray(Image.open(area_dir(self.cfg, "renders", f"{f.name}.png")).convert("RGB"))
            from PIL import ImageFilter

            core = np.asarray(Image.fromarray(nhd.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(31))) > 127
            samples.append(r[core & ~waterpaint.grow(m)][::7])
        if samples:
            s = np.concatenate(samples).astype(int)
            self.median = np.median(s, axis=0)
            self.threshold = max(30.0, 4.0 * float(np.median(np.abs(s - self.median).max(axis=1))))


def score_view(ctx, v, seed):
    """Water-repaint the raw redraw and compute every filter score."""
    size = ctx.size
    f = ctx.frames[v["frame"]]
    gx, gy, scale = f.col * size, f.row * size, 1.0
    if v["kind"] == "zoom":
        qx, qy = v["quarter"]
        gx, gy, scale = gx + qx * size // 2, gy + qy * size // 2, 0.5
        mask = np.asarray(Image.open(OUT / "control" / f"{v['view_id']}__mask.png").convert("L")) > 127
    else:
        mask = np.asarray(Image.open(area_dir(ctx.cfg, "masks", f"{v['frame']}.png")).convert("L")) > 127
    render = np.asarray(Image.open(OUT / "control" / f"{v['view_id']}.png").convert("RGB"))
    raw = Image.open(raw_path(v["view_id"], seed)).convert("RGB")
    if raw.size != (size, size):
        raw = raw.resize((size, size), Image.LANCZOS)
    tgt = np.asarray(raw).copy()
    wet = 0
    water = np.zeros((size, size), bool)
    if ctx.median is not None:
        nhd = waterpaint.rasterize_view(ctx.nhd, gx, gy, scale, size, size)
        if nhd.any():
            water = waterpaint.water_mask(render, nhd, waterpaint.grow(mask), ctx.median, ctx.threshold)
            tgt = waterpaint.apply(tgt, water, gx, gy, scale)
            wet = int(water.sum())
    ok = (waterpaint.rasterize_view(ctx.water_ok, gx, gy, scale, size, size) if not ctx.water_ok.is_empty
          else np.zeros((size, size), bool))
    wetl = (waterpaint.rasterize_view(ctx.wetlands, gx, gy, scale, size, size)
            if ctx.wetlands is not None and not ctx.wetlands.is_empty else None)
    pools = [((x - gx) / scale, (y - gy) / scale) for x, y in ctx.pools
             if -500 < (x - gx) / scale < size + 500 and -500 < (y - gy) / scale < size + 500]
    blobs = iw.find_blobs(tgt, render, ok, waterpaint.grow(mask, 9), pools_px=pools,
                          pool_radius_px=rp.POOL_RADIUS_PX / scale, min_area=int(iw.MIN_AREA_PX / scale ** 2),
                          wetlands=wetl)
    # Flat share, color and tone on land only: repainted water is ours
    dry = ~waterpaint.grow(water, 7)
    tone = tc.tone_delta(render[dry][None], tgt[dry][None]) if dry.any() else tc.tone_delta(render, tgt)
    col_raw = tc.invented_color_share(render, tgt)
    tgt, specks = tc.remove_invented_specks(render, tgt)
    col = tc.invented_color_share(render, tgt)
    scores = {"shift": list(registration_shift(Image.fromarray(render), Image.fromarray(tgt))),
              "flat_share": round(tc.flat_share_masked(tgt, dry), 4),
              "flat_share_all": round(flat_share(tgt), 4),
              "render_flat_share": round(tc.flat_share_masked(render, dry), 4),
              "flat_gain": round(tc.flat_share_masked(tgt, dry) - tc.flat_share_masked(render, dry), 4),
              "mean_abs_diff": round(float(np.abs(tgt[dry].astype(int) - render[dry].astype(int)).mean())
                                     if dry.any() else 0.0, 2),
              "water_share_repainted": round(wet / size ** 2, 4),
              "invented_water_blobs": sum(1 for b in blobs if not b["exempt"]),
              "invented_color_share": round(col, 5),
              "invented_color_share_before_cleanup": round(col_raw, 5),
              "speck_px_cleaned": specks,
              "featureless_share": round(tc.featureless_share(render), 4),
              **{k: round(x, 2) for k, x in tone.items()},
              "water_px_repainted": wet}
    return tgt, scores


def filter_cmd():
    views = json.loads((OUT / "plan.json").read_text())["views"]
    seeds = {v["view_id"]: sorted(int(p.stem.rsplit(".seed", 1)[1]) for p in (OUT / "raw").glob(f"{v['view_id']}.seed*.png"))
             for v in views}
    views = [v for v in views if seeds[v["view_id"]]]
    gen = {}
    for line in (OUT / "generate_log.jsonl").read_text().splitlines():
        r = json.loads(line)
        gen[(r["view_id"], r["seed"])] = r
    for d in ("target", "rejected"):
        for old in (OUT / d).glob("*.png"):
            old.unlink()  # rebuilt from raw/ every run
    (OUT / "target").mkdir(exist_ok=True)
    (OUT / "rejected").mkdir(exist_ok=True)
    rows, tgts = [], {}
    for region in REGIONS:
        mine = [v for v in views if v["region"] == region]
        if not mine:
            continue
        ctx = RegionCtx(region)
        ctx.color_model(mine)
        for v in mine:
            for seed in seeds[v["view_id"]]:
                tgt, s = score_view(ctx, v, seed)
                tgts[(v["view_id"], seed)] = tgt
                rows.append((v, seed, s))
        print(f"{region}: scored {len(mine)}", flush=True)
    # Tone outliers across the whole candidate set, per axis
    for key in ("dlum", "drg", "dyb"):
        flags = tc.robust_outliers([s[key] for _, _, s in rows], k=TONE_K)
        for (_, _, s), fl in zip(rows, flags):
            s["tone_outlier"] = s.get("tone_outlier", False) or fl
    manifest, rejected = [], []
    tries = {}
    for v, seed, s in rows:
        tries.setdefault(v["view_id"], {})[seed] = tc.reject_reasons(s, FLAT_RANGE, MAX_COLOR, min_diff=MIN_DIFF)
    for v, seed, s in rows:
        reasons = tries[v["view_id"]][seed]
        chosen = tc.first_passing(tries[v["view_id"]])
        if not reasons and seed != chosen:
            reasons = [f"another seed ({chosen}) already passed"]
        g = gen[(v["view_id"], seed)]
        cfg = load_config(v["region"])
        row = {
            "id": v["view_id"], "kind": v["kind"], "terrain": v["terrain"], "area": v["region"],
            "frame": v["frame"], "quarter": v["quarter"], "center_lonlat": v["center_lonlat"],
            "source_render": (str(area_dir(cfg, "renders", f"{v['frame']}.png").relative_to(REPO_ROOT))
                              if v["kind"] == "full" else
                              f"2x quarter {v['quarter']} of {v['frame']} re-rendered from {v.get('scene')}"),
            "control": f"output/trainset_clean/control/{v['view_id']}.png",
            "raw": str(raw_path(v["view_id"], seed).relative_to(REPO_ROOT)),
            "target_model": MODEL_ID, "lightning": LIGHTNING_ID, "style_lora": None,
            "prompt": PROMPT, "steps": g["steps"], "cfg": g["cfg"], "seed": g["seed"],
            "gpu_seconds": g["seconds"], "generated_at": g["at"],
            "postprocess": "pixelphilly.waterpaint repaint of mapped water (render color model); "
                           "trainset_clean.remove_invented_specks (cars and confetti -> 9 px median)",
            "scores": s, "features": v["features"],
        }
        tc.check_provenance(row)
        if reasons:
            Image.fromarray(tgts[(v["view_id"], seed)]).save(OUT / "rejected" / f"{v['view_id']}.seed{seed}.png")
            rejected.append({**row, "status": "rejected", "reasons": reasons})
        else:
            Image.fromarray(tgts[(v["view_id"], seed)]).save(OUT / "target" / f"{v['view_id']}.png")
            manifest.append({**row, "status": "ok", "target": f"output/trainset_clean/target/{v['view_id']}.png"})
    (OUT / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in manifest))
    (OUT / "rejected.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rejected))
    by = {}
    for r in manifest:
        by.setdefault(r["terrain"], [0, 0])[0] += 1
    for r in rejected:
        by.setdefault(r["terrain"], [0, 0])[1] += 1
    reasons = {}
    for r in rejected:
        for x in r["reasons"]:
            k = x.split(" (")[0].split(" 0")[0].split(" [")[0].split(" -")[0]
            k = " ".join(k.split()[:2])
            reasons[k] = reasons.get(k, 0) + 1
    print(f"kept {len(manifest)} of {len(rows)}; by terrain [kept, rejected]: {dict(sorted(by.items()))}")
    print("rejection reasons:", reasons)
    sheets(manifest, "kept")
    sheets(rejected, "rejected")


def sheets(rows, label, per=24):
    d = OUT / "sheets"
    d.mkdir(exist_ok=True)
    for old in d.glob(f"{label}_*.jpg"):
        old.unlink()
    tile = 256
    for s in range(0, len(rows), per):
        chunk = rows[s:s + per]
        img = Image.new("RGB", (4 * (2 * tile + 12), -(-len(chunk) // 4) * (tile + 22)), (245, 245, 242))
        dr = ImageDraw.Draw(img)
        for i, r in enumerate(chunk):
            x, y = (i % 4) * (2 * tile + 12), (i // 4) * (tile + 22)
            img.paste(Image.open(REPO_ROOT / r["control"]).resize((tile, tile)), (x, y + 20))
            t = (OUT / "target" / f"{r['id']}.png" if r["status"] == "ok"
                 else OUT / "rejected" / f"{r['id']}.seed{r['seed']}.png")
            img.paste(Image.open(t).resize((tile, tile)), (x + tile, y + 20))
            txt = f"{r['terrain']} {r['kind']} flat {r['scores']['flat_share']:.2f} col {r['scores']['invented_color_share']:.3f}"
            if r["status"] != "ok":
                txt = "; ".join(r["reasons"])[:80]
            dr.text((x + 2, y + 4), txt, fill=(20, 20, 20))
        img.save(d / f"{label}_{s // per:02d}.jpg", quality=82)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["plan", "generate", "filter"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--terrain", help="generate: only these terrain classes (comma list)")
    ap.add_argument("--only-rejected", action="store_true",
                    help="generate: only views tried with seed 0 and not yet kept (a second seed)")
    a = ap.parse_args()
    if a.command == "plan":
        plan()
    elif a.command == "generate":
        generate(a.limit, a.chunk, a.workers, a.seed, a.only_rejected,
                 a.terrain.split(",") if a.terrain else None)
    else:
        filter_cmd()
