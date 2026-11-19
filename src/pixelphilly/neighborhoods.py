"""Philadelphia neighborhood boundaries, and the cut-out mask that lifts one
neighborhood out of the v18 map for the print images
(scripts/41_neighborhood_prints.py).

Boundaries: data/raw/philadelphia-neighborhoods.geojson, 159 MultiPolygon
features in CRS84 (lon/lat), from OpenDataPhilly. Neighborhood boundaries by
Robert Cheetham, licensed CC BY 4.0. They are informal, mapmaker's
neighborhoods, not legal limits.

Method
------
load_neighborhoods() reads the features and returns, per neighborhood, the
display name (LISTNAME), a unique ASCII slug, the area in square miles and
the polygons in lon/lat. The area is computed from the geometry, in a
Lambert azimuthal equal-area projection on the WGS84 ellipsoid centered on
the neighborhood, because the file's own Shape_Area is null for some
features.

neighborhood_mask() decides which map pixels belong to a neighborhood. The
map is drawn by a camera looking down at 45 degrees, so anything tall is
drawn upward on screen (smaller y) from where it stands. Cutting the map
along the ground polygon alone would slice the tops off towers on the
north (upper) edge and keep the tops of towers that stand south of the
line but rise into it. So each pixel is assigned by where it stands:

  (a) ground: inside the projected ground polygon (PIL rasterization; holes
      and multiple parts handled by rasterizing each part on its own);
  (b) building pixels (the v18 occlusion mask, white = building or bridge
      cable) go with the building they belong to: kept when its base is
      inside the polygon, dropped when it is outside, wherever the pixel
      itself is. Two ways to tell which building a pixel belongs to:
      - Scene buildings (used when data/processed is present, as it is for
        the map's own builds): the footprints and heights the map was
        rendered from (SceneBuildings). Their screen silhouettes are filled
        far to near (prism_labels), so each building pixel gets the building
        actually drawn there; a building is inside when the center of its
        footprint is. Building pixels no scene building covers (render
        specks, bridge cables) go by the ground rule.
      - Column runs (the fallback): the bottom of the pixel's contiguous
        vertical run of building pixels in the same column is taken as the
        base. In dense blocks this fails: where a front building's roof
        meets the wall of a taller one behind it on screen, the two form one
        run, and the pilot showed whole columns of Market Street towers
        pulled into Rittenhouse as thin slivers by the rowhouses in front of
        them. That is why scene buildings come first.
  (c) tree pixels (the v18 tree mask, d > 0): by the trunk, at
      y + min(d, TREE_REACH_PX) (d runs to the bottom of a whole stand of
      woods, not one crown), then
      a majority vote among the tree pixels within TREE_VOTE_PX px, because
      d is per column and per-pixel answers cut canopy along the line into
      thin vertical stripes. Trees are checked last, so they override (b):
      where the tree mask is set the canopy is what is drawn, even over a
      building.

The work runs over the neighborhood's bounding box in map px, padded and
extended UP px upward (1,500 by default, about 620 m of height, well over
Philadelphia's tallest tower) so tall buildings standing near the upper
edge are whole. It is done in vertical strips of whole tile columns, so
only one strip's masks are in memory at a time.

Limits
------
- A building that straddles the line goes whole to the side holding its
  footprint's center.
- The masks and scenes match the AI drawing closely but not pixel for
  pixel, so a cut can leave a sliver of a wall or crown, a few px wide, on
  the wrong side, and an element the model drew but the scene lacks (a
  spire, a crane) is cut along the ground line.
- Trees are not individual objects in the mask, so a crown on the line can
  be cut part way, along a ragged, crown-scale edge, and where crowns
  standing outside cover ground inside, the backdrop shows through there.
- The painter's order sorts by footprint center; where two footprints touch
  or interlock it can be wrong by a pixel or two along the shared edge.
- The result is a mask in map px; the caller crops, blends and writes it.

Usage
-----
    hoods = load_neighborhoods(REPO_ROOT / "data/raw/philadelphia-neighborhoods.geojson")
    polys_px = project_polygons(hoods[0]["polygons_lonlat"], fit)
    scenes = SceneBuildings(regions_in_precedence_order, map_json["lattice_origin_px"])
    prisms = scenes.prisms(neighborhood_window(polys_px, width, height))
    m = neighborhood_mask(polys_px, read_building_tile, read_tree_tile, width, height, prisms=prisms)
    m["mask"], m["origin"]  # bool array, (x0, y0) of its top-left in map px
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from typing import NamedTuple

import numpy as np
from PIL import Image, ImageDraw

SQ_M_PER_SQ_MI = 1609.344**2
UP_PX = 1500
TREE_REACH_PX = 36  # the farthest a crown pixel sits above its trunk, in px (a tall crown is ~30 px)
TREE_VOTE_PX = 6  # half-width of the tree majority vote; crowns are ~20-30 px across


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def area_sqmi(polygons_lonlat) -> float:
    """Area in square miles, in an equal-area projection centered on the shape."""
    import pyproj
    from shapely.geometry import MultiPolygon

    pts = np.array([p for poly in polygons_lonlat for p in poly[0]], float)
    lon0, lat0 = (pts.min(0) + pts.max(0)) / 2
    tr = pyproj.Transformer.from_crs(
        "EPSG:4326", f"+proj=laea +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m", always_xy=True)

    def ring(r):
        x, y = tr.transform(*np.asarray(r, float).T)
        return list(zip(x, y))

    shape = MultiPolygon([(ring(poly[0]), [ring(h) for h in poly[1:]]) for poly in polygons_lonlat])
    return shape.area / SQ_M_PER_SQ_MI


def load_neighborhoods(path) -> list[dict]:
    """[{name, slug, sqmi, polygons_lonlat}] in file order. polygons_lonlat is a
    list of polygons, each a list of rings (exterior first, then holes), each a
    list of (lon, lat). A Polygon feature is treated as a one-part MultiPolygon."""
    fc = json.loads(Path(path).read_text())
    out, seen = [], {}
    for f in fc["features"]:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        polys = [[[(float(x), float(y)) for x, y, *_ in ring] for ring in poly] for poly in polys]
        name = f["properties"]["LISTNAME"]
        base = slugify(name) or "neighborhood"
        seen[base] = seen.get(base, 0) + 1
        slug = base if seen[base] == 1 else f"{base}-{seen[base]}"
        out.append({"name": name, "slug": slug, "sqmi": area_sqmi(polys), "polygons_lonlat": polys})
    return out


def project_polygons(polygons_lonlat, fit) -> list:
    """The polygons in map px at ground level, same nesting."""
    from .viewer_geo import lonlat_to_px

    def ring(r):
        a = np.asarray(r, float)
        x, y = lonlat_to_px(fit, a[:, 0], a[:, 1])
        return list(zip(x.tolist(), y.tolist()))

    return [[ring(r) for r in poly] for poly in polygons_lonlat]


def rasterize_polygons(polygons_px, x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """Bool (h, w): pixels inside the polygons, to within a pixel (PIL fills
    the boundary pixels too), for the window with top-left (x0, y0) in map px. Each part is drawn on its own (outer ring
    on, holes off) and the parts are OR-ed, so a part sitting in another's
    hole is not erased by drawing order."""
    out = np.zeros((h, w), bool)
    for poly in polygons_px:
        xs = [x for x, _ in poly[0]]
        ys = [y for _, y in poly[0]]
        if max(xs) < x0 or min(xs) > x0 + w or max(ys) < y0 or min(ys) > y0 + h:
            continue
        img = Image.new("1", (w, h), 0)
        d = ImageDraw.Draw(img)
        for k, r in enumerate(poly):
            d.polygon([(x - x0, y - y0) for x, y in r], fill=1 if k == 0 else 0)
        out |= np.array(img, bool)
    return out


def polygons_bbox(polygons_px):
    pts = np.array([p for poly in polygons_px for p in poly[0]], float)
    return pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()


class Prism(NamedTuple):
    """A building from the render scenes, in map px. rings: the footprint's
    outer ring(s) at ground level, (n, 2) arrays; dy: its height in px (the
    roof is drawn dy px above the base); cx, cy: the footprint's center at
    ground level, which decides inside or outside."""
    rings: list
    dy: float
    cx: float
    cy: float

    def bbox(self):
        xs = np.concatenate([r[:, 0] for r in self.rings])
        ys = np.concatenate([r[:, 1] for r in self.rings])
        return xs.min(), ys.min() - self.dy, xs.max(), ys.max()


def prism_labels(prisms, inside, x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """uint8 (h, w) for the window at (x0, y0): 0 = no building, 1 = the
    building drawn here stands inside, 2 = it stands outside.

    Each prism's screen silhouette (base, roof and the quad swept by every
    footprint edge) is filled in painter's order, far to near, so where
    buildings overlap on screen the nearest one, the one actually drawn,
    sets the pixel. The camera looks north-ish and down, so a larger
    ground-level screen y is nearer; sorting by the footprint center's y is
    exact for separate footprints on flat ground to within the odd pixel
    where two touch. `prisms` and `inside` (bool per prism) must already be in
    that order (see neighborhood_mask)."""
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    for p, ins in zip(prisms, inside):
        bx0, by0, bx1, by1 = p.bbox()
        if bx1 < x0 or bx0 > x0 + w or by1 < y0 or by0 > y0 + h:
            continue
        val = 1 if ins else 2
        for r in p.rings:
            base = [(x - x0, y - y0) for x, y in r]
            top = [(x, y - p.dy) for x, y in base]
            d.polygon(base, fill=val)
            d.polygon(top, fill=val)
            for i in range(len(base) - 1):
                d.polygon([base[i], base[i + 1], top[i + 1], top[i]], fill=val)
    return np.array(img, np.uint8)


def _assign_strip(ground, building, tree_d, labels=None):
    """The keep / drop rule for one strip; all arrays (h, w) in the same window.

    ground: bool, inside the ground polygon. building: bool. tree_d: uint8,
    0 = no tree, else trunk y = y + d. labels: optional prism_labels() output;
    where it names a building, it decides, and building pixels it does not
    name go by the ground rule. Without labels, the column-run rule decides.
    A building run that reaches the strip's last row is treated as standing
    outside: the window extends below the polygon, so its base is below the
    polygon too."""
    h, w = ground.shape
    keep = ground.copy()

    # Walk rows bottom-up, carrying for each column "the run this pixel is in
    # stands inside". A run's value is set at its bottom pixel from the ground
    # there and copied up the run.
    run_in = np.zeros(w, bool)
    below = np.zeros(w, bool)  # is the pixel below a building pixel
    for y in range(h - 1, -1, -1):
        b = building[y]
        run_in = np.where(below, run_in, ground[y] if y < h - 1 else False) & b
        keep[y] = np.where(b, run_in, keep[y])
        below = b
    if labels is not None:
        # Building pixels no scene building explains (render specks a few px
        # across, bridge cables) go by the ground rule: the column rule would
        # carry their run's base from whatever they touch and leave specks
        # floating above the cut.
        keep[building] = ground[building]
        keep[building & (labels == 1)] = True
        keep[building & (labels == 2)] = False

    ty, tx = np.nonzero(tree_d)
    if len(ty):
        # In woods the column runs of canopy chain crown after crown, and d
        # then points at the bottom of the whole stand, up to 255 px down;
        # in the pilot that cut 10-15 px wide gaps, 150 px tall, into
        # Chestnut Hill's wooded edge. No single crown is that tall, so the
        # trunk is taken at most TREE_REACH_PX below the pixel.
        trunk = ty + np.minimum(tree_d[ty, tx], TREE_REACH_PX).astype(np.int64)
        inside = trunk < h
        val = np.zeros(len(ty), bool)
        val[inside] = ground[trunk[inside], tx[inside]]
        # The tree mask's d comes from each column's own run of canopy, so
        # neighboring columns of one crown, or of crowns that overlap on
        # screen, can disagree, and along the line that cut canopy into
        # 1-3 px vertical stripes in the pilot. A majority vote over tree
        # pixels within TREE_VOTE_PX px smooths that to crown-sized edges.
        raw = np.zeros((h, w), bool)
        raw[ty, tx] = val
        trees = tree_d > 0
        votes = _box_sum(raw, TREE_VOTE_PX)
        total = _box_sum(trees, TREE_VOTE_PX)
        keep[ty, tx] = 2 * votes[ty, tx] >= total[ty, tx]
    return keep


def _box_sum(a: np.ndarray, r: int) -> np.ndarray:
    """Sum of a over the (2r + 1)-px square around each pixel, clipped at the
    edges (summed-area table; scipy is not a dependency)."""
    h, w = a.shape
    s = np.zeros((h + 1, w + 1), np.int32)
    np.cumsum(np.cumsum(a, 0, dtype=np.int32), 1, out=s[1:, 1:])
    y0 = np.clip(np.arange(h) - r, 0, h)[:, None]
    y1 = np.clip(np.arange(h) + r + 1, 0, h)[:, None]
    x0 = np.clip(np.arange(w) - r, 0, w)[None, :]
    x1 = np.clip(np.arange(w) + r + 1, 0, w)[None, :]
    return s[y1, x1] - s[y0, x1] - s[y1, x0] + s[y0, x0]


def neighborhood_window(polygons_px, width: int, height: int, up: int = UP_PX, pad: int = 16):
    """(x0, y0, x1, y1) in map px: the polygon's bounding box, padded, UP px
    taller above, with room below for trunk lookups (d <= 255), clipped to
    the canvas."""
    gx0, gy0, gx1, gy1 = polygons_bbox(polygons_px)
    return (max(0, int(np.floor(gx0)) - pad), max(0, int(np.floor(gy0)) - up - pad),
            min(width, int(np.ceil(gx1)) + pad), min(height, int(np.ceil(gy1)) + pad + 256))


def neighborhood_mask(polygons_px, read_building, read_tree, width: int, height: int,
                      tile: int = 512, up: int = UP_PX, pad: int = 16, strip_tiles: int = 4,
                      prisms=None) -> dict:
    """The neighborhood's cut-out mask in map px.

    read_building(tx, ty) -> bool (tile, tile) array or None (no building);
    read_tree(tx, ty) -> uint8 (tile, tile) depth array or None (no tree).
    width, height: the map canvas in px. prisms: optional list of Prism (the
    buildings from the render scenes, see SceneBuildings); with them, building
    pixels go by the building actually drawn there. Without them, the
    column-run rule decides.

    Returns {"mask": bool (h, w), "origin": (x0, y0), "cut_by_map_edge": the
    ground polygon reaches past the canvas, "touches_top": a kept building or
    tree pixel is on the window's top row, so something may be cut off}."""
    gx0, gy0, gx1, gy1 = polygons_bbox(polygons_px)
    cut = gx0 < 0 or gy0 < 0 or gx1 > width or gy1 > height
    x0, y0, x1, y1 = neighborhood_window(polygons_px, width, height, up, pad)
    top_clipped = y0 == 0

    inside = None
    if prisms:
        import shapely
        from shapely.geometry import MultiPolygon

        prisms = sorted(prisms, key=lambda p: p.cy)  # far to near
        area = MultiPolygon([(poly[0], poly[1:]) for poly in polygons_px]).buffer(0)
        inside = shapely.contains_xy(area, np.array([p.cx for p in prisms]), np.array([p.cy for p in prisms]))

    # Work in whole tiles, then crop to the window
    tx0, ty0, tx1, ty1 = x0 // tile, y0 // tile, (x1 - 1) // tile + 1, (y1 - 1) // tile + 1
    th = (ty1 - ty0) * tile
    ground_y0 = ty0 * tile
    mask = np.zeros((y1 - y0, x1 - x0), bool)
    for sx in range(tx0, tx1, strip_tiles):
        sx1 = min(tx1, sx + strip_tiles)
        sw = (sx1 - sx) * tile
        building = np.zeros((th, sw), bool)
        tree_d = np.zeros((th, sw), np.uint8)
        for tx in range(sx, sx1):
            for ty in range(ty0, ty1):
                ys, xs = (ty - ty0) * tile, (tx - sx) * tile
                b = read_building(tx, ty)
                if b is not None:
                    building[ys:ys + tile, xs:xs + tile] = b
                t = read_tree(tx, ty)
                if t is not None:
                    tree_d[ys:ys + tile, xs:xs + tile] = t
        # Crop the strip to the window rows so the bottom-of-window rule applies
        r0, r1 = y0 - ground_y0, y1 - ground_y0
        building, tree_d = building[r0:r1], tree_d[r0:r1]
        ground = rasterize_polygons(polygons_px, sx * tile, y0, sw, y1 - y0)
        labels = None
        if prisms:
            labels = prism_labels(prisms, inside, sx * tile, y0, sw, y1 - y0)
        keep = _assign_strip(ground, building, tree_d, labels)
        # Copy the strip's columns that fall in the window
        a, b = max(x0, sx * tile), min(x1, sx1 * tile)
        mask[:, a - x0:b - x0] = keep[:, a - sx * tile:b - sx * tile]

    touches_top = bool(mask[0].any()) and not top_clipped
    return {"mask": mask, "origin": (x0, y0), "cut_by_map_edge": bool(cut), "touches_top": touches_top}


class SceneBuildings:
    """Reads the buildings of the map's render scenes (data/processed, written
    by scripts/05_build_scene.py) as Prisms in map px.

    All v18 regions share one screen space (one projection origin and
    camera), so a building's screen position is cam.world_to_screen of its
    local meters, less the map's lattice origin (map.json
    lattice_origin_px). Regions are split into render tiles, each a scene
    with the frames it covers; only tiles whose frames reach the window are
    read. A building in two regions' overlap is read twice; both copies give
    the same answer, so that is harmless."""

    def __init__(self, regions, lattice_origin_px):
        from .projection import REPO_ROOT, area_setup, load_config
        from .scenes import scene_paths

        self.ox, self.oy = lattice_origin_px
        self.regions = []
        for name in regions:
            cfg = load_config(name)
            _, cam, frames = area_setup(cfg)
            by_name = {f.name: f for f in frames}
            if cfg.get("render_tile_frames"):
                index = json.loads((REPO_ROOT / "data" / "processed" / f"{cfg['name']}_tiles.json").read_text())
                tiles = [(REPO_ROOT / t["scene"], [by_name[n] for n in t["frames"] if n in by_name]) for t in index]
            else:
                tiles = [(REPO_ROOT / p, frames) for p in scene_paths(cfg)]
            boxes = []
            for path, fr in tiles:
                if not fr:
                    continue
                boxes.append((path, min(f.x0 for f in fr) - self.ox, min(f.y0 for f in fr) - self.oy,
                              max(f.x0 + f.size for f in fr) - self.ox, max(f.y0 + f.size for f in fr) - self.oy))
            self.regions.append((name, cam, boxes))

    def available(self) -> bool:
        return all(b[0].exists() for _, _, boxes in self.regions for b in boxes)

    def prisms(self, window) -> list:
        x0, y0, x1, y1 = window
        out, seen = [], set()
        for name, cam, boxes in self.regions:
            zx, zy = cam.world_to_screen(0.0, 0.0, 0.0)
            hx, hy = cam.world_to_screen(0.0, 0.0, 1.0)
            px_per_m = float(zy - hy)  # screen px a meter of height rises
            for path, bx0, by0, bx1, by1 in boxes:
                if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                    continue
                for b in json.loads(path.read_text())["buildings"]:
                    key = (name, b["id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    rings = []
                    for poly in b["polys"]:
                        r = np.asarray(poly[0], float)
                        sx, sy = cam.world_to_screen(r[:, 0], r[:, 1], 0.0)
                        rings.append(np.stack([sx - self.ox, sy - self.oy], 1))
                    dy = b["h"] * px_per_m
                    allp = np.concatenate(rings)
                    if (allp[:, 0].max() < x0 or allp[:, 0].min() > x1
                            or allp[:, 1].max() < y0 or allp[:, 1].min() - dy > y1):
                        continue
                    # The center of the largest part decides inside or outside
                    big = max(rings, key=lambda r: abs(_ring_area(r)))
                    cx, cy = _ring_centroid(big)
                    out.append(Prism(rings, dy, cx, cy))
        return out


def _ring_area(r):
    x, y = r[:, 0], r[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _ring_centroid(r):
    x, y = r[:, 0], r[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    a = cross.sum() / 2
    if abs(a) < 1e-9:
        return float(x.mean()), float(y.mean())
    return float(((x + np.roll(x, -1)) * cross).sum() / (6 * a)), float(((y + np.roll(y, -1)) * cross).sum() / (6 * a))


def mask_bbox(mask: np.ndarray):
    """(x0, y0, x1, y1), exclusive end, of the True pixels, or None."""
    rows, cols = np.flatnonzero(mask.any(1)), np.flatnonzero(mask.any(0))
    if not len(rows):
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1
