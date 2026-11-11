# Pixel Philly

An isometric pixel-art map of all of Philadelphia, drawn by an AI image model from City of Philadelphia open data. A project by Stephen Stirling.

**See it:** https://pixelphilly.sstirling.com (current version: **v18**, frozen Nov. 9, 2026)

The map is an **AI-generated illustration**, not a photograph or a survey. Buildings, streets and water come from public data, but an image model drew every pixel, and it gets details wrong. The drawing style was trained on images made with Google's Gemini 3 Pro Image model; see [Licensing and disclosure](#licensing-and-disclosure).

The idea comes from [tiny.london](https://tiny.london) and [isometric.nyc](https://isometric.nyc). Both start from renders of Google Photorealistic 3D Tiles. Google's Maps Platform terms bar that use: §3.2.3 (a)–(c) forbid storing or caching the content, creating content from it, and using it "to train, test, validate or fine-tune" AI models ([terms](https://cloud.google.com/maps-platform/terms), last modified Aug. 26, 2026). Pixel Philly builds its own 3D city from public data instead.

**Contents**
- [How it was made](#how-it-was-made)
- [Scale and cost](#scale-and-cost)
- [Map versions](#map-versions)
- [Rebuild the map](#rebuild-the-map)
- [Repository layout](#repository-layout)
- [Design decisions and assumptions](#design-decisions-and-assumptions)
- [Known issues](#known-issues)
- [Licensing and disclosure](#licensing-and-disclosure)
- [More detail](#more-detail)

## How it was made

```
 public data ──► 3D scene ──► isometric renders ──► QA gates ──► AI redraw ──► water repaint ──► fixes ──► tiles ──► viewer
 (City, PASDA,    (LiDAR       (three.js,           (no GPU      (Qwen +       (one style,       (targeted   (Deep    (OpenSeadragon,
  USGS, OSM)       shapes,      1,024 px frames      spend until  style LoRA,   invented water    redraws)    Zoom)     Cloudflare R2)
                   facades)     on one lattice)      they pass)   seam-free)    removed)
```

1. **Gather public data** (`scripts/01`–`04q`). Building footprints and heights (Licenses and Inspections), the 2022 LiDAR point cloud (laser-scanned heights; City of Philadelphia via PASDA, the Pennsylvania Spatial Data Access archive), the City's 2024 3-inch aerial photos, street trees, parks and pools (Parks & Recreation), water (Philadelphia Water Department and USGS), property records (Office of Property Assessment, or OPA), streets, highways, SEPTA rail, wetlands (U.S. Fish and Wildlife Service), the city limits, and OpenStreetMap for building colors, golf courses, piers and bridges. Every download is logged with its exact query in `data/raw/MANIFEST.json`; raw files are never edited. Sources, vintages and licenses: [`data/README.md`](data/README.md).

2. **Build a 3D scene** (`scripts/05_build_scene.py`).
   - Footprints are extruded to their heights. Where LiDAR covers a building, it is split into stepped parts at measured heights, so City Hall's tower, domes and stadium bowls take their real shapes (`src/pixelphilly/lidar.py`).
   - Ground and roofs carry the aerial photo, run through a median filter about 1 m wide so the model redraws roofs instead of copying the cars on them.
   - Walls get windows, storefronts, porches and cornices from property records (building type, stories, material) and OpenStreetMap colors (`src/pixelphilly/facades.py`).
   - Street trees are placed from the inventory; woods get tree canopies at LiDAR treetops; golf courses get corrected turf colors.
   - Ships at berth and the Ben Franklin and Walt Whitman bridges are modeled from reviewed outlines, LiDAR and published dimensions (`config/vessels.json`, `config/bridge_structures.json`).
   - Reviewed data fixes are applied here, not by hand on the drawing: wrong heights, footprints that aren't stadiums, structures gone since 2022 (`config/height_overrides.json`, `stadium_exclusions.json`, `structure_exclusions.json`, `part_caps.json`).

3. **Render isometric frames** (`scripts/06_render.py`, `render/`). A three.js page in headless Chromium draws the scene with an orthographic camera tilted 45° down at 0.293 m per pixel, turned to a 54° bearing so Philadelphia's street grid sits at 45° to the screen (the same relationship isometric.nyc has with Manhattan's grid). The city is cut into 1,024 px frames on one global lattice, a fixed grid of frame positions shared by every region, so every frame lines up to the pixel with its neighbors. (A frame's slot on the lattice is also called a cell.) The renderer also writes a white building mask, which `scripts/09_check_alignment.py` compares against an independent Python rasterization.

4. **Check before spending money** (`scripts/18_qa_scan.py`, `scripts/22_run_region.py`). No GPU time is bought until the region passes: alignment, no unexplained "needles" (thin, tall LiDAR spikes that would draw as towers), at least 95% of footprints matched to a property record, and an estimated cost under the budget. Hits are reviewed against the aerial and either fixed in the data or listed in `config/qa_exceptions.json` with a reason.

5. **Redraw as pixel art** (`scripts/15_joint_sample.py`, `gpu/modal_app.py`). An open image-editing model, Qwen-Image-Edit-2511 with the Lightning 8-step LoRA (both Apache 2.0), redraws each render, starting from noise and refining it over eight steps ("denoising"), with the prompt "Redraw this render as isometric pixel art in the pixel philly style." The style comes from a LoRA (a small add-on model that teaches the base model one look; `qe2511_oldcity_r16_v1`) trained on 141 Old City renders paired with Gemini 3 Pro Image redraws (`scripts/13`, `14`). Three replacement styles that used no Gemini output were tried. All three were noisier, invented more cars and colored specks, or both, so the map keeps this one. The drawing uses a fixed seed (0).

6. **Draw without seams.** Drawing frames one at a time leaves visible tone shifts at every border. Instead, as tiny.london does, the model denoises a whole region as one image: overlapping windows are predicted separately and averaged at every denoising step. The seam ratio measures this: the average color jump across frame borders divided by the average jump between any two neighboring pixels, so 1.0 means the borders are invisible. On the Old City test, joint drawing cut it from 3.7 to 1.09, about the same as the plain render's 1.08.

7. **Draw the city in regions.** One region tops out around 1,300 frames (the GPU job's four-hour limit), so the city is 12 regions on the same lattice. Each is drawn next to regions already finished: the neighbor's drawn frames are held fixed during denoising (the "known band," listed as "known neighbors" in the rebuild table below), then a 200 px strip on the new side is re-noised and redrawn to reconcile buildings that straddle the join (`src/pixelphilly/regions.py`, `joint_sampler.py`).

8. **Repaint water and fix mistakes** (`scripts/10_repaint_water.py`, `10b_scan_invented_water.py`). The model picks its own water color in every frame, so open water (USGS outlines checked against the render's colors) is repainted in one style. The same step removes water the model invented on land. Problems found by review are fixed by changing the scene and redrawing only the affected frames, with their neighbors held fixed: woods and golf, region borders, ships, the bridges.

9. **Cut tiles and show them** (`scripts/16_build_tiles.py`, `viewer/`). The regions merge into one Deep Zoom pyramid: the full map cut into 512 px lossless WebP tiles, plus smaller copies at each zoom level, so the browser loads only what's on screen. The viewer is plain JavaScript with OpenSeadragon: crisp pixels up close, shareable links, and address search through the City's AIS geocoder.

10. **Freeze and publish** (`scripts/26_freeze_map.py`). An accepted version gets a manifest with a SHA-256 over every file and is never rebuilt. The current version's illustration tiles and the viewer are hosted on Cloudflare R2.

## Scale and cost

- **Coverage:** the whole city, clipped to the city line. 12 regions, 3,254 frames of 1,024 × 1,024 px (cells per region in `output/philly/FROZEN_v18.json`).
- **Tiles:** 37,681 per layer; v18 is 75,367 files and 5.54 GB with the photo layer. Only the illustration layer is hosted: the 37,681 tiles (plus a libvips metadata file) in `map_files/`, `map.dzi` and `map.json`, about 4.3 GiB. The photo layer, the renders the drawing was made from, is built with `--with-photo` for side-by-side review but not published.
- **Seams:** inside a region, joint drawing keeps frame borders near 1.0. Where two separately drawn regions meet, they match less well: across the 335 frame edges on region joins, the median seam ratio in v18 is 2.45, and the worst is 10.32, on the South/North join (`output/philly/join_seams_v18.json`). At 1:1 the joins can be found, mostly as texture or color changes in parks and lots; at normal browsing zoom they are hard to see.
- **GPU cost (estimate): about $150.** `output/gpu_runs.jsonl` logs 155 runs totaling $149.71 and 37.4 hours on rented Nvidia H100 GPUs through [Modal](https://modal.com): $129.95 for drawing and redrawing the map, $12.78 for training LoRAs (the map's and a rejected clean-style one), $3.19 for building the clean-style training set, $2.23 for early tests and $1.56 of estimated start-up overhead. Each run's figure is estimated from its own server time. Start-up time for most drawing runs isn't logged, so the true total is somewhat higher; it hasn't been checked against Modal's bills.
- **Gemini calls (estimate): about $21**, billed separately: about $16 for the 141 training pairs and $4.82 for the Old City pilot.
- **Hosting:** Cloudflare R2's free tier covers this size; expected cost is about $0 a month.

## Map versions

| Version | Frozen | What it is | Open with |
|---|---|---|---|
| **v18** | Nov. 9, 2026 | **Current.** v17 plus the Ben Franklin and Walt Whitman bridges modeled in 3D. Viewer default and hosted | `?v=v18` (default) |
| v17 | Nov. 9, 2026 | v14 plus ship fixes (v15) and bridge-deck fixes (v16, v17). Also hosted | `?v=v17` |
| v14 | Nov. 4, 2026 | The first full-city map. Local only, plus an offline copy | `?v=v14` |

Each frozen version has a manifest, `output/philly/FROZEN_<version>.json`. Check one with `uv run python scripts/26_freeze_map.py --name philly --version v18 --verify`. Don't rebuild or edit a frozen version; **the next version is v19.** A change for v19 usually means: fix the scene data or a reviewed config list, rerender the affected region, redraw only the frames that changed ("Fix passes" below), merge and repaint, then build v19. Versions before v14 were working builds; the CHANGELOG describes each.

## Rebuild the map

Commands use `uv run`, which runs inside the project's `.venv`. Most steps take an area name through the `PP_AREA` environment variable; each area's settings are in `config/<area>.json`.

Drawing uses a fixed seed, but a byte-for-byte rerun of v18 from scratch hasn't been tested; the frozen tiles are the reference copy.

### One-time setup

```bash
uv sync --python 3.12 --group dev --group gpu    # creates .venv (Python 3.12) with test and GPU tools
uv run playwright install chromium                # the headless browser that renders the scene
uv run modal token new                            # Modal account for GPU time (per-second billing)
uv run modal deploy gpu/modal_app.py              # inference app (Qwen-Image-Edit-2511 + Lightning, pinned commits)
uv run modal run gpu/modal_app.py::download_weights   # ~58 GB into the pp-weights Volume, once
uv run modal deploy gpu/train_app.py              # training app (ai-toolkit)
```

**The style LoRA.** It lives in Modal's `pp-runs` Volume at `/runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors`. To train it again you need a Gemini API key (`cp .env.example .env`):

```bash
export PP_AREA=oldcity      # run the data, scene and render steps for Old City first (see below)
uv run python scripts/07_redraw.py --prompt redraw_v3 --max-calls 30    # Gemini redraws of the Old City frames
uv run python scripts/13_build_trainset.py                              # 141 training pairs (~$16 of Gemini calls)
uv run python scripts/14_train_lora.py prepare
uv run python scripts/14_train_lora.py start     # rank 16, 2,000 steps, ~1.6 h on an H100, ~$6.50; detached
uv run python scripts/14_train_lora.py status    # then `fetch` downloads checkpoints and samples
```

### Draw the 12 regions (run `qwen_joint_light8_fac`)

Draw the regions in this order. "Known neighbors" lists the finished neighbors held fixed, with the number of shared frames.

| # | Region | Known neighbors (shared frames) | How |
|---|---|---|---|
| 1 | `south_lidar` | none | `15_joint_sample.py` run directly |
| 2 | `north_lidar` | south (41) | `15` directly |
| 3 | `upper_north_lidar` | north (35) | `15` directly |
| 4 | `west_lidar` | south (24), north (2) | `15` directly |
| 5 | `west_north` | south (10), north (23), upper_north (5), west (64) | region runner, budget $4.83 |
| 6 | `germantown` | upper_north (40) | region runner, $5.75 |
| 7 | `southwest` | south (129), west (20) | region runner, $6.96 |
| 8 | `east_riverfront` | south (11), north (19), upper_north (4) | region runner, $4.19 |
| 9 | `roxborough` | north (2), upper_north (53), west_north (1), germantown (73) | region runner, $9.07 |
| 10 | `lower_northeast` | upper_north (22), east_riverfront (30), germantown (14) | region runner, $11.49 |
| 11 | `northwest` | germantown (117), roxborough (92) | region runner, $15.00 |
| 12 | `upper_northeast` | lower_northeast (153) | region runner, $11.00 |

**Regions 5–12: the region runner.** One command runs every step for a region: fetch, scene, render, mask, alignment, QA scan, the stop gates, the GPU drawing, collecting the result, the water repaint and the invented-water report. It is resumable and never launches the GPU job twice. For example (each region's known neighbors and budget are in the table above):

```bash
uv run python scripts/22_run_region.py west_north --plan    # list the steps and which are done
uv run python scripts/22_run_region.py west_north \
    --known south_lidar,north_lidar,upper_north_lidar,west_lidar \
    --run-name qwen_joint_light8_fac --lightning 8 --budget-usd 4.83 \
    --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
```

Inside, the runner issued this drawing and repaint (copied from `output/west_north/region_run.log`):

```bash
PP_AREA=west_north uv run python scripts/15_joint_sample.py --full --volume --detach --name qwen_joint_light8_fac \
    --lightning 8 --known-area south_lidar,north_lidar,upper_north_lidar,west_lidar --known-name qwen_joint_light8_fac \
    --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
PP_AREA=west_north uv run python scripts/15_joint_sample.py --collect --name qwen_joint_light8_fac   # repeated until done
PP_AREA=west_north uv run python scripts/10_repaint_water.py --prompt qwen_joint_light8_fac --invented-water fix \
    --known-area south_lidar,north_lidar,upper_north_lidar,west_lidar --known-prompt qwen_joint_light8_fac
```

If the runner stops partway, rerun it; finished steps are skipped.

**Regions 1–4** run the same steps one script at a time: the fetch scripts (`01`–`04k`, plus `04n` golf and `04o` piers where the config asks), `05_build_scene.py`, `06_render.py` and `06_render.py --mode mask`, `09_check_alignment.py`, `18_qa_scan.py`, then the `15_joint_sample.py --full --volume` drawing above (no `--known-area` for south_lidar), collect, and `10_repaint_water.py`. Upper North and West both need North finished first.

**Important settings** (all in `config/<area>.json`): `"building_shapes": "lidar"`, `"facades": "opa"`, `"woods_trees"`, `"golf_correct"` and `"lawn_correct"` in all 12 regions; `"clip_to_city": true` in regions 5–12; a shared `"projection_origin"` ([-75.165, 39.9275], south_lidar's center) in every region but South; `"vessels"` in south, southwest and east_riverfront; the `"bridge_*"` flags only in south_lidar. The fetch scripts take no arguments beyond `PP_AREA`. The bridge fetches aren't runner steps; run them by hand for south_lidar: `PP_AREA=south_lidar uv run python scripts/04p_fetch_bridges.py`, then `04q_fetch_bridge_towers.py`. The `fac` in the run name stands for facades.

### Fix passes: redraw only what changed

After a scene fix, only the frames whose render changed are redrawn, with every surrounding frame held at its finished pixels (`--context 1` keeps one ring of frames around each redrawn frame in the drawing window). Every pass below used this form; this is the last v18 pass, `_v18rest`, from the pipeline script logged in `output/philly/v18_pipeline.log` (its frame list is shortened here):

```bash
PP_AREA=south_lidar uv run python scripts/15_joint_sample.py --full --volume \
    --known-area south_lidar,north_lidar,upper_north_lidar,west_lidar,west_north,southwest,germantown,east_riverfront,roxborough,lower_northeast,northwest,upper_northeast \
    --known-name qwen_joint_light8_fac --redraw frame_06_12,frame_07_12 --context 1 --name qwen_joint_light8_fac_v18rest \
    --style /runs/lora/qe2511_oldcity_r16_v1/qe2511_oldcity_r16_v1.safetensors --lightning 8 --steps 8 \
    --prompt-text "Redraw this render as isometric pixel art in the pixel philly style."
# then the same command with --collect, repeated until done
```

**Merging a pass is a manual step; no script in the repo does it.**
1. Back up the frames being replaced, to `output/<area>/redraws/qwen_joint_light8_fac_pre_<suffix>/`, where the suffix names the pass (for example `_pre_bridges`).
2. Copy the pass's PNGs from `output/<area>/redraws/<pass>/` into `output/<area>/redraws/qwen_joint_light8_fac/`.
3. Repaint the area: `10_repaint_water.py --prompt qwen_joint_light8_fac --invented-water fix`.
4. Re-repaint any neighboring area that holds copies of those frames in `water_band/` (each area's repaint keeps its own copy of a neighbor's frames along the join, so water matches across it). `15_joint_sample.py` and `16_build_tiles.py` refuse to run on stale cells, so a missed step stops the build rather than slipping through.

Passes whose frames are in v18:

| Pass | Regions | Purpose |
|---|---|---|
| `_trees` | 10 regions | Woods drawn as tree canopies, with the golf correction folded in |
| `_border`, `_fix14c` | roxborough | Seams with germantown, upper_north and west_north |
| `_cobbs2` | west_lidar | The Cobbs Creek park strip |
| `_fix14`, `_fix14b`, `_fix14e` | west_north | North and upper_north borders, West Fairmount Park, the Cobbs strip, a cricket field |
| `_ships` | south_lidar, east_riverfront | Hulls and piers at berth (v15) |
| `_bridges3d`, `_v18rest` | south_lidar | The 3D suspension bridges and the other frames their geometry changed (v18) |

Other `qwen_joint_light8_fac_*` folders hold earlier tries; none of their frames are in v18.

### Build, check, freeze and publish

```bash
AREAS=south_lidar,north_lidar,upper_north_lidar,west_lidar,west_north,southwest,germantown,east_riverfront,roxborough,lower_northeast,northwest,upper_northeast
uv run python scripts/16_build_tiles.py --areas $AREAS --name philly --prompt qwen_joint_light8_fac --version v19 --with-photo
uv run python scripts/25_join_seams.py --areas $AREAS --prompt qwen_joint_light8_fac --name philly --version v19
uv run python scripts/26_freeze_map.py --name philly --version v19            # after the version is accepted
uv run python scripts/26_freeze_map.py --name philly --version v19 --verify
uv run python scripts/27_offline_copy.py --name philly --version v19          # optional: a copy that runs with no internet
uv run python scripts/34_site_images.py --version v19                         # favicon, touch icon, social preview
uv run python -m http.server 8000     # then open http://localhost:8000/viewer/?v=v19
```

- `16_build_tiles.py` refuses to overwrite an existing version. The order of `--areas` decides which region owns a shared frame; it is the order above, which swaps germantown and southwest relative to the drawing order.
- `26_freeze_map.py` writes a generic `purpose` into the manifest; edit it to describe the version.
- To make a new version the default, change the fallback version in `viewer/viewer.js` and the version line in `viewer/about.html`.

**Hosting** (Cloudflare R2 bucket `pixel-philly`, served at https://pixelphilly.sstirling.com through Cloudflare's cache). Objects keep their repo paths, so the viewer's relative links work unchanged. The rclone remote `r2` holds the credentials in `~/.config/rclone/rclone.conf`; never commit or print that file. To publish a version:

```bash
B=r2:pixel-philly/output/philly/tiles/v19
rclone copy output/philly/tiles/v19 $B --include "map_files/**" --transfers 32 --checkers 64 --s3-no-check-bucket \
  --header-upload "Cache-Control: public, max-age=31536000, immutable"       # tiles never change once published
rclone copy output/philly/tiles/v19 $B --include "map.dzi" --s3-no-check-bucket \
  --header-upload "Content-Type: application/xml" --header-upload "Cache-Control: public, max-age=300"
rclone copy output/philly/tiles/v19 $B --include "map.json" --s3-no-check-bucket \
  --header-upload "Content-Type: application/json" --header-upload "Cache-Control: public, max-age=300"
rclone check output/philly/tiles/v19/map_files $B/map_files --one-way        # expect 0 differences
rclone copy viewer r2:pixel-philly/viewer --s3-no-check-bucket --header-upload "Cache-Control: public, max-age=300"   # last
```

Upload the viewer last, so it never points at tiles that aren't there yet. The photo layer isn't uploaded. Two settings live in the Cloudflare dashboard, not the repo: a redirect from `/` to `/viewer/index.html`, and DNS. Address search works from this domain because the City's AIS API allows any origin. The hosted pages load a GoatCounter visit counter (no cookies); the offline copy removes it.

### Run the tests

```bash
uv run pytest      # projection, regions, LiDAR shaping, facades, water, bridges, viewer and more (tests/)
```

## Repository layout

| Path | What it is |
|---|---|
| `config/<area>.json` | One file per area: bounding box, camera, data and drawing options. The 12 city regions plus earlier and test areas (`oldcity`, `fishtown`, `centercity`, `downtown`, `atlas_*`, `test_*`); configs that no longer build are in `config/retired/`. `config/flyover/` holds video camera paths |
| `config/*.json` (others) | Reviewed lists applied in the scene build or QA: `qa_exceptions`, `height_overrides`, `stadium_exclusions`, `structure_exclusions`, `part_caps`, `invented_water_holds`, `golf`, `vessels`, `bridge_towers`, `bridge_structures`. Each entry records its reason and review date |
| `scripts/01`–`04q` (a few numbers are shared by two scripts, such as `23` and `25`; use the full file name) | Data downloads (buildings, trees, imagery, water, LiDAR, highways, rail, property records, OSM, streets, pools, parks, wetlands, city limits, golf, piers, bridges). `04m` prunes LiDAR tiles (dry run by default) |
| `scripts/05`, `06`, `09` | Scene build, render (color and mask), alignment check |
| `scripts/07`, `08`, `11`, `12`–`14` | Old City pilot tools: Gemini redraw, comparison page, palette test; Qwen baseline, training set and LoRA training |
| `scripts/10`, `10b` | Water repaint and invented-water scan |
| `scripts/15` | The joint, seam-free drawing on Modal (full regions, known bands, redraw passes) |
| `scripts/16` | Merge regions and cut Deep Zoom tiles |
| `scripts/17`–`21`, `24`, `25_clean_v2` | Experiments: problem atlas, landmark references, clean-style comparisons |
| `scripts/18`, `22`, `23_preflight_regions`, `25_join_seams` | QA scan, region runner, region pre-flight, seam scores |
| `scripts/23_build_clean_trainset` | The clean-style training set (not used in the map) |
| `scripts/26`–`28` | Freeze a version, make and check an offline copy |
| `scripts/29_flyover` | Flyover video from finished tiles |
| `scripts/29_trace_vessels`–`33` | Ship and bridge review: vessel tracing, crops and contact sheets |
| `scripts/34` | Favicon, touch icon and social preview cut from the tiles |
| `src/pixelphilly/` | The library: `projection.py` (the single source of truth for the camera), `lidar.py`, `facades.py`, `lawns.py`, `golf.py`, `vessels.py`, `bridges.py`, `water.py`/`waterpaint.py`, `regions.py`, `joint_sampler.py`, `region_runner.py`, `qa.py`/`qa_scan.py`, `viewer_geo.py` and others |
| `render/` | The three.js page that draws scenes (three.js r169, vendored, MIT) |
| `gpu/` | Modal apps: `modal_app.py` (drawing) and `train_app.py` (LoRA training) |
| `viewer/` | The map page, about page, OpenSeadragon 6.1.1 (vendored) and site images |
| `prompts/` | Versioned prompts from the Gemini pilot |
| `tests/` | pytest suite |
| `data/raw/`, `data/processed/` | Downloads (immutable, logged in `MANIFEST.json`) and derived files. Large files are git-ignored |
| `output/<area>/` | Everything generated for an area: renders, masks, drawings (`redraws/<run>/`), repainted frames, reports. `output/philly/tiles/<version>/` holds the merged maps |
| `output/gpu_runs.jsonl` | Cost estimate and duration of every GPU run |

## Design decisions and assumptions

Sources for each item are in [`data/README.md`](data/README.md); the reasoning and tests behind them are in the CHANGELOG.

- **Heights.** The City footprint layer's typical LiDAR height (`approx_hgt`) is used, then `max_hgt`, then 10 m. `max_hgt` is thrown off by cranes and stray returns, so it is not trusted alone. Where LiDAR is available, buildings are reshaped from the 0.5 m LiDAR grid into stepped parts; floating returns above roofs and stray spikes are removed by rules tested on landmarks (William Penn's statue survives at 166.8 m against 167 m published).
- **Flat ground.** Terrain is ignored; heights are measured from each building's local ground.
- **Walls (stylistic, from data).** The aerial shows roofs, not walls. Window grids, storefronts, porches and cornices are painted only where the property record says the building has them; storefronts and porches only on walls facing a street. Colors come from OpenStreetMap where mappers recorded them, else a palette by recorded material. Owner, sale, tax and condition fields are never fetched.
- **Water.** Open water is repainted a muted blue-gray (RGB 88, 124, 140) with light ripples. The real Delaware is brownish; blue is a pixel-art convention, as on tiny.london's Thames. A pixel is repainted only where USGS says water, the render's color matches the river and nothing is built on it, so boats, piers and bridges keep the drawing.
- **Trees and woods.** Street-tree canopy size is a rule of thumb from trunk diameter (1 m + 0.15 m per inch, 1.5–7 m), not a measurement. Woods get canopies at LiDAR treetops; a flat green forest floor was tried and failed, because the model read it as water.
- **Bridges.** The Ben Franklin and Walt Whitman are modeled from LiDAR deck profiles and published dimensions. Values not found in a source (the Walt Whitman's cable sag, hanger spacing, colors, crossbeam heights) are estimates, labeled as such in `config/bridge_structures.json`. Cables and hangers are drawn thicker than life so they show at map scale.
- **Alignment.** Every render's building mask is compared with an independent Python rasterization; frames must match with zero pixel offset. A few sparse frames full of small port structures fall below the overlap threshold from one-pixel edge rounding and were reviewed with diff images.
- **Data fixes are reviewed, not automatic.** When a check flags a building, the 2024 aerial is checked and the fix goes into a reviewed config list with its reason, so the change is visible and reversible.

## Known issues

Details and history in the CHANGELOG.

| Issue | Where | Cause | Kind |
|---|---|---|---|
| Ships: hull sides on the carrier and the SS United States carry window-like lines; the Moshulu keeps a flat drawing; cranes are partial | Navy Yard, Penn's Landing, Packer Ave | Drawing-model behavior; LiDAR masts drew as towers | Model, geometry |
| Bridges: the Ben Franklin's Pennsylvania anchorages draw as blue blocks (the real ones are stone); a thin brown strip along the deck's lower edge; the approaches end where the OSM bridge ways end | Delaware River | Modeling limits; estimated approach grades | Geometry |
| A second Packer Ave crane cluster draws as a high-rise | ~330 m south of the Walt Whitman | LiDAR shaped container cranes into roof parts; the reviewed cap covers only one cluster | Geometry |
| Shadow strips and dark rectangles at some bridge decks | W Roosevelt Blvd, Platt Bridge | Raw drawn colors in the water-level bridge bands; no safe color rule found | Repaint |
| Construction sites drawn with invented water or lawns | Penn's Landing and elsewhere | Model behavior on featureless ground | Model |
| Teal invented water isn't caught by the scan | One case at Cobbs Creek, found by eye and redrawn | The scan's hue band misses teal; widening it catches real pools | Scan rule |
| Stadium outer walls drawn with windows; Franklin Field's lower deck missing | The Linc, Citizens Bank Park, Franklin Field | Tall walls read as facades; aerial LiDAR can't see under the upper deck | Model, geometry |
| Region joins visible at 1:1 | All joins; worst on the South/North join | Two regions draw straddling content a little differently | Sampler |
| Merging a redraw pass is a manual copy, not a script | Fix passes | No merge script yet | Reproducibility |
| The map's credit line mentions OpenStreetMap only for facade colors; OSM also shaped golf courses, piers and the bridges | `map.json` credits | Not yet updated | Credits |

## Licensing and disclosure

- **City data.** OpenDataPhilly lists the City layers under the "City of Philadelphia License." The aerial imagery page says the City "retains all rights"; its use for this map has been cleared.
- **OpenStreetMap.** Building colors, golf courses, piers and the bridge towers, decks and approaches use OSM data (ODbL 1.0). Credit: "© OpenStreetMap contributors."
- **Gemini outputs as training data.** The style LoRA was trained on Gemini 3 Pro Image outputs, and the Gemini API terms restrict using outputs to develop models. Replacement styles with no Gemini output were noisier or invented more detail (`output/style/compare.html`), so the map keeps the original style. Anyone presenting or publishing the map should disclose that the style was trained on Gemini outputs.
- **Labeling.** Present the map as an AI-generated illustration.
- **Models.** Qwen-Image-Edit-2511 and the Lightning LoRA are Apache 2.0. tiny.london's Qwen-Image-2.1-Turbo was not used because its license is non-commercial.
- **Google 3D Tiles.** Deliberately not used; see the top of this file.

**Credits.** Method after [isometric-nyc](https://github.com/cannoneyed/isometric-nyc) by Andy Coenen (MIT) and the [tiny.london write-up](https://tiny.london/how/) by Boris Starkov. Data: City of Philadelphia; Philadelphia Parks & Recreation; Philadelphia Water Department; 2022 LiDAR from the City of Philadelphia via PASDA; USGS; U.S. Fish and Wildlife Service; National Park Service; SEPTA; OpenStreetMap contributors. Full list: [`data/README.md`](data/README.md).

## More detail

- [`docs/history.md`](docs/history.md): the build notebook, phase by phase, with the commands used at each stage (the Old City pilot, the seam-free method, LiDAR shapes, facades, regions, the style experiments, hosting research, the flyover video).
- [`CHANGELOG.md`](CHANGELOG.md): the day-by-day record, with every decision, test result and GPU cost.
- [`data/README.md`](data/README.md): every source, its vintage, license and query, and known data limits.
- [`viewer/about.html`](viewer/about.html): the public about page.
