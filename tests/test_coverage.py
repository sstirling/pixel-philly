"""Coverage-gap check: every global lattice cell that sees city ground must
belong to some region (pixelphilly.coverage). Synthetic city polygons."""

from shapely.geometry import box

from pixelphilly.coverage import city_cells, frames_by_cell, shared_cells, uncovered_cells
from pixelphilly.projection import IsoCamera, LocalFrame, frame_lattice, load_config

CFG = load_config("oldcity")
# A synthetic 4 x 4 km "city", larger than Old City so a missing strip is
# wider than a frame
W, S, E, N = -75.20, 39.93, -75.153, 39.966
SIZE = CFG["camera"]["frame_px"]
H = CFG["max_height_m"]
FRAME = LocalFrame([W, S, E, N])
CAM = IsoCamera.from_config(CFG)
CITY = box(W, S, E, N)


def _region(bbox):
    """A region's frames: its own bbox's lattice, kept where it sees bbox ∩ city."""
    return frame_lattice(CAM, FRAME, bbox, SIZE, H, ground=box(*bbox).intersection(CITY))


def test_city_cells_are_the_lattice_cells_that_see_city_ground():
    cells = city_cells(CAM, FRAME, CITY, SIZE)
    assert cells and all(0 < f <= 1 for f in cells.values())
    # The plain lattice at height 0 over the same box has exactly those cells
    ground = {(f.x0 // SIZE, f.y0 // SIZE) for f in frame_lattice(CAM, FRAME, [W, S, E, N], SIZE, 0.0, clip=True)}
    assert set(cells) == ground


def test_two_halves_leave_no_gap():
    mid = (W + E) / 2
    regions = {"w": _region([W, S, mid, N]), "e": _region([mid, S, E, N])}
    assert uncovered_cells(city_cells(CAM, FRAME, CITY, SIZE), regions) == {}


def test_a_missing_strip_is_reported():
    a, b = W + (E - W) * 0.3, W + (E - W) * 0.7
    regions = {"w": _region([W, S, a, N]), "e": _region([b, S, E, N])}
    gap = uncovered_cells(city_cells(CAM, FRAME, CITY, SIZE), regions)
    assert gap
    # Every gap cell sees ground in the missing strip
    strip = frame_lattice(CAM, FRAME, [a, S, b, N], SIZE, 0.0, clip=True)
    assert set(gap) <= {(f.x0 // SIZE, f.y0 // SIZE) for f in strip}


def test_shared_cells_between_neighbors():
    mid = (W + E) / 2
    w, e = _region([W, S, mid, N]), _region([mid, S, E, N])
    sh = shared_cells(frames_by_cell(w), frames_by_cell(e))
    # Tall things near the boundary are seen from both sides' frames
    assert sh and sh <= set(frames_by_cell(w)) and sh <= set(frames_by_cell(e))
