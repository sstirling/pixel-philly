# Pixel Philly: Old City pilot

A test of whether Philadelphia can get an isometric pixel-art map like [tiny.london](https://tiny.london) or [isometric.nyc](https://isometric.nyc) **without Google's 3D tiles**.

Both of those maps start from renders of Google Photorealistic 3D Tiles. Google's Maps Platform terms bar that use: §3.2.3 (a)–(c) forbid storing or caching the content, creating content from it, and using it "to train, test, validate or fine-tune" AI models ([terms](https://cloud.google.com/maps-platform/terms), last modified Aug. 26, 2026).

This pilot replaces the Google input with City of Philadelphia open data. It renders one neighborhood, Old City, and has an image model redraw the renders as pixel art.

**Status:** pilot, one neighborhood. The output is an AI-generated illustration, not a photograph or a survey.

## What it does

1. **Download city data** for the area: building footprints with LiDAR heights, 2024 3-inch aerial photos, the 2025 street-tree inventory and river polygons.
2. **Build a 3D scene.**
   - Footprints are extruded to their heights.
   - Ground and roofs carry the aerial photo.
   - Walls are tinted from each roof's color.
   - Trees are stylized canopies at inventory points.
3. **Render isometric frames** in headless Chromium with three.js.
   - The camera matches isometric-nyc and tiny.london: an orthographic camera tilted 45° down, at 0.293 m per pixel, rendering 1,024 px frames.
   - The view is turned to a 54° bearing so Philadelphia's street grid (bearing ~9°) sits at 45° to the screen. That's the same relationship isometric-nyc has with Manhattan's grid.
   - Every frame is the same camera with a shifted frustum, so frames line up to the pixel.
4. **Redraw each frame as pixel art** with Gemini 3 Pro Image.
   - The prompt says how to draw, never what to draw (tiny.london's main lesson).
   - Each frame gets one generated sentence saying whether water is in view.
5. **Repaint the river.** The model picks its own water color in every frame, so all open water is repainted in one style across the whole mosaic, using USGS river outlines (both banks) and the render's own colors to decide what is open water. This also erases anything the model invented on the water.
6. **Build a comparison page** with render/redraw sliders and stitched mosaics.

What this pilot does **not** do:
- train a model (LoRA)
- denoise the whole map jointly, which is how tiny.london avoids seams
- build a zoomable web viewer

Frames are redrawn one at a time and stitched, so tone shifts between frames remain on land.

## Reproduce it

Requirements:
- macOS or Linux with Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- a GPU-capable browser environment (Playwright downloads Chromium; on Apple silicon it renders on the GPU through Metal)
- a Gemini API key for step 7 only

```bash
# 1. Environment (creates .venv with Python 3.12)
uv sync --python 3.12
uv run playwright install chromium

# 2. Data. Downloads into data/raw/ and records every query in data/raw/MANIFEST.json
uv run python scripts/01_fetch_buildings.py
uv run python scripts/02_fetch_trees.py
uv run python scripts/03_fetch_imagery.py   # ~2,450 tiles, ~40 MB, a few minutes
uv run python scripts/04_fetch_water.py        # PWD water: used for the prompt's water sentence
uv run python scripts/04b_fetch_water_nhd.py   # USGS NHD water (both banks): used for the repaint

# 3. Scene. Writes data/processed/oldcity_scene.json, the ground texture and a QA report
uv run python scripts/05_build_scene.py

# 4. Render the 30 frames and the mosaic into output/<area>/renders/
uv run python scripts/06_render.py

# 5. Check the render against the Python projection (should print PASS)
uv run python scripts/06_render.py --mode mask
uv run python scripts/09_check_alignment.py

# 6. Tests
uv run pytest

# 7. AI redraw (costs money: $0.134 per frame at standard pricing, about $4 for all 30)
cp .env.example .env          # then paste your key from https://aistudio.google.com/apikey
uv run python scripts/07_redraw.py --prompt redraw_v3 --frames frame_02_02 frame_03_02   # try two first
uv run python scripts/07_redraw.py --prompt redraw_v3 --max-calls 30                      # the rest
# Redo a bad frame; the old image is kept in rejected/ and the reason logged
uv run python scripts/07_redraw.py --prompt redraw_v3 --redo frame_05_01 --reason "invented buildings on water"

# 8. Repaint open water in one style (output/<area>/postprocessed/redraw_v3/water/)
uv run python scripts/10_repaint_water.py --prompt redraw_v3

# 9. Optional, not recommended at present: one shared 40-color palette on a 2x pixel grid
uv run python scripts/11_pixelize.py --prompt redraw_v3

# 10. Comparison page: open output/<area>/compare/index.html in a browser
uv run python scripts/08_compare_page.py --prompt redraw_v3 --stage water
```

Redraws are stored per prompt version in `output/<area>/redraws/<version>/`, each with its own `log.jsonl`, so versions can be compared. Snapshots of the renders that fed v1 and v2 are in `output/renders_v1/` and `output/renders_v2/`.

Every step can be rerun:
- Raw downloads are never overwritten. A download made for a different extent is refused rather than reused.
- The redraw step skips frames that already have output and logs every call to `output/<area>/redraws/<version>/log.jsonl`. Rejected images are kept, not deleted.

### Another neighborhood

Every script works on any area, picked with the `PP_AREA` environment variable (default `oldcity`):

1. Copy `config/oldcity.json` to `config/<area>.json`.
2. Change `name`, `label` and `bbox_wgs84`. Keep the box at about 1.1 × 1.2 km: much larger and the aerial mosaic exceeds the GPU's 16,384 px texture limit. Keep the camera settings; the style LoRA learned at bearing 54°.
3. Run the data, scene and render steps with the area set:
   ```bash
   export PP_AREA=fishtown
   for s in 01_fetch_buildings 02_fetch_trees 03_fetch_imagery 04_fetch_water 04b_fetch_water_nhd 05_build_scene; do uv run python scripts/$s.py; done
   uv run python scripts/06_render.py && uv run python scripts/06_render.py --mode mask && uv run python scripts/09_check_alignment.py
   ```
4. Draw it with the trained LoRA, which needs no new training. Detach so a dropped connection can't cancel the run:
   ```bash
   uv run python scripts/15_joint_sample.py --full --detach --name qwen_joint_light8 --lightning 8 \
       --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
       --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
   uv run python scripts/15_joint_sample.py --collect --name qwen_joint_light8    # repeat until done (~5 min)
   uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8
   uv run python scripts/08_compare_page.py --prompt qwen_joint_light8 --stage water
   ```

**Where things go:**
- Everything generated for an area goes in `output/<area>/`. Raw and processed data files are prefixed with the area name.
- Each area has its own imagery entry in `data/raw/MANIFEST.json`. The tiles are cached in one shared folder.
- Scripts 12–14 (the Phase A baseline, the training set and the LoRA training) are pinned to Old City, where the training data lives.

## Layout

| Path | What it is |
|---|---|
| `config/<area>.json` | Area bbox, camera, imagery zoom, height defaults (`oldcity`, `fishtown`) |
| `src/pixelphilly/projection.py` | WGS84 → local meters → isometric pixels. The single source of truth for the camera; the renderer receives its numbers. |
| `src/pixelphilly/heights.py` | Building height rule (see below) |
| `src/pixelphilly/sources.py` | ArcGIS download helpers and the provenance manifest |
| `src/pixelphilly/water.py` | River polygons in screen space; the per-frame water sentence |
| `src/pixelphilly/qa.py` | Seam ratio, flat share (photo-copy test) and registration shift |
| `src/pixelphilly/lidar.py` | LAS → 0.5 m height grid, footprint base, stepped building parts, noise ceiling |
| `scripts/04c_fetch_lidar.py` | Downloads the City LiDAR tiles an area needs |
| `scripts/17_atlas_sheet.py` | Problem-atlas before/after sheet (`output/atlas/compare.html`) |
| `scripts/18_qa_scan.py` | Pre-GPU QA gate: needles, stadiums, LiDAR fallbacks, structures |
| `scripts/04d_fetch_highways.py`, `04e_fetch_rail.py` | Expressway, El and track centerlines that mask elevated decks out of LiDAR structures |
| `scripts/04l_fetch_city_limits.py` | City limits polygon for `"clip_to_city"` regions |
| `scripts/04m_prune_lidar.py`, `src/pixelphilly/lidar_tiles.py` | Deletes raw LiDAR tiles once every area needing them has a cached grid (dry run by default) |
| `scripts/22_run_region.py`, `src/pixelphilly/region_runner.py` | One command per region: fetch → build → checks → stop gates → GPU draw → collect → repaint → report |
| `scripts/23_preflight_regions.py`, `src/pixelphilly/coverage.py` | Region sizes, overlaps, LiDAR needs, viewer fit, and gaps inside the city line |
| `config/qa_exceptions.json` | Reviewed needles and alignment frames the runner's gates let through |
| `config/height_overrides.json`, `config/stadium_exclusions.json`, `src/pixelphilly/reviewed.py` | Reviewed fixes to source data, applied in the scene build: wrong City heights; footprints that aren't stadiums |
| `scripts/25_join_seams.py` | Seam ratio for every border between regions in a merged map |
| `src/pixelphilly/regions.py` | Region machinery: shared frames, known-band and repair masks, union lattice, frame placement |
| `render/` | three.js page that draws the scene (three.js r169 vendored, MIT) |
| `prompts/redraw_v*.txt` | Redraw prompts, versioned; v3 is current. Each change gets a new file name. |
| `scripts/01–11` | The pipeline. Run order is in "Reproduce it"; 08 builds the page, 09 checks alignment. |
| `data/README.md` | Sources, licenses and vintages |
| `tests/` | Projection, lattice and height-rule tests |

## Decisions and assumptions

- **Heights.**
  - The city layer has `approx_hgt` and `max_hgt` (feet, from LiDAR). `max_hgt` is thrown off by cranes, taller neighbors and stray returns; 1 Dock St reads 50 ft approx vs. 369 ft max.
  - So `approx_hgt` is used, then `max_hgt`, then a 10 m default.
  - Fallbacks and buildings whose `max_hgt` is over 3× `approx_hgt` are listed in `data/processed/oldcity_qa.json`, not silently corrected.
- **Flat ground.** Old City lies between roughly 3 and 15 m above sea level. Terrain is ignored.
- **Texture mapping.** The aerial is in Web Mercator. A quadratic fit maps local meters to texture coordinates. Its worst error is printed by step 3 and must be under 5 cm; it was 0.05 mm.
- **Wall color (stylistic assumption).**
  - The aerial shows roofs, not façades, and the city publishes no façade-material data.
  - Buildings 20 m or shorter are blended 55% toward brick (RGB 150, 82, 62). Taller buildings take their roof's mean color.
  - In Old City most low buildings are brick rowhouses and warehouses, but not all are. This is an assumption about appearance, not data.
  - Set `wall_tint` to `null` in the config to turn it off.
- **Simplified aerial.** A 5 px median filter (about 1.1 m) is applied to the aerial before rendering (`ground_filter` in the config). It removes cars and rooftop clutter that the model otherwise copies instead of redrawing, and keeps roof outlines, streets and shadows.
- **Water style.** Repainted water is a muted blue-gray (RGB 88, 124, 140) with sparse light ripple dashes and a darker shore band. The real Delaware is brownish; blue is a pixel-art convention, the same choice tiny.london made for the Thames. Change `WATER_STYLE` in `scripts/10_repaint_water.py`. A pixel is repainted only if NHD says water, the render's color there is within 30 levels of the river's median color, and no building covers it. So the bridge deck, its shadow, piers and boats keep the model's drawing.
- **Trees.** Canopy radius is 1 m + 0.15 m per inch of trunk diameter, clamped to 1.5–7 m. This is a stylistic rule of thumb, not a measurement.
- **Alignment.** Step 5 renders buildings as a white mask and compares it with an independent Python rasterization of the same buildings. On the first run:
  - every frame containing buildings matched with zero pixel offset
  - intersection-over-union was at least 0.991

## Phase 2: one seam-free image (Oct. 20)

The per-frame Gemini map has visible seams: frame-border seam ratio 3.7 after the water repaint, where 1.0 is invisible. Phase 2 removes them the way tiny.london did. A fine-tuned open model draws the **whole canvas as one image**, with overlapping windows whose predictions are averaged at every denoising step. On Old City the frame-border seam ratio fell to **1.09**, the same as the plain render's 1.08.

**Models:**
- Qwen-Image-Edit-2511 and lightx2v's Lightning 8-step LoRA, both Apache 2.0, pinned to exact commits in `gpu/modal_app.py`.
- tiny.london's Qwen-Image-2.1-Turbo was not used: its license is non-commercial.

**Training data, internal use only.** The pixel-philly style LoRA was trained on 141 Gemini 3 Pro Image v3 redraws, with water repainted.
- The Gemini API terms bar using the service "to develop models that compete with the Services". A Philadelphia-only style LoRA arguably doesn't compete, but the terms don't define the word.
- **Legal review is required before anything made with this LoRA is published.**
- Every target's source is in `output/oldcity/trainset/manifest.jsonl`, so the LoRA can be retrained on artist-made or open-model targets without changing the rest of the pipeline.

**GPU:** Modal, per-second billing. One-time setup: `uv run modal token new`.

```bash
uv sync --group dev --group gpu
uv run modal deploy gpu/modal_app.py                   # inference image (Qwen + Lightning)
uv run modal run gpu/modal_app.py::download_weights    # ~58 GB into the pp-weights Volume, once
uv run modal deploy gpu/train_app.py                   # ai-toolkit training image

uv run python scripts/12_qwen_baseline.py              # Phase A: prompt-only Qwen on 6 frames (~$1)
uv run python scripts/13_build_trainset.py             # Phase B: 141 training pairs (~$16 of Gemini calls)
uv run python scripts/14_train_lora.py prepare         # Phase C: upload dataset + config
uv run python scripts/14_train_lora.py start           #          train on an H100 (~1.6 h, ~$6.50); detached
uv run python scripts/14_train_lora.py status          #          progress; `fetch` downloads checkpoints and samples
uv run python scripts/15_joint_sample.py --test-crop --name test --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
uv run python scripts/15_joint_sample.py --full --name qwen_joint_light8 --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."   # Phase D: ~5 min, ~$0.36
uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8
uv run python scripts/08_compare_page.py --prompt qwen_joint_light8 --stage water
```

**Safety checks before spending GPU time:**
- Every GPU script first runs a CPU smoke test: `check_env` for inference, `check_config` for training.
- A broken environment then fails for a fraction of a cent instead of crash-looping an H100.
- Spend estimates for each run are logged to `output/gpu_runs.jsonl`.

**Known limits of the phase 2 output:**
- The Ben Franklin Bridge is drawn from its photo shadow, because the city data has no bridge structure.
- The LoRA still invents a landscaped lot on the riverfront pier.
- Some edge ground still reads like the photo.
- Overfitting to Old City is likely. Generalization to other neighborhoods is untested.

## Downtown prototype and the zoomable viewer

A pannable, zoomable map of downtown Philadelphia, roughly 40th St to the Delaware and Washington Ave to Girard Ave, built with the same pipeline as the neighborhood tests. It is a local prototype, not published.

**What changes for an area this size** (`config/downtown.json`):

- **`clip_frames_to_area`.** The box sits about 45° to the screen, so only the 304 lattice frames that touch it are kept, out of 546. Downloads use the ground those frames see, sent to ArcGIS as a polygon.
- **`render_tile_frames: 4`.** The aerial for the whole area would be about 35,000 px, over the GPU's 16,384 px texture limit (now a hard error). Each 4 × 4-frame render tile gets its own scene, ground mosaic (≤ 12,544 px) and UV fit in `data/processed/downtown/tiles/`. Buildings and trees within 360 m of a tile's ground are included, so tall buildings leaning in from outside still render.
- **`camera_distance_m: 20000`.** With the default 3 km camera, the far edge of a 7 km area fell past the far plane and was cut off. Found by the alignment check.
- **Generation runs through the `pp-runs` Volume** (`AreaSampler.joint_volume`):
  - render frames are uploaded
  - only windows touching kept frames run
  - the latent is saved before decoding
  - each frame is decoded with a 128 px halo
- **Water repaint works frame by frame** with a 32 px halo, instead of on the whole ~570 MP mosaic in RAM.

```bash
export PP_AREA=downtown
for s in 01_fetch_buildings 02_fetch_trees 03_fetch_imagery 04_fetch_water 04b_fetch_water_nhd 05_build_scene; do uv run python scripts/$s.py; done   # ~25 min
uv run python scripts/06_render.py && uv run python scripts/06_render.py --mode mask && uv run python scripts/09_check_alignment.py      # ~3 min
uv run python scripts/15_joint_sample.py --full --volume --name qwen_joint_light8 --lightning 8 \
    --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."      # detached, ~45 min on one H100
uv run python scripts/15_joint_sample.py --collect --name qwen_joint_light8                     # repeat until done
uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8
uv run python scripts/16_build_tiles.py --prompt qwen_joint_light8 --version v3 --with-photo    # DZI pyramids: illustration (lossless WebP) + photo layer (WebP Q82)
uv run python -m http.server 8000      # from the repo root, then open:
# http://localhost:8000/viewer/?area=downtown&v=v3
```

**The viewer** (`viewer/`, vanilla JS):
- OpenSeadragon 6.1.1, vendored. Pixels are crisp at 1:1 and closer, smooth when zoomed out.
- Address search through the City's AIS API (no key needed). Pins mark street level.
- Shareable links: the view is kept in the URL hash.
- A persistent "AI-generated illustration" label.
- **Photo toggle** (tiles built with `--with-photo`): switches between the illustration and the render it was drawn from. That's the City's 2024 aerial photos on extruded footprints, from the same camera, so the layers line up pixel for pixel.
  - The label and credits switch with the layer, so neither is mistaken for the other.
  - The chosen layer is kept in shareable links (`&layer=photo`).
  - The photo layer is not a true orthophoto: walls are plain, trees are stylized, and places without city imagery show the background.
- Keyboard pan and zoom; honors reduced motion; works at 320 px.

**The address-search projection:**
- Lon/lat are converted to map pixels by a cubic fitted in `src/pixelphilly/viewer_geo.py` (error about 2 × 10⁻⁷ px), evaluated in `viewer/projection.js`.
- `tests/test_viewer.py` checks the JavaScript against the Python projection in headless Chromium.

**Tile versions are immutable:** `16_build_tiles.py` refuses to overwrite an existing version.

## Problem atlas and LiDAR building shapes (Oct. 22)

The footprint layer gives each building one outline and one height, so City Hall's tower, domes and stadium bowls all render as flat-topped boxes. The atlas is nine small test areas (`config/atlas_<spot>.json`, about 500 m across), one per problem: City Hall, the Art Museum, 30th Street, the Cathedral Basilica, Independence Hall, Franklin Field, Lincoln Financial Field, Citizens Bank Park and a Penn's Landing construction site. Each spot has a baseline config and a `_lidar` twin that differs only in `"building_shapes": "lidar"`.

**How LiDAR shapes work** (`src/pixelphilly/lidar.py`):
1. `scripts/04c_fetch_lidar.py` downloads the City's 2022 classified LAS tiles (PASDA dataset 7154, ~1 GB each) that fall within 100 m of the area box.
2. Points are gridded at 0.5 m: the highest return per cell (the surface) and the lowest ground return (class 2). The files have no CRS record; they are EPSG:6565 (PA South, US survey feet), assigned in code.
3. For each footprint: base = 10th percentile of ground in a 3–10 m ring outside it. Heights inside the footprint (shrunk 0.5 m) are split into tiers of `max(2 m, 6% of height)`, regions under 6 m² merge into their neighbors, and each tier becomes its own extruded part at the median measured height of its cells. Parts under 1 m become open ground, which opens stadium fields and courtyards.
4. **Noise ceiling.** The LAS files contain clusters of returns floating far above roofs that the vendor didn't classify as noise (about 1,200 points 80–110 m above the Ritz-Carlton residences, all from one flight line). Cells more than 3 m above the footprint's highest City height (`max(approx_hgt, max_hgt)`) are dropped and refilled from the surrounding roof. A building taller than its City record (a new tower, for instance) would be clipped at that record.
5. **Stray spires.** Some clusters of stray returns sit under the ceiling (City Hall's ceiling is 170 m because of its tower, so 145 m clusters on its 45 m wings passed). A region under 40 m² that rises more than max(20 m, its surroundings) above the tallest neighboring region is flattened into the roof. The check runs at every tier step, because a cluster split across tiers at one step can re-form at a coarser one. The only exception is a region within 5 m of the building's City **typical** height (`approx_hgt`), such as the Linc's roof canopy or a mid-rise wing on a low footprint. The City's `max_hgt` plays no part: it is the highest LiDAR return, so the same stray points often set it. Real steeples taper (Independence Hall rises in small steps from its tower body), and William Penn is only 17 m above the tower top, so neither trips the rule. `PP_LIDAR_LOG=1` prints every flattened and kept region.
6. **Confirmed tall elements.** Cells within 5 m of the City record (`max(approx_hgt, max_hgt)`) are "confirmed", unless they were flattened as spikes. The tallest confirmed element standing on a tall part is kept down to 2 m², so William Penn (166.8 m vs. 167 m published) survives the speck filter. Without a City record nothing is confirmed.
7. Each part's height is the median of its own cells, not of every cell in its tier.
8. Parts use the same scene format as whole buildings, so the renderer and alignment check are unchanged. Areas without the setting are byte-identical to before.

```bash
for spot in cityhall artmuseum 30thst cathedral indhall franklinfield linc cbp pennslanding; do
  for v in "" _lidar; do
    export PP_AREA=atlas_${spot}${v}
    for s in 01_fetch_buildings 02_fetch_trees 03_fetch_imagery 04_fetch_water 04b_fetch_water_nhd; do uv run python scripts/$s.py; done
    [ -n "$v" ] && uv run python scripts/04c_fetch_lidar.py     # ~24 GB for all nine spots
    uv run python scripts/05_build_scene.py && uv run python scripts/06_render.py && uv run python scripts/06_render.py --mode mask && uv run python scripts/09_check_alignment.py
    uv run python scripts/15_joint_sample.py --full --volume --detach --name qwen_joint_light8 --lightning 8 \
        --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
        --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
  done
done
# then --collect each area until done, and:
uv run python scripts/17_atlas_sheet.py     # output/atlas/compare.html and contact.jpg
```

**Results** (details in `output/atlas/compare.html`): clear gains for City Hall's tower, the Cathedral dome and the Art Museum's roofs. The biggest change is in stadiums: the baseline drew the inside of the Linc and Citizens Bank Park as apartment-style window walls, and LiDAR gives open bowls with tiered seating. All three stadiums already have L&I footprints, so no OSM outlines were needed. City Hall's tallest part is William Penn at 166.8 m (167 m published). Construction sites are not addressed: the baseline Penn's Landing drawing invented a swimming pool on one.

**Tiled areas** (downtown): `05_build_scene.py` shapes every footprint once, before splitting the area into render tiles, so overlapping tiles always agree. On City Hall, a tiled build and a single-scene build give identical parts. Downtown runs as its own area, `config/downtown_lidar.json`, so v3 stays reproducible:

```bash
export PP_AREA=downtown_lidar
for s in 01_fetch_buildings 02_fetch_trees 03_fetch_imagery 04_fetch_water 04b_fetch_water_nhd 04c_fetch_lidar; do uv run python scripts/$s.py; done  # 54 LAS tiles
uv run python scripts/05_build_scene.py      # ~35 min the first time (LAS gridding, 4.6 GB peak RAM); the grid is cached
uv run python scripts/06_render.py && uv run python scripts/06_render.py --mode mask && uv run python scripts/09_check_alignment.py
uv run python scripts/15_joint_sample.py --full --volume --detach --name qwen_joint_light8 --lightning 8 \
    --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
uv run python scripts/15_joint_sample.py --collect --name qwen_joint_light8       # repeat until done (~52 min)
uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8
uv run python scripts/16_build_tiles.py --prompt qwen_joint_light8 --version v4 --with-photo
# http://127.0.0.1:8137/viewer/?area=downtown_lidar&v=v4
```

## Downtown and South Philly (Oct. 23)

`config/south_lidar.json` covers downtown plus South Philadelphia in one area: bbox [-75.205, 39.880, -75.125, 39.975], 40th St/the Schuylkill to the Delaware and Girard Ave to the bottom of the Navy Yard, about 72 km².
- **Why one area:** it's drawn in one joint pass, so there's no seam between downtown and South Philly. Today each area has its own projection origin and frame grid, so separately drawn areas wouldn't line up. Drawing region by region with the neighbor held fixed is deferred to the citywide plan.
- **Scale:** 672 frames, 58 render tiles, 113 LiDAR tiles, 115,885 footprints.

```bash
export PP_AREA=south_lidar
for s in 01_fetch_buildings 02_fetch_trees 03_fetch_imagery 04_fetch_water 04b_fetch_water_nhd 04c_fetch_lidar; do uv run python scripts/$s.py; done
uv run python scripts/05_build_scene.py         # ~70 min the first time, 3.9 GB peak RAM
uv run python scripts/06_render.py && uv run python scripts/06_render.py --mode mask && uv run python scripts/09_check_alignment.py
uv run python scripts/18_qa_scan.py             # needles, stadiums, LiDAR fallbacks -> output/<area>/qa_scan.json
uv run python scripts/15_joint_sample.py --full --volume --detach --name qwen_joint_light8 --lightning 8 \
    --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
uv run python scripts/15_joint_sample.py --collect --name qwen_joint_light8       # repeat until done (~2 h)
uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8
uv run python scripts/16_build_tiles.py --prompt qwen_joint_light8 --version v1 --with-photo
# http://127.0.0.1:8137/viewer/?area=south_lidar&v=v1
```

**QA scan** (`scripts/18_qa_scan.py`, `src/pixelphilly/qa_scan.py`). This is the gate before paying for a drawing.
- **Needles:** parts under 40 m² that are more than twice the tallest part within 3 m and over 20 m above it.
- **Stadiums:** footprints given seat-colored risers.
- **LiDAR fallbacks:** the count of single-height fallbacks.

Check every hit against the 2024 aerial. The known exception is 905-11 Walnut St: a 51 m part that matches its footprint's typical City height.

**Alignment exceptions:** sparse frames full of small objects (port and Navy Yard structures) can fall under IoU 0.97 with zero shift. One-pixel edge rounding between the WebGL and Python rasterizers dominates small outlines. These are reviewed with diff images, not waved through.

## Regions: North Philly drawn next to South Philly (Oct. 23–24)

One canvas tops out around 1,300 frames (the GPU job's 4-hour cap), so the city is drawn as regions, each drawn next to an existing neighbor and merged into one map.

1. **Shared screen space.** `"projection_origin": [lon, lat]` in a config replaces the bbox center (`projection.local_frame`). `north_lidar` uses `south_lidar`'s origin [-75.165, 39.9275], so frames land on one global lattice: frame corners are multiples of 1,024 px from the origin.
2. **Known band.** North's frames that South already drew (41 along Girard Ave) are held fixed. Their drawn pixels are VAE-encoded, and after every denoising step those cells are reset to where South's image would be at that noise level (`joint_denoise(..., known=...)`, RePaint in flow-matching form). Band frames aren't decoded, so South's pixels stay authoritative.
   - **Hard mask:** a soft ramp mixed two images' latents into an olive smear (join seam ratio 6–8), so the mask is hard.
3. **Repair pass.** A 200 px strip on the new side of the join is re-noised to σ ≈ 0.64 and redrawn, with everything else fixed (tiny.london's repair step). That reconciles buildings that straddle the join.
4. **Water.** North's repaint reads South's finished frames as halo context and uses South's ripple coordinates. South's band frames are re-repainted with North as their neighbor (`water_band/`), which removes the dark shore line South had drawn along its old edge. Only water pixels change: 2,096 px in one frame.
5. **Merge.** `16_build_tiles.py --areas south_lidar,north_lidar --name philly` builds one pyramid on the global lattice. The first-listed area owns shared cells, and band overrides replace their cells.

```bash
export PP_AREA=north_lidar        # config sets projection_origin to south_lidar's
for s in 01_fetch_buildings 02_fetch_trees 03_fetch_imagery 04_fetch_water 04b_fetch_water_nhd 04c_fetch_lidar 04d_fetch_highways 04e_fetch_rail; do uv run python scripts/$s.py; done
uv run python scripts/05_build_scene.py && uv run python scripts/06_render.py && uv run python scripts/06_render.py --mode mask
uv run python scripts/09_check_alignment.py && uv run python scripts/18_qa_scan.py
uv run modal deploy gpu/modal_app.py
# cheap join test first (3 x 3 frames across the join, ~$0.15):
uv run python scripts/15_joint_sample.py --full --volume --name qwen_joint_light8_boundary_rep --known-area south_lidar \
    --known-name qwen_joint_light8 --only-near-known 1 --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
# full region (~45 min, ~$3):
uv run python scripts/15_joint_sample.py --full --volume --detach --name qwen_joint_light8 --known-area south_lidar --known-name qwen_joint_light8 \
    --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
uv run python scripts/15_joint_sample.py --collect --name qwen_joint_light8
uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8      # also re-repaints the band (water_band/)
unset PP_AREA; uv run python scripts/16_build_tiles.py --areas south_lidar,north_lidar --name philly --version v2 --with-photo
# http://127.0.0.1:8137/viewer/?area=philly&v=v7  (v7 = four regions with facades, invented water and courtyard fixes)
```

**The join today:** median seam ratio 2.36 across the 28 join edges, against 1.02 inside each region. At 1:1 the worst spots are a grass-texture change in the park and a faint line through a parking lot; rowhouse joins are hard to find. At normal browsing zoom the join doesn't show.

## Landmarks from public-domain references: experiment A (Oct. 25)

Track 3 of the facades/landmarks plan: can a reference photo make a landmark look like itself?

**Reference set.** `scripts/19_landmark_refs.py` writes `data/landmarks/manifest.json`: 40 landmarks inside the mapped regions, each with a Wikidata QID, Wikidata (P625) coordinates cross-checked against the City's AIS geocoder where there is a street address, the mapped regions that contain it, and up to 3 reference photos with source URL, image URL, license, author and a ready credit line. Photos come only from Library of Congress HABS/HAER (public domain) or Wikimedia Commons files licensed CC0, public domain or CC BY. CC BY-SA and all other licenses are rejected. The photos download to `data/landmarks/refs/<slug>/` (git-ignored). The choice of photo is a keyword heuristic; only photos with `"reviewed": true` have been checked by eye.

**Multi-image edits.** `Editor.run` in `gpu/modal_app.py` takes two optional job fields: `style` (the style LoRA, as in `joint`) and `references` (PNG/JPEG bytes). With references the call is `image=[*references, render]`. diffusers takes the output size from the last image, so the render goes last and the prompt calls it "Picture 2". Without references the call is unchanged.

```bash
uv run python scripts/19_landmark_refs.py                  # manifest + downloads (~10 min, polite rate)
uv run python scripts/20_landmark_experiment_a.py --refs city_hall=2,1 art_museum=1,0 --dry-run
uv run python scripts/20_landmark_experiment_a.py --refs city_hall=2,1 art_museum=1,0   # ~2 min, ~$0.15
```

The inputs are 1,024 px crops of the atlas mosaics centered on each landmark (`output/landmarks/experiment_a/<slug>_render.png`; City Hall from `atlas_cityhall_lidar` at mosaic (1458, 1368), the art museum from `atlas_artmuseum_lidar` at (1536, 1478)). The comparison sheet is `output/landmarks/experiment_a.jpg`; scores are in `output/landmarks/experiment_a/results.json`. An output is accepted only if the whole-frame and central registration shifts are within 2 px and the central edge correlation is at least half of the no-reference output's. The whole-frame shift alone missed one output that pasted the photo into the middle of the frame.

**Result.** With prompt p1 ("...match its facade, materials and details, but keep exactly the shapes and positions of Picture 2"), City Hall's tower turns from a generic Art Deco shaft into a recognizable City Hall tower: cream stone, clock faces, a slate-blue mansard and dormers. All 4 p1 outputs stayed on the render. The art museum gains columns on the north wing's facade and warmer sandstone, a smaller gain. Prompt p2 (which names the landmark and calls Picture 1 "a photo") copied the photo's viewpoint outright in 2 of 4 outputs. A reference can't add geometry the render lacks: City Hall's main block stays missing, and so does the Penn statue in most outputs.

## Façades from property records and OpenStreetMap (Oct. 25–26)

The aerial shows roofs, not walls, so renders had plain tinted walls and the drawing model invented façades. Areas with `"facades": "opa"` now draw walls from data, procedurally, in the renderer's wall shader. Paint only: building geometry, masks and alignment are unchanged, and a detail appears only where the data says the building has it.

- **What each building is:** the City's property records (OPA, `scripts/04f_fetch_opa.py`), joined by parcel (about 98% of footprints in the atlas spots), then address, then location. The record gives the style (rowhouse with porch front, typical row, twin, mixed-use with storefront, warehouse, office tower, …), stories and main material. Owner, sale, tax and condition fields are never fetched; condition and vacancy are not drawn.
- **What the shader paints:** a window grid per floor and bay (dark panes, a light sill), a storefront (bulkhead, glass, sign band) on mixed-use buildings, a porch (light porch-roof trim, a shadowed recess with posts) on porch-front rows, a cornice on rowhouses, and curtain-wall glass on modern towers.
- **Which walls:** storefronts and porches go only on walls facing a street: a wall's outward ray must meet a City street centerline within 25 m (`scripts/04h_fetch_streets.py`, `facades.front_dirs`).
- **Wall colour:** OpenStreetMap `building:colour` or `building:material` where mappers recorded them (`scripts/04g_fetch_osm.py`; mostly downtown; a tower's colored `building:part` colours that LiDAR part), else the record's material palette with a small per-building variation. OPA's "MASONRY" also covers limestone and terra cotta, so non-rowhouse buildings above 20 m with no OSM colour keep their own aerial colour, as before façades (City Hall's pale towers had turned red).
- **Atlas spots:** `atlas_passyunk_fac`, `atlas_porch_fac` (Allegheny West), `atlas_twin_fac` (West Philadelphia), `atlas_indhall_fac`, `atlas_cityhall_fac`. Areas without the option are byte-identical.

### Landmark references in the joint sampler (Oct. 26): tested, not recommended

`15_joint_sample.py --full --volume --landmarks --landmark-baseline qwen_joint_light8` gives each approved landmark's windows its reference photo as a second conditioning image. On four atlas spots, it improved one landmark, the Union League. It visibly damaged seven: pasted photo patches, PSFS's sign floating in the sky, and a neighbor restyled. The automatic check, experiment A's rule, caught only one of the seven. Results are in `output/landmarks/joint_compare.jpg` and `.json`. Don't use the `qwen_joint_light8_landmarks` drawings.

## Citywide regions: clipping, LiDAR pruning, the region runner (Oct. 28)

The rest of the city is eight more regions on the same global lattice (`projection_origin` [-75.165, 39.9275]), each a copy of `west_lidar`'s settings plus `"clip_to_city": true`.

**Clipping to the city line.** `scripts/04l_fetch_city_limits.py` fetches the City's `City_Limits` polygon. With `"clip_to_city": true`, `projection.area_setup` keeps only the frames that see bbox ∩ city (its ground outline swept up to `max_height_m`; `projection.swept_screen_polygon`), so edge regions don't draw Upper Darby, Montgomery County or New Jersey. Frame indices still come from the whole bbox, so mosaics line up. `render_ground_polygon` and every fetch extent follow the kept frames; they still include the ground those frames show just past the line, so no kept frame has a hole in its data. Configs without the flag are unchanged (Old City scene SHA-256 `eaca1872…eaac4`, all existing frame lists identical).

**Pre-flight** (`scripts/23_preflight_regions.py`, no downloads): frames after clipping, frames shared with earlier regions (the known band), new frames, cost, LiDAR tiles, the viewer fit, and a coverage check: every global lattice cell that shows city ground must belong to some region. Result in `output/preflight_regions.json`.

| Region | bbox | Frames | New | Known from | LiDAR tiles (on disk / to fetch, GB; tiles an earlier region fetches aren't counted again) |
|---|---|---|---|---|---|
| `east_riverfront` | -75.125, 39.960, -75.045, 40.010 | 227 | 193 | south 11, north 19, upper_north 4 | 53 (7 / 46, ~39) |
| `west_north` | -75.285, 39.963, -75.205, 40.010 | 210 | 108 | south 10, north 23, upper_north 5, west 64 | 48 (22 / 26, ~22) |
| `southwest` | -75.285, 39.865, -75.189, 39.945 | 404 | 255 | south 129, west 20 | 96 (27 / 69, ~58) |
| `germantown` | -75.205, 40.035, -75.125, 40.082 | 294 | 254 | upper_north 40 | 58 (9 / 49, ~41) |
| `roxborough` | -75.270, 40.010, -75.190, 40.075 | 319 | 190 | north 2, upper_north 53, west_north 1, germantown 73 | 69 (12 / 40, ~34) |
| `lower_northeast` | -75.125, 40.010, -74.970, 40.060 | 539 | 473 | upper_north 22, east_riverfront 30, germantown 14 | 106 (4 / 89, ~75) |
| `northwest` | -75.245, 40.050, -75.170, 40.100 | 244 | 35 | germantown 117, roxborough 92 | 58 (0 / 16, ~13) |
| `upper_northeast` | -75.100, 40.050, -74.955, 40.140 | 697 | 544 | lower_northeast 153 | 141 (0 / 111, ~93) |

All 3,091 lattice cells that show city ground are covered; no city ground lies outside every region's box. Union viewer fit 7.2e-5 px. Boxes were widened from the first proposal to close gaps (Holmesburg–Torresdale riverfront, the Cobbs Creek strip, Bridesburg's riverfront, the Schuylkill mouth and four slivers). Overlaps become known bands.

**LiDAR pruning** (`scripts/04m_prune_lidar.py`; rules in `data/README.md`). A dry run by default; `--apply` deletes and records each tile in `data/raw/MANIFEST.json`.

**Region runner** (`scripts/22_run_region.py`):

```bash
uv run python scripts/22_run_region.py germantown --known upper_north_lidar --plan             # steps and what's done
uv run python scripts/22_run_region.py germantown --known upper_north_lidar --stop-before-gpu  # everything up to the gates
uv run python scripts/22_run_region.py germantown --known upper_north_lidar --run-name <run> \
    --prompt-text "<prompt>" [--style /runs/lora/<lora>.safetensors] [--known-run <run>] [--budget-usd 15]
```

- **Steps:** 04l, 01–04k (04b with 12 retries a minute apart; 04c skipped once the grid is cached), 05, 06 color and mask, 09, 18, then the gates, then `15_joint_sample.py --full --volume --detach` with the known areas, `--collect` every 2 minutes until done, `10_repaint_water.py --invented-water fix`, and the `10b_scan_invented_water.py` dry-run report (`output/<area>/invented_water_scan/<run>/`). `output/<area>/region_report.json` is written at every stop.
- **Resumable:** a step is skipped when its outputs exist and are newer than its inputs (fetches: when their raw files exist). The GPU launch is never repeated once `joint/<run>/call.json` exists.
- **Stop gates, before any GPU spend:** alignment FAIL (`qa.alignment_failed`, the rule 09 uses); any needle not in `config/qa_exceptions.json`; facade match rate under 0.95; or the run's frames × $0.011 over `--budget-usd`. Every frame in the run counts, known band included, since known frames still pass through the sampler (West: 158 frames, 132 new, 28.1 min).
- `config/qa_exceptions.json` holds the reviewed 905-11 Walnut St piece and the South Philly port crane `s1459-0`. A needle matches by id within its areas, or anywhere within 3 m and 2 m of height, since structure ids are renumbered per area. South's `s1762-0` (46 m, 7 m², at -75.12585, 39.90468, near the Packer Ave terminal) was reviewed Oct. 28 and is in the exceptions too, with 310603-9 and the Bleigh Ave water tower (21880-1).
- **Exceptions vs. fixes.** An exception lets a reviewed hit through the gate unchanged. When the hit is a data error, the data is fixed instead, in the scene build, so the gate passes on corrected data:
  - `config/height_overrides.json` gives a footprint the median height of its neighbors within 25 m (`"neighbor"`) or a fixed height (`"meters"`), and keeps it out of LiDAR shaping. First entry: 5458 Tacony St, a small tank recorded at 138 ft.
  - `config/stadium_exclusions.json` lists footprints that pass the seating-row rule but aren't stadiums: the airport terminal and garages, the Richmond Generating Station, a sawtooth-roof plant on G St, and a Port Richmond pier warehouse, a care-home campus at 8700 Ridge Ave, Holmesburg Prison, Fox Chase Cancer Center, Jefferson Torresdale Hospital and the Philadelphia Mills mall.
  - `config/structure_exclusions.json` lists LiDAR structures (objects with no footprint) the 2022 LiDAR saw but the 2024 aerial shows gone, by a reviewed lon/lat point. First entry: a 42,000 m² rubble lot by the Manayunk Canal.
  - Each entry records the reason, the aerial checked and the review date. Unlisted footprints are untouched (Old City byte-identical).
- **Woods as trees** (`"woods_trees": true`, all 12 city regions since Nov. 4; `lawns.canopy_trees`): woods get the street-tree canopy geometry at LiDAR treetops, one per 7 m block, thinned over 15 m toward the woods edge. Treetops from the neighboring regions' LiDAR grids (same projection origin) fill the area beyond a region's own LiDAR box, so woods don't stop in a straight line at a region border (`lawns.merge_canopy_trees`). A tinted forest floor was tried and failed: the model read the smooth green as water (CHANGELOG, Nov. 3).
- **Golf courses** (`"golf_correct": true`, all 12 city regions; `pixelphilly.golf`, `lawns.correct_golf`, `scripts/04n_fetch_golf.py`): inside OSM golf courses and PPR "Golf" properties, turf gets a wider lawn band (hue 30–75, S 0.15–0.70, V 0.30–0.92), fairways, greens and tees a yellower, lighter green (hue ~82) and rough the park target. Bunkers and water hazards are left out; wooded rough stays woods. Reviewed construction sites (Cobbs Creek "Olde" and Karakung, `config/golf.json`) get no correction. OSM golf water hazards are water candidates for the repaint, so the Bala clubhouse pond stays water. OSM names the Torresdale course "Union League Golf Club"; that name is unverified, so don't use it in captions without a source.
- **Invented-water review:** `10b_scan_invented_water.py --from-redraws` lists what the repair changed; real water (ponds, pools, creeks outside the mapped polygons) goes into `config/invented_water_holds.json` after a check on the 2024 aerial, and the area is repainted. Known gap: the scan's hue band (185–215°) misses teal water (hue ~165°). A teal lake the model drew on the Cobbs Creek construction site was found by eye and redrawn (CHANGELOG, Nov. 4); a teal scan elsewhere found only real basins and pools.
- **Redrawing a few frames** of a drawn area: `15_joint_sample.py --full --volume --known-area <neighbors>,<area itself> --known-name <run> --redraw frame_a,frame_b [--context 2] --name <new run>`. The frames within `--context` stay at their finished pixels. Known pixels must be final: 15 refuses to run if a known frame's drawing is newer than its repainted PNG (a redraw merged, its repaint pending, or a later area's `water_band/` re-repaint not rerun) or if a known area has a GPU run in flight, and 16 refuses to build a map with such cells (`regions.stale_known`, `in_flight_runs`). Run redraws of neighboring areas one after another, each repainted before the next. An area's known pixels only cover cells in its own frame list: to match a seam with an area that has no frame there, redraw on that area's side.
- **Join seams:** `scripts/25_join_seams.py --areas ... --prompt <run> --version vN` (output `output/philly/join_seams_vN.json`).

## A clean style: Phase 1 comparison (Oct. 28)

The style LoRA in every drawing so far (`qe2511_oldcity_r16_v1`) was trained on Gemini 3 Pro Image outputs. Phase 1 tested two replacements that use no Gemini output anywhere. **Nothing has been switched yet.** Configs and docs still point at the old LoRA until Stephen picks.

- **Candidate A: no style LoRA.** Qwen-Image-Edit-2511 + Lightning-8 (both Apache 2.0) with the prompt "Redraw this render as isometric pixel art." Run name `qwen_joint_light8_nolora`. `15_joint_sample.py` already worked without `--style`.
- **Candidate B: a self-distilled LoRA.** `qe2511_clean_r16_v1`: rank 16, 2,000 steps, trained on 228 filtered A redraws of our own renders. Caption: "Redraw this render as isometric pixel art in the pixel philly clean style." Run name `qwen_joint_light8_cleanlora`.

**Comparison:** `output/style/compare.html` (self-contained) and `compare.jpg`, with numbers in `metrics.json` and notes in `notes.json` (`scripts/24_style_compare.py`). It covers 8 atlas spots:
- the 5 facade spots;
- 3 new terrain spots:
  - `atlas_wissahickon_fac`: woods, creek and Lincoln Drive;
  - `atlas_airport_fac`: PHL terminal piers, apron and runway 9R/27L;
  - `atlas_northeast_fac`: by OPA, 73% twins and 16% singles.

Every variant got `10_repaint_water.py --invented-water fix`.

**Result: B v1 is worse than A on all 8 spots.**
- B's drawings are noisier and blockier, with more invented cars and colored specks: 1.0–1.8% of pixels vs. A's 0.2–0.8%, by the invented-color measure below.
- Self-distillation amplified A's habits instead of filtering them out.
- A draws clean pixel-art geometry and facades, but it invents:
  - cars, including on roofs near City Hall;
  - confetti in parking lots;
  - planes on the airport apron;
  - bright lawns where the render shows paving.
- The old (Gemini-derived) style still invents the least.

**The training set** (`scripts/23_build_clean_trainset.py`, `src/pixelphilly/trainset_clean.py`, tests in `tests/test_trainset_clean.py`):
1. **plan:** classifies every region frame (South, North, Upper North, West) by terrain from measured features.
   - Features: building, water and park share; lawn-green share; median footprint area; tallest footprint; known stadium and port locations.
   - Frames within 512 px (~150 m) of any of the 8 comparison spots are excluded.
   - The pick is stratified by terrain with a fixed seed: 213 full frames and 119 2x quarters.
   - Quarters are re-rendered at 2x from the frame's render-tile scene, not cropped and upscaled, so edges and facade windows are drawn at full resolution. They register with the 1x render at 0 px.
2. **generate:** `Editor.run` with A's prompt, Lightning-8 and seed 0, then seed 1 for views that failed. 523 images, ~4.5 s each.
3. **filter:** mapped water repainted, then reject a pair if any of these hold:
   - registration shift > 2 px;
   - any invented-water blob;
   - flat share outside 0.26–0.72 on land. Renders' median is 0.265. In the pilot, woods drawn as flat camouflage scored 0.75–0.82, good parks 0.68–0.70.
   - invented color > 1.2% (A's median on the facade spots). This counts saturated non-green pixels where the render has no saturated color within 7 px: cars and confetti.
   - near-copy: mean difference from the render < 13 levels. Copies invent the least color, so without this rule the color filter favored them.
   - more than 15% of the view on the renderer's no-data gray;
   - a tone outlier: robust z > 3.5 on mean luminance or chroma shift.

   Small invented specks are painted over with a 9 px median before the color check (`remove_invented_specks`). In dense car areas the median is itself a car, so this helps little, and it likely left blotchy patches that B learned.
4. **Result:** 228 of 523 tries kept. Per-pair provenance is in `output/trainset_clean/manifest.jsonl`: source render or re-rendered quarter, area, frame, model and Lightning commits, prompt, seed, every filter score. Every row passes `check_provenance` (no Gemini, `redraw_v3` or old LoRA/trainset reference). Rejected tries are in `rejected.jsonl`, contact sheets in `sheets/`.

Kept by terrain: rowhouse 70, tower 40, river 36, industrial 27, park 18, port 15, woods 11, open 6, stadium 5. Woods and stadiums are thin because the city has few of them outside the comparison spots.

```bash
for a in wissahickon airport northeast; do export PP_AREA=atlas_${a}_fac
  for s in 01_fetch_buildings 02_fetch_trees 03_fetch_imagery 04_fetch_water 04b_fetch_water_nhd 04c_fetch_lidar 04d_fetch_highways \
           04e_fetch_rail 04f_fetch_opa 04g_fetch_osm 04h_fetch_streets 04i_fetch_pools 04j_fetch_parks 04k_fetch_wetlands; do uv run python scripts/$s.py; done
  uv run python scripts/05_build_scene.py && uv run python scripts/06_render.py && uv run python scripts/06_render.py --mode mask
  uv run python scripts/09_check_alignment.py && uv run python scripts/18_qa_scan.py; done
# A on any spot (then --collect, then the repaint fix):
uv run python scripts/15_joint_sample.py --full --volume --name qwen_joint_light8_nolora --lightning 8 --prompt-text "Redraw this render as isometric pixel art."
uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8_nolora --invented-water fix
# B:
uv run python scripts/23_build_clean_trainset.py plan
uv run python scripts/23_build_clean_trainset.py generate                       # seed 0 (~$1.70)
uv run python scripts/23_build_clean_trainset.py filter
uv run python scripts/23_build_clean_trainset.py generate --seed 1 --only-rejected   # (~$1.20)
uv run python scripts/23_build_clean_trainset.py filter
uv run python scripts/14_train_lora.py prepare --profile clean && uv run python scripts/14_train_lora.py start --profile clean  # ~1.6 h, ~$6.30
uv run python scripts/15_joint_sample.py --full --volume --name qwen_joint_light8_cleanlora --lightning 8 \
    --style /runs/lora/qe2511_clean_r16_v1/qe2511_clean_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly clean style."
uv run python scripts/24_style_compare.py
```

**GPU:** about $13.56 for Phase 1. That's $12.00 logged in `output/gpu_runs.jsonl`, plus an estimated $1.56 of container start and weight loading, which joint runs don't log.

## The current map: v17, frozen (Nov. 9)

`philly` v17 is the accepted map and the viewer default (`?area=philly&v=v17`). It is v14 plus the ship fixes (v15) and the bridge fixes (v16, v17); see the CHANGELOG. It has the same 12 regions and tile counts as v14 (75,367 files). Don't rebuild or edit `output/philly/tiles/v17/`; build v18 instead.
- **Manifest:** `output/philly/FROZEN_v17.json`.
- **Check it:** `uv run python scripts/26_freeze_map.py --name philly --version v17 --verify`.
- **Known flaws Stephen accepted:** raw shadow strips along some bridge decks (W Roosevelt Blvd), plus dark rectangles and a three-box outline on the water at the Platt Bridge.
- **Not yet made for v17:** an offline copy. The one below is v14. Build one with `27_offline_copy.py --version v17`.
- **Hosted:** v17's illustration layer is online at https://pixelphilly.sstirling.com/viewer/index.html (see "Hosting" below).

## Next: v18, the 3D suspension bridges (Nov. 9; building, not the viewer default)

v18 is v17 plus the Ben Franklin and Walt Whitman bridges modeled in 3D: raised decks from the 2022 LiDAR, both towers with crossbeams, main cables, hangers, the Ben Franklin's stiffening truss and the approach spans. Stephen asked for this Nov. 9, after the v17 bridges drew with buildings on the roadway, a shadow slab and missing towers. Method and sources: `data/README.md` ("Suspension bridges"); the iterations, LiDAR checks and costs: the CHANGELOG.
- **Build:** `uv run python scripts/16_build_tiles.py --areas <12 areas> --name philly --prompt qwen_joint_light8_fac --version v18 --with-photo`, then `25_join_seams.py` and `33_bridge_crops.py --before v17 --after v18`.
- **Results:** v18 built Nov. 9 at 10:54 p.m. (`output/philly/build_v18.log`): 37,681 tiles per layer. 326 of 28,188 full-resolution tiles differ from v17. Seams are identical to v17 on all 22 region pairs (`output/philly/join_seams_v18.log`). The tan band under the cables is gone after the members-zone repaint fix. Crops: `output/review/bridges/nj/final_v18/` (v17 vs v18) and `output/review/bridges/crops_None/` (bridge sheet, 105 crops). The build first stopped on the stale-cell guard: southwest's `water_band/south_lidar/` copies of 11 redrawn frames predated the redraw; southwest was re-repainted (`output/southwest/repaint_v18.log`) and the build rerun. Not the viewer default until Stephen accepts it.
- **Status:** not the viewer default until Stephen accepts it. v14 and v17 stay frozen.
- **Rebuilding the bridges from scratch:** `PP_AREA=south_lidar uv run python scripts/04q_fetch_bridge_towers.py` (tower outlines; `04p_fetch_bridges.py` must already have run), then `05_build_scene.py`, the render, the redraw of the changed frames and `10_repaint_water.py` for south_lidar. The area flags are `"bridge_decks"`, `"bridge_shadows"`, `"bridge_towers"` and `"bridge_structures"` in `config/south_lidar.json`.
- **Rolling back to v17's bridges:** the v17 drawings, renders, masks, scene and water outputs are kept under `*_pre_bridges` names (listed in the CHANGELOG).

## The talk map: v14, frozen (Nov. 4)

`philly` v14 is the map for Stephen's talk: all 12 regions, 37,681 tiles per layer. It is frozen. Don't rebuild or edit `output/philly/tiles/v14/`; build v15 instead.
- **Manifest:** `output/philly/FROZEN_v14.json` lists the file count, bytes, tiles per layer, regions, drawing run, prompt, LoRA and date. It also holds a SHA-256 over every file (`scripts/26_freeze_map.py`).
- **Check it:** `uv run python scripts/26_freeze_map.py --name philly --version v14 --verify`.
- **Viewer:** v14 was the default until Nov. 9; it stays available at `?area=philly&v=v14`.

**Offline copy** (`scripts/27_offline_copy.py`): `output/philly_offline_v14/` holds the viewer, the vendored OpenSeadragon, the v14 tiles (both layers), the manifest, start scripts (`start.command`/`start.sh`/`start.bat`, Python's built-in server on 127.0.0.1:8137) and a README with the steps. The copy sets `data-offline="1"`, which turns off address search, the only feature that calls a remote API (the City's AIS). With networking off, a Playwright check logged no request off 127.0.0.1 (CHANGELOG, Nov. 4).

```bash
uv run python scripts/27_offline_copy.py --name philly --version v14   # -> output/philly_offline_v14/
cd output/philly_offline_v14 && sh start.sh                             # http://127.0.0.1:8137/viewer/?area=philly&v=v14
```

**Hosting** (live since Nov. 9, 2026; the plan below was researched Nov. 4):

- **What's up:** v17's illustration layer (37,682 tiles, 4.34 GiB) and `viewer/`, in the Cloudflare R2 bucket `pixel-philly`, served at https://pixelphilly.sstirling.com/viewer/index.html. The photo layer was not uploaded.
- **Upload:** rclone, about 7 minutes; `rclone check` found 0 differences. Log: `output/philly/r2_upload_v17.log`. The objects keep their repo paths (`output/philly/tiles/v17/...`).
- **Credentials:** the rclone remote `r2` is in `~/.config/rclone/rclone.conf`. Never commit or print that file.
- **Root redirect:** `/` goes to `/viewer/index.html` through a Redirect Rule in the Cloudflare dashboard, not in the repo.
- **Address search:** works from this origin, because the City's AIS API sends `access-control-allow-origin: *`.
- **Visit counter:** the hosted pages load GoatCounter (Stephen's account, no cookies). `27_offline_copy.py` removes it from the offline copy.
- **A new version** (v18 once accepted) goes under its own prefix; don't overwrite v17's tiles.

The original plan follows.


- **Recommended: Cloudflare R2 behind a custom domain.**
  - Storage is $0.015/GB-month with 10 GB-month free.
  - Writes cost $4.50 per million and reads $0.36 per million, with 1M writes and 10M reads free each month.
  - Egress is free.
  - At ~5.5 GB and ~75k objects (both layers), the one-time upload and storage fall inside the free tier.
  - Sources: https://developers.cloudflare.com/r2/pricing/, https://developers.cloudflare.com/r2/buckets/public-buckets/.
- **Use a custom domain, not r2.dev.** The r2.dev URL is rate-limited, gets no caching and is meant for development. A custom domain puts Cloudflare's cache in front, so cache hits never reach R2. The domain must be a zone in the same Cloudflare account; a partial (CNAME) setup works when the DNS is hosted elsewhere.
- **Caching:**
  - Cloudflare caches `.webp` by default.
  - The `.dzi` and `map.json` files need a cache rule, or a short `Cache-Control`.
  - Turn on Smart Tiered Cache.
- **Paths:** keep versioned prefixes (`/v14/`). Upload tiles with `Cache-Control: public, max-age=31536000, immutable`, and never overwrite them. A new version goes under a new prefix.
- **What Stephen needs to provide:**
  - A Cloudflare account with R2 enabled. Checkout asks for a payment method even for free-tier use.
  - The account ID and a bucket name.
  - An R2 API token with Object Read & Write scoped to that bucket. It gives an access key ID and a secret, and the secret is shown once. Keep both out of git.
  - A subdomain on Cloudflare DNS, e.g. `map.example.org`.
  - The viewer's origin, for CORS.
- **Commands** (rclone ≥ 1.59, https://developers.cloudflare.com/r2/examples/rclone/):

```ini
# ~/.config/rclone/rclone.conf
[r2]
type = s3
provider = Cloudflare
access_key_id = <ACCESS_KEY_ID>
secret_access_key = <SECRET>
endpoint = https://<ACCOUNT_ID>.r2.cloudflarestorage.com
acl = private
no_check_bucket = true
```

```bash
B=r2:<BUCKET>/philly/v14
rclone copy output/philly/tiles/v14 $B --exclude "*.dzi" --exclude "map.json" \
  --transfers 32 --checkers 64 --s3-no-check-bucket --progress \
  --header-upload "Cache-Control: public, max-age=31536000, immutable"
rclone copy output/philly/tiles/v14 $B --include "*.dzi" --s3-no-check-bucket \
  --header-upload "Content-Type: application/xml" --header-upload "Cache-Control: public, max-age=300"
rclone copy output/philly/tiles/v14 $B --include "map.json" --s3-no-check-bucket \
  --header-upload "Content-Type: application/json" --header-upload "Cache-Control: public, max-age=300"
rclone check output/philly/tiles/v14 $B --one-way --size-only        # nothing missing
curl -I https://map.example.org/philly/v14/map_files/12/0_0.webp     # Content-Type image/webp, Cache-Control set
```

- **CORS:**
  - Needed only if the viewer is served from a different origin than the tiles. The simplest setup puts the viewer files in the same bucket, so no CORS is needed.
  - Otherwise, set the CORS policy in the dashboard: `[{"AllowedOrigins":["https://<viewer origin>"],"AllowedMethods":["GET","HEAD"],"AllowedHeaders":["*"],"MaxAgeSeconds":86400}]`. Or use `npx wrangler r2 bucket cors set <BUCKET> --file cors.json`.
  - With cross-origin tiles, set OpenSeadragon's `crossOriginPolicy: "Anonymous"`.
  - `wrangler r2 object put` uploads one file per call, so it isn't practical for the tiles.
- **Content types:** rclone is expected to set `image/webp` from the extension, but this wasn't verified in its docs. Check with `curl -I` after the first upload.
- **Alternatives** (all checked Nov. 4):
  - GitHub Pages: no. Sites are capped at 1 GB, with a 100 GB/month soft bandwidth limit.
  - Cloudflare Pages: the free plan allows 20,000 files, the paid plan 100,000.
  - Vercel: a CLI deploy is capped at 15,000 files.
  - Netlify: deploys reportedly fail around 40,000 files.
  - S3 + CloudFront works, with request fees past the free tier.
  - Backblaze B2 + Cloudflare, or Bunny CDN ($0.01/GB), also work.
- **Before publishing** (licenses; for Stephen and the credits page he is writing):
  - **City imagery:** the photo layer is the City's 2024 aerial imagery, and the illustration is derived from it. OpenDataPhilly says the City "retains all rights" to the aerials. Resolved: Stephen (Nov. 9): "We're good on the aerial imagery."
  - **OpenStreetMap (ODbL):** OSM data shaped the façade colors and the golf-course corrections. Credit "© OpenStreetMap contributors" on the page. The map's credits string mentions OSM only for façade colors; it should cover golf courses too.
  - **Gemini disclosure:** the style LoRA was trained on Gemini 3 Pro Image outputs, and the Gemini API terms restrict using outputs to develop models. Stephen decided (Nov. 2) to disclose it wherever the map is presented or published; see Licensing below.
  - **Other credits:** check the remaining sources for the credits page: USGS NHD water; LiDAR (2022, "City of Philadelphia via PASDA"); USFWS NWI wetlands; PPR parks and trees; the City water (PWD), limits and footprint layers; SEPTA rail.

## Preview flyover video (Nov. 5)

`uv run python scripts/29_flyover.py preview` renders `output/flyover/preview.mp4` from the frozen v14 tiles. The video is 30 s at 1080p, 30 fps: City Hall's tower, down Broad St, then a pull-back to the whole city.

- **Editing the route:** the camera path lives in `config/flyover/preview.json`; that file's `about` explains the fields. Copy it to `config/flyover/<name>.json` for another route.
- **Test cuts:** add `--seconds 10`.
- **Pixel art:** keep close-up scales at 1 or 0.5 and pan at a constant scale, so the pixels stay crisp.
- **Credit line:** the burned-in credit is provisional until the credits page is written.

## Open issues

Tracked across rounds; details in CHANGELOG.

| Issue | Where | Likely cause | Kind |
|---|---|---|---|
| Ships (Stephen, Oct. 23 and Nov. 5): **mostly fixed in v15, pending review** | Navy Yard, Packer Ave, Pier 82, Penn's Landing, Tioga, Schuylkill | Reviewed vessel outlines from the 2024 aerial (`config/vessels.json`) and OSM piers now protect hulls and piers from the water repaint. Each accepted hull is one structure at water level, shaped by the 2022 LiDAR where it saw the same hull or flat at an assumed height by kind. Still open: the carrier's and SS United States's hull sides carry window-like lines; the Moshulu keeps its flat v14-style drawing (LiDAR masts drew as towers); cranes stay partial | Geometry and drawing |
| Ben Franklin and Walt Whitman bridges (Stephen, Nov. 9: "look awful," "buildings on the roadway"): **fixed in v18, pending review** | Delaware River, south_lidar | Modeled in 3D (`config/bridge_structures.json`): deck buildings, the shadow slab and the invented spans are gone, and both towers draw. Accepted flaws: the Ben Franklin's PA anchorages draw as blue blocks (real ones are stone); a thin brown strip (~8 px) along the deck's lower edge; the Ben Franklin's PA approach ends ~8 m up near 5th St; the NJ approaches use estimated grades and end in the air | Geometry |
| Second Packer Ave crane cluster drawn as a high-rise | ~330 m south of the Walt Whitman | The 2022 LiDAR shaped container cranes into roof parts; the reviewed cap (`config/part_caps.json`) covers only the cluster by the PA tower. Not addressed | Geometry (reviewed list) |
| Shadow strips and Platt Bridge rectangles (accepted in v17) | W Roosevelt Blvd, Platt Bridge | Raw drawn colors inside the water-level bridge bands; no safe color rule (CHANGELOG, Nov. 8) | Repaint |
| Construction sites drawn with invented water or lawns | Penn's Landing and elsewhere | Drawing-model behavior on featureless ground | Model (training) |
| Teal invented water not caught by the scan | Cobbs Creek construction site (found by eye and redrawn Nov. 4) | The scan's water hue band is 185–215°; the model sometimes draws water at hue ~165°. Widening the band also catches real pools and basins, so each hit would need review | Scan rule |
| Stadium outer walls drawn with windows | The Linc, CBP, Franklin Field | Drawing-model behavior: tall walls read as façades | Model (training) |
| Franklin Field's lower deck missing | Franklin Field | Hidden under the upper deck; aerial LiDAR can't see it. Showing it would mean inferred geometry and raised parts in the renderer | Geometry (inferred) |
| CBP's tallest element capped at 50.5 m (was 71 m) | Citizens Bank Park | The base is now street level, not the sunken field, and the 99.5th-percentile cap clips it | Geometry |
| One kept needle, 51 m | 905-11 Walnut St | Matches the footprint's typical City height; the aerial is inconclusive | Geometry |
| Region joins slightly visible at 1:1 | All region joins (worst: a pool drawn two colors at the North/West corner, seam 6.94) | The two regions draw straddling content a little differently; the repair pass narrows it (join seam median 2.36 vs. 1.02 inside regions) | Sampler |

## Licensing and open questions (for legal / standards)

- **City data.** OpenDataPhilly lists these layers under the "City of Philadelphia License". Its aerial imagery page says the city "retains all rights." Stephen said Nov. 9 that use of the aerial imagery is cleared ("We're good on the aerial imagery").
- **OpenStreetMap.** The bridge towers, bridge decks and approaches come from OSM (ODbL 1.0); credit "© OpenStreetMap contributors".
- **Gemini outputs as training data.** The map's style LoRA (`qe2511_oldcity_r16_v1`) was trained on Gemini 3 Pro Image outputs (see Phase 2 above). The Gemini API terms restrict using outputs to develop models.
  - **Attempts to replace it with a clean style:**
    - prompt-only drawing;
    - a LoRA self-distilled from prompt-only drawings;
    - a full-quality, palette-snapped variant.
  - All three looked clearly worse (Stephen, Oct. 29 and Nov. 2; `output/style/compare.html`, `output/trainset_clean_v2/sweep/`).
  - **Decision (Stephen, Nov. 2):** the map uses the original style. Counsel isn't available for this project. Anyone presenting or publishing the map should disclose that the style was trained on Gemini outputs.
- **Labelling.** Treat the output as an AI-generated illustration and label it that way.
- **Google 3D Tiles.** Deliberately not used; see the top of this file.

## Credits

Method after [isometric-nyc](https://github.com/cannoneyed/isometric-nyc) by Andy Coenen (MIT) and the [tiny.london write-up](https://tiny.london/how/) by Boris Starkov.

Data: City of Philadelphia; Philadelphia Parks & Recreation; Philadelphia Water Department; 2022 LiDAR from the City of Philadelphia via PASDA. See `data/README.md`.
