"""Joint denoising of a whole canvas with overlapping windows (MultiDiffusion).

This is the seam fix from tiny.london (https://tiny.london/how/), after
Bar-Tal et al. 2023 (https://arxiv.org/abs/2302.08113). Instead of drawing
frames one at a time and stitching them, ONE latent covers the whole canvas.
At every step the model predicts on overlapping windows, the predictions are
averaged with tent weights where windows overlap, and one Euler step moves
the whole canvas. Neighboring windows edit the same numbers, so they cannot
drift apart into a seam. Grids alternate between steps so window edges never
sit in the same place twice in a row.

Flow-matching convention (Qwen-Image's scheduler):
    x_sigma = (1 - sigma) * x0 + sigma * noise,  velocity v = noise - x0,
    Euler step: x <- x + (sigma_next - sigma) * v.

The model is passed in as `predict`, so this file has no model code and is
tested on CPU with toy predictors (tests/test_joint_sampler.py). The Modal
GPU job wraps the real transformer in a `predict` function.
"""

from __future__ import annotations

from typing import Callable, Sequence

import torch

from .windows import WIN, window_weight

# predict(x_window [C, win, win], y, x, sigma) -> velocity [C, win, win]
Predict = Callable[[torch.Tensor, int, int, float], torch.Tensor]


def joint_denoise(
    noise: torch.Tensor,
    sigmas: Sequence[float],
    grids: Sequence[Sequence[tuple[int, int]]],
    predict: Predict,
    win: int = WIN,
    on_step: Callable[[int, torch.Tensor], None] | None = None,
    active: torch.Tensor | None = None,
    known: tuple[torch.Tensor, torch.Tensor] | None = None,
    start: torch.Tensor | None = None,
) -> torch.Tensor:
    """Denoise a [C, H, W] latent canvas.

    active: optional [H, W] bool mask. Grids should then contain only
    windows touching it (windows.active_grids); coverage is required only on
    active cells, and cells no window covers are left as they are.

    sigmas runs from ~1 down to 0 (len = steps + 1). grids[i % len(grids)]
    gives the window positions used at step i. on_step(i, latents) is called
    after each step, e.g. to checkpoint so a long run can resume.

    known: optional (x0_known [C, H, W], mask [H, W] in 0..1) for drawing a
    region next to one already drawn. After every step the masked cells are
    reset to where the known image would be at that noise level,
    (1 - sigma) * x0_known + sigma * noise, using this run's own noise
    (RePaint, Lugmayr et al. 2022, https://arxiv.org/abs/2201.09865, in
    flow-matching form). Windows overlapping the band see the neighbor's
    real content at every step, so new content continues it; at sigma = 0
    cells with mask 1 equal x0_known exactly. A mask that ramps from 1 to 0
    spreads any remaining tone difference instead of leaving a hard edge.

    start: optional initial latent (default `noise`). The region-join repair
    pass re-noises a finished canvas to sigmas[0] with fresh noise and
    passes that here, with `noise` the fresh noise (the known-cell target
    above uses it) and `sigmas` the tail of the run's schedule.
    """
    _, height, width = noise.shape
    latents = (noise if start is None else start).clone()
    weights = {}
    for g in grids:
        for y, x in g:
            if (y, x) not in weights:
                w = window_weight(y, x, height, width, win)
                weights[(y, x)] = torch.from_numpy(w).to(noise.device, noise.dtype)

    for i in range(len(sigmas) - 1):
        sigma, sigma_next = float(sigmas[i]), float(sigmas[i + 1])
        vel = torch.zeros_like(latents)
        wsum = torch.zeros((height, width), device=noise.device, dtype=noise.dtype)
        for y, x in grids[i % len(grids)]:
            w = weights[(y, x)]
            v = predict(latents[:, y : y + win, x : x + win], y, x, sigma)
            vel[:, y : y + win, x : x + win] += v * w
            wsum[y : y + win, x : x + win] += w
        covered = wsum > 0
        if not torch.all(covered if active is None else covered[active]):
            raise RuntimeError("a canvas cell is not covered by any window in this grid")
        step = torch.where(covered, vel / torch.where(covered, wsum, torch.ones_like(wsum)), torch.zeros_like(vel))
        latents = latents + (sigma_next - sigma) * step
        if known is not None:
            x0_known, mask = known
            target = (1.0 - sigma_next) * x0_known + sigma_next * noise
            latents = mask * target + (1.0 - mask) * latents
        if on_step is not None:
            on_step(i, latents)
    return latents


def independent_tiles(
    noise: torch.Tensor,
    sigmas: Sequence[float],
    tile: int,
    predict: Predict,
) -> torch.Tensor:
    """The naive baseline: denoise non-overlapping tiles separately and paste
    them together. Used by the tests to show the seam metric detects seams."""
    _, height, width = noise.shape
    out = noise.clone()
    for y in range(0, height, tile):
        for x in range(0, width, tile):
            t = noise[:, y : y + tile, x : x + tile].clone()
            for i in range(len(sigmas) - 1):
                v = predict(t, y, x, float(sigmas[i]))
                t = t + (float(sigmas[i + 1]) - float(sigmas[i])) * v
            out[:, y : y + tile, x : x + tile] = t
    return out
