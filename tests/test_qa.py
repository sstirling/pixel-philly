import numpy as np
import pytest
from PIL import Image

from pixelphilly.qa import flat_share, registration_shift, seam_ratio


def noisy(h, w, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(100, 130, (h, w, 3)).astype(np.uint8)


def test_seam_ratio_near_one_without_seams():
    assert seam_ratio(noisy(256, 256), 64) == pytest.approx(1.0, abs=0.05)


def test_seam_ratio_high_with_tile_offsets():
    img = noisy(256, 256).astype(int)
    # Checkerboard of tile brightness: every border is a 30-level step, three
    # times the ~10-level noise jump between ordinary neighbors
    for r in range(4):
        for c in range(4):
            if (r + c) % 2:
                img[r * 64 : (r + 1) * 64, c * 64 : (c + 1) * 64] += 30
    assert seam_ratio(np.clip(img, 0, 255).astype(np.uint8), 64) > 2.0


def test_flat_share_extremes():
    flat = np.full((50, 50, 3), 120, np.uint8)
    assert flat_share(flat) == 1.0
    rng = np.random.default_rng(1)
    photo = rng.integers(0, 255, (50, 50, 3)).astype(np.uint8)
    assert flat_share(photo) < 0.01


def test_registration_shift_recovers_known_offset():
    rng = np.random.default_rng(2)
    base = (rng.random((256, 256)) > 0.97).astype(np.uint8) * 255
    a = Image.fromarray(base)
    b = Image.fromarray(np.roll(base, (5, -7), axis=(0, 1)))
    assert registration_shift(a, b) == (7, -5)
    assert registration_shift(a, a) == (0, 0)


def test_local_seam_ratio_ignores_global_content_but_sees_seams():
    from pixelphilly.qa import seam_ratio_local

    img = noisy(256, 256).astype(int)
    # A busy left half and a quiet right half: content, not a seam
    img[:, :128] += np.random.default_rng(3).integers(0, 60, (256, 128, 3))
    clean = np.clip(img, 0, 255).astype(np.uint8)
    assert seam_ratio_local(clean, [64, 192], [64, 192]) == pytest.approx(1.0, abs=0.15)
    seamed = img.copy()
    seamed[:, 64:] += 40  # a hard step at x = 64
    seamed[64:, :] += 40  # and at y = 64
    assert seam_ratio_local(np.clip(seamed, 0, 255).astype(np.uint8), [64], [64]) > 2.0
