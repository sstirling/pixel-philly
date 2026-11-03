"""Repaint open water in the stitched AI redraws with one consistent style.

Gemini picks its own river color in every frame (blue, brown, olive, tan),
which leaves the Delaware as a patchwork, and it sometimes invents objects on
open water. tiny.london fixed the same problems with a water check against
OpenStreetMap and a local repair. This does the deterministic equivalent on
the whole mosaic; the rules and style are in src/pixelphilly/waterpaint.py.

It then clears everything where the city has no aerial imagery (the New
Jersey side of the river on the downtown map) to the viewer's background
color. The scene is flat grey there, and the model invents content on
featureless input; see src/pixelphilly/nodata.py.

Writes output/postprocessed/<prompt>/water/<frame>.png, mosaic.png,
water_mask.png and report.json (including the render's water color model,
which 13_build_trainset.py reuses for training targets), and prints seam
ratios before and after.

Usage: uv run python scripts/10_repaint_water.py --prompt redraw_v3

Regions (an area drawn next to one already finished, 15_joint_sample.py
--known-area): only frames with a redraw are repainted and written; the
known band's frames belong to the known area. Their FINISHED frames
(output/<known>/postprocessed/<prompt>/<stage>/) give the halo context, and
ripples are placed in the known area's mosaic coordinates so they continue
across the join. The known area comes from the run's result.json, or from
--known-area. The mosaic.png is skipped for regions: 16_build_tiles.py
--areas reads per-frame files.
"""

import argparse
import json

import numpy as np
from PIL import Image, ImageFilter

from shapely.ops import unary_union

from pixelphilly import nodata, waterpaint
from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.qa import seam_ratio
from pixelphilly.regions import PlacedFrame, known_sources, place_frames, ripple_offset, ripple_root


def load_mosaic(frames, size, folder, cols, rows, mode="RGB"):
    m = Image.new(mode, (cols * size, rows * size))
    for f in frames:
        m.paste(Image.open(folder / f"{f.name}.png").convert(mode), (f.col * size, f.row * size))
    return m


HALO = 32  # px of neighboring frames read around each frame in the tiled path


class FrameReader:
    """Read any mosaic-coordinate rectangle from per-frame PNGs, without ever
    assembling the whole mosaic (a downtown mosaic is ~570 MP)."""

    def __init__(self, folder, frames, size, mode="RGB", paths=None):
        """paths: optional {frame name: file} overriding folder/<name>.png;
        frames missing from it read as empty (regions: redraws_paths)."""
        self.folder, self.size, self.mode, self.paths = folder, size, mode, paths
        self.by_cell = {(f.col, f.row): f for f in frames if paths is None or f.name in paths}
        self.cache = {}

    def frame(self, col, row):
        if (col, row) not in self.by_cell:
            return None
        if (col, row) not in self.cache:
            if len(self.cache) > 64:
                self.cache.clear()
            f = self.by_cell[(col, row)]
            path = self.folder / f"{f.name}.png" if self.paths is None else self.paths[f.name]
            self.cache[(col, row)] = np.asarray(Image.open(path).convert(self.mode))
        return self.cache[(col, row)]

    def region(self, x0, y0, w, h):
        chans = 3 if self.mode == "RGB" else 1
        out = np.zeros((h, w, chans), np.uint8) if chans == 3 else np.zeros((h, w), np.uint8)
        s = self.size
        for row in range(y0 // s, (y0 + h - 1) // s + 1):
            for col in range(x0 // s, (x0 + w - 1) // s + 1):
                img = self.frame(col, row)
                if img is None:
                    continue
                fx0, fy0 = col * s, row * s
                ax, ay = max(x0, fx0), max(y0, fy0)
                bx, by = min(x0 + w, fx0 + s), min(y0 + h, fy0 + s)
                if ax < bx and ay < by:
                    out[ay - y0:by - y0, ax - x0:bx - x0] = img[ay - fy0:by - fy0, ax - fx0:bx - fx0]
        return out


def frames_to_write(frames, redraw_dir):
    """Frames with a redraw. A region run leaves its known band undrawn
    (South's frames); every frame of a single-area run has one."""
    return [f for f in frames if (redraw_dir / f"{f.name}.png").exists()]


def redraw_paths(frames, redraw_dir, shared=None, known_dir=None, known_paths=None):
    """{frame name: PNG} for the redraw reader: this run's redraw where there
    is one, else, for a known-band frame, the known areas' finished pixel
    for that cell (known_paths: {frame name: PNG}, from
    regions.known_sources, i.e. the merged map's pixels; or, one known area,
    shared + known_dir), so halos at the join see the neighbors' pixels."""
    paths = {}
    for f in frames:
        own = redraw_dir / f"{f.name}.png"
        if own.exists():
            paths[f.name] = own
        elif known_paths and f.name in known_paths:
            paths[f.name] = known_paths[f.name]
        elif shared and f.name in shared:
            paths[f.name] = known_dir / f"{shared[f.name]}.png"
    return paths


class BandContext:
    """Frames and files for repainting the known band in this area's mosaic
    (frames: this area's lattice plus the known areas' frames beyond it,
    placed by screen position; paths: {frame name: PNG})."""

    def __init__(self, frames, paths):
        self.frames, self.paths = frames, paths


def band_context_multi(frames, known, owners, own_path, known_path):
    """Per-cell sources for the band repaint with any number of known areas.

    known: [(area, frames)] in precedence order. owners: {this frame name:
    (owning area, its frame name)} for band cells. own_path(f) and
    known_path(area, frame name) give the files. Cells of this lattice: the
    owner's file for band cells, this area's otherwise. Cells beyond this
    lattice: the first known area that has them (placed by screen position,
    named "known:<area>:<frame>" since lattice names repeat between areas)."""
    out, paths, taken = [], {}, set()
    for f in frames:
        out.append(f)
        taken.add((f.x0, f.y0))
        paths[f.name] = known_path(*owners[f.name]) if f.name in owners else own_path(f)
    for area, kframes in known:
        for p in place_frames(kframes, frames):
            if (p.x0, p.y0) in taken:
                continue
            taken.add((p.x0, p.y0))
            q = PlacedFrame(col=p.col, row=p.row, x0=p.x0, y0=p.y0, size=p.size, name=f"known:{area}:{p.name}")
            out.append(q)
            paths[q.name] = known_path(area, p.name)
    return BandContext(out, paths)


def band_context(frames, kframes, shared, own_dir, known_dir, known_only_dir=None):
    """band_context_multi for one known area: shared {this frame name: known
    frame name}; known_dir for band cells, known_only_dir (default
    known_dir) beyond this lattice."""
    known_only_dir = known_only_dir or known_dir
    owners = {n: ("known", k) for n, k in shared.items()}
    ctx = band_context_multi(frames, [("known", kframes)], owners, lambda f: own_dir / f"{f.name}.png",
                             lambda area, name: known_dir / f"{name}.png")
    for name in list(ctx.paths):
        if name.startswith("known:"):
            ctx.paths[name] = known_only_dir / f"{name.split(':')[-1]}.png"
    return ctx


def repaint_band(cfg, args, frame, cam, frames, known, sources, ripple, x_origin, y_origin):
    """Repaint the known band (frames this area shares with known areas) from
    each owning area's PRE-repaint redraws, with context from all areas.

    When a known area (South) was repainted, the frames beyond its lattice
    (now this area's) didn't exist: its water mask stopped at its edge and
    the repaint drew a shore band along that frame edge, now the join (a
    hard dark 4 px line in open water across the Schuylkill, seam ratio
    7.6). Repainting the band with both sides present removes it. Each
    owner's own color model is used, and ripples are placed in the root
    area's coordinates (ripple), so water comes out the same wherever
    nothing else changed. Written to water_band/<owner>/<owner's frame
    name>.png (owners' frame names repeat) with report.json "owners";
    16_build_tiles.py --areas (regions.cell_sources) uses them in place of
    the owners' finished frames."""
    size = cfg["camera"]["frame_px"]
    owners = {n: (o, k) for n, (o, k, _) in sources.items()}
    kmap = {k["cfg"]["name"]: k for k in known}
    models = {}
    for area, k in kmap.items():
        rep = json.loads((REPO_ROOT / "output" / area / "postprocessed" / k["prompt"] / "water" / "report.json").read_text())
        models[area] = (np.asarray(rep["render_water_median_rgb"], float), float(rep["color_threshold"]))
    kframes = [(a, k["frames"]) for a, k in kmap.items()]
    root = lambda area: REPO_ROOT / "output" / area  # noqa: E731
    rctx = band_context_multi(frames, kframes, {}, lambda f: area_dir(cfg, "renders", f"{f.name}.png"),
                              lambda a, n: root(a) / "renders" / f"{n}.png")
    mctx = band_context_multi(frames, kframes, {}, lambda f: area_dir(cfg, "masks", f"{f.name}.png"),
                              lambda a, n: root(a) / "masks" / f"{n}.png")
    dctx = band_context_multi(frames, kframes, owners, lambda f: area_dir(cfg, "redraws", args.prompt, f"{f.name}.png"),
                              lambda a, n: root(a) / "redraws" / kmap[a]["prompt"] / f"{n}.png")
    renders = FrameReader(None, rctx.frames, size, paths=rctx.paths)
    masks = FrameReader(None, mctx.frames, size, "L", paths=mctx.paths)
    redraws = FrameReader(None, dctx.frames, size, paths=dctx.paths)
    cfgs = [cfg] + [k["cfg"] for k in known]
    nhd_geom = unary_union([waterpaint.nhd_geometry(c, frame, cam, x_origin, y_origin) for c in cfgs])
    nd_geom = unary_union([nodata.nodata_geometry(c, frame, cam, x_origin, y_origin) for c in cfgs])
    ox, oy = ripple
    out_dir = area_dir(cfg, "postprocessed", args.prompt, "water_band")
    band = [f for f in frames if f.name in owners]
    repainted = 0
    for f in band:
        owner, kname = owners[f.name]
        median, threshold = models[owner]
        gx, gy = f.col * size - HALO, f.row * size - HALO
        span = size + 2 * HALO
        render = renders.region(gx, gy, span, span)
        bmask = waterpaint.grow(masks.region(gx, gy, span, span) > 127)
        nhd = waterpaint.rasterize_view(nhd_geom, gx, gy, 1.0, span, span)
        water = waterpaint.water_mask(render, nhd, bmask, median, threshold)
        out = waterpaint.apply(redraws.region(gx, gy, span, span).copy(), water, gx + ox, gy + oy, 1.0)
        if not nd_geom.is_empty:
            out[nodata.nodata_mask(nd_geom, gx, gy, span, span)] = nodata.BACKGROUND
        (out_dir / owner).mkdir(parents=True, exist_ok=True)
        Image.fromarray(out[HALO:HALO + size, HALO:HALO + size]).save(out_dir / owner / f"{kname}.png")
        repainted += int(water[HALO:HALO + size, HALO:HALO + size].sum())
    used = sorted({owners[f.name][0] for f in band}, key=list(kmap).index)
    report = {"owners": used,
              "frames_written": {a: sum(1 for f in band if owners[f.name][0] == a) for a in used},
              "color_models": {a: {"render_water_median_rgb": models[a][0].tolist(), "color_threshold": models[a][1]}
                               for a in used},
              "ripple_offset_px": [ox, oy], "water_px_repainted": repainted,
              "frames": {a: {owners[f.name][1]: f.name for f in band if owners[f.name][0] == a} for a in used}}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def known_for(cfg, args):
    """[{"cfg", "frames", "prompt", "stage"}] for a region run's known areas
    in precedence order, or []. --known-area (comma list) wins; otherwise
    the run's result.json (written by 15_joint_sample.py --collect) names
    them ("areas", or "area" for runs before several known areas)."""
    areas, prompt, stage = args.known_area, args.known_prompt or args.prompt, args.known_stage or "water"
    if areas:
        areas = [a.strip() for a in areas.split(",") if a.strip()]
    else:
        info = known_info(cfg["name"], args.prompt)
        if not info:
            return []
        areas = info.get("areas") or [info["area"]]
        prompt, stage = args.known_prompt or info["run"], args.known_stage or info.get("stage") or "water"
    out = []
    for a in areas:
        kcfg = load_config(a)
        out.append({"cfg": kcfg, "frames": area_setup(kcfg)[2], "prompt": prompt, "stage": stage})
    return out


def known_info(area, prompt):
    res = REPO_ROOT / "output" / area / "joint" / prompt / "result.json"
    return json.loads(res.read_text()).get("known") if res.exists() else None


def ripple_reference(cfg, args, known):
    """(root area name, offset px): ripples go in the root area's mosaic
    coordinates (regions.ripple_root: follow each run's first known area to
    the area drawn alone, South), the same reference for every region."""
    names = [k["cfg"]["name"] for k in known]

    def known_of(area):
        if area == cfg["name"]:
            return names
        info = known_info(area, args.prompt)
        return (info.get("areas") or [info["area"]]) if info else None

    root = ripple_root(cfg["name"], known_of)
    _, _, frames = area_setup(cfg)
    return root, ripple_offset(frames, area_setup(load_config(root))[2])


def main_tiled(cfg, args, frame, cam, frames):
    """Frame-by-frame repaint for large areas. Each frame is processed with a
    HALO of its neighbors so shore bands and ripples continue across frame
    edges; the color model is sampled from all frames first."""
    size = cfg["camera"]["frame_px"]
    x_origin = min(f.x0 - f.col * size for f in frames)
    y_origin = min(f.y0 - f.row * size for f in frames)
    out_dir = area_dir(cfg, "postprocessed", args.prompt, "water")
    out_dir.mkdir(parents=True, exist_ok=True)
    renders = FrameReader(area_dir(cfg, "renders"), frames, size)
    masks = FrameReader(area_dir(cfg, "masks"), frames, size, "L")
    redraw_dir = area_dir(cfg, "redraws", args.prompt)
    known = known_for(cfg, args)
    if known:
        names = [k["cfg"]["name"] for k in known]
        prompt = known[0]["prompt"]
        found = sorted(p.parts[-5] for p in (REPO_ROOT / "output").glob(f"*/postprocessed/{prompt}/water_band/report.json"))
        sources = known_sources(frames, [(k["cfg"]["name"], k["frames"]) for k in known], prompt, known[0]["stage"],
                                REPO_ROOT, override_from=names + [a for a in found if a not in names + [cfg["name"]]])
        missing = [str(p) for _, _, p in sources.values() if not p.exists()]
        if missing:
            raise SystemExit(f"{len(missing)} finished known frames missing, e.g. {missing[:3]}")
        redraws = FrameReader(redraw_dir, frames, size,
                              paths=redraw_paths(frames, redraw_dir, known_paths={n: p for n, (_, _, p) in sources.items()}))
        root, (ox, oy) = ripple_reference(cfg, args, known)
        todo = frames_to_write(frames, redraw_dir)
        per_area = {a: sum(1 for o, _, _ in sources.values() if o == a) for a in names}
        print(f"region run next to {', '.join(names)}: {len(todo)} frames to repaint, {len(sources)} known-band frames "
              f"({per_area}); ripples in {root}'s coordinates, offset ({ox}, {oy}) px")
    else:
        redraws = FrameReader(redraw_dir, frames, size)
        ox, oy = 0, 0
        todo = frames
    nhd_geom = waterpaint.nhd_geometry(cfg, frame, cam, x_origin, y_origin)
    nd_geom = nodata.nodata_geometry(cfg, frame, cam, x_origin, y_origin)

    # Color model of open water from the render, sampled across all frames
    samples = []
    for f in frames:
        gx, gy = f.col * size, f.row * size
        nhd = waterpaint.rasterize_view(nhd_geom, gx, gy, 1.0, size, size)
        if nhd.sum() < 5000:
            continue
        core = np.asarray(Image.fromarray(nhd.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(31))) > 127
        b = waterpaint.grow(masks.frame(f.col, f.row) > 127)
        samples.append(renders.frame(f.col, f.row)[core & ~b][::7])
    sample = np.concatenate(samples).astype(int)
    median = np.median(sample, axis=0)
    typical = np.median(np.abs(sample - median).max(axis=1))
    threshold = max(30.0, 4.0 * float(typical))

    repainted = cleared = 0
    for f in todo:
        gx, gy = f.col * size - HALO, f.row * size - HALO
        span = size + 2 * HALO
        render = renders.region(gx, gy, span, span)
        bmask = waterpaint.grow(masks.region(gx, gy, span, span) > 127)
        nhd = waterpaint.rasterize_view(nhd_geom, gx, gy, 1.0, span, span)
        water = waterpaint.water_mask(render, nhd, bmask, median, threshold)
        out = waterpaint.apply(redraws.region(gx, gy, span, span).copy(), water, gx + ox, gy + oy, 1.0)
        if not nd_geom.is_empty:
            # Mask over the haloed region, so growth reaches in from neighbors
            nd = nodata.nodata_mask(nd_geom, gx, gy, span, span)
            out[nd] = nodata.BACKGROUND
            cleared += int(nd[HALO:HALO + size, HALO:HALO + size].sum())
        Image.fromarray(out[HALO:HALO + size, HALO:HALO + size]).save(out_dir / f"{f.name}.png")
        repainted += int(water[HALO:HALO + size, HALO:HALO + size].sum())

    if not known:
        cols = max(f.col for f in frames) + 1
        rows = max(f.row for f in frames) + 1
        mosaic = Image.new("RGB", (cols * size, rows * size))
        for f in frames:
            mosaic.paste(Image.open(out_dir / f"{f.name}.png"), (f.col * size, f.row * size))
        mosaic.save(out_dir / "mosaic.png")
    report = {"render_water_median_rgb": [round(v, 1) for v in median.tolist()],
              "color_threshold": round(float(threshold), 1), "water_px_repainted": repainted,
              "nodata_px_cleared": cleared, "mode": "per-frame with halo", "halo_px": HALO}
    if known:
        band_report = repaint_band(cfg, args, frame, cam, frames, known, sources, (ox, oy), x_origin, y_origin)
        report["known_band_repaint"] = {k: v for k, v in band_report.items() if k != "frames"}
    if known:
        report["region"] = {"known_areas": names, "known_band_frames": per_area, "frames_written": len(todo),
                            "ripple_root": root, "ripple_offset_px": [ox, oy],
                            "mosaic_png": "skipped (16_build_tiles.py --areas)"}
    if args.invented_water == "fix":
        report["invented_water"] = fix_invented_water(cfg, frame, cam, frames, args, out_dir)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


# --- invented water on land (pixelphilly.invented_water) ----------------------
INVENTED_HALO = 128  # px of context around each frame when looking for blobs
WATER_MARGIN_PX = 24  # mapped water (NHD, PWD) grown by ~7 m: shores and piers stay the repaint's business
POOL_RADIUS_PX = 85  # ~25 m: a blob this close to a City pool point is that pool


def invented_water_context(cfg, frame, cam, x_origin, y_origin):
    """(mapped water grown by WATER_MARGIN_PX, City pool points, NWI wetlands)
    in mosaic px."""
    from shapely.geometry import shape

    water = unary_union([waterpaint.water_geometry(cfg, frame, cam, x_origin, y_origin, s)
                         for s in ("water_nhd", "water")]).buffer(WATER_MARGIN_PX)
    pools = []
    path = REPO_ROOT / "data" / "raw" / f"{cfg['name']}_pools.geojson"
    if path.exists():
        for feat in json.loads(path.read_text())["features"]:
            if feat.get("geometry"):
                g = shape(feat["geometry"]).centroid
                e, n = frame.to_local([g.x], [g.y])
                sx, sy = cam.world_to_screen(np.asarray(e), np.asarray(n), 0.0)
                pools.append((float(sx[0]) - x_origin, float(sy[0]) - y_origin))
    wetlands = waterpaint.water_geometry(cfg, frame, cam, x_origin, y_origin, "wetlands")
    return water, pools, wetlands


def courtyard_geometry(cfg, frame, cam, x_origin, y_origin):
    """Courtyard holes of the City's building footprints, in mosaic px at
    ground level (pixelphilly.invented_water.courtyard_lawn)."""
    from shapely.geometry import Polygon, shape

    path = REPO_ROOT / "data" / "raw" / f"{cfg['name']}_buildings.geojson"
    holes = []
    if path.exists():
        for feat in json.loads(path.read_text())["features"]:
            if not feat.get("geometry"):
                continue
            g = shape(feat["geometry"])
            for poly in getattr(g, "geoms", [g]):
                for ring in getattr(poly, "interiors", []):
                    lon, lat = np.asarray(ring.coords).T
                    e, n = frame.to_local(lon, lat)
                    sx, sy = cam.world_to_screen(np.asarray(e), np.asarray(n), 0.0)
                    p = Polygon(np.column_stack([sx - x_origin, sy - y_origin])).buffer(0)
                    if not p.is_empty:
                        holes.append(p)
    return unary_union(holes) if holes else Polygon()


def scan_invented_water(cfg, frames, size, drawing, renders, masks, water_geom, pools, wetlands_geom=None,
                        holds=(), courtyards_geom=None):
    """Look for invented water frame by frame, each with INVENTED_HALO of
    context. Returns (blobs, repaired): blobs as logged in report.json
    (frame, area_px, bbox in mosaic px, exempt), merged across frames;
    repaired: {frame name: repaired frame array} for frames with a
    non-exempt blob (nothing is written here)."""
    from pixelphilly import invented_water as iw

    found, repaired = [], {}
    for f in frames:
        gx, gy = f.col * size - INVENTED_HALO, f.row * size - INVENTED_HALO
        span = size + 2 * INVENTED_HALO
        d = drawing.region(gx, gy, span, span)
        r = renders.region(gx, gy, span, span)
        bmask = waterpaint.grow(masks.region(gx, gy, span, span) > 127, 9)
        ok = waterpaint.rasterize_view(water_geom, gx, gy, 1.0, span, span) if not water_geom.is_empty else \
            np.zeros((span, span), bool)
        local_pools = [(x - gx, y - gy) for x, y in pools if -500 < x - gx < span + 500 and -500 < y - gy < span + 500]
        wet = (waterpaint.rasterize_view(wetlands_geom, gx, gy, 1.0, span, span)
               if wetlands_geom is not None and not wetlands_geom.is_empty else None)
        blobs = iw.find_blobs(d, r, ok, bmask, pools_px=local_pools, pool_radius_px=POOL_RADIUS_PX, wetlands=wet)
        # Lawn the model invented in a paved courtyard (City Hall, v5); the
        # silhouettes are used ungrown so courtyards stay open
        if courtyards_geom is not None and not courtyards_geom.is_empty:
            holes = waterpaint.rasterize_view(courtyards_geom, gx, gy, 1.0, span, span)
            blobs += iw.courtyard_lawn(d, r, masks.region(gx, gy, span, span) > 127, holes)
        blobs = iw.apply_holds(blobs, gx, gy, holds)
        h0, h1 = INVENTED_HALO, INVENTED_HALO + size
        mine = [b for b in blobs if b["bbox"][0] < h1 and b["bbox"][2] > h0 and b["bbox"][1] < h1 and b["bbox"][3] > h0]
        for b in mine:
            x0, y0, x1, y1 = b["bbox"]
            found.append({"frame": f.name, "area_px": b["area_px"], "bbox": [x0 + gx, y0 + gy, x1 + gx, y1 + gy],
                          "exempt": b["exempt"], "kind": b.get("kind", "invented water")})
        if any(not b["exempt"] for b in mine):
            repaired[f.name] = iw.repair(d, r, mine)[h0:h1, h0:h1]
    # One entry per blob: frames that saw the same blob share an overlapping bbox
    merged = []
    for b in sorted(found, key=lambda b: -b["area_px"]):
        x0, y0, x1, y1 = b["bbox"]
        hit = next((m for m in merged if x0 < m["bbox"][2] and x1 > m["bbox"][0] and y0 < m["bbox"][3]
                    and y1 > m["bbox"][1] and m["exempt"] == b["exempt"] and m["kind"] == b["kind"]), None)
        if hit:
            hit["frames"].append(b["frame"])
            hit["bbox"] = [min(x0, hit["bbox"][0]), min(y0, hit["bbox"][1]), max(x1, hit["bbox"][2]),
                           max(y1, hit["bbox"][3])]
        else:
            merged.append({"frames": [b["frame"]], "area_px": b["area_px"], "bbox": list(b["bbox"]),
                           "exempt": b["exempt"], "kind": b["kind"]})
    return merged, repaired


def load_holds(cfg):
    """Reviewed hold list for this area (config/invented_water_holds.json):
    flags a person couldn't confirm as invented, left as drawn."""
    path = REPO_ROOT / "config" / "invented_water_holds.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get(cfg["name"], [])


def fix_invented_water(cfg, frame, cam, frames, args, out_dir):
    """--invented-water fix: after the repaint, scan the finished frames and
    rewrite those with invented water. Returns the report entry."""
    size = cfg["camera"]["frame_px"]
    x_origin = min(f.x0 - f.col * size for f in frames)
    y_origin = min(f.y0 - f.row * size for f in frames)
    done = [f for f in frames if (out_dir / f"{f.name}.png").exists()]
    water_geom, pools, wetlands = invented_water_context(cfg, frame, cam, x_origin, y_origin)
    blobs, repaired = scan_invented_water(
        cfg, done, size, FrameReader(out_dir, done, size), FrameReader(area_dir(cfg, "renders"), frames, size),
        FrameReader(area_dir(cfg, "masks"), frames, size, "L"), water_geom, pools, wetlands,
        holds=load_holds(cfg), courtyards_geom=courtyard_geometry(cfg, frame, cam, x_origin, y_origin))
    for name, img in repaired.items():
        Image.fromarray(img).save(out_dir / f"{name}.png")
    print(f"invented water: {sum(not b['exempt'] for b in blobs)} blobs repaired in {len(repaired)} frames, "
          f"{sum(bool(b['exempt']) for b in blobs)} exempt")
    from pixelphilly.invented_water import MIN_AREA_PX

    return {"blobs": blobs, "frames_rewritten": sorted(repaired), "min_area_px": MIN_AREA_PX}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="redraw_v3")
    ap.add_argument("--known-area", help="region runs: areas already drawn next to this one, comma list in "
                    "precedence order (default: from the "
                    "run's result.json)")
    ap.add_argument("--known-prompt", help="the known area's run (default: --prompt, or result.json's)")
    ap.add_argument("--known-stage", help="the known area's finished stage (default water)")
    ap.add_argument("--invented-water", choices=["off", "fix"], default="off",
                    help="fix: after the repaint, find water the model drew on open ground and repaint it from "
                    "the render (pixelphilly.invented_water; every blob logged in report.json). Dry run: "
                    "scripts/10b_scan_invented_water.py")
    args = ap.parse_args()

    cfg = load_config()
    if cfg.get("render_tile_frames"):
        frame, cam, frames = area_setup(cfg)
        main_tiled(cfg, args, frame, cam, frames)
        return
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    cols = max(f.col for f in frames) + 1
    rows = max(f.row for f in frames) + 1
    x_origin = min(f.x0 for f in frames)
    y_origin = min(f.y0 for f in frames)
    W, H = cols * size, rows * size

    redraw_dir = area_dir(cfg, "redraws", args.prompt)
    out_dir = area_dir(cfg, "postprocessed", args.prompt, "water")
    out_dir.mkdir(parents=True, exist_ok=True)

    redraw = np.asarray(load_mosaic(frames, size, redraw_dir, cols, rows)).copy()
    render = np.asarray(Image.open(area_dir(cfg, "renders", "mosaic.png")).convert("RGB"))
    buildings = waterpaint.grow(np.asarray(load_mosaic(frames, size, area_dir(cfg, "masks"), cols, rows, "L")) > 127)

    nhd_geom = waterpaint.nhd_geometry(cfg, frame, cam, x_origin, y_origin)
    nhd = waterpaint.rasterize_view(nhd_geom, 0, 0, 1.0, W, H)
    median, threshold = waterpaint.color_model(render, nhd, buildings)
    water = waterpaint.water_mask(render, nhd, buildings, median, threshold)

    before = seam_ratio(redraw, size)
    out = waterpaint.apply(redraw, water)
    nd_geom = nodata.nodata_geometry(cfg, frame, cam, x_origin, y_origin)
    cleared = 0
    if not nd_geom.is_empty:
        nd = nodata.nodata_mask(nd_geom, 0, 0, W, H)
        out[nd] = nodata.BACKGROUND
        cleared = int(nd.sum())
    after = seam_ratio(out, size)

    Image.fromarray(out).save(out_dir / "mosaic.png")
    Image.fromarray((water * 255).astype(np.uint8)).save(out_dir / "water_mask.png")
    for f in frames:
        Image.fromarray(out[f.row * size : (f.row + 1) * size, f.col * size : (f.col + 1) * size]).save(
            out_dir / f"{f.name}.png"
        )

    report = {
        "render_water_median_rgb": [round(v, 1) for v in median.tolist()],
        "color_threshold": round(float(threshold), 1),
        "water_px_repainted": int(water.sum()),
        "nhd_px": int(nhd.sum()),
        "nhd_px_kept_not_water": int((nhd & ~water).sum()),
        "nodata_px_cleared": cleared,
        "seam_ratio_before": round(before, 3),
        "seam_ratio_after": round(after, 3),
    }
    if args.invented_water == "fix":
        report["invented_water"] = fix_invented_water(cfg, frame, cam, frames, args, out_dir)
        if report["invented_water"]["frames_rewritten"]:
            mosaic = Image.open(out_dir / "mosaic.png").convert("RGB")
            for f in frames:
                if f.name in report["invented_water"]["frames_rewritten"]:
                    mosaic.paste(Image.open(out_dir / f"{f.name}.png"), (f.col * size, f.row * size))
            mosaic.save(out_dir / "mosaic.png")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
