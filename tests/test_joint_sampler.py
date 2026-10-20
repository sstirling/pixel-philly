"""CPU tests of the joint sampler with toy 'models'.

Each toy window predicts the true image plus its own constant color bias:
the per-frame tone drift seen in the Gemini pilot, in miniature. Denoising
windows independently must leave seams; denoising jointly must not.
"""

import numpy as np
import torch

from pixelphilly.joint_sampler import independent_tiles, joint_denoise
from pixelphilly.qa import seam_ratio_lines
from pixelphilly.windows import WIN, two_grids

C, H, W = 3, 320, 320
SIGMAS = [1.0, 0.75, 0.5, 0.25, 0.0]


def make_target(seed=0):
    g = torch.Generator().manual_seed(seed)
    return torch.randn(C, H, W, generator=g) * 0.1


def biased_predictor(x0, seed=1, amplitude=1.0):
    """Flow-matching velocity toward x0 plus a per-window constant bias."""
    rng = np.random.default_rng(seed)
    biases = {}

    def predict(x_win, y, x, sigma):
        if (y, x) not in biases:
            biases[(y, x)] = torch.tensor(rng.normal(0, amplitude, C), dtype=x_win.dtype)[:, None, None]
        h, w = x_win.shape[1:]
        target = x0[:, y : y + h, x : x + w] + biases[(y, x)]
        return (x_win - target) / sigma

    return predict


def to_image(t):
    return t.permute(1, 2, 0).numpy()


def test_oracle_predictor_recovers_target_exactly():
    x0 = make_target()
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(5))
    oracle = lambda xw, y, x, s: (xw - x0[:, y : y + xw.shape[1], x : x + xw.shape[2]]) / s  # noqa: E731
    out = joint_denoise(noise, SIGMAS, two_grids(H, W), oracle)
    assert torch.allclose(out, x0, atol=1e-5)


def test_independent_tiles_leave_seams_joint_does_not():
    x0 = make_target()
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(5))
    lines = [128, 256]  # tile borders of the independent baseline

    tiled = independent_tiles(noise, SIGMAS, 128, biased_predictor(x0))
    joint = joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0))

    tiled_ratio = seam_ratio_lines(to_image(tiled), lines, lines)
    # For the joint result, check every edge of every window in both grids
    edges = sorted({p for g in two_grids(H, W) for y, x in g for p in (y, y + WIN, x, x + WIN)} - {0, H, W})
    joint_ratio = seam_ratio_lines(to_image(joint), edges, edges)
    reference = seam_ratio_lines(to_image(x0), edges, edges)

    assert tiled_ratio > 2.0, tiled_ratio
    assert joint_ratio < reference + 0.15, (joint_ratio, reference)


def test_same_seed_same_output():
    x0 = make_target()
    runs = []
    for _ in range(2):
        noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(9))
        runs.append(joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0, seed=3)))
    assert torch.equal(runs[0], runs[1])
