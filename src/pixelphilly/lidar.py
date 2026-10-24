"""Building shapes from the City's 2022 LiDAR.

The footprint layer gives each building one outline and one height, so towers,
spires, domes and stadium bowls render as flat boxes. LiDAR measures the real
surface. This module turns it into "stepped parts": each footprint is split
into height tiers, and each tier is extruded as its own box. The renderer and
alignment check need no changes (parts use the same {"h", "polys"} format as
whole buildings), and stepped forms suit pixel art: towers become tiers,
domes terraces, stadiums tiered stands around an open field.

Source: PASDA dataset 7154, Philadelphia 2022 classified LAS (flown March 29,
2022, leaf-off). Coordinates are PA State Plane South, US survey feet
(EPSG:6565); heights NAVD88 feet. The files carry no CRS record, so it is
assigned here. There is no "building" class: buildings and trees are both
class 1, so footprints are what separate them.

Grid convention: ndsm[row, col], 0.5 m cells, row 0 at the north edge.
origin = (west edge, north edge) in local meters.
"""

from __future__ import annotations

import os
import sys

import numpy as np

LAS_CRS = "EPSG:6565"
US_FT_TO_M = 1200 / 3937  # US survey foot
KEEP_CLASSES = (1, 2, 9, 17)  # unclassified (buildings, trees), ground, water, bridge deck
GROUND_CLASS = 2
MIN_PART_M2 = 6.0  # smaller tier regions merge into their neighbors
MIN_PART_HEIGHT_M = 1.0  # lower parts become open ground (courtyards, stadium fields)
# Part cap: past it, tiers coarsen (x1.5) until the building fits. It stops a
# small building fragmenting into noise, but a fixed 60 flattened stadium
# seating: Franklin Field's upper-deck rows sit ~1-3 m apart, and coarsening
# merged them into a flat roof. Big buildings get one part per PART_AREA_M2
# of built area (cells at least MIN_PART_HEIGHT_M up; 10 x 10 m, ~16
# minimum-size parts' worth, still far from noise), so anything under
# 6,000 m² built keeps 60. Built area, not footprint area: a mostly open
# footprint (Penn's Landing's 4.1 ha plaza site, 87% ground) shouldn't buy
# room for hundreds of specks
MAX_PARTS = 60
PART_AREA_M2 = 100.0
INSET_M = 0.5  # keeps wall-edge returns and overhanging trees out of the footprint
# A footprint with this much ground of its own (Franklin Field: 886 m² under
# its open stands) bases on it (see footprint_base). Large enough that stray
# class-2 returns through skylights or under canopies don't count (most
# buildings have none; ~40 of the ~1,450 atlas LiDAR footprints reach it)
INTERIOR_GROUND_M2 = 500.0
# Stadium seating rows come out as stepped parts, and the faces between them
# are seat risers, not façades (the brick wall tint drew Franklin Field's
# upper deck as brick with windows). A part is a terrace when it is a strip
# narrower than TERRACE_MAX_WIDTH_M (seating rows are ~2-4 m deep; a main
# roof or a tower setback is wider) and it touches a part of the same
# building TERRACE_STEP_MIN_M-TERRACE_STEP_MAX_M taller and one that much
# lower: mid-cascade. Rows climb ~2 m (Franklin Field's upper deck: 14.7,
# 16.6, 18.6, 20.7, 23.5, 25.3 m); 1 m is below the 2 m tier step, and
# office-tower setbacks are bigger (9 m in the test). Open ground below
# doesn't count, so a single step (a parapet, a penthouse ring) never
# qualifies, and the front row and the rim keep their walls
TERRACE_MAX_WIDTH_M = 8.0
TERRACE_STEP_MIN_M = 1.0
TERRACE_STEP_MAX_M = 4.0
# LiDAR structures: ships, cranes and container stacks have no L&I footprint,
# so they drew as flat aerial texture (containers' photographed sides became
# little brick buildings). The class-1 grid sees them. A structure is a
# connected region of class-1 cells outside every footprint, 2.5-90 m above
# its local base, at least STRUCT_MIN_M2, and flat. Median 3x3 roughness
# (std of 0.5 m max-Z cells) separates them from trees: containers 0.02, a
# ship 0.03, rooftops 0.06, tree canopy 1.4-1.9 (Washington Sq.,
# Rittenhouse). Bridges and elevated roads are flat too, but they're class
# 17, which the structure grid leaves out
STRUCT_FOOTPRINT_GAP_M = 1.5  # a building's own edge returns belong to its footprint parts
STRUCT_MIN_HEIGHT_M = 2.5  # above parked cars and fences; a container stack is ~2.6 m per box
STRUCT_MAX_HEIGHT_M = 90.0  # tallest ship superstructures and cranes are well under this; higher is noise
STRUCT_MIN_M2 = 60.0  # one 40 ft container is ~30 m², a bus ~30 m²: single vehicles stay out
STRUCT_MAX_ROUGH = 0.3  # flat objects 0.02-0.06 vs. canopy 1.4-1.9
STRUCT_RING_M = (3.0, 15.0)  # ground ring that sets a region's base
# Tree clusters can pass the roughness test: only flat cells (and one cell
# around them) become candidates, so a canopy leaves a lacy region of locally
# flat patches whose median roughness is low (north_lidar: 0.05-0.23). What
# gives them away is shape. Solidity (area / convex hull area) measured on
# north_lidar regions: trees 0.32 (ring around a dirt field), 0.37 (cemetery
# near Laurel Hill), 0.52 (along an elevated roadway); real objects 0.70 (a
# 2022 construction site), 0.71 (a school with solar panels), 0.83-0.92
# (buildings and a warehouse with no footprint), 0.99 (East Park Reservoir's
# covered tanks). Roughness p75 separates them only thinly (trees 0.19-0.28,
# real up to 0.17)
STRUCT_MIN_SOLIDITY = 0.6
# Coarse ground for picking candidate cells before regions exist: the lowest
# ground return per STRUCT_BLOCK_M block, spread into empty blocks (under a
# big container yard or ship) up to STRUCT_FILL_BLOCKS blocks away. It only
# gates candidates; each region's base is measured again from its own ring
STRUCT_BLOCK_M = 16.0
STRUCT_FILL_BLOCKS = 10
STRUCT_CHUNK_ROWS = 2048  # row strips bound memory on the ~14k x 21k south grid
# The LiDAR was flown in March 2022 and the aerial in 2024; ships leave and
# container stacks move. A structure is kept only if the photo shows
# something there: if PHOTO_SAME_FRAC or more of its pixels are within
# PHOTO_COLOR_TOL (max RGB channel difference) of the median color of the
# ground ring around it, the photo shows only that ground. Calibrated on the
# 2024 aerial: kept regions measured 0.03 (the Navy Yard carrier) and
# 0.18-0.29 (Packer container stacks); regions with nothing there measured
# 0.63 (Packer pavement with a shadow strip), 0.97 (a basin berth whose
# ship had left) and 0.98-1.00 (empty terminal pavement)
PHOTO_COLOR_TOL = 25
PHOTO_SAME_FRAC = 0.5
# Over water, a region that is one color is open water even if a pier or
# deck in the ring shifts the ring's median (the vanished ship's berth read
# 0.95 one color vs. 0.71 for the carrier). On land a single color isn't
# enough, since a plain roof is one color too. Also the rule with no ring
PHOTO_UNIFORM_FRAC = 0.9

# Only stadiums get terraces: a pitched roof drawn in 2 m tiers looks just
# like a seating cascade (163 ordinary buildings matched), but stands wrap a
# field. A footprint is a stadium when the open area inside its convex hull
# (holes included) has one piece of at least FIELD_MIN_M2: a football field
# alone is ~5,350 m², while rowhouse and campus courtyards are far smaller.
# FIELD_CLEAN_M erodes and regrows that area so slivers between wings and
# along a jagged outline don't join up into one big piece
FIELD_MIN_M2 = 5000.0
FIELD_CLEAN_M = 2.0
# Wrapping open ground isn't enough on its own: Penn's Quadrangle wraps
# lawns over 5,000 m² and two of its pitched-roof strips read as rows. A
# seating bowl has dozens of rows (Franklin Field 30-32, the Linc 42, CBP
# 34); the Quad has 2, and the Rivers Casino garage (1001-99 N Delaware Ave)
# and the Art Museum's stepped wings 12 each
MIN_STAND_ROWS = 20
TERRACE_TOUCH_M = 0.6  # about one grid cell: adjacent parts' simplified edges don't meet exactly
# Buildings within the area's bbox plus this margin get LiDAR shapes; farther
# out they keep their single footprint height (keeps downloads to the tiles
# around each spot; the shape test is about what's at the center)
LIDAR_MARGIN_M = 100.0
RES_M = 0.5
# Cells more than this above the footprint's L&I height are treated as noise.
# The files hold clusters of class-1 returns floating far above roofs (e.g.
# ~1,200 points 80-110 m above the Ritz-Carlton residences, all from one
# flight line), which the vendor's noise classes (7, 18) missed
CEILING_TOL_M = 3.0
# Small clusters of stray returns also sit under the ceiling: when one
# element sets it (City Hall's record is 170 m, and ~20 m² clusters at 150 m
# on its ~50 m wings rendered as needle spires), when there is no record
# (545892 by the Cathedral Basilica: 7 m² clusters at 160-180 m on a 74 m
# roof), and when the noise set the record itself (L&I's max_hgt is the
# highest LiDAR return: 226-30 N 2nd St, a 62 m record on an 18 m roof with
# no tower or shadow in the 2024 aerial). So max_hgt never exempts a
# spike. A region smaller than SPIKE_MAX_M2 is flattened into its
# surroundings when it rises more than max(SPIKE_MIN_JUMP_M, SPIKE_RATIO x
# the tallest neighboring region) above them, i.e. it more than doubles
# everything next to it, unless its height is within CONFIRM_TOL_M of the
# City's typical height (approx_hgt). max_hgt is the highest return, so noise
# sets it; approx_hgt is the typical height, which noise doesn't move. Every
# confirmed noise case sits far above it (N 2nd St 18 m vs 62; City Hall's
# wings 52 vs 145; 1412 Chestnut 25 vs 95), and the real cases match it
# (the Linc's canopy 55 vs 53-55.5; 1224 Chestnut 41 vs 41.5, a 25 m²
# section over 17 m roofs). Real steeples taper (Independence Hall climbs
# continuously from its tower body to ~42 m), so each step up is small and
# none trips this; William Penn rises ~17 m over the tower top, under the
# 20 m floor. The size cap leaves real towers alone (an 8 x 8 m tower is
# 64 m²) and keeps big footprints fast; the 20 m floor leaves rooftop
# penthouses alone; comparing with the tallest neighboring region, not a
# typical one, keeps a tower's own tier pieces beside the tower body (City
# Hall's 103 m piece next to its 120 m body)
SPIKE_MAX_M2 = 40.0
SPIKE_MIN_JUMP_M = 20.0
SPIKE_RATIO = 1.0
SPIKE_RING_M = 1.0  # width of the ring that samples the surroundings
# Cells within CONFIRM_TOL_M of the City height record are "confirmed": the
# record says something that tall is there (William Penn's statue, ~2 x 2 m
# at 167 m, under City Hall's 170 m record). Confirmed clusters the median
# filter and speck merge would erase are kept down to MIN_CONFIRMED_M2
# (cells flattened as spikes are never confirmed)
CONFIRM_TOL_M = 5.0
MIN_CONFIRMED_M2 = 2.0
CONFIRM_LOST_M = 2.0  # how far below its measured height a confirmed cell may render (the minimum tier step)
_CONFIRMED_LABEL = 1 << 20  # tier label for a rescued element: one region, never a normal tier


def lidar_region_local(cfg):
    """(LocalFrame, shapely box in local meters) where buildings get LiDAR shapes."""
    from shapely.geometry import box

    from .projection import local_frame

    fr = local_frame(cfg)
    w, s, e, n = cfg["bbox_wgs84"]
    ee, nn = fr.to_local([w, e], [s, n])
    m = LIDAR_MARGIN_M
    return fr, box(ee[0] - m, nn[0] - m, ee[1] + m, nn[1] + m)


def tier_step(max_height_m: float) -> float:
    """Tier spacing: 2 m for ordinary buildings, 6% of height for tall ones,
    so a 150 m tower gets ~17 tiers rather than 75."""
    return max(2.0, 0.06 * max_height_m)


def _transform(origin, res):
    from rasterio.transform import Affine

    return Affine(res, 0, origin[0], 0, -res, origin[1])


def _median3(a: np.ndarray) -> np.ndarray:
    """3x3 nan-median (scipy isn't a dependency)."""
    p = np.pad(a, 1, constant_values=np.nan)
    stack = np.stack([p[i : i + a.shape[0], j : j + a.shape[1]] for i in range(3) for j in range(3)])
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmedian(stack, axis=0)


def _flatten_spikes(h, tiers, mask, win_origin, res, typical=None):
    """Flatten small regions far above everything around them (see SPIKE_*).
    Edits h in place; returns [(region height, surroundings height, area m²,
    (x, y))] for each flattened region. A region within CONFIRM_TOL_M of
    `typical` (the City's approx_hgt, m above base) is the building itself
    and stays. max_hgt plays no part: it is the highest LiDAR return, so it
    can be set by the very noise being removed."""
    from rasterio.features import rasterize, shapes
    from shapely.geometry import shape as to_shape

    tf = _transform(win_origin, res)
    regions = [to_shape(g) for g, _ in shapes(tiers, mask=mask & (tiers > 0), transform=tf, connectivity=8)]
    small = [i for i, p in enumerate(regions) if p.area < SPIKE_MAX_M2]
    if not small:
        return []
    # "Surroundings" = the tallest neighboring region, by each region's
    # median. Not the tallest ring cell: stray returns come in clouds, and
    # the speck merge folds the cloud's outliers into the roof region
    # without lowering their heights, so a cell max would read ~150 m on
    # City Hall's 45 m wing
    labels = rasterize([(p, i + 1) for i, p in enumerate(regions)], out_shape=h.shape, transform=tf, fill=0,
                       dtype="int32")
    labels = np.where(mask, labels, 0)
    medians = _region_medians(labels, h)
    flattened = []
    pad = int(np.ceil(SPIKE_RING_M / res)) + 1
    for i in small:
        poly = regions[i]
        # Small window around the region, so cost scales with the region,
        # not the footprint
        minx, miny, maxx, maxy = poly.bounds
        c0 = max(int(round((minx - win_origin[0]) / res)) - pad, 0)
        c1 = min(int(round((maxx - win_origin[0]) / res)) + pad, h.shape[1])
        r0 = max(int(round((win_origin[1] - maxy) / res)) - pad, 0)
        r1 = min(int(round((win_origin[1] - miny) / res)) + pad, h.shape[0])
        sub_lab = labels[r0:r1, c0:c1]
        sub_h = h[r0:r1, c0:c1]  # view: edits land in h
        inside = sub_lab == i + 1
        sub_tf = _transform((win_origin[0] + c0 * res, win_origin[1] - r0 * res), res)
        ring = rasterize([(poly.buffer(SPIKE_RING_M), 1)], out_shape=sub_lab.shape, transform=sub_tf, fill=0,
                         dtype="uint8").astype(bool)
        ring &= mask[r0:r1, c0:c1] & ~inside
        if i + 1 not in medians or not ring.any():
            continue
        around = [medians[k] for k in np.unique(sub_lab[ring]) if k > 0 and k in medians]
        low = ring & (sub_lab == 0)  # open ground or below the first tier
        if low.any():
            around.append(float(np.median(sub_h[low])))
        region_h, ring_max = medians[i + 1], max(around)
        if typical is not None and abs(region_h - typical) <= CONFIRM_TOL_M:
            continue
        if region_h - ring_max > max(SPIKE_MIN_JUMP_M, SPIKE_RATIO * ring_max):
            sub_h[inside] = np.float32(np.median(sub_h[ring]))
            c = poly.centroid
            flattened.append((region_h, ring_max, poly.area, (c.x, c.y)))
    return flattened


def _region_medians(labels, h):
    """{label: median of h over its cells} for labels > 0, in one sort
    (a loop of label == k masks is slow on stadium-sized windows)."""
    sel = labels > 0
    lab, vals = labels[sel], h[sel]
    order = np.lexsort((vals, lab))
    lab, vals = lab[order], vals[order]
    keys, starts = np.unique(lab, return_index=True)
    ends = np.append(starts[1:], len(lab))
    out = {}
    for k, a, b in zip(keys, starts, ends):
        n = b - a
        out[int(k)] = float(vals[a + n // 2]) if n % 2 else float((vals[a + n // 2 - 1] + vals[a + n // 2]) / 2)
    return out


def building_parts(footprint, ndsm: np.ndarray, origin, res: float, max_parts: int = MAX_PARTS,
                   base: float = 0.0, ceiling: float | None = None, typical: float | None = None):
    """Split one footprint (shapely, local meters) into stepped parts.
    `max_parts` is raised to one part per PART_AREA_M2 of built area.

    ndsm: surface heights on the grid described by origin/res; `base` is
    subtracted, so pass a DSM with the building's base elevation, or heights
    already above the base with base=0. `ceiling` (m above base, usually the
    footprint's L&I max_hgt) drops cells more than CEILING_TOL_M above it as
    noise and refills them from their neighbors, and keeps a small element
    that reaches it (CONFIRM_TOL_M). Small spikes far above their roof are
    flattened with or without a record (SPIKE_*), except a region within
    CONFIRM_TOL_M of `typical` (m above base, the footprint's L&I
    approx_hgt). Set PP_LIDAR_LOG=1 to print flattened spikes to stderr. Returns [{"h": float, "polys": [[exterior, *holes], ...]}],
    or None when the grid has no data inside the footprint (the caller then
    falls back to the footprint's single height).
    """
    from rasterio.features import rasterize, shapes, sieve
    from shapely.geometry import shape as to_shape

    inner = footprint.buffer(-INSET_M)
    if inner.is_empty:
        inner = footprint
    # Grid window around the footprint, one cell of padding
    minx, miny, maxx, maxy = footprint.bounds
    c0 = max(int((minx - origin[0]) / res) - 1, 0)
    c1 = min(int((maxx - origin[0]) / res) + 2, ndsm.shape[1])
    r0 = max(int((origin[1] - maxy) / res) - 1, 0)
    r1 = min(int((origin[1] - miny) / res) + 2, ndsm.shape[0])
    if c1 <= c0 or r1 <= r0:
        return None
    win_origin = (origin[0] + c0 * res, origin[1] - r0 * res)
    tf = _transform(win_origin, res)
    h = ndsm[r0:r1, c0:c1].astype(np.float32) - np.float32(base)
    mask = rasterize([(inner, 1)], out_shape=h.shape, transform=tf, fill=0, dtype="uint8").astype(bool)
    if not mask.any() or np.isnan(h[mask]).all():
        return None
    if ceiling is not None:
        noise = mask & (h > ceiling + CEILING_TOL_M)
        h[noise] = np.nan
        # Grow the surrounding roof inward until the noise cells are filled
        # (a cluster can be dozens of cells across, more than one 3x3 pass)
        for _ in range(200):
            gap = noise & np.isnan(h)
            if not gap.any():
                break
            h[gap] = _median3(np.where(mask, h, np.nan))[gap]
        confirmed = mask & ~np.isnan(h) & (h >= ceiling - CONFIRM_TOL_M)
    else:
        confirmed = np.zeros_like(mask)
    h_raw = np.nan_to_num(h)  # pre-median heights, for confirmed cells

    h = _median3(np.where(mask, h, np.nan))
    h = np.where(mask & np.isnan(h), 0.0, h)
    min_cells = int(np.ceil(MIN_PART_M2 / (res * res)))
    flat = np.zeros_like(mask)  # cells flattened as spikes, never "confirmed"

    def tiered(step):
        t = np.where(mask, np.round(np.nan_to_num(h) / step), 0).astype(np.int32)
        # Merge small regions (specks, antennas, stray returns) into neighbors
        return np.where(mask, sieve(t, size=min_cells, connectivity=8, mask=mask), 0).astype(np.int32)

    def drop_spikes(tiers, step=None):
        """Flatten spikes among the regions these tiers form; if any went,
        re-tier at `step` (when given). The rule must see the regions that
        become parts: a cloud whose heights straddle tier boundaries splits
        into pieces under
        MIN_PART_M2, the merge folds each into the roof (labels only, the
        heights stay), and at a coarser step after MAX_PARTS the same cells
        land in one tier and come back as one part. That's how City Hall's
        west-wing cluster survived on the downtown grid's cell alignment."""
        before = h.copy()
        flattened = _flatten_spikes(h, tiers, mask, win_origin, res, typical)
        if not flattened:
            return tiers
        flat[:] |= h != before
        if os.environ.get("PP_LIDAR_LOG") == "1":
            c = footprint.centroid
            for region_h, ring_max, area, (x, y) in flattened:
                print(f"lidar spike flattened: footprint ({c.x:.1f}, {c.y:.1f}) region {region_h:.1f} m "
                      f"surroundings {ring_max:.1f} m area {area:.1f} m² at ({x:.1f}, {y:.1f})", file=sys.stderr)
        return tiered(step) if step else tiers

    # A first pass before hmax and the tier step are set, so a spike can't
    # inflate either; the tier loop below repeats it at each step
    drop_spikes(tiered(tier_step(float(np.nanpercentile(h[mask], 99.5)))))
    hmax = float(np.nanpercentile(h[mask], 99.5))  # robust to stray spikes
    step = tier_step(hmax)
    min_confirmed_cells = int(np.ceil(MIN_CONFIRMED_M2 / (res * res)))

    def regions_of(tiers, hfill):
        """[(polygon, label)] and {index + 1: median height of its own cells}.
        Each region gets the median measured height of its own cells, not
        its tier's: two blocks at 140 and 148 m in one 12 m tier stay 140
        and 148, and a 15 m base under a 150 m tower stays 15 m."""
        regions = [(to_shape(g), int(v)) for g, v in shapes(tiers, mask=mask & (tiers > 0), transform=tf,
                                                              connectivity=8)]
        if not regions:
            return regions, np.zeros(h.shape, np.int32), {}
        labels = rasterize([(g, i + 1) for i, (g, _) in enumerate(regions)], out_shape=h.shape, transform=tf,
                           fill=0, dtype="int32")
        labels = np.where(mask, labels, 0)
        return regions, labels, _region_medians(labels, hfill)

    # A flattened spike's cells may sit within CONFIRM_TOL_M of the record
    # (when the spike itself set it); they must not come back as an element
    confirmed &= ~flat
    # Built area only: open ground (fields, plazas) never becomes parts
    built_m2 = float((mask & (np.nan_to_num(h) >= MIN_PART_HEIGHT_M)).sum()) * res * res
    max_parts = max(max_parts, int(built_m2 / PART_AREA_M2))
    while True:
        tiers = drop_spikes(tiered(step), step)
        confirmed &= ~flat
        hfill = np.nan_to_num(h)
        regions, labels, medians = regions_of(tiers, hfill)
        kept = None
        if confirmed.any():
            # The record is one number: it confirms the building's tallest
            # element (City Hall's statue of William Penn, 167 m cells
            # diluted into a 163 m region, or erased outright by the median
            # and speck merge). If the cluster holding the highest confirmed
            # cell would render more than CONFIRM_LOST_M below its measured
            # height, it becomes its own part. Only that one cluster: rooftop
            # mechanicals near the record are what it measured on ordinary
            # buildings, and rescuing them all brings back the clutter the
            # merge removes. Lone lost cells (a tower's corners, rounded off
            # by the median) are too small to count, so a record doesn't
            # change shapes that already survive
            lookup = np.zeros(len(regions) + 1, np.float32)
            for k, v in medians.items():
                lookup[k] = v
            lost = (confirmed & (h_raw - lookup[labels] > CONFIRM_LOST_M)).astype(np.uint8)
            clusters = [to_shape(g) for g, _ in shapes(lost, mask=lost.astype(bool), transform=tf, connectivity=8)]
            clusters = [g for g in clusters if g.area >= min_confirmed_cells * res * res]
            rendered = lookup[labels]
            best, best_h = None, -np.inf
            for g in clusters:
                cells = rasterize([(g, 1)], out_shape=h.shape, transform=tf, fill=0,
                                  dtype="uint8").astype(bool) & lost.astype(bool)
                ring = rasterize([(g.buffer(SPIKE_RING_M), 1)], out_shape=h.shape, transform=tf, fill=0,
                                 dtype="uint8").astype(bool) & mask & ~cells
                if not cells.any() or not ring.any():
                    continue
                # A real element stands on something tall (the statue on the
                # tower top); a cluster that more than doubles everything
                # around it is spike-shaped, e.g. a stray-return cloud at
                # 165-173 m over City Hall's 45 m south wing, just under its
                # record, and is not rescued
                top, around = float(h_raw[cells].max()), float(rendered[ring].max())
                if float(np.median(h_raw[cells])) - around > max(SPIKE_MIN_JUMP_M, SPIKE_RATIO * around):
                    continue
                if top > best_h:
                    best, best_h = cells, top
            if best is not None:
                # Re-merge what's left of the region the cluster came out of,
                # so a remnant under MIN_PART_M2 joins its neighbor instead of
                # being dropped (which would leave a hole in the roof)
                rest = mask & ~best
                tiers = np.where(rest, sieve(np.where(rest, tiers, 0).astype(np.int32), size=min_cells,
                                             connectivity=8, mask=rest), 0)
                tiers = np.where(best, _CONFIRMED_LABEL, tiers).astype(np.int32)
                hfill = np.where(best, h_raw, hfill)
                regions, labels, medians = regions_of(tiers, hfill)
                kept = (float(np.median(h_raw[best])), float(best.sum() * res * res))
        parts = []
        for i, (geom, val) in sorted(enumerate(regions), key=lambda t: t[1][1]):
            if i + 1 not in medians:
                continue
            height = medians[i + 1]
            if height < MIN_PART_HEIGHT_M:
                continue
            min_area = MIN_CONFIRMED_M2 if val >= _CONFIRMED_LABEL else MIN_PART_M2
            merged = geom.simplify(0.3 * res / 0.5).buffer(0)
            polys = [merged] if merged.geom_type == "Polygon" else list(getattr(merged, "geoms", []))
            for p in polys:
                if p.geom_type != "Polygon" or p.area < min_area:
                    continue
                rings = [np.round(np.asarray(p.exterior.coords)[:-1], 2).tolist()]
                rings += [np.round(np.asarray(r.coords)[:-1], 2).tolist() for r in p.interiors]
                # A rescued element is backed by the City record, so the
                # percentile cap (meant for stray returns) doesn't apply
                cap = np.inf if val >= _CONFIRMED_LABEL else hmax
                parts.append({"h": round(float(min(height, cap)), 2), "polys": [rings]})
        if len(parts) <= max_parts:
            if kept and os.environ.get("PP_LIDAR_LOG") == "1":
                c = footprint.centroid
                print(f"lidar confirmed element kept: footprint ({c.x:.1f}, {c.y:.1f}) {kept[0]:.1f} m, "
                      f"{kept[1]:.1f} m²", file=sys.stderr)
            return parts
        step *= 1.5  # too many parts: coarser tiers



def _strip_width(g) -> float:
    """Short side of the rectangle with the same area and perimeter. Exact
    for rectangles, and it follows a curved strip: a horseshoe of seats at
    Franklin Field is ~3 m deep but its minimum rotated rectangle is 122 m
    across. Compact shapes (no such rectangle) count as wide."""
    half, area = g.length / 2, g.area
    disc = half * half - 4 * area
    return (half - np.sqrt(disc)) / 2 if disc > 0 else float(np.sqrt(area))


def encloses_field(footprint) -> bool:
    """Whether a footprint (shapely, local meters) wraps a playing field:
    one open piece of at least FIELD_MIN_M2 inside its convex hull. The hull
    closes a horseshoe open at one end (Franklin Field); a fully enclosed
    field is a hole, which the hull difference includes too."""
    open_area = footprint.convex_hull.difference(footprint)
    open_area = open_area.buffer(-FIELD_CLEAN_M).buffer(FIELD_CLEAN_M)
    pieces = getattr(open_area, "geoms", [open_area])
    return any(g.area >= FIELD_MIN_M2 for g in pieces)

def stand_terraces(footprint, parts) -> set[int]:
    """terrace_parts for a stadium's stands: only when the footprint wraps a
    field (encloses_field) and has at least MIN_STAND_ROWS terraces; else
    no terraces, so stepped roofs elsewhere keep their wall color."""
    if not encloses_field(footprint):
        return set()
    terraces = terrace_parts(parts)
    return terraces if len(terraces) >= MIN_STAND_ROWS else set()

def terrace_parts(parts) -> set[int]:
    """Indexes of the parts of ONE building (as building_parts returns them)
    that are mid-cascade seating rows (see TERRACE_*)."""
    from shapely import STRtree
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    geoms = [unary_union([Polygon(p[0], p[1:]) for p in part["polys"]]) for part in parts]
    heights = [part["h"] for part in parts]
    tree = STRtree(geoms)
    out = set()
    for i, g in enumerate(geoms):
        if g.is_empty or _strip_width(g) >= TERRACE_MAX_WIDTH_M:
            continue
        up = down = False
        for j in tree.query(g, predicate="dwithin", distance=TERRACE_TOUCH_M):
            dh = heights[j] - heights[i]
            if TERRACE_STEP_MIN_M <= dh <= TERRACE_STEP_MAX_M:
                up = True
            elif TERRACE_STEP_MIN_M <= -dh <= TERRACE_STEP_MAX_M:
                down = True
        if up and down:
            out.add(i)
    return out


def _roughness(a: np.ndarray) -> np.ndarray:
    """3x3 nan-std per cell (float16), in row strips. Deviations are taken
    from the center cell before squaring, so float32 keeps cm precision at
    100 m heights."""
    H, W = a.shape
    out = np.full((H, W), np.nan, dtype=np.float16)
    for r0 in range(0, H, STRUCT_CHUNK_ROWS):
        r1 = min(r0 + STRUCT_CHUNK_ROWS, H)
        p = np.pad(a[max(r0 - 1, 0):min(r1 + 1, H)].astype(np.float32),
                   ((1 if r0 == 0 else 0, 1 if r1 == H else 0), (1, 1)), constant_values=np.nan)
        c = p[1:-1, 1:-1]
        s1 = np.zeros_like(c)
        s2 = np.zeros_like(c)
        n = np.zeros_like(c)
        for i in range(3):
            for j in range(3):
                d = p[i:i + c.shape[0], j:j + c.shape[1]] - c
                ok = np.isfinite(d)
                d = np.where(ok, d, 0)
                s1 += d
                s2 += d * d
                n += ok
        with np.errstate(invalid="ignore", divide="ignore"):
            var = s2 / n - (s1 / n) ** 2
        out[r0:r1] = np.where(np.isfinite(c), np.sqrt(np.clip(var, 0, None)), np.nan)
    return out


def _dilate(m: np.ndarray) -> np.ndarray:
    """3x3 binary dilation (scipy isn't a dependency)."""
    p = np.pad(m, 1)
    out = np.zeros_like(m)
    for i in range(3):
        for j in range(3):
            out |= p[i:i + m.shape[0], j:j + m.shape[1]]
    return out


def _coarse_ground(ground: np.ndarray, res: float, water_level):
    """(block grid, block size in cells): lowest ground per block, spread
    into empty blocks, then the water level (or NaN) where none is near."""
    import warnings

    B = max(int(round(STRUCT_BLOCK_M / res)), 1)
    H, W = ground.shape
    hb, wb = -(-H // B), -(-W // B)
    g = np.full((hb * B, wb * B), np.nan, dtype=np.float32)
    g[:H, :W] = ground
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        blocks = np.nanmin(g.reshape(hb, B, wb, B), axis=(1, 3))
        for _ in range(STRUCT_FILL_BLOCKS):
            gap = np.isnan(blocks)
            if not gap.any():
                break
            blocks[gap] = _median3(blocks)[gap]
    if water_level is not None:
        blocks = np.where(np.isnan(blocks), np.float32(water_level), blocks)
    return blocks, B


def structures(struct: np.ndarray, ground: np.ndarray, origin, res: float, footprints, water_level=None,
               exclude=None):
    """Extruded objects with no footprint (ships, cranes, container stacks;
    see STRUCT_*), each region shaped with building_parts so a ship's
    superstructure steps up from its hull.

    struct: class-1-only max-Z grid; ground: class-2 min-Z grid (NaN where
    none), both NAVD88 m on the DSM's grid convention. footprints: shapely
    polygons in local m. water_level: base over water, where there's no
    ground (None skips regions with no ground nearby). exclude: shapely
    polygons in local m whose cells can't be structures (buffered highway
    centerlines: I-95's decks are mostly class 1, not bridge class 17).
    Returns parts [{"h", "polys", "region", "over_water"}], "region"
    numbering the structures and "over_water" true where the base is the
    water level."""
    from rasterio.features import rasterize, shapes
    from shapely.geometry import shape as to_shape

    H, W = struct.shape
    tf = _transform(origin, res)
    blocks, B = _coarse_ground(ground, res, water_level)
    cand = np.zeros((H, W), dtype=bool)
    for r0 in range(0, H, STRUCT_CHUNK_ROWS):
        r1 = min(r0 + STRUCT_CHUNK_ROWS, H)
        base = blocks[np.arange(r0, r1)[:, None] // B, np.arange(W)[None, :] // B]
        with np.errstate(invalid="ignore"):
            above = struct[r0:r1] - base
            cand[r0:r1] = (above >= STRUCT_MIN_HEIGHT_M) & (above <= STRUCT_MAX_HEIGHT_M)
    shapes_out = [(f.buffer(STRUCT_FOOTPRINT_GAP_M), 1) for f in footprints or [] if not f.is_empty]
    shapes_out += [(g, 1) for g in exclude or [] if not g.is_empty]
    if shapes_out:
        near = rasterize(shapes_out, out_shape=(H, W), transform=tf, fill=0, dtype="uint8").astype(bool)
        cand &= ~near
        del near
    rough = _roughness(np.where(cand, struct, np.nan))
    # Flat cells plus one cell around them: a ship's hull-to-deckhouse step
    # is rough right at the step, and dropping it would split the ship
    cand &= _dilate(rough < STRUCT_MAX_ROUGH)
    if not cand.any():
        return []

    out = []
    pad = int(np.ceil(STRUCT_RING_M[1] / res)) + 1
    lo, hi = STRUCT_RING_M
    k = 0
    for geom, _ in shapes(cand.astype(np.uint8), mask=cand, transform=tf, connectivity=8):
        poly = to_shape(geom)
        if poly.area < STRUCT_MIN_M2:
            continue
        solidity = poly.area / poly.convex_hull.area
        if solidity < STRUCT_MIN_SOLIDITY:
            if os.environ.get("PP_LIDAR_LOG") == "1":
                c = poly.centroid
                print(f"lidar structure rejected (solidity {solidity:.2f}): {poly.area:.0f} m² at "
                      f"({c.x:.1f}, {c.y:.1f})", file=sys.stderr)
            continue
        minx, miny, maxx, maxy = poly.bounds
        c0 = max(int((minx - origin[0]) / res) - pad, 0)
        c1 = min(int((maxx - origin[0]) / res) + pad + 1, W)
        r0 = max(int((origin[1] - maxy) / res) - pad, 0)
        r1 = min(int((origin[1] - miny) / res) + pad + 1, H)
        sub_tf = _transform((origin[0] + c0 * res, origin[1] - r0 * res), res)
        shape_ = (r1 - r0, c1 - c0)
        inside = rasterize([(poly, 1)], out_shape=shape_, transform=sub_tf, fill=0, dtype="uint8").astype(bool)
        r = rough[r0:r1, c0:c1][inside].astype(np.float32)
        r = r[np.isfinite(r)]
        if not r.size or float(np.median(r)) >= STRUCT_MAX_ROUGH:
            continue
        ring = rasterize([(poly.buffer(hi).difference(poly.buffer(lo)), 1)], out_shape=shape_, transform=sub_tf,
                         fill=0, dtype="uint8").astype(bool)
        g = ground[r0:r1, c0:c1][ring]
        g = g[np.isfinite(g)]
        over_water = not g.size
        if g.size:
            base = float(np.percentile(g, 10))
        elif water_level is not None:
            base = float(water_level)  # over water: no ground returns
        else:
            continue
        # The ring base can sit above the coarse one that picked the cells
        # (a trailer row beside a raised lot); keep only what clears the floor
        parts = [p for p in building_parts(poly, struct, origin, res, base=base) or []
                 if p["h"] >= STRUCT_MIN_HEIGHT_M]
        if not parts:
            continue
        for part in parts:
            out.append({**part, "region": k, "over_water": over_water})
        k += 1
    return out


def photo_agrees(rgb: np.ndarray, over_water: bool, ring_rgb: np.ndarray | None = None) -> bool:
    """Whether the 2024 aerial shows something where a 2022 LiDAR structure
    stands (see PHOTO_*). rgb: (N, 3) pixels inside the structure; ring_rgb:
    pixels of the ground ring around it. Without a ring, a region that is
    one color is taken as empty water or pavement."""
    rgb = np.asarray(rgb, dtype=np.int16).reshape(-1, 3)
    if not len(rgb):
        return True  # nothing to judge by: keep the LiDAR's word
    own = (np.abs(rgb - np.median(rgb, axis=0)).max(axis=1) < PHOTO_COLOR_TOL).mean()
    ring_rgb = None if ring_rgb is None else np.asarray(ring_rgb, dtype=np.int16).reshape(-1, 3)
    if ring_rgb is None or not len(ring_rgb):
        return own < PHOTO_UNIFORM_FRAC
    same = (np.abs(rgb - np.median(ring_rgb, axis=0)).max(axis=1) < PHOTO_COLOR_TOL).mean()
    if same >= PHOTO_SAME_FRAC:
        return False
    return not (over_water and own >= PHOTO_UNIFORM_FRAC)

def dsm_from_las(paths, frame, bounds_local, res: float = 0.5, with_struct: bool = False):
    """Max-Z surface and min-Z ground grids (meters, NAVD88) over a local
    bounding box from City LAS tiles. Points are read in chunks and gridded
    with a sort-and-reduce, so a ~1 GB tile needs a few GB of RAM at most.

    Returns (dsm, ground, origin) where origin = (west, north) in local m.
    With with_struct=True, returns (dsm, ground, origin, struct): struct is
    the max Z of class 1 only (buildings, trees, ships, cranes, containers),
    for structures(); bridges (17), water (9) and ground (2) are left out.
    """
    import laspy
    from pyproj import Transformer

    e0, n0, e1, n1 = bounds_local
    W = int(np.ceil((e1 - e0) / res))
    H = int(np.ceil((n1 - n0) / res))
    origin = (e0, n1)
    dsm = np.full(H * W, -np.inf, dtype=np.float32)
    ground = np.full(H * W, np.inf, dtype=np.float32)
    struct = np.full(H * W, -np.inf, dtype=np.float32) if with_struct else None
    to_wgs = Transformer.from_crs(LAS_CRS, "EPSG:4326", always_xy=True)

    def reduce_into(target, idx, z, op):
        # A tile is bigger than the area, so many chunks have no points
        # inside it (reduceat fails on an empty array)
        if idx.size == 0:
            return
        order = np.argsort(idx, kind="stable")
        idx, z = idx[order], z[order]
        starts = np.flatnonzero(np.r_[True, idx[1:] != idx[:-1]])
        vals = op.reduceat(z, starts)
        cells = idx[starts]
        target[cells] = op(target[cells], vals)

    for path in paths:
        with laspy.open(path) as f:
            for pts in f.chunk_iterator(5_000_000):
                cls = np.asarray(pts.classification)
                keep = np.isin(cls, KEEP_CLASSES)
                if not keep.any():
                    continue
                x = np.asarray(pts.x)[keep]
                y = np.asarray(pts.y)[keep]
                z = (np.asarray(pts.z)[keep] * US_FT_TO_M).astype(np.float32)
                cls = cls[keep]
                lon, lat = to_wgs.transform(x, y)
                e, n = frame.to_local(lon, lat)
                col = ((np.asarray(e) - e0) / res).astype(np.int64)
                row = ((n1 - np.asarray(n)) / res).astype(np.int64)
                inside = (col >= 0) & (col < W) & (row >= 0) & (row < H)
                idx = row[inside] * W + col[inside]
                reduce_into(dsm, idx, z[inside], np.maximum)
                g = cls[inside] == GROUND_CLASS
                if g.any():
                    reduce_into(ground, idx[g], z[inside][g], np.minimum)
                if with_struct:
                    c1 = cls[inside] == 1
                    if c1.any():
                        reduce_into(struct, idx[c1], z[inside][c1], np.maximum)
    dsm = dsm.reshape(H, W)
    ground = ground.reshape(H, W)
    dsm[~np.isfinite(dsm)] = np.nan
    ground[~np.isfinite(ground)] = np.nan
    if with_struct:
        struct = struct.reshape(H, W)
        struct[~np.isfinite(struct)] = np.nan
        return dsm, ground, origin, struct
    return dsm, ground, origin


def footprint_base(footprint, ground: np.ndarray, origin, res: float):
    """A building's base elevation from ground returns (class 2).

    Usually the 10th percentile of ground in a 3-10 m ring around it: a roof
    hides the ground inside, and the low end of the ring is the street at the
    walls rather than a raised lawn or plaza. But the ring can dip into a
    cut or trench beside the building: at Franklin Field it catches the rail
    cut to the east, base 7.0 m vs. the field at ~11.7 m, so the stadium
    drew 4.7 m high. Footprints with at least INTERIOR_GROUND_M2 of their own
    ground returns (open-air stands, big courtyards, ground seen under open
    structures) say where their grade is: the base moves to their median,
    clamped to the ring's 10th-50th percentile. The clamp keeps the old base
    as a floor (track bed under 119 S 31st St at 3.9 m vs. a 7.7 m street)
    and the ring's median as a ceiling (ground-classified terraces inside
    HUP at 17.4 m vs. a 13.4 m street)."""
    from rasterio.features import rasterize

    def ground_in(geom):
        minx, miny, maxx, maxy = geom.bounds
        c0 = max(int((minx - origin[0]) / res), 0)
        c1 = min(int((maxx - origin[0]) / res) + 1, ground.shape[1])
        r0 = max(int((origin[1] - maxy) / res), 0)
        r1 = min(int((origin[1] - miny) / res) + 1, ground.shape[0])
        if c1 <= c0 or r1 <= r0:
            return np.array([], dtype=ground.dtype)
        tf = _transform((origin[0] + c0 * res, origin[1] - r0 * res), res)
        win = ground[r0:r1, c0:c1]
        m = rasterize([(geom, 1)], out_shape=win.shape, transform=tf, fill=0, dtype="uint8").astype(bool)
        vals = win[m]
        return vals[np.isfinite(vals)]

    ring = ground_in(footprint.buffer(10).difference(footprint.buffer(3)))
    if not ring.size:
        return None
    base = float(np.percentile(ring, 10))
    inner = footprint.buffer(-INSET_M)
    if not inner.is_empty:
        own = ground_in(inner)
        if own.size * res * res >= INTERIOR_GROUND_M2:
            base = float(np.clip(np.median(own), base, np.median(ring)))
    return base
