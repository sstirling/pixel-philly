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

# 4. Render the 30 frames and the mosaic into output/renders/
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

# 8. Repaint open water in one style (output/postprocessed/redraw_v3/water/)
uv run python scripts/10_repaint_water.py --prompt redraw_v3

# 9. Optional, not recommended at present: one shared 40-color palette on a 2x pixel grid
uv run python scripts/11_pixelize.py --prompt redraw_v3

# 10. Comparison page: open output/compare/index.html in a browser
uv run python scripts/08_compare_page.py --prompt redraw_v3 --stage water
```

Redraws are stored per prompt version in `output/redraws/<version>/`, each with its own `log.jsonl`, so versions can be compared. Snapshots of the renders that fed v1 and v2 are in `output/renders_v1/` and `output/renders_v2/`.

Every step can be rerun:
- Raw downloads are never overwritten. A download made for a different extent is refused rather than reused.
- The redraw step skips frames that already have output and logs every call to `output/redraws/<version>/log.jsonl`. Rejected images are kept, not deleted.

### Another neighborhood

1. Copy `config/oldcity.json`.
2. Change `name`, `label` and `bbox_wgs84`.
3. Set `max_height_m` above the tallest building in the area.
4. Point the scripts at the new config. Right now they load `oldcity` by default via `load_config()`.

## Layout

| Path | What it is |
|---|---|
| `config/oldcity.json` | Area bbox, camera, imagery zoom, height defaults |
| `src/pixelphilly/projection.py` | WGS84 → local meters → isometric pixels. The single source of truth for the camera; the renderer receives its numbers. |
| `src/pixelphilly/heights.py` | Building height rule (see below) |
| `src/pixelphilly/sources.py` | ArcGIS download helpers and the provenance manifest |
| `src/pixelphilly/water.py` | River polygons in screen space; the per-frame water sentence |
| `src/pixelphilly/qa.py` | Seam ratio, flat share (photo-copy test) and registration shift |
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

## Licensing and open questions (for legal / standards)

- **City data.** OpenDataPhilly lists these layers under the "City of Philadelphia License". Its aerial imagery page says the city "retains all rights." Before publishing, confirm with maps@phila.gov that publication and AI-derived works are allowed.
- **Gemini outputs.** Check the Gemini API terms for any limit on publishing outputs or using them as training data. Training data would matter only if this moves to a fine-tuned model.
- **Labelling.** Treat the output as an AI-generated illustration and label it that way.
- **Google 3D Tiles.** Deliberately not used; see the top of this file.

## Credits

Method after [isometric-nyc](https://github.com/cannoneyed/isometric-nyc) by Andy Coenen (MIT) and the [tiny.london write-up](https://tiny.london/how/) by Boris Starkov.

Data: City of Philadelphia; Philadelphia Parks & Recreation; Philadelphia Water Department. See `data/README.md`.
