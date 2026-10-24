"""The alignment check must ignore 1 px edge rounding but catch real offsets."""

import importlib.util

import numpy as np

from pixelphilly.projection import REPO_ROOT

spec = importlib.util.spec_from_file_location("align", REPO_ROOT / "scripts" / "09_check_alignment.py")
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)


def rowhouses():
    """Dense rowhouse block: many narrow buildings, lots of vertical edges."""
    m = np.zeros((512, 512), bool)
    for x in range(20, 490, 14):
        m[100:400, x : x + 11] = True
    return m


def test_one_pixel_edge_rounding_passes():
    # North Philly (Oct. 23): the Python rasterizer draws each vertical wall
    # 1 px wider than WebGL. In a dense rowhouse frame that alone gave IoU
    # 0.966 with zero shift
    expected = rowhouses()
    rendered = expected.copy()
    rendered[:, 1:] &= expected[:, :-1]  # WebGL drops each shape's left column
    raw = np.count_nonzero(rendered & expected) / np.count_nonzero(rendered | expected)
    assert raw < 0.97  # the raw IoU would fail
    assert align.tolerant_iou(rendered, expected) > 0.99


def test_real_offset_still_fails():
    expected = rowhouses()
    rendered = np.roll(expected, 4, axis=1)  # a 4 px misregistration
    assert align.tolerant_iou(rendered, expected) < 0.9
