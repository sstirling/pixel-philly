"""Facades from the City's property records (OPA).

The aerial shows roofs, not walls, so renders have plain tinted walls and the
drawing model invents façades (brick with windows on everything, including
stadium seats). OPA records say what each building is: rowhouse, twin,
warehouse, office tower; how many stories; and the main material
("ROW 2 STY MASONRY"). This module joins records to footprints and turns them
into a small facade spec the renderer draws procedurally (render/render.js):
wall color, window color and grid, storefront, porch and cornice bands.

Join (join): footprint parcel_id_num -> pwd_parcels.parcelid -> brt_id =
OPA parcel_number (95% of Old City footprints), then footprint address = OPA
location (97%, but condos repeat an address: the majority style wins), then
OPA points inside the footprint. Measured Oct. 24.

Field notes (verified on live data):
- building_code_description: type, stories and material, the material as
  the last word (MASONRY, MASON, MAS+OTHER, FRAME, STONE, METAL).
- building_code_description_new: the style ("ROW PORCH FRONT", "TWIN
  CONVENTIONAL", "WAREHOUSE", "OFFICE BLDNG - High Rise"); null for codes 41-47.
- general_construction is undocumented; A looks like masonry, C/D frame, E/J
  stone. Used only when the code names no material.
- number_stories is null for many big buildings; then height / 3.2 m.
- year_built is unreliable for big public buildings; used only to tell a
  modern glass tower from a pre-war masonry one.

Editorial rule: exterior_condition (vacant, sealed) is never fetched or
drawn, so the map doesn't mark blocks by condition.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

STYLES = ["row_porch", "row_typical", "row_postwar", "row_modern", "river_row", "twin", "detached", "apartment_low",
          "mixed_storefront", "warehouse", "office_tower", "institutional", "other",
          # Era option only ("facade_eras": true); appended so the ids above don't change
          "row_old", "twin_old", "twin_postwar", "detached_postwar"]
STYLE_IDS = {s: i + 1 for i, s in enumerate(STYLES)}  # 0 = no facade (render.js)
BAND_STOREFRONT, BAND_PORCH, BAND_CORNICE, BAND_GLASS = 1, 2, 4, 8
BAND_PENT, BAND_HEAVY_CORNICE = 16, 32  # era option only (render.js facadeColor)

DEFAULT_FLOOR_M = 3.2
GLASS_HEIGHT_M = 45.0  # glass needs a tower this tall (and see modern_glass_record)
# Philadelphia's glass curtain-wall towers come with the post-1985 skyline
# (One Liberty Place, 1987, onward); the 1960s-early 70s towers (Academy House,
# 1972) are concrete or masonry. 1975 keeps those out with margin
GLASS_YEAR = 1975
NOT_GLASS_WORDS = ("GOV", "MUNICIPAL", "CULTURAL", "RELIGIOUS", "SCHOOL", "HOSPITAL")

# sRGB wall palettes per material; one entry per building, by a hash of its id
PALETTES = {
    "brick": [(152, 74, 58), (140, 66, 52), (165, 86, 66), (128, 62, 50), (158, 96, 74), (146, 80, 62)],
    "stone": [(176, 168, 150), (160, 156, 146), (190, 180, 160)],
    "frame": [(196, 192, 178), (170, 180, 186), (205, 198, 170), (150, 160, 150)],
    "metal": [(150, 154, 158), (130, 136, 140)],
    "glass": [(96, 120, 138), (80, 104, 124), (112, 132, 146)],
}
JITTER = 12  # +- per channel, so neighbors in a row differ slightly
WINDOW_RGB = {"glass": (44, 58, 72), "default": (52, 60, 70)}
# Bay spacing (m along the wall) per style
SPACING_M = {"row_porch": 1.8, "row_typical": 1.8, "row_postwar": 2.0, "row_modern": 2.0, "river_row": 1.8,
             "twin": 2.0, "detached": 2.4, "apartment_low": 2.6, "mixed_storefront": 1.8, "warehouse": 4.5,
             "office_tower": 1.6, "institutional": 3.0, "other": 2.6,
             "row_old": 1.8, "twin_old": 2.0, "twin_postwar": 2.0, "detached_postwar": 2.4}
GC_MATERIAL = {"A": "brick", "B": "brick", "C": "frame", "D": "frame", "E": "stone", "J": "stone"}
# Styles that really are brick housefronts; others above TALL_M or TALL_STORIES
# with "MASONRY" and no OSM colour take their own aerial colour instead
ROW_STYLES = {"row_porch", "row_typical", "row_postwar", "row_modern", "river_row", "twin", "detached",
              "row_old", "twin_old", "twin_postwar", "detached_postwar"}
# The wall_tint cutoff: above it walls kept the aerial colour before façades.
# Height only, not stories: a 5-6 story Center City building under 20 m was
# brick-tinted before façades and is usually brick
TALL_M = 20.0
# OSM building:material -> palette (concrete and plaster read as pale stone at this scale)
OSM_MATERIALS = {"brick": "brick", "stone": "stone", "limestone": "stone", "sandstone": "stone", "marble": "stone",
                 "granite": "stone", "concrete": "stone", "plaster": "stone", "glass": "glass", "metal": "metal",
                 "steel": "metal", "aluminium": "metal", "wood": "frame", "timber_framing": "frame"}
# --- Era option ("facade_eras": true) -------------------------------------
# Why and with what evidence: docs/building_age_styles.md (sections 1 and 3)
# and docs/building_age_plan.md, Phase A. OPA's year_built covers 98% of
# footprints, but 75% of years are assessor estimates heaped on round numbers
# (1925, 1920, 1950), so the style code decides the era where it names one
# and the year decides only otherwise. An estimated year still sets the era:
# a heaped year marks the block's era even when it is wrong for the house.
ERAS = ["unknown", "georgian_federal", "mid19", "late_victorian", "streetcar", "interwar", "postwar", "late20", "new"]
ERA_YEARS = [(1840, "georgian_federal"), (1880, "mid19"), (1905, "late_victorian"), (1930, "streetcar"),
             (1945, "interwar"), (1975, "postwar"), (2000, "late20"), (2027, "new")]
POSTWAR_WORDS = ("POST WAR", "RANCH", "CAPE", "SPLIT LEVEL", "BI LEVEL")
# Wall colors per era: only colors the sources name (brick; OSM color and
# the tall-building aerial rule still win). Postwar, late-20th-century and
# unknown keep PALETTES["brick"]: no source found names postwar Northeast
# brick colors (docs/building_age_styles.md, "Gaps").
ERA_PALETTES = {
    # Handmade brick, Flemish bond with dark glazed headers: a darker, mottled
    # red (PHC Old City inventory; SAH, Elfreth's Alley)
    "georgian_federal": [(124, 54, 44), (134, 60, 48), (114, 50, 42), (142, 66, 52), (128, 64, 54)],
    # Pressed red brick fronts (Encyclopedia of Greater Philadelphia,
    # "Brickmaking"); brownstone is not in OPA, so no brownstone here
    "mid19": [(150, 70, 56), (140, 64, 52), (158, 78, 60), (132, 62, 50)],
    # Adds yellow-tan and purplish-brown brick (PHC Southeast Spruce Hill)
    "late_victorian": [(152, 74, 58), (140, 66, 52), (186, 160, 112), (174, 150, 106), (112, 74, 68),
                       (102, 66, 62)],
    # Adds orange, "Pompeiian" and buff brick (PHC Girard Estate; PHC Old City,
    # "Tapestry Brick")
    "streetcar": [(152, 74, 58), (146, 80, 62), (180, 98, 60), (170, 90, 56), (160, 86, 58), (198, 172, 126)],
    "interwar": [(152, 74, 58), (146, 80, 62), (180, 98, 60), (170, 90, 56), (198, 172, 126), (188, 162, 118)],
    # New construction: metal, vinyl, stucco or composite panel, charcoal and
    # black brick (WHYY 2019; Hidden City field guides, 2012, 2015)
    "new": [(150, 150, 148), (136, 138, 140), (210, 208, 202), (196, 194, 188), (72, 72, 74), (60, 60, 64)],
}
HEAVY_CORNICE_ERAS = ("mid19", "late_victorian")  # bracketed wood or pressed-metal cornices
NO_CORNICE_STYLES = ("row_postwar", "row_modern", "twin_postwar", "detached_postwar")

FRONT_RAY_M = 25.0  # a wall faces a street if its outward ray meets a centerline this close
FRONT_MIN_EDGE_M = 2.0


def parse_building_code(desc):
    """(kind, stories, material) from building_code_description."""
    if not desc:
        return None, None, None
    d = desc.upper().strip()
    if d.startswith("ROW"):
        kind = "row"
    elif d.startswith("SEMI/DET"):
        kind = "twin"
    elif d.startswith("DET"):
        kind = "detached"
    elif d.startswith("APT"):
        kind = "apartment"
    elif "CONDO" in d and "PARKING" not in d:
        kind = "condo"
    elif d.startswith("IND"):
        kind = "industrial"
    elif d.startswith("OFF"):
        kind = "office"
    elif "CHURCH" in d or "SCHOOL" in d:
        kind = "institutional"
    elif d.startswith(("STORE", "STR")):
        kind = "store"
    else:
        kind = "other"
    m = re.search(r"(\d+(?:\.\d+)?)\s*STY", d)
    stories = int(round(float(m.group(1)))) if m else None
    last = d.split()[-1]
    if "MAS" in last:
        material = "brick"
    elif "FRAME" in last:
        material = "frame"
    elif "STONE" in last:
        material = "stone"
    elif "METAL" in last:
        material = "metal"
    else:
        material = None
    return kind, stories, material


def era_of(rec) -> str:
    """Era key (ERAS) for an OPA record: the style code where it names an era
    (POST WAR, RANCH, CAPE, SPLIT LEVEL, BI LEVEL -> postwar; ROW MODERN ->
    new), else the year; "OLD STYLE" keeps an early year but is never later
    than late_victorian. No plausible year -> unknown."""
    if not rec:
        return "unknown"
    new = (rec.get("building_code_description_new") or "").upper()
    if any(w in new for w in POSTWAR_WORDS):
        return "postwar"
    if "ROW MODERN" in new:
        return "new"
    year = _year(rec)
    era = next((name for limit, name in ERA_YEARS if year is not None and year < limit), "unknown")
    if "OLD STYLE" in new and (era == "unknown" or ERAS.index(era) > ERAS.index("late_victorian")):
        return "late_victorian"
    return era


def style_of(rec, height_m: float, eras: bool = False) -> str:
    """Facade style from a record's new and old building codes. eras=True
    (the "facade_eras" option) also returns row_old, twin_old, twin_postwar
    and detached_postwar, which today's styles fold into row_typical, twin
    and detached."""
    style = _style_of(rec, height_m)
    if not eras or not rec:
        return style
    new = (rec.get("building_code_description_new") or "").upper()
    era = era_of(rec)
    if style == "row_typical" and ("OLD STYLE" in new or era in ("georgian_federal", "mid19")):
        return "row_old"
    if style == "twin":
        if "OLD STYLE" in new:
            return "twin_old"
        if any(w in new for w in POSTWAR_WORDS):
            return "twin_postwar"
    if style == "detached" and any(w in new for w in POSTWAR_WORDS):
        return "detached_postwar"
    return style


def _style_of(rec, height_m: float) -> str:
    if not rec:
        return "other"
    new = (rec.get("building_code_description_new") or "").upper()
    old = (rec.get("building_code_description") or "").upper()
    cat = (rec.get("category_code_description") or "").upper()
    if new:
        if "PORCH FRONT" in new:
            return "row_porch"
        if "RIVER ROW" in new:
            return "river_row"
        if "POST WAR" in new and new.startswith("ROW"):
            return "row_postwar"
        if "ROW MODERN" in new:
            return "row_modern"
        if "MIXED" in new:
            return "mixed_storefront"
        if new.startswith(("ROW", "DOWNTOWN ROW")):
            return "row_typical"
        if new.startswith("TWIN"):
            return "twin"
        if "HIGH RISE" in new:
            return "office_tower"
        if "APARTMENT" in new:
            return "apartment_low"
        if "WAREHOUSE" in new or new.startswith(("IND", "FACTORY")):
            return "warehouse"
        if "OFFICE" in new:
            return "office_tower" if height_m > GLASS_HEIGHT_M else "other"
        if any(w in new for w in ("RELIGIOUS", "SCHOOL", "GOV", "MUNICIPAL", "HOSPITAL", "CHURCH", "COLLEGE",
                                  "CULTURAL")):
            return "institutional"
        if "DETACHED" in new or "SINGLE" in new:
            return "detached"
    kind, _, _ = parse_building_code(old)
    if kind == "row":
        mixed = "STR" in old or "STORE" in old or "MIXED" in cat
        return "mixed_storefront" if mixed else "row_typical"
    if kind == "twin":
        return "twin"
    if kind == "detached":
        return "detached"
    if kind == "apartment":
        return "apartment_low"
    if kind == "condo":
        return "office_tower" if height_m > GLASS_HEIGHT_M else "apartment_low"
    if kind == "industrial":
        return "warehouse"
    if kind == "office":
        return "office_tower" if height_m > GLASS_HEIGHT_M else "other"
    if kind == "institutional":
        return "institutional"
    return "other"


def modern_glass_record(rec, height_m: float) -> bool:
    """OPA evidence of a glass curtain-wall tower: a high-rise office building
    (not apartments, hotels or a public building), taller than GLASS_HEIGHT_M,
    built GLASS_YEAR or later by a recorded (not estimated) year. OPA's year
    is wrong for some public buildings (City Hall: 2015), hence the
    exclusions; anything else gets no glass."""
    if not rec or height_m <= GLASS_HEIGHT_M:
        return False
    new = (rec.get("building_code_description_new") or "").upper()
    text = new + " " + (rec.get("category_code_description") or "").upper()
    # "OFFICE BLDNG - High Rise" only: the Mid Rise code covers masonry
    # offices like 1625 Chestnut St (1990, 57 m)
    if "OFFICE" not in new or "HIGH RISE" not in new or any(w in text for w in NOT_GLASS_WORDS):
        return False
    if str(rec.get("year_built_estimate") or "").strip().upper() == "Y":
        return False
    year = _year(rec)
    return year is not None and year >= GLASS_YEAR


def glassish(rgb) -> bool:
    """A blue-to-teal, not-too-saturated OSM colour that reads as glass."""
    import colorsys

    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return 0.47 <= h <= 0.67 and 0.12 <= s <= 0.75 and v >= 0.2


def _year(rec):
    try:
        y = int(str(rec.get("year_built") or "").strip())
        return y if y > 1600 else None
    except ValueError:
        return None


def _jitter(rgb, key: str):
    h = hashlib.md5(key.encode()).digest()
    return [max(0, min(255, c + (h[i] % (2 * JITTER + 1)) - JITTER)) for i, c in enumerate(rgb)]


def _pick(seq, key: str):
    return seq[int(hashlib.md5(("p" + key).encode()).hexdigest(), 16) % len(seq)]


def _typology(height_m: float, footprint) -> tuple[str, str]:
    """Default style and material for a footprint with no record."""
    if height_m > GLASS_HEIGHT_M:
        return "office_tower", "brick"  # never assumed glass; tall: its own aerial colour (facade_spec)
    r = footprint.minimum_rotated_rectangle
    xs, ys = r.exterior.coords.xy
    sides = sorted(((xs[i + 1] - xs[i]) ** 2 + (ys[i + 1] - ys[i]) ** 2) ** 0.5 for i in range(2))
    if footprint.area > 2500 and height_m <= 20:
        return "warehouse", "brick"
    if sides[0] <= 7.5 and height_m <= 15:
        return "row_typical", "brick"
    return "other", "brick"


def facade_spec(rec, height_m: float, footprint, bid, osm=None, front=None, eras: bool = False) -> dict:
    """Facade of one building. rec: its OPA record (or None: a typology
    default by height and footprint shape); height_m: the building's height;
    footprint: shapely polygon (local m); bid: building id, which seeds the
    small per-building color variation. osm: osm_match() for this footprint
    or LiDAR part. front: front_dirs() (street-facing wall directions).
    eras: the "facade_eras" option (era styles, palettes and bands; see
    ERA_PALETTES); False gives exactly the output from before the option.

    Wall colour precedence: OSM colour, then OSM material, then the OPA
    material's palette. Except: a non-rowhouse building above TALL_M whose
    only clue is OPA "MASONRY" gets roof_color, and
    05_build_scene.py fills in its own colour sampled from the aerial (the
    look before façades): MASONRY also covers limestone and terra cotta,
    and at City Hall pale stone towers had turned brick red."""
    key = str(bid)
    if rec:
        style = style_of(rec, height_m, eras=eras)
        _, _, material = parse_building_code(rec.get("building_code_description"))
        material = material or GC_MATERIAL.get((rec.get("general_construction") or "").strip().upper(), "brick")
        try:
            stories = int(rec.get("number_stories") or 0)
        except (TypeError, ValueError):
            stories = 0
    else:
        style, material = _typology(height_m, footprint)
        stories = 0
    if stories <= 0:
        stories = max(1, int(round(height_m / DEFAULT_FLOOR_M)))
    floor_h = min(5.0, max(2.6, height_m / stories)) if height_m > 0 else DEFAULT_FLOOR_M
    osm = osm or {}
    source, roof_color = "palette", False
    # Glass only on evidence: OSM (material glass, or a glass-blue colour),
    # else an OPA record that is clearly a modern office tower. When OSM
    # gives a colour or material, it decides
    if osm.get("material"):
        material, source = osm["material"], "osm_material"
    if osm.get("colour") and glassish(osm["colour"]):
        material = "glass"
    elif not osm and style == "office_tower" and modern_glass_record(rec, height_m):
        material = "glass"
    era = era_of(rec) if eras else None
    wall = _jitter(_pick(PALETTES[material], key), key)
    if (eras and source == "palette" and material == "brick" and era in ERA_PALETTES
            and (era != "new" or style == "row_modern")):
        wall, source = _jitter(_pick(ERA_PALETTES[era], key), key), "palette_era"
    if osm.get("colour"):
        wall, source = list(osm["colour"]), "osm"
    elif source in ("palette", "palette_era") and material == "brick" and style not in ROW_STYLES and height_m > TALL_M:
        roof_color, source = True, "aerial"
    window = list(WINDOW_RGB["glass" if material == "glass" else "default"])
    cornice = style.startswith("row_") or style in ("river_row", "mixed_storefront")
    extra = {}
    if eras:
        cornice = cornice and style not in NO_CORNICE_STYLES
        extra = {"era": era, "pent": style == "row_old" and era == "georgian_federal",
                 "heavy_cornice": cornice and era in HEAVY_CORNICE_ERAS}
    return {
        "color_source": source,
        "roof_color": roof_color,
        "front": list(front or []),
        "style": style,
        "material": material,
        "stories": stories,
        "floor_h": round(floor_h, 2),
        "wall_rgb": wall,
        "window_rgb": window,
        "spacing_m": SPACING_M[style],
        "storefront": style == "mixed_storefront",
        "porch": style == "row_porch",
        "cornice": cornice,
        "glass": material == "glass",
        **extra,
    }


def compact(spec: dict) -> dict:
    """The scene JSON form render.js reads: s style id, w wall rgb, g window
    rgb, f floor height m, p bay spacing m, b band flags (BAND_*); d up to
    two street-facing directions (east, north unit vectors, zero-padded;
    absent: every wall counts as street-facing); u use the aerial colour."""
    bands = ((BAND_STOREFRONT if spec["storefront"] else 0) | (BAND_PORCH if spec["porch"] else 0)
             | (BAND_CORNICE if spec["cornice"] else 0) | (BAND_GLASS if spec["glass"] else 0)
             | (BAND_PENT if spec.get("pent") else 0) | (BAND_HEAVY_CORNICE if spec.get("heavy_cornice") else 0))
    out = {"s": STYLE_IDS[spec["style"]], "w": spec["wall_rgb"], "g": spec["window_rgb"], "f": spec["floor_h"],
           "p": spec["spacing_m"], "b": bands}
    if "era" in spec:
        out["e"] = ERAS.index(spec["era"])  # era option: for QA and review; render.js ignores it
    if spec.get("roof_color"):
        out["u"] = 1  # 05_build_scene.py replaces w with the aerial colour and drops this
    if spec.get("front"):
        dirs = [round(float(v), 4) for d in spec["front"][:2] for v in d]
        out["d"] = dirs + [0.0] * (4 - len(dirs))
    return out


def _norm_addr(a):
    return re.sub(r"\s+", " ", str(a or "").upper()).strip()


def _majority(rows):
    """The record whose style is most common (condos: many rows on one building)."""
    if not rows:
        return None
    key = lambda r: r.get("building_code_description_new") or r.get("building_code_description") or ""  # noqa: E731
    top, _ = Counter(key(r) for r in rows).most_common(1)[0]
    return next(r for r in rows if key(r) == top)


def join(footprints, opa_rows, pwd):
    """{footprint id: (record or None, "parcel" | "address" | "point" | None)}.

    footprints: dicts with id, parcel_id_num, address, geom (shapely, any CRS
    shared with the rows' "_pt" points). opa_rows: OPA records with "_pt".
    pwd: {pwd parcelid (str): brt_id}. Precedence: parcel key, then address
    (a range like "100-16 S ..." also tries its first number), then OPA
    points inside the footprint; several rows -> the majority style."""
    from shapely.strtree import STRtree

    by_parcel, by_addr = {}, {}
    for r in opa_rows:
        by_parcel.setdefault(str(r.get("parcel_number")), []).append(r)
        by_addr.setdefault(_norm_addr(r.get("location")), []).append(r)
    pts = [r["_pt"] for r in opa_rows]
    tree = STRtree(pts) if pts else None
    out = {}
    for fp in footprints:
        pid = fp.get("parcel_id_num")
        try:
            pid = str(int(float(pid))) if pid not in (None, "") else None
        except ValueError:
            pid = None
        brt = pwd.get(pid) if pid else None
        rows = by_parcel.get(str(brt)) if brt else None
        if rows:
            out[fp["id"]] = (_majority(rows), "parcel")
            continue
        addr = _norm_addr(fp.get("address"))
        rows = None
        if addr:
            rows = by_addr.get(addr) or by_addr.get(re.sub(r"^(\d+)-\d+[A-Z]?\b", r"\1", addr))
        if rows:
            out[fp["id"]] = (_majority(rows), "address")
            continue
        inside = [opa_rows[i] for i in tree.query(fp["geom"], predicate="contains")] if tree else []
        out[fp["id"]] = (_majority(inside), "point") if inside else (None, None)
    return out


def front_dirs(footprint, streets) -> list[tuple[float, float]]:
    """Street-facing wall directions (outward unit normals, local east/north)
    for porch and storefront bands, at most two (a corner lot).

    A wall edge faces a street when a ray from its midpoint along its
    outward normal meets a street centerline (City Street_Centerline, all
    classes) within FRONT_RAY_M. The nearest hit is the front; a second hit
    pointing more than 60 degrees away is a corner's side street. A
    rowhouse's front is a short side, but so is its back on an alley, which
    the centerline layer mostly lacks; this picks the street side without
    guessing from shape."""
    from shapely.geometry import LineString, Polygon
    from shapely.geometry.polygon import orient
    from shapely.ops import unary_union

    if not streets:
        return []
    poly = footprint if footprint.geom_type == "Polygon" else max(getattr(footprint, "geoms", []), key=lambda g: g.area)
    poly = orient(Polygon(poly.exterior).simplify(0.3), 1.0)  # counter-clockwise: outward normal = (dy, -dx)
    lines = unary_union([s for s in streets if s.distance(poly) <= FRONT_RAY_M + 5])
    if lines.is_empty:
        return []
    hits = []
    pts = list(poly.exterior.coords)
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        length = (dx * dx + dy * dy) ** 0.5
        if length < FRONT_MIN_EDGE_M:
            continue
        nx, ny = dy / length, -dx / length
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ray = LineString([(mx + 0.05 * nx, my + 0.05 * ny), (mx + FRONT_RAY_M * nx, my + FRONT_RAY_M * ny)])
        hit = ray.intersection(lines)
        if not hit.is_empty:
            hits.append((hit.distance(LineString([(mx, my), (mx + 1e-9, my)])), (nx, ny)))
    if not hits:
        return []
    hits.sort(key=lambda h: h[0])
    first = hits[0][1]
    out = [first]
    for _, d in hits[1:]:
        if d[0] * first[0] + d[1] * first[1] < 0.5:
            out.append(d)
            break
    return [(round(a, 6) + 0.0, round(b, 6) + 0.0) for a, b in out]


def parse_colour(value):
    """OSM building:colour (hex or a CSS colour name) -> (r, g, b), or None."""
    if not value or not str(value).strip():
        return None
    from PIL import ImageColor

    try:
        return tuple(ImageColor.getrgb(str(value).strip())[:3])
    except ValueError:
        return None


def osm_material(tag):
    """OSM building:material -> a palette material, or None."""
    return OSM_MATERIALS.get(str(tag or "").strip().lower())


def osm_index(items) -> dict:
    """items with an STRtree over their shapes, for osm_match over many
    footprints and parts (a region: ~116k footprints, ~233k parts)."""
    from shapely import STRtree

    return {"items": items, "tree": STRtree([it["geom"] for it in items])}


def osm_match(geom, items) -> dict:
    """OSM colour and material for a footprint or LiDAR part: from OSM shapes
    that overlap it mutually by half or more (each covers >= 50% of the
    other), building:part shapes first (a tower's top), then larger overlap.
    items: [{"geom", "tags", "part"}], or osm_index(items) (same result,
    via the spatial index). Returns {"colour", "material"} (keys only when
    found)."""
    if isinstance(items, dict):
        idx = items["tree"].query(geom)
        items = [items["items"][i] for i in sorted(idx)]
    found = []
    for it in items:
        g = it["geom"]
        if not g.intersects(geom):
            continue
        inter = g.intersection(geom).area
        if inter < 0.5 * geom.area or inter < 0.5 * g.area:
            continue
        found.append((not it.get("part"), -inter, it["tags"]))
    found.sort(key=lambda f: (f[0], f[1]))
    out = {}
    for _, _, tags in found:
        if "colour" not in out:
            c = parse_colour(tags.get("building:colour"))
            if c:
                out["colour"] = c
        if "material" not in out:
            m = osm_material(tags.get("building:material"))
            if m:
                out["material"] = m
    return out
