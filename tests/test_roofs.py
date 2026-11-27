"""Front slopes on postwar rows (pixelphilly.roofs; docs/building_age_plan.md, Phase B)."""

import numpy as np
import pytest
from shapely.geometry import Polygon, box

from pixelphilly import roofs

# A 5 m wide, 12 m deep rowhouse whose front faces south (-n)
ROW = box(0, 0, 5, 12)
SOUTH = (0.0, -1.0)


def test_front_edge_picks_the_wall_facing_the_street():
    (p0, p1) = roofs.front_edge(ROW, SOUTH)
    ys = {round(p0[1], 6), round(p1[1], 6)}
    assert ys == {0.0}
    assert abs(abs(p1[0] - p0[0]) - 5) < 1e-6


def test_front_edge_none_when_no_wall_faces_that_way():
    tri = Polygon([(0, 0), (10, 0), (0, 10)])
    assert roofs.front_edge(tri, (1.0, 1.0)) is not None  # the hypotenuse faces northeast
    assert roofs.front_edge(box(0, 0, 5, 12), (0.7071, 0.7071)) is None  # 45 degrees off every wall


def test_short_front_edge_is_refused():
    assert roofs.front_slope(box(0, 0, 2, 12), 9.0, SOUTH, 1) is None


def test_front_slope_geometry():
    fs = roofs.front_slope(ROW, 9.0, SOUTH, 1)
    assert fs is not None
    d, drop, over = roofs.FRONT_SLOPE_DEPTH_M, roofs.FRONT_SLOPE_DROP_M, roofs.FRONT_SLOPE_OVERHANG_M
    # The strip is the front `depth` meters of the footprint; the rest stays full height
    assert fs["strip"].equals_exact(box(0, 0, 5, d), 1e-6) or abs(fs["strip"].symmetric_difference(box(0, 0, 5, d)).area) < 1e-6
    assert abs(fs["main"].area - 5 * (12 - d)) < 1e-6
    assert abs(fs["strip_h"] - (9.0 - drop)) < 1e-9
    pts = np.array([p for tri in fs["facets"] for p in tri])
    assert len(fs["facets"]) == 2
    # From the overhang (lowest) to the inner edge, which meets the main roof at full height
    assert abs(pts[:, 2].max() - 9.0) < 1e-9
    assert abs(pts[:, 2].min() - (9.0 - drop - over * drop / d)) < 1e-9
    assert abs(pts[:, 1].min() - (-over)) < 1e-9 and abs(pts[:, 1].max() - d) < 1e-9
    assert abs(pts[:, 0].min()) < 1e-9 and abs(pts[:, 0].max() - 5) < 1e-9
    # Every facet faces up (and toward the street)
    for a, b, c in fs["facets"]:
        nrm = np.cross(np.subtract(b, a), np.subtract(c, a))
        assert nrm[2] > 0 and nrm[1] < 0
    assert len(fs["color"]) == 3


def test_slope_is_continuous_at_the_wall():
    """The facet passes through the strip's top edge at the wall line, so
    the strip's wall and the slope meet with no gap or step."""
    fs = roofs.front_slope(ROW, 9.0, SOUTH, 1)
    (a, b, c), _ = fs["facets"]
    # z along the depth direction (n) is linear: z(n) = h - drop + n * drop / depth
    d, drop = roofs.FRONT_SLOPE_DEPTH_M, roofs.FRONT_SLOPE_DROP_M
    for p in (a, b, c):
        assert abs(p[2] - (9.0 - drop + p[1] * drop / d)) < 1e-9


def test_tall_or_low_buildings_are_refused():
    assert roofs.front_slope(ROW, roofs.MAX_H_M + 1, SOUTH, 1) is None
    assert roofs.front_slope(ROW, 2.5, SOUTH, 1) is None


def test_outer_footprint_rejects_inner_edges():
    """A LiDAR part's edge that is an internal step (not on the building's
    outline) is not a street wall."""
    outer = box(0, -3, 5, 12)  # the building reaches 3 m farther toward the street
    assert roofs.front_slope(ROW, 9.0, SOUTH, 1, outer=outer) is None
    assert roofs.front_slope(ROW, 9.0, SOUTH, 1, outer=ROW) is not None


def test_color_is_stable_and_from_the_palette():
    a = roofs.front_slope(ROW, 9.0, SOUTH, "123-0")["color"]
    assert a == roofs.front_slope(ROW, 9.0, SOUTH, "123-0")["color"]
    base = [tuple(c) for c in roofs.SHINGLE_PALETTE]
    assert any(max(abs(x - y) for x, y in zip(a, c)) <= roofs.SHINGLE_JITTER for c in base)


@pytest.mark.parametrize("angle", [0, 33, 90, 147, 260])
def test_rotated_rows(angle):
    """Rows run every which way: the strip is always `depth` deep."""
    from shapely import affinity

    poly = affinity.rotate(ROW, angle, origin=(0, 0))
    t = np.radians(angle)
    d = (float(np.sin(t)), float(-np.cos(t)))  # SOUTH rotated
    fs = roofs.front_slope(poly, 9.0, d, 7)
    assert fs is not None
    assert abs(fs["strip"].area - 5 * roofs.FRONT_SLOPE_DEPTH_M) < 1e-6


def test_polys_round_trip():
    fs = roofs.front_slope(ROW, 9.0, SOUTH, 1)
    polys = roofs.to_polys(fs["strip"])
    assert len(polys) == 1 and len(polys[0]) == 1
    assert abs(Polygon(polys[0][0]).area - fs["strip"].area) < 1e-6


# --- scene builder, alignment check and headless render ----------------------

import importlib.util  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from PIL import Image, ImageFilter  # noqa: E402

from pixelphilly.projection import REPO_ROOT, IsoCamera, load_config  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_scene = _load("build_scene_roofs", "05_build_scene.py")
align = _load("align_roofs", "09_check_alignment.py")

SIZE = 256
GRAY = (128, 128, 128)
H = 9.0


def _row(direction, n=4):
    """n 5 x 12 m rowhouses side by side, fronts facing `direction` (S or N),
    marked for a front slope as attach_facades would."""
    out = []
    for i in range(n):
        g = box(i * 5.0 - 10, -6, i * 5.0 - 5, 6)
        out.append({"id": 100 + i, "h": H, "fixed_color": [150, 110, 95],
                    "polys": roofs.to_polys(g), "_front_slope": (direction, g)})
    return out


def test_add_front_slopes_cuts_marked_buildings_only():
    marked = _row(SOUTH, 2)
    plain = {"id": 7, "h": H, "polys": roofs.to_polys(box(30, 0, 35, 12))}
    out, facets, qa = build_scene.add_front_slopes({"front_slopes": ["ROW POST WAR"]}, marked + [plain])
    assert qa == {"front_slope_parts_marked": 2, "front_slope_parts_cut": 2, "front_slope_refused": {}}
    assert [b["id"] for b in out] == [100, "100-f", 101, "101-f", 7]
    assert len(facets) == 2 and set(facets[0]) == {"t", "c"}
    assert out[-1] is plain
    assert all("_front_slope" not in b for b in out)
    # LiDAR part ids keep the objectid first
    part = {**_row(SOUTH, 1)[0], "id": "5902-0"}
    out, _, _ = build_scene.add_front_slopes({"front_slopes": ["x"]}, [part])
    assert [b["id"] for b in out] == ["5902-0", "5902-f0"]
    # Written scene: private keys dropped, the cut pieces colored from the whole footprint
    (main, strip) = build_scene.colored(out, ground=None, cfg={})
    assert list(main) == ["id", "h", "color", "polys"] and strip["h"] == round(H - roofs.FRONT_SLOPE_DROP_M, 2)


def test_add_front_slopes_off_by_default():
    marked = _row(SOUTH, 2)
    out, facets, qa = build_scene.add_front_slopes({}, marked)
    assert out is marked and facets == [] and qa == {}


def test_scene_has_roof_facets_only_when_there_are_some():
    cfg = {"name": "t", "camera": {"frame_px": 64}}
    cam = IsoCamera(54.0, 45.0, 0.293)
    frame = SimpleNamespace(lon0=-75.1, lat0=39.9)
    ground = {"uv": ([0] * 6, [0] * 6), "extent_m": [0, 0, 1, 1]}
    args = (cfg, frame, cam, [], ground, "g.jpg", [], [])
    assert "roof_facets" not in build_scene.scene_dict(*args)
    assert "roof_facets" not in build_scene.scene_dict(*args, None, [])
    f = {"t": [[[0, 0, 1], [1, 0, 1], [0, 1, 1]]], "c": [1, 2, 3]}
    assert build_scene.scene_dict(*args, None, [f])["roof_facets"] == [f]


def test_facets_in_reach():
    f_in = {"t": [[[1, 1, 9], [2, 1, 9], [1, 2, 9]]], "c": [0, 0, 0]}
    f_out = {"t": [[[500, 1, 9], [502, 1, 9], [501, 2, 9]]], "c": [0, 0, 0]}
    assert build_scene.facets_in_reach([f_in, f_out], box(0, 0, 100, 100)) == [f_in]


@pytest.fixture(scope="module")
def slope_scenes():
    """A row of four on a flat gray aerial, plain and with front slopes,
    fronts facing south (toward the camera's side) and north."""
    root = REPO_ROOT / "output" / "_test_render_roofs"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    Image.new("RGB", (64, 64), GRAY).save(root / "ground.png")
    cfg = load_config("south_lidar")
    cam = IsoCamera.from_config(cfg)
    mpp = cam.meters_per_pixel
    sx, sy = cam.world_to_screen(0.0, 0.0, H / 2)
    half = SIZE / 2
    x0, y0 = float(sx) - half, float(sy) - half
    frame = {"name": "f", "col": 0, "row": 0, "left": x0 * mpp, "right": (x0 + SIZE) * mpp,
             "top": -y0 * mpp, "bottom": -(y0 + SIZE) * mpp}
    scene = {"name": "t", "camera": cam.three_js_params(3000.0), "meters_per_pixel": mpp, "frame_px": SIZE,
             "frames": [frame], "trees": [],
             "ground": {"image": "output/_test_render_roofs/ground.png", "extent_m": [-200, -200, 200, 200],
                        "uv_poly": {"u": [0.0025, 0, 0.5, 0, 0, 0], "v": [0, 0.0025, 0.5, 0, 0, 0]}}}
    out = {}
    for name, d in (("south", SOUTH), ("north", (0.0, 1.0))):
        row = _row(d)
        plain = build_scene.colored([{k: v for k, v in b.items() if k != "_front_slope"} for b in row], None, {})
        cut, facets, _ = build_scene.add_front_slopes({"front_slopes": ["x"]}, row)
        cut = build_scene.colored(cut, None, {})
        (root / f"{name}_plain.json").write_text(json.dumps({**scene, "buildings": plain}))
        (root / f"{name}_slope.json").write_text(json.dumps({**scene, "buildings": cut, "roof_facets": facets}))
        out[name] = SimpleNamespace(plain=plain, cut=cut, facets=facets)
    yield SimpleNamespace(root=root, cam=cam, x0=x0, y0=y0, rows=out)
    shutil.rmtree(root, ignore_errors=True)


def _render(rel, mode="color"):
    from pixelphilly.browser_render import Renderer

    with Renderer(f"output/_test_render_roofs/{rel}", SIZE) as r:
        return np.asarray(r.frame(0, mode)).astype(int)


@pytest.mark.parametrize("side", ["south", "north"])
def test_slope_mask_matches_projection(slope_scenes, side):
    t = slope_scenes
    r = t.rows[side]
    mask = _render(f"{side}_slope.json", "mask")[..., 0] > 127
    expected = align.rasterize(align.silhouettes(r.cut, t.cam, r.facets), {"x0": t.x0, "y0": t.y0}, SIZE)
    assert expected.sum() > 1000
    assert align.tolerant_iou(mask, expected) > 0.99


@pytest.mark.parametrize("side", ["south", "north"])
def test_slope_changes_only_the_front_roof_edge(slope_scenes, side):
    """Everything the cut changes lies within the top meter (and the
    overhang) of the street-side strip; the walls below and the rest of the
    roof render exactly as before."""
    t = slope_scenes
    r = t.rows[side]
    plain = _render(f"{side}_plain.json")
    slope = _render(f"{side}_slope.json")
    diff = np.abs(slope - plain).max(axis=2) > 6
    band = []
    for f in r.facets:
        pts = np.array([p for tri in f["t"] for p in tri])
        e0, e1, n0, n1 = pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()
        ring = [[e0, n0], [e1, n0], [e1, n1], [e0, n1]]
        band.append({"h": H, "z0": H - 1.0, "polys": [[ring]]})
    region = align.rasterize(align.silhouettes(band, t.cam), {"x0": t.x0, "y0": t.y0}, SIZE)
    near = np.asarray(Image.fromarray(region.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))) > 0
    assert diff.sum() > 30, "the slope shows"
    assert not (diff & ~near).any(), int((diff & ~near).sum())


def test_refusals_are_counted_by_reason():
    from collections import Counter

    why = Counter()
    roofs.front_slope(ROW, 40.0, SOUTH, 1, reasons=why)
    roofs.front_slope(box(0, 0, 2, 12), 9.0, SOUTH, 1, reasons=why)
    roofs.front_slope(ROW, 9.0, (0.7071, 0.7071), 1, reasons=why)
    assert why == {"height": 1, "short_wall": 1, "no_street_wall": 1}


def test_staircase_lidar_part_is_cut_along_the_city_outline():
    """Mayfair's streets run diagonally; LiDAR parts traced on the 0.5 m
    grid have stair-step fronts with no long edge. The street wall comes
    from the City footprint, and steps poking past it fall in the strip."""
    from shapely import affinity
    from shapely.geometry import box as b_

    outline = affinity.rotate(ROW, 36, origin=(0, 0))
    t = np.radians(36)
    d = (float(np.sin(t)), float(-np.cos(t)))
    # Rasterize the outline at 0.5 m: union of grid cells whose center is inside
    from shapely.geometry import Point
    from shapely.ops import unary_union

    xmin, ymin, xmax, ymax = outline.bounds
    cells = [b_(x, y, x + 0.5, y + 0.5) for x in np.arange(np.floor(xmin), xmax, 0.5)
             for y in np.arange(np.floor(ymin), ymax, 0.5) if outline.contains(Point(x + 0.25, y + 0.25))]
    stairs = unary_union(cells)
    fs = roofs.front_slope(stairs, 9.0, d, 1, outer=outline)
    assert fs is not None
    # Nothing of the main block is left in front of the slope's inner line
    nx, ny = d
    (x0, y0), _ = roofs.front_edge(outline, d)
    depth_in = [-((x - x0) * nx + (y - y0) * ny) for g in getattr(fs["main"], "geoms", [fs["main"]])
                for x, y in g.exterior.coords]
    assert min(depth_in) > roofs.FRONT_SLOPE_DEPTH_M - 0.05


def test_front_split_by_tiny_jogs_still_counts_as_one_wall():
    # 6317-like: a 4.6 m front drawn as 2.8 m + 0.8 m + 1 m pieces a few cm off line
    jog = Polygon([(0, 0), (2.8, 0.03), (3.6, 0.0), (4.6, 0.04), (4.6, 12), (0, 12)])
    assert roofs.front_slope(jog, 9.0, SOUTH, 1) is not None


def test_part_behind_the_front_gets_no_slope():
    outline = box(0, 0, 5, 12)
    rear = box(0, 6, 5, 12)
    why = __import__("collections").Counter()
    assert roofs.front_slope(rear, 9.0, SOUTH, 1, outer=outline, reasons=why) is None
    assert why == {"not_at_front": 1}


# --- Phase C: roof pitch and fitted gables and hips --------------------------

RES = 0.5
ORIGIN = (-20.0, 20.0)  # (west, north) of the synthetic grid
N = 80


def _grid(fp, zfun, noise=0.03, seed=0, ground=0.0):
    """A synthetic 0.5 m surface: zfun(e, n) inside the footprint, ground
    elsewhere, with a little noise; like the cached LiDAR grids."""
    from shapely import contains_xy

    rows, cols = np.indices((N, N))
    e = ORIGIN[0] + (cols + 0.5) * RES
    n = ORIGIN[1] - (rows + 0.5) * RES
    inside = contains_xy(fp, e, n)
    rng = np.random.default_rng(seed)
    dsm = np.where(inside, zfun(e, n), ground) + rng.normal(0, noise, (N, N))
    return dsm.astype(np.float32), np.full((N, N), ground, np.float32)


def _gable(fp_rect, eave, pitch_deg, along_long=True):
    """z of a gable over a rectangle (shapely box, maybe rotated)."""
    u, v, c, half_l, half_w = roofs.rect_frame(fp_rect)
    k = np.tan(np.radians(pitch_deg))

    def z(e, n):
        s = (e - c[0]) * u[0] + (n - c[1]) * u[1]
        t = (e - c[0]) * v[0] + (n - c[1]) * v[1]
        return eave + k * ((half_w - np.abs(t)) if along_long else (half_l - np.abs(s)))
    return z


def _hip(fp_rect, eave, pitch_deg):
    u, v, c, half_l, half_w = roofs.rect_frame(fp_rect)
    k = np.tan(np.radians(pitch_deg))

    def z(e, n):
        s = (e - c[0]) * u[0] + (n - c[1]) * u[1]
        t = (e - c[0]) * v[0] + (n - c[1]) * v[1]
        return eave + k * np.minimum(half_l - np.abs(s), half_w - np.abs(t))
    return z


HOUSE = box(-6, -4, 6, 4)  # 12 x 8 m


def test_roof_pitch_classes():
    from shapely import affinity

    fp = affinity.rotate(HOUSE, 20, origin=(0, 0))
    dsm, gnd = _grid(fp, _gable(fp, 6.0, 35))
    assert roofs.roof_pitch(fp, dsm, gnd, ORIGIN)["cls"] == "pitched"
    dsm, gnd = _grid(fp, lambda e, n: np.full_like(e, 7.0))
    assert roofs.roof_pitch(fp, dsm, gnd, ORIGIN)["cls"] == "flat"
    dsm, gnd = _grid(fp, lambda e, n: np.full_like(e, 1.0))
    assert roofs.roof_pitch(fp, dsm, gnd, ORIGIN)["cls"] == "low"


@pytest.mark.parametrize("angle", [0, 20, 63])
@pytest.mark.parametrize("kind", ["gable", "gable_cross", "hip"])
def test_roof_model_finds_the_right_form(kind, angle):
    from shapely import affinity

    fp = affinity.rotate(HOUSE, angle, origin=(0, 0))
    zf = {"gable": _gable(fp, 6.0, 35), "gable_cross": _gable(fp, 6.0, 35, along_long=False),
          "hip": _hip(fp, 6.0, 30)}[kind]
    dsm, gnd = _grid(fp, zf, seed=angle)
    m = roofs.roof_model(fp, dsm, gnd, ORIGIN, base=0.0)
    assert m is not None
    assert m["kind"] == kind
    assert abs(m["eave"] - 6.0) < 0.35
    assert abs(m["pitch_deg"] - (30 if kind == "hip" else 35)) < 4
    assert m["ridge"] > m["eave"] + 1.5


def test_roof_model_refuses_flat_roofs_trees_and_odd_shapes():
    from collections import Counter

    why = Counter()
    dsm, gnd = _grid(HOUSE, lambda e, n: np.full_like(e, 7.0))
    assert roofs.roof_model(HOUSE, dsm, gnd, ORIGIN, base=0.0, reasons=why) is None
    # A tree crown: bumpy, no plane fits
    rng = np.random.default_rng(3)
    dsm, gnd = _grid(HOUSE, lambda e, n: 6 + 3 * np.sin(e * 1.7) * np.cos(n * 1.3) + rng.normal(0, 0.8, e.shape))
    assert roofs.roof_model(HOUSE, dsm, gnd, ORIGIN, base=0.0, reasons=why) is None
    # An L-shaped footprint is not simple enough
    ell = Polygon([(-6, -4), (6, -4), (6, 4), (0, 4), (0, 0), (-6, 0)])
    dsm, gnd = _grid(ell, _gable(box(-6, -4, 6, 4), 6.0, 35))
    assert roofs.roof_model(ell, dsm, gnd, ORIGIN, base=0.0, reasons=why) is None
    assert set(why) <= {"flat", "no_fit", "not_simple"} and why["not_simple"] == 1 and sum(why.values()) == 3


def test_roof_model_tolerates_a_chimney_and_some_tree_cover():
    fp = HOUSE
    zf = _gable(fp, 6.0, 35)

    def z(e, n):
        out = zf(e, n)
        out = np.where((np.abs(e - 3) < 0.6) & (np.abs(n - 1) < 0.6), out + 2.0, out)  # chimney
        return np.where(e < -4.5, out + 2.5, out)  # a tree over one end
    dsm, gnd = _grid(fp, z)
    m = roofs.roof_model(fp, dsm, gnd, ORIGIN, base=0.0)
    assert m is not None and m["kind"] == "gable"


@pytest.mark.parametrize("kind", ["gable", "hip"])
def test_roof_mesh_is_closed_and_follows_the_model(kind):
    from shapely import affinity
    from shapely.ops import unary_union

    fp = affinity.rotate(Polygon([(-6, -4), (6, -4), (6, 4), (-6, 4.6)]), 15, origin=(0, 0))  # not quite a rectangle
    zf = _gable(fp, 6.0, 35) if kind == "gable" else _hip(fp, 6.0, 30)
    dsm, gnd = _grid(fp, zf)
    m = roofs.roof_model(fp, dsm, gnd, ORIGIN, base=0.0)
    assert m is not None and m["kind"] == kind
    mesh = roofs.roof_mesh(fp, m)
    v = np.array(mesh["v"])
    tris = [Polygon(v[list(t), :2]) for t in mesh["t"]]
    # The roof triangles tile the footprint exactly
    cover = unary_union(tris)
    assert abs(cover.area - fp.area) < 1e-3 * fp.area
    assert sum(t.area for t in tris) == pytest.approx(fp.area, rel=1e-3)
    # Every vertex sits on the model surface
    for e, n, z in v:
        assert z == pytest.approx(roofs.model_z(m, e, n), abs=0.02)
    # The ring: the footprint's outline with the ridge (and hip) crossings
    # added, so gable-end walls rise to the ridge; its z matches the roof
    ring = np.array(mesh["ring"])
    assert Polygon(ring).area == pytest.approx(fp.area, rel=1e-3)
    assert len(ring) > len(fp.exterior.coords) - 1
    for (e, n), z in zip(ring, mesh["ring_z"]):
        assert z == pytest.approx(roofs.model_z(m, e, n), abs=0.02)
    assert max(mesh["ring_z"]) == pytest.approx(max(v[:, 2]), abs=0.02) if kind == "gable" else True
    # Counter-clockwise ring (outward wall normals in render.js and 09)
    assert Polygon(ring).exterior.is_ccw


def _sides_roof(fp_rect, eave, pitch_deg, sides):
    """z = eave + k * distance to the nearest of the given rectangle sides
    ("s+", "s-", "t+", "t-")."""
    u, v, c, half_l, half_w = roofs.rect_frame(fp_rect)
    k = np.tan(np.radians(pitch_deg))

    def z(e, n):
        s = (e - c[0]) * u[0] + (n - c[1]) * u[1]
        t = (e - c[0]) * v[0] + (n - c[1]) * v[1]
        d = {"s+": half_l - s, "s-": half_l + s, "t+": half_w - t, "t-": half_w + t}
        return eave + k * np.minimum.reduce([d[x] for x in sides])
    return z


@pytest.mark.parametrize("n_sides", [1, 3])
def test_twin_halves_fit_with_the_party_wall_side_left_out(n_sides):
    """One half of a twin under a hip over the pair has eaves on three sides;
    under a gable whose ridge is the party wall, one side (a single slope)."""
    from shapely import affinity

    fp = affinity.rotate(box(-5, -4, 5, 4), 25, origin=(0, 0))
    _, _, _, half_l, half_w = roofs.rect_frame(fp)
    sides = ("t-",) if n_sides == 1 else ("s+", "s-", "t-")
    dsm, gnd = _grid(fp, _sides_roof(fp, 5.5, 28 if n_sides == 3 else 22, sides))
    m = roofs.roof_model(fp, dsm, gnd, ORIGIN, base=0.0)
    assert m is not None
    assert len(m["sides"]) == n_sides
    mesh = roofs.roof_mesh(fp, m)
    for e, n, z in mesh["v"]:
        assert z == pytest.approx(roofs.model_z(m, e, n), abs=0.02)
    # The party wall rises to the ridge along its whole length
    assert max(mesh["ring_z"]) == pytest.approx(m["ridge"], abs=0.05)


@pytest.mark.parametrize("shift", [(1.0, 0.0), (-0.5, 1.0)])
def test_roof_model_registers_a_shifted_lidar_roof(shift):
    """The LiDAR roof often sits up to a meter off the City footprint
    (misregistration, eave overhangs). The fit finds the shift first."""
    from shapely import affinity

    fp = affinity.rotate(HOUSE, 30, origin=(0, 0))
    moved = affinity.translate(fp, *shift)
    dsm, gnd = _grid(moved, _gable(moved, 6.0, 35))
    m = roofs.roof_model(fp, dsm, gnd, ORIGIN, base=0.0)
    assert m is not None and m["kind"] == "gable"
    assert abs(m["eave"] - 6.0) < 0.4
    assert np.hypot(*np.subtract(m["shift"], shift)) <= 0.5 + 1e-9


# --- Phase C: scene, alignment check and render ------------------------------

def _fitted_building(kind, angle=20, bid=500, offset=(0.0, 0.0)):
    from shapely import affinity

    fp = affinity.translate(affinity.rotate(HOUSE, angle, origin=(0, 0)), *offset)
    zf = _gable(fp, 6.0, 35) if kind == "gable" else _hip(fp, 6.0, 30)
    dsm, gnd = _grid(affinity.translate(fp, -offset[0], -offset[1]), lambda e, n: zf(e + offset[0], n + offset[1]))
    m = roofs.roof_model(affinity.translate(fp, -offset[0], -offset[1]), dsm, gnd, ORIGIN, base=0.0)
    assert m is not None and m["kind"] == kind
    m = {**m, "center": (m["center"][0] + offset[0], m["center"][1] + offset[1])}
    b = roofs.roof3d_building({"id": bid, "h": 9.0, "fixed_color": [150, 110, 95]}, fp, m)
    return b


def test_roof3d_building_record():
    b = _fitted_building("gable")
    assert b["id"] == "500-0"
    assert set(b["roof3d"]) == {"ring_z", "t", "v"}
    ring = b["polys"][0][0]
    assert len(ring) == len(b["roof3d"]["ring_z"])
    assert b["h"] == pytest.approx(max(v[2] for v in b["roof3d"]["v"]), abs=0.01)
    # Cornice bands (4, 32) would paint whole gable ends; they are dropped
    fac = {"s": 3, "f": 3.0, "p": 4.0, "b": 4 | 32 | 2, "w": [1, 2, 3], "g": [4, 5, 6]}
    m = roofs.roof_model(HOUSE, *_grid(HOUSE, _gable(HOUSE, 6.0, 35)), ORIGIN, base=0.0)
    b2 = roofs.roof3d_building({"id": 7, "h": 9.0, "facade": fac}, HOUSE, m)
    assert b2["facade"]["b"] == 2
    # colored() writes roof3d through, and nothing new for other buildings
    (out,) = build_scene.colored([b], ground=None, cfg={})
    assert out["roof3d"] == b["roof3d"]
    (plain,) = build_scene.colored([{"id": 1, "h": 5.0, "polys": [[[[0, 0], [1, 0], [1, 1]]]],
                                     "fixed_color": [1, 2, 3]}], ground=None, cfg={})
    assert "roof3d" not in plain


def test_alignment_silhouette_of_a_fitted_roof():
    """The projected outline follows the ridge: higher than the eave prism,
    lower than a box at ridge height."""
    cam = IsoCamera(54.0, 45.0, 0.293)
    b = _fitted_building("gable")
    (fitted,) = align.silhouettes([b], cam)
    eave = {"h": 6.0, "polys": b["polys"]}
    ridge = {"h": b["h"], "polys": b["polys"]}
    (lo,) = align.silhouettes([eave], cam)
    (hi,) = align.silhouettes([ridge], cam)
    assert lo.area < fitted.area < hi.area
    assert fitted.difference(hi.buffer(1e-6)).area < 1e-6


@pytest.fixture(scope="module")
def roof3d_scenes():
    root = REPO_ROOT / "output" / "_test_render_roof3d"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    Image.new("RGB", (64, 64), GRAY).save(root / "ground.png")
    cfg = load_config("south_lidar")
    cam = IsoCamera.from_config(cfg)
    mpp = cam.meters_per_pixel
    sx, sy = cam.world_to_screen(0.0, 0.0, 5.0)
    half = SIZE / 2
    x0, y0 = float(sx) - half, float(sy) - half
    frame = {"name": "f", "col": 0, "row": 0, "left": x0 * mpp, "right": (x0 + SIZE) * mpp,
             "top": -y0 * mpp, "bottom": -(y0 + SIZE) * mpp}
    scene = {"name": "t", "camera": cam.three_js_params(3000.0), "meters_per_pixel": mpp, "frame_px": SIZE,
             "frames": [frame], "trees": [],
             "ground": {"image": "output/_test_render_roof3d/ground.png", "extent_m": [-200, -200, 200, 200],
                        "uv_poly": {"u": [0.0025, 0, 0.5, 0, 0, 0], "v": [0, 0.0025, 0.5, 0, 0, 0]}}}
    blds = build_scene.colored([_fitted_building("gable", 20, 1, (-9, 0)), _fitted_building("hip", 70, 2, (9, 2))],
                               None, {})
    (root / "roof3d.json").write_text(json.dumps({**scene, "buildings": blds}))
    yield SimpleNamespace(cam=cam, x0=x0, y0=y0, buildings=blds)
    shutil.rmtree(root, ignore_errors=True)


def test_fitted_roofs_render_to_their_projection(roof3d_scenes):
    from pixelphilly.browser_render import Renderer

    t = roof3d_scenes
    with Renderer("output/_test_render_roof3d/roof3d.json", SIZE) as r:
        mask = np.asarray(r.frame(0, "mask"))[..., 0] > 127
        color = np.asarray(r.frame(0, "color")).astype(int)
    expected = align.rasterize(align.silhouettes(t.buildings, t.cam), {"x0": t.x0, "y0": t.y0}, SIZE)
    assert expected.sum() > 2000
    assert align.tolerant_iou(mask, expected) > 0.99
    # The roof shows the (gray) aerial, the walls are lit brick: both present
    gray = (np.abs(color - np.array(GRAY)).max(axis=2) <= 3) & mask
    assert gray.sum() > 300
    assert ((np.abs(color - np.array(GRAY)).max(axis=2) > 20) & mask).sum() > 300
