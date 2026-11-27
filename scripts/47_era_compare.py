"""Building-eras pilot, Phase D: measure the drawings and build the blind review.

The pilot (docs/building_age_plan.md; results in docs/building_age_styles.md,
section 7) drew four test spots as a baseline and three cumulative era
versions, each with identical boxes and cameras:

  base  atlas_<spot>_eb, run qwen_joint_light8_eb      today's settings
  A     atlas_<spot>_ea, run qwen_joint_light8_eraA    + era walls ("facade_eras")
  B     atlas_<spot>_ea, run qwen_joint_light8_eraB    + front slopes ("front_slopes")
  C     atlas_<spot>_ea, run qwen_joint_light8_eraC    + fitted gables and hips ("roof_fit")

Renders aren't stored per run, so each era phase's renders, masks and
scene were copied before the next phase overwrote them (renders_eraA/,
masks_eraA/, data/processed/atlas_<spot>_ea_scene_eraA.json, and so on).
Drawings are read after the water repair (postprocessed/<run>/water/) when
it exists, as scripts/24_style_compare.py does.

Measures, written to output/era_pilot/metrics.json and report.md:

- Quality per variant (helpers from 24_style_compare.py): frame-border
  seam ratio, flat share, invented saturated color, worst registration shift
  against the variant's own render, invented-water blobs.
- Cue retention per step (base->A, A->B, B->C): where the render changed
  (any channel by more than CHANGE_LEVELS), how much of that change the
  drawing made too. retention = sum(dD . dR) / sum(dR . dR) over those
  pixels (1.0: the drawing changed exactly as the render did; 0: not at
  all); followed_share = share of those pixels where the drawing also
  changed; noise_share = share of building pixels at least NOISE_GAP_PX from
  any render change where the drawing changed anyway (run-to-run noise).
- Era-wall retention by era class (step base->A): the same, with each pixel
  labeled by the era of the building drawn there (from the A scene's facade
  era code). Labels come from projected building silhouettes painted far to
  near, an approximation of what's visible: a label can be wrong at the edge
  where a near building overlaps a far one.

The blind review (output/era_pilot/review/index.html): REVIEW_N buildings per
spot sampled from the C scene, round-robin over roof classes (fitted, front
slope, flat) and then eras (largest first; unknown eras left out), each shown as a north-up crop of the 2024 aerial plus the base
and C drawings in random order, labeled A and B. The page holds only opaque
ids; which side is which is in output/era_pilot/review_key.json, which the
reviewer shouldn't open. Scores stay in the browser (localStorage) and the
page downloads them as JSON. Crops show buildings, never addresses.

Usage:
  uv run python scripts/47_era_compare.py                  # metrics + review page
  uv run python scripts/47_era_compare.py --review-only    # rebuild the review page only
  uv run python scripts/47_era_compare.py --score ~/Downloads/era_review.json
"""

from __future__ import annotations

import argparse
import base64
import functools
import html
import importlib.util
import io
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from pixelphilly.projection import REPO_ROOT, IsoCamera, area_dir, area_setup, load_config

OUT = REPO_ROOT / "output" / "era_pilot"
SPOTS = {
    "indhall": "Independence Hall and Society Hill",
    "northeast": "Northeast twins and singles",
    "passyunk": "East Passyunk rows (control)",
    "mayfair": "Mayfair postwar rows",
}
VARIANTS = {  # key: (area suffix, run, renders folder, masks folder, scene file suffix)
    "base": ("eb", "qwen_joint_light8_eb", "renders", "masks", ""),
    "A": ("ea", "qwen_joint_light8_eraA", "renders_eraA", "masks_eraA", "_eraA"),
    "B": ("ea", "qwen_joint_light8_eraB", "renders_eraB", "masks_eraB", "_eraB"),
    "C": ("ea", "qwen_joint_light8_eraC", "renders_eraC", "masks_eraC", "_eraC"),
}
STEPS = [("base", "A", "era walls"), ("A", "B", "front slopes"), ("B", "C", "fitted gables and hips")]
CHANGE_LEVELS = 15  # a pixel changed when any channel moved by more than this (of 255)
NOISE_GAP_PX = 4
REVIEW_N = 20
CROP_PX = 160  # drawing crop, 1:1 (about 47 m at 0.29 m/px)
AERIAL_M = 22.0  # half-width of the aerial crop
SHOW_PX = 320


@functools.lru_cache(maxsize=None)
def _load_script(name, fname):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- measures ----------------------------------------------------------------

def step_retention(r_old, r_new, d_old, d_new, building):
    """How much of a render change the drawing kept (see the module
    docstring). Arrays are H x W x 3 floats; `building` is the H x W mask
    of building pixels (for the noise baseline)."""
    dr = r_new.astype(float) - r_old.astype(float)
    dd = d_new.astype(float) - d_old.astype(float)
    changed = np.abs(dr).max(axis=2) > CHANGE_LEVELS
    moved = np.abs(dd).max(axis=2) > CHANGE_LEVELS
    near = np.asarray(Image.fromarray((np.abs(dr).max(axis=2) > 6).astype(np.uint8) * 255)
                      .filter(ImageFilter.MaxFilter(2 * NOISE_GAP_PX + 1))) > 0
    quiet = building & ~near
    den = float((dr[changed] ** 2).sum())
    return {"changed_px": int(changed.sum()),
            "retention": float((dd[changed] * dr[changed]).sum() / den) if den else None,
            "followed_share": float(moved[changed].mean()) if changed.any() else None,
            "noise_share": float(moved[quiet].mean()) if quiet.any() else None,
            "_sums": (float((dd[changed] * dr[changed]).sum()), den, int(moved[changed].sum()), int(changed.sum()),
                      int(moved[quiet].sum()), int(quiet.sum()))}


def combine(parts):
    """Pool step_retention results over frames (from their raw sums)."""
    num = sum(p["_sums"][0] for p in parts)
    den = sum(p["_sums"][1] for p in parts)
    fol, chg = sum(p["_sums"][2] for p in parts), sum(p["_sums"][3] for p in parts)
    nmv, nq = sum(p["_sums"][4] for p in parts), sum(p["_sums"][5] for p in parts)
    return {"changed_px": chg, "retention": round(num / den, 3) if den else None,
            "followed_share": round(fol / chg, 3) if chg else None,
            "noise_share": round(nmv / nq, 4) if nq else None}


def retention_by_label(r_old, r_new, d_old, d_new, labels, names):
    """retention and followed share per label (names: label -> name) over
    the pixels where the render changed."""
    dr = r_new.astype(float) - r_old.astype(float)
    dd = d_new.astype(float) - d_old.astype(float)
    changed = np.abs(dr).max(axis=2) > CHANGE_LEVELS
    moved = np.abs(dd).max(axis=2) > CHANGE_LEVELS
    out = {}
    for lab, name in names.items():
        m = changed & (labels == lab)
        den = float((dr[m] ** 2).sum())
        out[name] = {"changed_px": int(m.sum()), "retention": float((dd[m] * dr[m]).sum() / den) if den else None,
                     "followed_share": float(moved[m].mean()) if m.any() else None,
                     "_sums": (float((dd[m] * dr[m]).sum()), den, int(moved[m].sum()), int(m.sum()), 0, 0)}
    return out


def label_raster(sil, labels, frame, size):
    """Pixel labels for one frame: silhouettes (screen polygons, global px)
    painted far to near by their lowest screen point (nearer buildings sit
    lower on screen in this view). 0 = no building."""
    img = Image.new("I", (size, size), 0)
    d = ImageDraw.Draw(img)
    x0, y0 = frame["x0"], frame["y0"]
    order = sorted(range(len(sil)), key=lambda i: sil[i].bounds[3])
    for i in order:
        g = sil[i]
        minx, miny, maxx, maxy = g.bounds
        if maxx < x0 or minx > x0 + size or maxy < y0 or miny > y0 + size or not labels[i]:
            continue
        for p in getattr(g, "geoms", [g]):
            if p.geom_type == "Polygon" and not p.is_empty:
                d.polygon([(x - x0, y - y0) for x, y in p.exterior.coords], fill=int(labels[i]))
    return np.asarray(img)


# --- blind review ------------------------------------------------------------

def stratified_sample(items, n, seed=0, largest_first=False):
    """Up to n items, round-robin over strata (each shuffled with `seed`),
    so rare strata are represented. Strata take turns smallest first, or
    largest first (the eras that cover most of a spot)."""
    rng = random.Random(seed)
    groups = defaultdict(list)
    for it in items:
        groups[it["stratum"]].append(it)
    for k in sorted(groups):
        rng.shuffle(groups[k])
    out, keys = [], sorted(groups, key=lambda k: (-len(groups[k]) if largest_first else len(groups[k]), k))
    while len(out) < n and any(groups[k] for k in keys):
        for k in keys:
            if groups[k] and len(out) < n:
                out.append(groups[k].pop())
    return out


def roof_then_era_sample(items, n, seed=0):
    """Up to n items, round-robin over roof classes first (fitted, front
    slope, flat: Phases B and C need their own buildings judged), then over
    eras within each class (stratified_sample)."""
    by_roof = defaultdict(list)
    for it in items:
        by_roof[it["roof"]].append(it)
    queues = {r: stratified_sample([{**it, "stratum": it["era"]} for it in v], len(v), seed, largest_first=True)
              for r, v in by_roof.items()}
    out = []
    while len(out) < n and any(queues.values()):
        for r in sorted(queues, key=lambda r: (len(queues[r]), r)):
            if queues[r] and len(out) < n:
                it = queues[r].pop(0)
                out.append({**it, "stratum": f"{it['era']}/{it['roof']}"})
    return out


def blind(items, seed=0):
    """Shuffle the review order and flip a coin per item for which drawing
    goes on the left. Returns (order: [{"rid"}], key: {rid: {"left": "base"
    or "era", **the item's other fields}})."""
    rng = random.Random(seed)
    items = list(items)
    rng.shuffle(items)
    order, key = [], {}
    for i, it in enumerate(items):
        rid = f"r{i + 1:03d}"
        key[rid] = {"left": rng.choice(["base", "era"]), **{k: v for k, v in it.items() if not hasattr(v, "save")}}
        order.append({"rid": rid})
    return order, key


def score(review, key):
    """Unblind a downloaded review: counts of era_better, base_better, same,
    neither_right and unscored, overall, by spot and by stratum."""
    scores = review.get("scores", {})

    def blank():
        return {"era_better": 0, "base_better": 0, "same": 0, "neither_right": 0, "unscored": 0}

    out = {"all": blank(), "by_spot": defaultdict(blank), "by_stratum": defaultdict(blank)}
    for rid, k in key.items():
        s = scores.get(rid)
        if s in ("left", "right"):
            what = "era_better" if (s == "left") == (k["left"] == "era") else "base_better"
        else:
            what = {"same": "same", "neither": "neither_right"}.get(s, "unscored")
        for bucket in (out["all"], out["by_spot"][k.get("spot")], out["by_stratum"][k.get("stratum")]):
            bucket[what] += 1
    out["by_spot"] = dict(out["by_spot"])
    out["by_stratum"] = dict(out["by_stratum"])
    return out


def _b64(img, q=88):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Building Look Review</title>
<style>
:root { --bg: #fafaf7; --fg: #1d1d1b; --muted: #5d5d58; --line: #d9d8d0; --accent: #1f5f8b; --chip: #ecebe4; }
@media (prefers-color-scheme: dark) { :root { --bg: #161615; --fg: #ecebe6; --muted: #a9a8a0; --line: #3a3a36;
  --accent: #7fb6dc; --chip: #262624; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 1060px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
p { margin: 0 0 12px; color: var(--muted); }
.bar { position: sticky; top: 0; background: var(--bg); padding: 8px 0; border-bottom: 1px solid var(--line);
  display: flex; gap: 12px; flex-wrap: wrap; align-items: center; z-index: 1; }
.item { border-bottom: 1px solid var(--line); padding: 16px 0; }
.item h2 { font-size: 1rem; margin: 0 0 8px; }
.row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
figure { margin: 0; }
img { width: 100%; height: auto; image-rendering: pixelated; display: block; border-radius: 4px; }
figcaption { font-size: .85rem; color: var(--muted); margin-top: 2px; }
fieldset { border: 0; padding: 0; margin: 8px 0 0; display: flex; flex-wrap: wrap; gap: 6px; }
label { background: var(--chip); border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px; cursor: pointer; }
input:checked + span { font-weight: 700; color: var(--accent); }
input { margin-right: 6px; }
textarea { width: 100%; margin-top: 6px; background: var(--chip); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 6px; font: inherit; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
button { font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent);
  color: var(--bg); cursor: pointer; }
@media (max-width: 640px) { .row { grid-template-columns: 1fr 1fr; } .row figure:first-child { grid-column: 1 / -1; } }
</style></head><body><main>
<h1>Which drawing looks more like the building?</h1>
<p>Each item shows a building at the center of the frame: a north-up crop of the 2024 aerial photo, then two pixel-art
drawings of the same place, A and B, in random order. Pick the drawing whose building (walls, colors, roof shape) looks
more like the real one, or say they're about the same or that neither is right. Scores save in this browser; use
Download when you're done.</p>
<div class="bar"><span id="count"></span><button type="button" id="dl">Download scores</button></div>
__ITEMS__
</main>
<script>
const KEY = "era-review-v1";
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {scores: {}, notes: {}}; }
  catch (e) { return {scores: {}, notes: {}}; } };
const save = (s) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} };
const state = load();
const items = document.querySelectorAll(".item");
const count = () => { document.getElementById("count").textContent =
  `${Object.keys(state.scores).length} of ${items.length} scored`; };
items.forEach((it) => {
  const rid = it.dataset.rid;
  it.querySelectorAll("input").forEach((inp) => {
    if (state.scores[rid] === inp.value) inp.checked = true;
    inp.addEventListener("change", () => { state.scores[rid] = inp.value; save(state); count(); });
  });
  const ta = it.querySelector("textarea");
  ta.value = state.notes[rid] || "";
  ta.addEventListener("input", () => { state.notes[rid] = ta.value; save(state); });
});
count();
document.getElementById("dl").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify({...state, downloaded_at: new Date().toISOString()}, null, 1)],
    {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "era_review.json";
  a.click();
});
</script></body></html>
"""


def write_review_page(items, path):
    """items: [{"rid", "spot_label", "aerial", "left", "right"}] with PIL
    images. Writes one self-contained HTML page (images as data URIs)."""
    blocks = []
    for n, it in enumerate(items, 1):
        rid = html.escape(it["rid"])
        opts = "".join(f'<label><input type="radio" name="{rid}" value="{v}"><span>{t}</span></label>'
                       for v, t in (("left", "A looks more right"), ("same", "About the same"),
                                    ("right", "B looks more right"), ("neither", "Neither is right")))
        spot = html.escape(it["spot_label"])
        blocks.append(
            f'<section class="item" data-rid="{rid}"><h2>{n}. {spot}</h2><div class="row">'
            f'<figure><img src="{_b64(it["aerial"])}" alt="2024 aerial photo, north up, building {n} at center">'
            f'<figcaption>2024 aerial (north up)</figcaption></figure>'
            f'<figure><img src="{_b64(it["left"])}" alt="Drawing A of building {n}"><figcaption>A</figcaption></figure>'
            f'<figure><img src="{_b64(it["right"])}" alt="Drawing B of building {n}"><figcaption>B</figcaption></figure>'
            f'</div><fieldset><legend class="sr">Your pick for {n}</legend>{opts}</fieldset>'
            f'<textarea rows="1" placeholder="Note (optional)" aria-label="Note for {n}"></textarea></section>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PAGE.replace("__ITEMS__", "\n".join(blocks)))


# --- per-spot work -------------------------------------------------------------

def _variant(spot, key):
    suffix, run, rdir, mdir, scene_sfx = VARIANTS[key]
    cfg = load_config(f"atlas_{spot}_{suffix}")
    return cfg, run, area_dir(cfg, rdir), area_dir(cfg, mdir), REPO_ROOT / "data" / "processed" / f"{cfg['name']}_scene{scene_sfx}.json"


def _rgb(p):
    return np.asarray(Image.open(p).convert("RGB")).astype(float)


def _corner_marks(img):
    """Small corner brackets around the center: the building under review."""
    d = ImageDraw.Draw(img)
    w, h = img.size
    c, r, k = (w // 2, h // 2), w // 5, w // 14
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = c[0] + sx * r, c[1] + sy * r
            d.line([(x, y), (x - sx * k, y)], fill=(255, 210, 0), width=2)
            d.line([(x, y), (x, y - sy * k)], fill=(255, 210, 0), width=2)
    return img


def spot_metrics(spot, style, align):
    from pixelphilly.facades import ERAS
    from pixelphilly.qa import flat_share, registration_shift
    from pixelphilly.trainset_clean import invented_color_share

    out = {"quality": {}, "steps": {}, "era_walls_by_era": {}}
    v = {k: _variant(spot, k) for k in VARIANTS}
    for key, (cfg, run, rdir, _, _) in v.items():
        folder = style.drawn_dir(cfg, run)
        _, _, frames = area_setup(cfg)
        s = cfg["camera"]["frame_px"]
        img, have = style.mosaic(cfg, folder)
        flats, colors, shifts = [], [], []
        for f in frames:
            d = np.asarray(Image.open(folder / f"{f.name}.png").convert("RGB"))
            r = np.asarray(Image.open(rdir / f"{f.name}.png").convert("RGB"))
            flats.append(flat_share(d))
            colors.append(invented_color_share(r, d))
            shifts.append(max(abs(x) for x in registration_shift(Image.fromarray(r), Image.fromarray(d))))
        rep = folder / "report.json"
        water = None
        if rep.exists():
            iwr = json.loads(rep.read_text()).get("invented_water")
            if iwr:
                water = sum(1 for b in iwr["blobs"] if not b["exempt"])
        out["quality"][key] = {"run": run, "seam": round(style.border_seam(img, have, s) or float("nan"), 3),
                               "flat": round(float(np.mean(flats)), 3),
                               "invented_color_pct": round(100 * float(np.mean(colors)), 2),
                               "max_shift_px": int(max(shifts)), "invented_water_blobs": water}
    # Cue retention per step
    cfg_a = v["A"][0]
    cam = IsoCamera.from_config(cfg_a)
    _, _, frames = area_setup(cfg_a)
    scene_a = json.loads(v["A"][4].read_text())
    sil = align.silhouettes(scene_a["buildings"], cam)
    era_lab = [((b.get("facade") or {}).get("e", -1) + 1) for b in scene_a["buildings"]]  # 0 = no era
    names = {i + 1: e for i, e in enumerate(ERAS)}
    s = cfg_a["camera"]["frame_px"]
    for old, new, what in STEPS:
        parts, by_era = [], defaultdict(list)
        for f in frames:
            r0, r1 = _rgb(v[old][2] / f"{f.name}.png"), _rgb(v[new][2] / f"{f.name}.png")
            d0 = _rgb(style.drawn_dir(v[old][0], v[old][1]) / f"{f.name}.png")
            d1 = _rgb(style.drawn_dir(v[new][0], v[new][1]) / f"{f.name}.png")
            bld = np.asarray(Image.open(v[new][3] / f"{f.name}.png").convert("L")) > 127
            parts.append(step_retention(r0, r1, d0, d1, bld))
            if (old, new) == ("base", "A"):
                labels = label_raster(sil, era_lab, {"x0": f.x0, "y0": f.y0}, s)
                for name, res in retention_by_label(r0, r1, d0, d1, labels, names).items():
                    by_era[name].append(res)
        out["steps"][f"{old}->{new}"] = {"what": what, **combine(parts)}
        for name, rs in by_era.items():
            c = combine(rs)
            if c["changed_px"]:
                out["era_walls_by_era"][name] = {k: c[k] for k in ("changed_px", "retention", "followed_share")}
    return out


def review_items(spot, style, n, seed):
    """Sample buildings from the C scene and cut their crops."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from pixelphilly.facades import ERAS
    from pixelphilly.qa_scan import footprint_id

    cfg_c, run_c, _, _, scene_c = _variant(spot, "C")
    cfg_b, run_b, _, _, _ = _variant(spot, "base")
    scene = json.loads(scene_c.read_text())
    cam = IsoCamera.from_config(cfg_c)
    _, _, frames = area_setup(cfg_c)
    s = cfg_c["camera"]["frame_px"]
    ox, oy = frames[0].x0 - frames[0].col * s, frames[0].y0 - frames[0].row * s
    have = {(f.col, f.row) for f in frames}
    groups = defaultdict(list)
    for b in scene["buildings"]:
        if str(b["id"]).startswith("s") or not b.get("facade"):
            continue
        groups[footprint_id(b["id"])].append(b)
    items = []
    for fid, parts in groups.items():
        geom = unary_union([Polygon(p[0], p[1:]).buffer(0) for b in parts for p in b["polys"]])
        if geom.area < 30:
            continue
        roof = ("fitted" if any(b.get("roof3d") for b in parts)
                else "front_slope" if any("-f" in str(b["id"]) for b in parts) else "flat")
        e = parts[0]["facade"].get("e")
        era = ERAS[e] if e is not None else "unknown"
        if era == "unknown":  # nothing for the era option to judge
            continue
        h = max(b["h"] for b in parts)
        c = geom.representative_point()
        sx, sy = cam.world_to_screen(c.x, c.y, h / 2)
        mx, my = float(sx) - ox, float(sy) - oy
        half = CROP_PX // 2
        corners = [(mx - half, my - half), (mx + half, my - half), (mx - half, my + half), (mx + half, my + half)]
        if not all((int(x // s), int(y // s)) in have for x, y in corners):
            continue
        items.append({"fid": fid, "stratum": f"{era}/{roof}", "era": era, "roof": roof, "e": c.x, "n": c.y,
                      "mx": mx, "my": my})
    picked = roof_then_era_sample(items, n, seed)
    if not picked:
        return []
    base_img, _ = style.mosaic(cfg_b, style.drawn_dir(cfg_b, run_b))
    era_img, _ = style.mosaic(cfg_c, style.drawn_dir(cfg_c, run_c))
    out = []
    for it in picked:
        half = CROP_PX // 2
        box = (int(it["mx"] - half), int(it["my"] - half), int(it["mx"] + half), int(it["my"] + half))
        aerial = aerial_crop(cfg_c, it["e"], it["n"], AERIAL_M, SHOW_PX)
        show = lambda im: _corner_marks(im.crop(box).resize((SHOW_PX, SHOW_PX), Image.NEAREST))  # noqa: E731
        out.append({**{k: it[k] for k in ("fid", "stratum", "era", "roof")}, "spot": spot,
                    "spot_label": SPOTS[spot], "aerial": _corner_marks(aerial),
                    "base": show(base_img), "era_img": show(era_img)})
    return out


def aerial_crop(cfg, e, n, half_m, size):
    """North-up crop of the raw 2024 imagery tiles (data/raw/imagery, z19,
    unfiltered; the scene's ground image is median-filtered for the render)
    centered on local (e, n), half_m meters each way."""
    bs = _load_script("build_scene", "05_build_scene.py")
    frame, _, _ = area_setup(cfg)
    z = cfg["imagery_zoom"]
    lon, lat = frame.to_wgs84(np.array([e - half_m, e + half_m]), np.array([n + half_m, n - half_m]))
    px, py = bs.merc_px(lon, lat, z)
    t = bs.TILE
    x0, x1, y0, y1 = int(px[0] // t), int(px[1] // t), int(py[0] // t), int(py[1] // t)
    m = Image.new("RGB", ((x1 - x0 + 1) * t, (y1 - y0 + 1) * t), (128, 128, 128))
    tile_dir = REPO_ROOT / "data" / "raw" / "imagery" / "CityImagery_2024_3in" / str(z)
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            path = tile_dir / f"{ty}_{tx}.jpg"
            if path.exists():
                with Image.open(path) as im:
                    m.paste(im.convert("RGB"), ((tx - x0) * t, (ty - y0) * t))
    box = (int(px[0] - x0 * t), int(py[0] - y0 * t), int(px[1] - x0 * t), int(py[1] - y0 * t))
    return m.crop(box).resize((size, size), Image.LANCZOS)


def write_report(metrics, path):
    lines = ["# Building-eras pilot: Phase D measures", "",
             "Written by `scripts/47_era_compare.py`. Retention: the share of the render's change the drawing "
             "made too (1.0 = all, 0 = none); followed: pixels where the drawing changed with the render; noise: "
             "building pixels away from any render change where the drawing changed anyway.", ""]
    for spot, m in metrics.items():
        lines += [f"## {SPOTS[spot]}", "", "| Variant | Seam | Flat | Invented color % | Max shift px | Invented water |",
                  "|---|---|---|---|---|---|"]
        for k, q in m["quality"].items():
            lines.append(f"| {k} | {q['seam']} | {q['flat']} | {q['invented_color_pct']} | {q['max_shift_px']} | "
                         f"{q['invented_water_blobs']} |")
        lines += ["", "| Step | Render px changed | Retention | Followed | Noise |", "|---|---|---|---|---|"]
        for k, st in m["steps"].items():
            lines.append(f"| {k} ({st['what']}) | {st['changed_px']:,} | {st['retention']} | {st['followed_share']} | "
                         f"{st['noise_share']} |")
        if m["era_walls_by_era"]:
            lines += ["", "| Era (walls, base->A) | Render px changed | Retention | Followed |", "|---|---|---|---|"]
            for e, r in sorted(m["era_walls_by_era"].items(), key=lambda kv: -kv[1]["changed_px"]):
                lines.append(f"| {e} | {r['changed_px']:,} | {round(r['retention'], 3) if r['retention'] is not None else '–'} | "
                             f"{r['followed_share']} |")
        lines.append("")
    path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spots", nargs="+", default=list(SPOTS))
    ap.add_argument("--sample", type=int, default=REVIEW_N)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--score", help="a downloaded era_review.json to unblind")
    ap.add_argument("--no-review", action="store_true")
    ap.add_argument("--review-only", action="store_true", help="rebuild the review page, keep metrics.json")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.score:
        key = json.loads((OUT / "review_key.json").read_text())
        res = score(json.loads(Path(args.score).expanduser().read_text()), key)
        (OUT / "review_results.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps(res["all"]), "\nby spot:", json.dumps(res["by_spot"], indent=1))
        return
    style = _load_script("style_compare", "24_style_compare.py")
    align = _load_script("align", "09_check_alignment.py")
    if not args.review_only:
        metrics = {}
        for spot in args.spots:
            print(f"  {spot}: measures ...", flush=True)
            metrics[spot] = spot_metrics(spot, style, align)
        (OUT / "metrics.json").write_text(json.dumps(metrics, indent=1) + "\n")
        write_report(metrics, OUT / "report.md")
        print(f"Wrote {(OUT / 'metrics.json').relative_to(REPO_ROOT)} and report.md")
    if args.no_review:
        return
    items = []
    for spot in args.spots:
        print(f"  {spot}: review crops ...", flush=True)
        items += review_items(spot, style, args.sample, args.seed)
    order, key = blind([{k: v for k, v in it.items() if k not in ("aerial", "base", "era_img")} for it in items],
                       seed=args.seed)
    by_fid = {(it["spot"], it["fid"]): it for it in items}
    page_items = []
    for o in order:
        k = key[o["rid"]]
        it = by_fid[(k["spot"], k["fid"])]
        left, right = (it["era_img"], it["base"]) if k["left"] == "era" else (it["base"], it["era_img"])
        page_items.append({"rid": o["rid"], "spot_label": it["spot_label"], "aerial": it["aerial"],
                           "left": left, "right": right})
    write_review_page(page_items, OUT / "review" / "index.html")
    (OUT / "review_key.json").write_text(json.dumps(key, indent=1) + "\n")
    print(f"Wrote {len(page_items)} review items: output/era_pilot/review/index.html "
          f"(key in review_key.json; strata {dict(Counter(k['stratum'] for k in key.values()))})")


if __name__ == "__main__":
    main()
