"""Image quality measures used across the pipeline.

seam_ratio and flat_share follow the checks described in the tiny.london
write-up (https://tiny.london/how/); registration_shift is the phase
correlation used to catch redraws that drift off the render's geometry.
"""

import numpy as np
from PIL import Image, ImageFilter


def seam_ratio_lines(img: np.ndarray, cols, rows) -> float:
    """Mean color jump across the given boundary lines / mean jump elsewhere.

    `cols` are x positions b where a vertical boundary falls between pixel
    columns b-1 and b; `rows` likewise for horizontal boundaries. About 1.0
    means the lines are invisible; well above 1 means seams. Jumps are mean
    absolute differences between adjacent pixels, averaged over channels.
    """
    m = img.astype(float)
    if m.ndim == 2:
        m = m[..., None]
    dx = np.abs(np.diff(m, axis=1)).mean(axis=2)
    dy = np.abs(np.diff(m, axis=0)).mean(axis=2)
    bx = [b - 1 for b in cols]
    by = [b - 1 for b in rows]
    seam = np.concatenate([dx[:, bx].ravel(), dy[by, :].ravel()])
    keep_x = np.ones(dx.shape[1], bool)
    keep_x[bx] = False
    keep_y = np.ones(dy.shape[0], bool)
    keep_y[by] = False
    other = np.concatenate([dx[:, keep_x].ravel(), dy[keep_y, :].ravel()])
    return float(seam.mean() / other.mean())


def seam_ratio(mosaic: np.ndarray, tile: int) -> float:
    """seam_ratio_lines with boundaries every `tile` pixels (frame borders)."""
    cols = list(range(tile, mosaic.shape[1], tile))
    rows = list(range(tile, mosaic.shape[0], tile))
    return seam_ratio_lines(mosaic, cols, rows)


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


def seam_ratio_local(img: np.ndarray, cols, rows, band: int = 16) -> float:
    """Like seam_ratio_lines, but each boundary line is compared with the
    lines up to `band` px on either side of it instead of the whole image.

    With few boundary lines, the global version is swayed by content that
    happens to sit on a line (one building edge on a window border read as a
    "seam" in the Phase D crop test). Comparing against immediate neighbors
    cancels most of that. Returns the median per-line ratio; about 1.0 means
    no seam.
    """
    m = img.astype(float)
    if m.ndim == 2:
        m = m[..., None]
    px = np.abs(np.diff(m, axis=1)).mean(axis=(0, 2))  # jump between col b-1 and b at index b-1
    py = np.abs(np.diff(m, axis=0)).mean(axis=(1, 2))
    ratios = []
    for prof, lines in ((px, cols), (py, rows)):
        for b in lines:
            i = b - 1
            lo, hi = max(0, i - band), min(len(prof), i + band + 1)
            nb = np.r_[prof[lo : max(lo, i - 1)], prof[min(hi, i + 2) : hi]]
            if len(nb) and nb.mean() > 0:
                ratios.append(prof[i] / nb.mean())
    return float(np.median(ratios))


def alignment_failed(row: dict) -> bool:
    """The alignment check's verdict on one frame of
    output/<area>/masks/alignment_report.json (scripts/09_check_alignment.py;
    the region runner's gate uses the same rule).

    Frames that are mostly river carry too few building pixels for the
    shift search to mean anything; only frames with real content are
    judged. On sparse frames the search can also tie between offsets while
    the overlap is near perfect (downtown frame_23_09: IoU 0.995, "shift"
    -4,-2); a real 4 px offset would pull IoU well below 0.99, so a shift
    only fails a frame whose IoU is also under 0.99. Judged on the 1 px
    tolerant IoU (edge rounding isn't misalignment); the raw IoU stays in
    the report."""
    dx, dy = row["best_shift_px"]
    tiou = row["iou_1px"]
    shifted = max(abs(dx), abs(dy)) > 2 and tiou < 0.99
    return row["building_px"] > 5000 and (tiou < 0.97 or shifted)
