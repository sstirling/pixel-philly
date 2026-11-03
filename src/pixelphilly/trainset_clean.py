"""Candidate B's training set: Qwen-Image-Edit-2511 (prompt only, no style
LoRA) redraws of our own renders, filtered by the pipeline's own QA.

Why: the first style LoRA (qe2511_oldcity_r16_v1) was trained on Gemini 3
Pro Image outputs, whose terms are unclear for this use. Every target here
comes from Apache-2.0 weights run on renders of City open data, and each
pair's provenance is written to output/trainset_clean/manifest.jsonl.

The filters (reject_reasons) are measurable and deterministic:
- registration shift <= 2 px against the render (pixelphilly.qa), so the
  model learns to stay on the geometry;
- no invented water (pixelphilly.invented_water.find_blobs);
- flat share in a pixel-art range (pixelphilly.qa.flat_share; the range is
  set in scripts/23_build_clean_trainset.py from current drawings);
- invented saturated color (invented_color_share): prompt-only Qwen sprinkles
  cars and red/blue specks over roads, lots and even roofs. The old style
  invents ~0.1% of such pixels, prompt-only Qwen a median ~1.2%;
- tone: mean luminance/chroma shift against the render, outliers by a
  robust z-score across the whole candidate set (robust_outliers).

Terrain classes (classify_terrain) are only for stratified sampling, so the
set covers rowhouses, towers, parks, river, stadiums, industry, port and
woods rather than mostly rowhouses (most of the city).
"""

from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageFilter

from .invented_water import _hsv

MAX_SHIFT_PX = 2
NODATA_GRAY = 128  # render ground where the City has no aerial (measured)
# invented_color_share: a saturated, reasonably bright pixel where the
# render has no saturated color within COLOR_NEIGHBORHOOD_PX
COLOR_S_MIN = 0.5
COLOR_V_MIN = 0.3
RENDER_S_MAX = 0.3
COLOR_NEIGHBORHOOD_PX = 7
GREEN_HUE = (70.0, 170.0)
SPECK_MEDIAN_PX = 9

# Words that must never appear in a clean pair's provenance: the Gemini model
# and prompt, the Gemini-trained LoRA and the old Gemini training set
FORBIDDEN = ("gemini", "redraw_v3", "qe2511_oldcity", "oldcity/trainset", "nano banana")


def shift_ok(shift, max_px: int = MAX_SHIFT_PX) -> bool:
    return max(abs(int(shift[0])), abs(int(shift[1]))) <= max_px


def invented_color_mask(render: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Target pixels that are saturated, non-green color (cars, confetti)
    where the render has no saturated color nearby. Greens are left out:
    trees and lawns drawn on the leaf-off (brown) aerial are a drawing
    choice, not specks."""
    _, rs, _ = _hsv(render)
    rs_max = np.asarray(Image.fromarray(np.round(rs * 255).astype(np.uint8))
                        .filter(ImageFilter.MaxFilter(COLOR_NEIGHBORHOOD_PX))) / 255.0
    th, ts, tv = _hsv(target)
    green = (th >= GREEN_HUE[0]) & (th <= GREEN_HUE[1])
    return (ts >= COLOR_S_MIN) & (tv >= COLOR_V_MIN) & (rs_max < RENDER_S_MAX) & ~green


def invented_color_share(render: np.ndarray, target: np.ndarray) -> float:
    """Share of target pixels in invented_color_mask."""
    return float(invented_color_mask(render, target).mean())


def remove_invented_specks(render: np.ndarray, target: np.ndarray):
    """Paint invented specks (invented_color_mask, grown 1 px for their
    antialiased edges) with a SPECK_MEDIAN_PX median of the target around
    them. A car is a few pixels across, so the median is the street or roof
    under it; a large invented patch survives and still counts in
    invented_color_share. Returns (cleaned copy, pixels changed)."""
    m = invented_color_mask(render, target)
    if not m.any():
        return target.copy(), 0
    grown = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 127
    med = np.asarray(Image.fromarray(target).filter(ImageFilter.MedianFilter(SPECK_MEDIAN_PX)))
    out = target.copy()
    out[grown] = med[grown]
    return out, int(grown.sum())


def tone_delta(render: np.ndarray, target: np.ndarray) -> dict:
    """Mean shift target - render: luminance (0-255) and two opponent chroma
    axes (red-green, yellow-blue). A redraw that turns a frame tomato red or
    night-dark shows up here."""
    def stats(a):
        a = a.reshape(-1, 3).astype(float)
        r, g, b = a[:, 0], a[:, 1], a[:, 2]
        return np.array([(0.299 * r + 0.587 * g + 0.114 * b).mean(), (r - g).mean(), (0.5 * (r + g) - b).mean()])
    d = stats(target) - stats(render)
    return {"dlum": float(d[0]), "drg": float(d[1]), "dyb": float(d[2])}


def robust_outliers(values, k: float = 3.5) -> list[bool]:
    """True where |value - median| > k * 1.4826 * MAD (a robust z-score)."""
    v = np.asarray(values, float)
    med = np.median(v)
    mad = 1.4826 * np.median(np.abs(v - med))
    if mad == 0:
        return [False] * len(v)  # no spread: nothing stands out
    return [bool(abs(x - med) > k * mad) for x in v]


def reject_reasons(scores: dict, flat_range, max_color: float, max_featureless: float = 0.15,
                   min_diff: float = 0.0) -> list[str]:
    """Every filter a candidate fails (empty list: keep). min_diff: mean
    absolute difference from the render (land pixels) below which the
    'redraw' is the photo with light edits."""
    out = []
    if scores.get("mean_abs_diff", min_diff) < min_diff:
        out.append(f"near-copy of the render (mean diff {scores['mean_abs_diff']} < {min_diff})")
    if scores.get("featureless_share", 0.0) > max_featureless:
        out.append(f"no-data ground {scores['featureless_share']:.2f} > {max_featureless}")
    if not shift_ok(scores["shift"]):
        out.append(f"shift {tuple(scores['shift'])}")
    lo, hi = flat_range
    if not lo <= scores["flat_share"] <= hi:
        out.append(f"flat share {scores['flat_share']:.3f} outside [{lo}, {hi}]")
    if scores["invented_water_blobs"]:
        out.append(f"invented water ({scores['invented_water_blobs']} blobs)")
    if scores["invented_color_share"] > max_color:
        out.append(f"invented color {scores['invented_color_share']:.4f} > {max_color}")
    if scores["tone_outlier"]:
        out.append("tone outlier")
    return out


def classify_terrain(f: dict) -> str:
    """One terrain label per view, from measured features:
    building_share, water_share, park_share (screen shares, 0-1),
    green_share (render pixels in the lawn-green band), median_footprint_m2,
    max_height_m of footprints whose center is in view, and tags (from
    known places: "stadium", "port"). Order matters: the first rule wins."""
    tags = set(f.get("tags", ()))
    if f["water_share"] >= 0.85:
        return "open_water"
    if "stadium" in tags:
        return "stadium"
    if "port" in tags:
        return "port"
    if f["water_share"] >= 0.15:
        return "river"
    if f["max_height_m"] >= 60:
        return "tower"
    if f["park_share"] >= 0.4 and f["building_share"] < 0.08:
        return "park" if f["green_share"] >= 0.2 else "woods"
    if f["building_share"] < 0.05:
        return "open"
    if f["median_footprint_m2"] >= 600:
        return "industrial"
    return "rowhouse"


def stratified_pick(items, quotas: dict, seed: int = 0) -> list:
    """Up to quotas[label] items per terrain label, picked at random with a
    fixed seed (reproducible). Labels without a quota are dropped."""
    rng = random.Random(seed)
    out = []
    for label in sorted(quotas):
        pool = sorted((x for x in items if x["terrain"] == label), key=lambda x: x["id"])
        rng.shuffle(pool)
        out += pool[:quotas[label]]
    return out


def near_eval(rect, eval_polys, margin_px: float) -> bool:
    """rect = (x0, y0, size) in screen px; eval_polys: the evaluation spots'
    ground, projected to the same screen space. True if the view comes
    within margin_px of any of them (excluded from training)."""
    from shapely.geometry import box

    x0, y0, s = rect
    r = box(x0, y0, x0 + s, y0 + s)
    return any(r.distance(p) <= margin_px for p in eval_polys)


def check_provenance(row: dict) -> None:
    """Raise ValueError if any value of a manifest row mentions a Gemini
    source, the Gemini-trained LoRA or the old Gemini training set."""
    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                yield from walk(x)
        elif isinstance(v, str):
            yield v
    for s in walk(row):
        low = s.lower()
        for word in FORBIDDEN:
            if word in low:
                raise ValueError(f"{row.get('id')}: provenance mentions {word!r}: {s}")


def _flat_map(img: np.ndarray, tol: int) -> np.ndarray:
    """Per-pixel version of qa.flat_share (interior pixels only)."""
    a = img.astype(int)
    c = a[1:-1, 1:-1]
    ok = np.ones(c.shape[:2], bool)
    h, w = a.shape[:2]
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            n = a[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
            ok &= np.abs(n - c).max(axis=2) <= tol
    return ok


def flat_share_masked(img: np.ndarray, keep: np.ndarray, tol: int = 6) -> float:
    """qa.flat_share over the pixels where `keep` is True only. Used with
    repainted water masked out: the repaint is flat by construction, so a
    river frame would otherwise look 'too flat'."""
    k = keep[1:-1, 1:-1]
    if not k.any():
        return 0.0
    return float(_flat_map(img, tol)[k].mean())


def featureless_share(render: np.ndarray) -> float:
    """Share of render pixels in perfectly flat, colorless patches: the
    gray ground where the City has no aerial (outside the city line). The
    model invents houses there; such views make poor targets, and the
    pipeline clears that ground anyway (pixelphilly.nodata)."""
    # The renderer's ground has no aerial there and reads exactly (128, 128,
    # 128); flat white or gray roofs are not it
    gray = (np.abs(render.astype(int) - NODATA_GRAY).max(axis=2) <= 2)
    flat = np.zeros(render.shape[:2], bool)
    flat[1:-1, 1:-1] = _flat_map(render, 1)
    return float((flat & gray).mean())


def first_passing(tries: dict):
    """tries: {seed: [reject reasons]}. The lowest seed with no reasons, or
    None. One pair per view, so a view never appears twice."""
    ok = [seed for seed, reasons in tries.items() if not reasons]
    return min(ok) if ok else None
