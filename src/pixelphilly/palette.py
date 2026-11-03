"""v2 training targets: snap to a palette derived from our own data, then
remove small invented specks (cars, confetti) by connected components.

Why:
- A limited palette gives the flat, consistent color areas of pixel art and
  stops each target from inventing its own colors. The palette comes only
  from our renders (City aerial on extruded footprints, with the facade
  shader), never from any model's drawings, so it carries no style from
  the Gemini-trained LoRA.
- Snapping is dither-free (nearest color), so flat areas stay flat.
- Speck removal works on the snapped index image: every 8-connected region
  of one color smaller than max_px is a candidate (rasterio's sieve, which
  fills it from its neighbors). A candidate is removed only where the
  render has no similar color nearby. A car is a few small blobs on
  asphalt; a red roof or a dark window the render really has is kept. This
  works in car-dense lots, where a median filter (Phase 1) only smeared
  the cars together.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

PRESENT_DIST = 40.0  # RGB distance at which the render "has" a palette color
PRESENT_RADIUS_PX = 5  # ... within this many pixels of the speck


def build_palette(samples, k: int = 56, seed: int = 0, n: int = 200_000, iters: int = 25) -> np.ndarray:
    """k-means (k-means++ start, fixed seed) over pixels sampled from the
    given images. Returns (k, 3) uint8, sorted by luminance."""
    rng = np.random.default_rng(seed)
    px = np.concatenate([np.asarray(s, np.uint8).reshape(-1, 3) for s in samples]).astype(np.float32)
    if len(px) > n:
        px = px[rng.choice(len(px), n, replace=False)]
    # k-means++
    centers = [px[rng.integers(len(px))]]
    d2 = ((px - centers[0]) ** 2).sum(1)
    for _ in range(1, k):
        c = px[rng.choice(len(px), p=d2 / d2.sum())] if d2.sum() > 0 else px[rng.integers(len(px))]
        centers.append(c)
        d2 = np.minimum(d2, ((px - c) ** 2).sum(1))
    C = np.array(centers, np.float32)
    for _ in range(iters):
        lab = _nearest(px, C)
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = px[m].mean(0)
    C = np.clip(np.round(C), 0, 255).astype(np.uint8)
    lum = C.astype(float) @ np.array([0.299, 0.587, 0.114])
    return C[np.lexsort((C[:, 2], C[:, 1], C[:, 0], lum))]


def _nearest(px: np.ndarray, C: np.ndarray, chunk: int = 262_144) -> np.ndarray:
    out = np.empty(len(px), np.int32)
    C = C.astype(np.float32)
    cc = (C ** 2).sum(1)
    for i in range(0, len(px), chunk):
        p = px[i:i + chunk].astype(np.float32)
        out[i:i + chunk] = np.argmin(cc[None, :] - 2 * p @ C.T, axis=1)
    return out


def snap(img: np.ndarray, palette: np.ndarray):
    """Nearest palette color per pixel, no dithering. Returns (rgb, index)."""
    a = np.asarray(img, np.uint8)
    idx = _nearest(a.reshape(-1, 3), palette).reshape(a.shape[:2])
    return palette[idx], idx


def remove_specks(idx: np.ndarray, palette: np.ndarray, render: np.ndarray, max_px: int = 40) -> np.ndarray:
    """Index image with invented specks filled from their neighbors (see the
    module docstring)."""
    from rasterio.features import sieve

    idx = np.asarray(idx, np.int32)
    sieved = sieve(idx, size=max_px + 1, connectivity=8)
    changed = sieved != idx
    if not changed.any():
        return idx.copy()
    r = np.asarray(render, np.float32)
    present = np.zeros_like(changed)
    for c in np.unique(idx[changed]):
        near = np.sqrt(((r - palette[c].astype(np.float32)) ** 2).sum(-1)) < PRESENT_DIST
        if near.any():
            near = np.asarray(Image.fromarray(near.astype(np.uint8) * 255)
                              .filter(ImageFilter.MaxFilter(2 * PRESENT_RADIUS_PX + 1))) > 127
            present |= (idx == c) & near
    speck = changed & ~present
    # Only blobs at least 3 px thick (an opening): cars and confetti are
    # blobs; 1-2 px lines (mullions, lane markings, outlines) are detail
    m = Image.fromarray(speck.astype(np.uint8) * 255)
    opened = np.asarray(m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))) > 127
    speck &= np.asarray(Image.fromarray(opened.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 127
    out = idx.copy()
    out[speck] = sieved[speck]
    return out
