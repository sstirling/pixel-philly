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


def l_shaped_active():
    """An L-shaped region inside the canvas; the rest is inactive."""
    active = np.zeros((H, W), bool)
    active[:, :160] = True
    active[160:, :] = True
    return active


def test_active_mask_leaves_inactive_cells_untouched():
    from pixelphilly.windows import active_grids

    x0 = make_target()
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(5))
    active = l_shaped_active()
    grids = active_grids(two_grids(H, W), active)
    oracle = lambda xw, y, x, s: (xw - x0[:, y : y + xw.shape[1], x : x + xw.shape[2]]) / s  # noqa: E731
    out = joint_denoise(noise, SIGMAS, grids, oracle, active=torch.from_numpy(active))
    act = torch.from_numpy(active)
    # Active cells are fully denoised; inactive cells far from the region keep their noise
    assert torch.allclose(out[:, act], x0[:, act], atol=1e-5)
    far = ~torch.from_numpy(np.pad(active, 0))
    far[:, :160 + WIN] = False
    far[160 - WIN :, :] = False
    assert torch.equal(out[:, far], noise[:, far])


def test_active_mask_still_seamless():
    from pixelphilly.windows import active_grids

    x0 = make_target()
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(5))
    active = l_shaped_active()
    grids = active_grids(two_grids(H, W), active)
    joint = joint_denoise(noise, SIGMAS, grids, biased_predictor(x0), active=torch.from_numpy(active))
    edges = sorted({p for g in grids for y, x in g for p in (y, y + WIN, x, x + WIN)} - {0, H, W})
    # Measure only inside the active region (the bottom band is active across the full width)
    band = to_image(joint)[160:, :]
    ref = to_image(x0)[160:, :]
    cols = [e for e in edges if 0 < e < W]
    assert seam_ratio_lines(band, cols, []) < seam_ratio_lines(ref, cols, []) + 0.15


# --- Known-region conditioning: drawing a region next to an existing one ---

def band_mask(rows=100, ramp=8):
    """Known band along the top: 1 for rows < rows, ramping to 0 over `ramp`."""
    m = torch.zeros(H, W)
    m[:rows] = 1.0
    for k in range(ramp):
        m[rows + k] = 1.0 - (k + 1) / (ramp + 1)
    return m


def test_known_band_is_reproduced_exactly():
    # South Philly's drawn frames along the shared edge must come back
    # unchanged, so the merged map keeps South's pixels
    x0 = make_target()
    known = make_target(seed=7)  # a different, already-drawn image
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(5))
    mask = band_mask()
    out = joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0), known=(known, mask))
    full = mask == 1.0
    assert torch.allclose(out[:, full], known[:, full], atol=1e-6)


def test_ramp_leaves_no_hard_edge_at_the_band():
    # With an oracle model drawing x0 and a known band that is x0 + 1 (a
    # different tone), the transition spreads over the ramp: no row-to-row
    # jump bigger than one ramp step
    x0 = make_target()
    known = x0 + 1.0
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(5))
    oracle = lambda xw, y, x, s: (xw - x0[:, y : y + xw.shape[1], x : x + xw.shape[2]]) / s  # noqa: E731
    out = joint_denoise(noise, SIGMAS, two_grids(H, W), oracle, known=(known, band_mask(ramp=8)))
    offset = (out - x0).mean(dim=(0, 2))  # per-row tone offset
    jumps = (offset[1:] - offset[:-1]).abs()
    assert offset[:100].min() > 0.99 and offset[120:].abs().max() < 1e-4
    assert jumps.max() < 1.0 / 9 + 1e-3, float(jumps.max())


def test_no_known_region_changes_nothing():
    x0 = make_target()
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(9))
    a = joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0, seed=3))
    b = joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0, seed=3), known=None)
    assert torch.equal(a, b)


def test_start_none_or_noise_changes_nothing():
    x0 = make_target()
    noise = torch.randn(C, H, W, generator=torch.Generator().manual_seed(9))
    a = joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0, seed=3))
    b = joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0, seed=3), start=None)
    c = joint_denoise(noise, SIGMAS, two_grids(H, W), biased_predictor(x0, seed=3), start=noise.clone())
    assert torch.equal(a, b) and torch.equal(a, c)


def _repair(x0_cur, strip, predict, sigmas, k):
    """The repair pass as AreaSampler.joint_volume runs it: re-noise the
    finished canvas to sigmas[k] with fresh noise, then denoise the tail with
    every cell outside the strip held at x0_cur."""
    from pixelphilly.windows import active_grids

    noise2 = torch.randn(x0_cur.shape, generator=torch.Generator().manual_seed(1))
    s0 = sigmas[k]
    start = (1 - s0) * x0_cur + s0 * noise2
    fixed = (~strip).float()
    grids = active_grids(two_grids(H, W), strip.numpy())
    return joint_denoise(noise2, sigmas[k:], grids, predict, start=start, active=strip,
                         known=(x0_cur, fixed))


def test_repair_redraws_only_the_strip():
    # Region join repair (tiny.london's repair step, SDEdit-style): South's
    # cells and the new interior stay exactly as drawn
    x0_cur = make_target(seed=11)
    strip = torch.zeros(H, W, dtype=torch.bool)
    strip[150:175] = True  # 25 cells below a join at row 150
    out = _repair(x0_cur, strip, biased_predictor(make_target(), seed=4), [1.0, 0.6, 0.4, 0.2, 0.0], 1)
    assert torch.equal(out[:, ~strip], x0_cur[:, ~strip])
    assert not torch.allclose(out[:, strip], x0_cur[:, strip])


def test_repair_pulls_the_strip_toward_both_sides():
    # The new side was drawn a tone darker than the known side. In the
    # repair the model sees both, so a predictor that draws the tone of the
    # window's own surroundings (fixed cells it can see) closes part of the gap
    known_tone, new_tone = 1.0, 0.0
    x0_cur = torch.full((C, H, W), new_tone)
    x0_cur[:, :150] = known_tone
    strip = torch.zeros(H, W, dtype=torch.bool)
    strip[150:175] = True

    def context(x_win, y, x, sigma):
        win = x0_cur[:, y : y + x_win.shape[1], x : x + x_win.shape[2]]
        target = torch.full_like(x_win, float(win.mean()))  # the tone the window sees around it
        return (x_win - target) / sigma

    out = _repair(x0_cur, strip, context, [1.0, 0.6, 0.4, 0.2, 0.0], 1)
    row = out.mean(dim=(0, 2))
    # The strip takes a tone between the two sides, so the original hard
    # 1 -> 0 edge becomes two smaller steps
    assert new_tone + 0.1 < float(row[160]) < known_tone - 0.1
    jumps = (row[141:185] - row[140:184]).abs()
    assert float(jumps.max()) < 0.75 * (known_tone - new_tone)
