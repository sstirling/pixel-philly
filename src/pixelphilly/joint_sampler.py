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
) -> torch.Tensor:
    """Denoise a [C, H, W] latent canvas.

    sigmas runs from ~1 down to 0 (len = steps + 1). grids[i % len(grids)]
    gives the window positions used at step i. on_step(i, latents) is called
    after each step, e.g. to checkpoint so a long run can resume.
    """
    _, height, width = noise.shape
    latents = noise.clone()
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
        if not torch.all(wsum > 0):
            raise RuntimeError("a canvas cell is not covered by any window in this grid")
        latents = latents + (sigma_next - sigma) * vel / wsum
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
