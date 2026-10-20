"""Image quality measures used across the pipeline.

seam_ratio and flat_share follow the checks described in the tiny.london
write-up (https://tiny.london/how/); registration_shift is the phase
correlation used to catch redraws that drift off the render's geometry.
"""

import numpy as np
from PIL import Image, ImageFilter


def seam_ratio(mosaic: np.ndarray, tile: int) -> float:
    """Mean color jump across tile borders / mean jump everywhere else.

    About 1.0 means borders are invisible; well above 1 means seams. Jumps
    are mean absolute RGB differences between horizontally and vertically
    adjacent pixels.
    """
    m = mosaic.astype(float)
    dx = np.abs(np.diff(m, axis=1)).mean(axis=2)
    dy = np.abs(np.diff(m, axis=0)).mean(axis=2)
    bx = [tile * c - 1 for c in range(1, m.shape[1] // tile)]
    by = [tile * r - 1 for r in range(1, m.shape[0] // tile)]
    seam = np.concatenate([dx[:, bx].ravel(), dy[by, :].ravel()])
    keep_x = np.ones(dx.shape[1], bool)
    keep_x[bx] = False
    keep_y = np.ones(dy.shape[0], bool)
    keep_y[by] = False
    other = np.concatenate([dx[:, keep_x].ravel(), dy[keep_y, :].ravel()])
    return float(seam.mean() / other.mean())


def flat_share(img: np.ndarray, tol: int = 6) -> float:
    """Share of pixels whose whole 3x3 neighborhood is within `tol` levels.

    Pixel art is mostly flat fills; a photo is not. tiny.london used this to
    reject redraws that were really the photo with a filter on it.
    """
    a = img.astype(int)
    c = a[1:-1, 1:-1]
    ok = np.ones(c.shape[:2], bool)
    h, w = a.shape[:2]
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            n = a[1 + dy : h - 1 + dy, 1 + dx : w - 1 + dx]
            ok &= np.abs(n - c).max(axis=2) <= tol
    return float(ok.mean())


def _edges(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES), float)
    return (a - a.mean()) / (a.std() + 1e-9)


def registration_shift(reference: Image.Image, other: Image.Image):
    """(dx, dy) translation of `other` relative to `reference`, by phase
    correlation of edge maps. (0, 0) means the redraw sits on the render."""
    a, b = _edges(reference), _edges(other)
    f = np.fft.fft2(a) * np.conj(np.fft.fft2(b))
    r = np.fft.ifft2(f / (np.abs(f) + 1e-9)).real
    y, x = np.unravel_index(r.argmax(), r.shape)
    h, w = a.shape
    return int((x + w // 2) % w - w // 2), int((y + h // 2) % h - h // 2)
