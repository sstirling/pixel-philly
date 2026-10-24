"""10_repaint_water.py for a region drawn next to an already drawn area.

North Philly's run draws 198 frames; the 41 frames of its lattice that
overlap South Philly (the known band) are South's and were never decoded.
"""

import importlib.util

import numpy as np
from PIL import Image

from pixelphilly import waterpaint
from pixelphilly.projection import REPO_ROOT, Frame
from pixelphilly.regions import mosaic_origin, ripple_offset

SIZE = 16


def _script():
    spec = importlib.util.spec_from_file_location("repaint", REPO_ROOT / "scripts" / "10_repaint_water.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _areas():
    # Two areas on one screen lattice. Known ("south") lattice starts at
    # global cell (0, 2); the new area ("north") at (1, 0); they share cells
    # in global row 2
    south = [Frame(col=c, row=r, x0=c * SIZE, y0=(r + 2) * SIZE, size=SIZE) for r in range(2) for c in range(3)]
    north = [Frame(col=c, row=r, x0=(c + 1) * SIZE, y0=r * SIZE, size=SIZE) for r in range(3) for c in range(2)]
    return south, north


def test_single_area_offset_is_zero():
    south, _ = _areas()
    assert ripple_offset(south, None) == (0, 0)
    assert ripple_offset(south, south) == (0, 0)


def test_same_screen_pixel_gets_the_same_ripple_in_both_areas():
    south, north = _areas()
    ox, oy = ripple_offset(north, south)
    (nx, ny), (sx, sy) = mosaic_origin(north), mosaic_origin(south)
    assert (ox, oy) == (nx - sx, ny - sy) == (SIZE, -2 * SIZE)
    # A patch at screen (x, y): north mosaic coords (x - nx, y - ny), south (x - sx, y - sy)
    x, y, w, h = 1 * SIZE + 3, 2 * SIZE + 5, 400, 300  # ripples are sparse: a patch big enough to hold some
    north_r = waterpaint.ripple_mask(w, h, x - nx + ox, y - ny + oy)
    south_r = waterpaint.ripple_mask(w, h, x - sx, y - sy)
    assert north_r.any() and np.array_equal(north_r, south_r)
    # Without the offset the phases differ (what the join would have shown)
    assert not np.array_equal(waterpaint.ripple_mask(w, h, x - nx, y - ny), south_r)


def test_reader_falls_back_to_the_known_area_for_band_cells(tmp_path):
    rp = _script()
    south, north = _areas()
    shared = {f.name: k.name for f in north for k in south if (f.x0, f.y0) == (k.x0, k.y0)}
    assert len(shared) == 2
    (tmp_path / "redraws").mkdir()
    (tmp_path / "known").mkdir()
    for f in north:
        if f.name not in shared:
            Image.new("RGB", (SIZE, SIZE), (0, 0, 200)).save(tmp_path / "redraws" / f"{f.name}.png")
    for k in south:
        Image.new("RGB", (SIZE, SIZE), (200, 0, 0)).save(tmp_path / "known" / f"{k.name}.png")
    paths = rp.redraw_paths(north, tmp_path / "redraws", shared, tmp_path / "known")
    reader = rp.FrameReader(tmp_path / "redraws", north, SIZE, paths=paths)
    band = next(f for f in north if f.name in shared)
    new = next(f for f in north if f.name not in shared)
    assert tuple(reader.frame(band.col, band.row)[0, 0]) == (200, 0, 0), "band cell reads South's finished frame"
    assert tuple(reader.frame(new.col, new.row)[0, 0]) == (0, 0, 200)
    # A region straddling both reads both
    reg = reader.region(band.col * SIZE - 4, band.row * SIZE - 4, 8, 8)
    assert {tuple(p) for p in reg.reshape(-1, 3)} >= {(200, 0, 0)}


def test_frames_without_a_redraw_are_skipped(tmp_path):
    rp = _script()
    south, north = _areas()
    shared = {f.name: k.name for f in north for k in south if (f.x0, f.y0) == (k.x0, k.y0)}
    (tmp_path / "redraws").mkdir()
    for f in north:
        if f.name not in shared:
            Image.new("RGB", (SIZE, SIZE)).save(tmp_path / "redraws" / f"{f.name}.png")
    todo = rp.frames_to_write(north, tmp_path / "redraws")
    assert {f.name for f in todo} == {f.name for f in north} - set(shared)


def test_known_frames_are_placed_in_this_areas_mosaic():
    # The band repaint's halo reaches into South-only frames beyond North's
    # lattice; they must sit at their screen position in North's mosaic,
    # which can mean negative col/row
    from pixelphilly.regions import place_frames

    south, north = _areas()
    placed = place_frames(south, north)
    ox, oy = mosaic_origin(north)
    for k, p in zip(south, placed):
        assert (p.col * SIZE + ox, p.row * SIZE + oy) == (k.x0, k.y0)
        assert p.name == k.name
    assert min(p.col for p in placed) == -1


def test_band_context_paths_choose_the_owner_of_each_cell(tmp_path):
    # Band frames are repainted from South's PRE-repaint redraws; North-only
    # cells give North's redraws; cells beyond North's lattice give South's
    rp = _script()
    south, north = _areas()
    shared = {f.name: k.name for f in north for k in south if (f.x0, f.y0) == (k.x0, k.y0)}
    ctx = rp.band_context(north, south, shared, tmp_path / "n", tmp_path / "s")
    by_pos = {(f.col, f.row): ctx.paths[f.name] for f in ctx.frames}
    band = next(f for f in north if f.name in shared)
    new = next(f for f in north if f.name not in shared)
    assert by_pos[(band.col, band.row)] == tmp_path / "s" / f"{shared[band.name]}.png"
    assert by_pos[(new.col, new.row)] == tmp_path / "n" / f"{new.name}.png"
    south_only = [k for k in south if k.name not in shared.values()]
    assert len(ctx.frames) == len(north) + len(south_only)


def test_band_context_with_two_known_areas_first_listed_owns_cells_beyond(tmp_path):
    # West's band repaint reads South and North; a cell both have beyond
    # West's lattice comes from South (first listed), and band cells come
    # from their owner
    rp = _script()

    def lat(cells, c0, r0):
        return [Frame(col=c - c0, row=r - r0, x0=c * SIZE, y0=r * SIZE, size=SIZE) for c, r in cells]

    south = lat([(c, 2) for c in range(4)], 0, 2)
    north = lat([(c, r) for r in (1, 2) for c in range(1, 4)], 1, 1)
    west = lat([(3, 1), (3, 2), (4, 1), (4, 2)], 3, 1)
    owners = {f.name: ("south" if f.y0 == 2 * SIZE else "north", "k") for f in west if f.x0 == 3 * SIZE}
    ctx = rp.band_context_multi(west, [("south", south), ("north", north)], owners,
                                lambda f: tmp_path / "west" / f.name, lambda a, n: tmp_path / a / n)
    by_xy = {(f.x0 // SIZE, f.y0 // SIZE): ctx.paths[f.name] for f in ctx.frames}
    assert by_xy[(3, 2)] == tmp_path / "south" / "k" and by_xy[(3, 1)] == tmp_path / "north" / "k"
    assert by_xy[(2, 2)].parent.name == "south", "a cell South and North share beyond the lattice is South's"
    assert by_xy[(1, 1)].parent.name == "north" and by_xy[(4, 1)].parent.name == "west"
