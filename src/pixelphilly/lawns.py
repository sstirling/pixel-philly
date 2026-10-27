"""Dormant lawns in the leaf-off aerial, shifted toward green.

The City's 2024 aerial was flown in March: lawns under bare trees are
brown-tan, and the drawing model draws them as dirt (Independence Square,
Washington Square). Inside park polygons only (City PPR_Properties; the
National Park Service's Independence NHP boundary, which the City layer
lacks), pixels classified as dormant grass get their hue moved toward lawn
green. Brightness is kept, so mowing stripes, shade and tree shadows stay.
Paint only, opt-in per config ("lawn_correct": true), applied to the ground
texture before rendering; roofs are excluded (building footprints).

Classification, from measured cluster colors in the 2024 aerial
(atlas_indhall_fac ground): dormant grass H 43-54, S 0.25-0.40, V 0.33-0.65
(Washington Square, Independence Square, the Mall); paths and paving S
0.06-0.20, V 0.65-0.93; shadow V < 0.25; ball-field clay is redder (H ~20-30).
DORMANT_BAND sits between them, with soft edges (EDGE) so lawn meets path
without a seam. Bare dirt in a park is the main risk: brown dirt with grass-
like hue and saturation would turn green too.
"""

from __future__ import annotations

import numpy as np

from .invented_water import _hsv

DORMANT_BAND = {"h": (35.0, 65.0), "s": (0.22, 0.60), "v": (0.30, 0.72)}
EDGE = {"h": 6.0, "s": 0.04, "v": 0.06}  # soft ramp width just inside each band edge
TARGET_HUE = 88.0  # lawn green
MIN_SAT = 0.30
STRENGTH = 0.9


def _ramp(x, lo, hi, w):
    """1 well inside [lo, hi], falling linearly to 0 over w at each edge."""
    return np.clip(np.minimum(x - lo, hi - x) / w, 0.0, 1.0)


def dormant_weight(rgb) -> np.ndarray:
    h, s, v = _hsv(rgb)
    b = DORMANT_BAND
    return (_ramp(h, *b["h"], EDGE["h"]) * _ramp(s, *b["s"], EDGE["s"]) * _ramp(v, *b["v"], EDGE["v"]))


def _hsv_to_rgb(h, s, v):
    h = (h % 360.0) / 60.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def correct(rgb: np.ndarray, region: np.ndarray) -> np.ndarray:
    """rgb (H, W, 3) uint8; region (H, W) bool (park polygons minus building
    footprints). Returns a corrected copy; pixels outside the region or not
    dormant grass are unchanged."""
    out = rgb.copy()
    w = dormant_weight(rgb) * region
    sel = w > 0
    if not sel.any():
        return out
    h, s, v = _hsv(rgb[sel])
    k = w[sel] * STRENGTH
    h2 = h + (TARGET_HUE - h) * k
    s2 = s + (np.maximum(s, MIN_SAT) - s) * k
    out[sel] = np.clip(np.round(_hsv_to_rgb(h2, s2, v) * 255), 0, 255).astype(np.uint8)
    return out
