import numpy as np
import pytest

from pixelphilly.windows import SHIFT, STRIDE, WIN, grid, positions, tent, two_grids, weight_sum

# The Old City canvas: 6,144 x 5,120 px = 768 x 640 latent cells
H, W = 640, 768


@pytest.mark.parametrize("offset", [0, SHIFT])
def test_grid_covers_every_cell_with_positive_weight(offset):
    g = grid(H, W, offset)
    total = weight_sum(H, W, g)
    assert total.min() > 0, "some latent cell has zero total weight"


def test_offsets_are_even_and_in_bounds():
    for g in two_grids(H, W):
        for y, x in g:
            assert y % 2 == 0 and x % 2 == 0
            assert 0 <= y <= H - WIN and 0 <= x <= W - WIN


def test_grids_differ_so_edges_move_between_steps():
    a, b = two_grids(H, W)
    assert set(a) != set(b)


def test_regular_interior_weights_sum_to_one():
    # Away from clamped edge windows, ramps equal the overlap, so the tents
    # of a regular grid sum to exactly 1 along each axis
    starts = range(0, 5 * STRIDE, STRIDE)
    total = np.zeros(5 * STRIDE + WIN)
    for s in starts:
        total[s : s + WIN] += tent()
    interior = total[WIN : 4 * STRIDE]
    assert np.allclose(interior, 1.0)


def test_edge_windows_have_no_ramp_at_canvas_edge():
    t = tent(at_start=True)
    assert t[0] == 1.0 and t[-1] < 0.05


def test_positions_reject_canvas_smaller_than_window():
    with pytest.raises(ValueError):
        positions(100)
