"""Window grids and blending weights for joint denoising.

All sizes here are in LATENT cells. Qwen-Image's VAE downsamples 8x and the
transformer packs latents 2x2, so one latent cell is 8 image pixels and every
window offset must be even for the 2x2 packing to line up.

Defaults follow tiny.london's sampler: 1,024 px windows (128 latents) on a
768 px stride (96 latents), with a second grid shifted half a stride (48
latents) used on alternate steps so window edges never sit in the same place
two steps running.
"""

from __future__ import annotations

import numpy as np

WIN = 128
STRIDE = 96
SHIFT = 48


def positions(length: int, win: int = WIN, stride: int = STRIDE, offset: int = 0) -> list[int]:
    """Start positions along one axis that cover [0, length).

    Starts are offset + k * stride, plus 0 and the last full window
    (length - win) so the canvas edges are always covered. All are even.
    """
    if length < win:
        raise ValueError(f"canvas axis {length} is smaller than the window {win}")
    last = length - win
    starts = {0, last}
    s = offset
    while s < last:
        starts.add(s)
        s += stride
    out = sorted(starts)
    if any(p % 2 for p in out):
        raise ValueError(f"odd window offset in {out}; use even sizes for 2x2 packing")
    return out


def grid(height: int, width: int, offset: int = 0, win: int = WIN, stride: int = STRIDE):
    """(y, x) top-left latent coordinates of every window in one grid."""
    return [(y, x) for y in positions(height, win, stride, offset) for x in positions(width, win, stride, offset)]


def two_grids(height: int, width: int, win: int = WIN, stride: int = STRIDE, shift: int = SHIFT):
    """Grid A (no offset) and grid B (shifted), used on alternating steps."""
    return [grid(height, width, 0, win, stride), grid(height, width, shift, win, stride)]


def tent(win: int = WIN, ramp: int = WIN - STRIDE, at_start: bool = False, at_end: bool = False) -> np.ndarray:
    """1-D window weight: linear ramps of `ramp` cells at each end, flat 1 in
    between. A side that touches the canvas edge gets no ramp, otherwise the
    edge cells would be weighted near zero with nothing overlapping them.
    Ramp values are (i + 0.5) / ramp, so no weight is exactly zero.
    """
    w = np.ones(win, dtype=np.float32)
    r = (np.arange(ramp, dtype=np.float32) + 0.5) / ramp
    if not at_start:
        w[:ramp] = r
    if not at_end:
        w[win - ramp :] = r[::-1]
    return w


def window_weight(y: int, x: int, height: int, width: int, win: int = WIN, ramp: int = WIN - STRIDE) -> np.ndarray:
    """2-D tent weight (win x win) for the window at (y, x)."""
    wy = tent(win, ramp, at_start=(y == 0), at_end=(y + win == height))
    wx = tent(win, ramp, at_start=(x == 0), at_end=(x + win == width))
    return np.outer(wy, wx)


def weight_sum(height: int, width: int, windows, win: int = WIN) -> np.ndarray:
    """Total weight at every latent cell for one grid (must be > 0 everywhere)."""
    total = np.zeros((height, width), dtype=np.float32)
    for y, x in windows:
        total[y : y + win, x : x + win] += window_weight(y, x, height, width, win)
    return total
