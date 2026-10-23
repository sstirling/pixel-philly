# Changelog

## 2026-10-20: Old City pilot

### Research and approach
- Studied how tiny.london was built, from its [write-up](https://tiny.london/how/) and site code:
  - the pipeline is Google 3D Tiles → Gemini training targets → Qwen LoRA → joint denoising
  - the viewer is OpenSeadragon on R2
- Ruled out Google Photorealistic 3D Tiles as input. Maps Platform ToS §3.2.3 (a)–(c) bars storing it, creating content from it and using it to train AI.
- Chose City of Philadelphia open data instead: footprints with LiDAR heights, 2024 3-inch aerials, the tree inventory and PWD water.

### Built
- Shared projection module: WGS84 → local azimuthal-equidistant meters → isometric screen pixels, with frame lattice and three.js camera parameters.
- Data downloaders with a provenance manifest. Each downloader pages through ArcGIS results and checks the server count matches the download. Raw files are never overwritten, and a raw file fetched for a different extent is refused rather than reused.
- Scene builder:
  - aerial mosaic
  - building extrusion data with the height rule
  - per-building wall color from the aerial
  - tree canopies from trunk diameter
  - QA report
- three.js renderer driven by Playwright. It runs on the GPU through ANGLE/Metal on Apple silicon.
- Alignment check comparing WebGL masks with an independent Python rasterization.
- Gemini 3 Pro Image redraw script:
  - versioned prompt
  - per-frame water sentence
  - call cap and resumable runs
  - JSONL call log
- Self-contained comparison page with wipe sliders, mosaics and a river overlay.

### Changes made during the build
- **Camera bearing 15° → 54°.** Philadelphia's grid in Old City runs at a bearing of ~9°, measured from footprint edges, so a 15° view left streets nearly parallel to the frame. That looked like a tilted top-down map. At 54°, the grid sits at 45° to the screen, matching isometric-nyc's relationship to Manhattan's grid. This needed a larger fetch extent, so the raw data was re-downloaded.
- **Texture mapping: affine → quadratic fit.** The larger, ~3 km extent made the affine Web Mercator fit drift 0.28 m. The quadratic fit's worst error is 0.05 mm.
- **Ground texture cap 8,192 → 16,384 px.** The full z19 mosaic (12,800 px) now loads without downsampling. The renderer refuses textures over the GPU's limit rather than letting WebGL degrade them silently.

### Tuning the look (three prompt versions, two test frames each)

The test frames are frame_02_02 and frame_03_02, in the Old City core near 2nd and Arch. All six calls succeeded, ~16–17 s each, for about $0.80 in total.

"Flat share" is tiny.london's photo-copy test: the share of pixels whose 3×3 neighborhood is flat (tolerance 6 levels here). tiny.london's careful redraws scored 0.42–0.55 and half-copies 0.18–0.35. Our tolerance may differ from theirs, so compare our scores with each other, not with those ranges.

| Version | Render input | Prompt change | Flat share (02_02 / 03_02) | Result |
|---|---|---|---|---|
| v1 | aerial, walls take roof color | fidelity-first, style-only | 0.50 / 0.32 | Clean illustration, not pixel art. Everything beige. Invented a grove in a park. |
| v2 | walls ≤20 m tinted toward brick | true pixel art, "richer, more saturated", keep render colors | 0.37 / 0.27 | Copied more photo texture. Color inconsistent: one frame went tomato red. |
| v3 | brick tint + 5 px median-filtered aerial | v1 wording + pixel-art lines; keep hue, drop "saturated" | 0.48 / 0.40 | Best. Consistent muted brick across frames, real pixel edges, cars gone, less invention. |

Other findings:
- Every redraw registered against its render at scale 1.00 with zero pixel shift (phase correlation on edges), so frames can be stitched without drift.
- The deterministic pixelize step (`07b_pixelize.py`, since renamed `11_pixelize.py`: 2× box downscale, shared 40-color palette, nearest upscale) made v2 look mushy because v2 had copied photo texture. It is kept as an option to retry on v3.
- Earlier, the first redraw attempt failed with 429 RESOURCE_EXHAUSTED: this model has a free-tier quota of 0. Billing was enabled on the key's project. The redraw script now stops at the first quota error and counts cost only for calls that returned an image.

### Full Old City run (v3, all 30 frames)

- **Run.** 28 more calls, all succeeded (~16–18 s each). Total model spend for the pilot is 36 successful calls, about $4.82 at standard pricing.
- **Registration.** 28 of 30 frames match their render with zero shift, and frame_00_04 is off by 1 px. frame_05_01 reports a 155 px shift because the model invented a block of waterfront buildings on what the render shows as open river (99% water by the PWD layer).
- **Flat share.** Min 0.26 (frame_05_04), median 0.56, max 0.95 (open-water frames).
- **Seams.** This uses tiny.london's measure: the mean color jump across frame borders divided by the mean jump between neighboring pixels everywhere else. The render scores 1.08; the stitched redraws score 4.37, so there are strong seams.
  - On land they show as tone shifts between frames.
  - On the river they are glaring: each frame chose its own water color (blue, brown, olive, tan).
- **Other artifacts:**
  - The Ben Franklin Bridge was drawn from its flat photo and shadow, not as a structure.
  - One boat survived despite the prompt.
  - A tall white building got a tan wall face in frame_02_02.
- **What would fix the seams and the water.** Per-frame prompting can't. This is exactly what tiny.london solved with a fine-tuned model and joint denoising of the whole canvas, plus an OpenStreetMap water check and repair. Cheaper partial steps:
  - re-run hallucinated frames
  - pin the water to one color in post-processing using the water polygons, after adding the New Jersey half from OpenStreetMap
  - snap all frames to one shared palette with the pixelize step

### Fixes after the full run

1. **Redid frame_05_01.** One call, $0.13.
   - The first try is kept as `output/redraws/redraw_v3/rejected/frame_05_01_try1.png`, with the reason logged.
   - The new redraw sits within 2 px of the render and dropped the invented block, but still drew a few small buildings on a pier corner that the render shows as lawn.
   - `07_redraw.py` gained `--redo/--reason` for this.
2. **Repainted the water** (`10_repaint_water.py`).
   - Added the USGS NHD water area (`04b_fetch_water_nhd.py`) because the PWD layer stops at the state line.
   - Of 6.9 million NHD pixels in the mosaic, 5.9 million passed the open-water test and were repainted. The other 1.0 million were kept: bridge deck and shadow, piers, boats, shoreline.
   - Seam ratio 4.39 → 3.69 at full resolution.
3. **Pixelized** (`11_pixelize.py`, renamed from `07b`; now runs on the water-repainted frames by default).
   - At full resolution the seam ratio rose to 5.28. That is an artifact of the measure: inside each 2×2 art pixel the neighbor jump is zero, which shrinks the denominator.
   - Measured at art-pixel scale (all mosaics downscaled 2×, frame size 512): render 1.08, raw redraws 3.19, water-repainted 2.66, pixelized 2.64. The palette snap does almost nothing for seams, since a shared palette keeps each frame's tone.
   - Visually it is worse: dark outlines merge into wall colors, and roofs get speckled.
   - Kept as an option; the comparison page defaults to the water-repainted stage.

Also added `src/pixelphilly/qa.py` (seam ratio, flat share, registration shift) with 4 tests; 15 tests pass.

Total model spend for the pilot: 37 successful calls, about $4.96 at standard pricing.

**Still unsolved:**
- Tone shifts between frames on land.
- The bridge drawn from its photo shadow.
- A few water patches near piers that kept the model's color.
- The small invented buildings on the pier in frame_05_01.

The land tone shifts are what tiny.london's joint denoising solves. A cheaper experiment would be to match each frame's color statistics to its neighbors where they overlap; that would need overlapping frames, which the current lattice doesn't have.

## 2026-10-23: downtown redrawn with LiDAR building shapes (downtown_lidar v2)

Stephen approved redrawing downtown with LiDAR shapes after the atlas fixes. It runs as a new area, `config/downtown_lidar.json` (downtown plus `"building_shapes": "lidar"`), so v3 is untouched.

### Tiled scenes support LiDAR
- `main_tiled` in `05_build_scene.py` shapes every footprint once, before tiling, so overlapping render tiles always agree. The `NotImplementedError` guard is gone, and the LiDAR QA keys are written for tiled areas too.
- **Check:** a tiled build of City Hall (2 × 2-frame tiles) and the single-scene build gave identical part ids, heights and outlines (2,849 of 2,849).
- A progress line every 5,000 footprints.

### Data and build
- **Data:** 71,517 footprints (fetched Oct. 22), 41,906 trees, 43 PWD and 23 NHD water polygons. The USGS NHD service returned a 504 once; the retry loop was fixed to check the right exit code.
- **LiDAR:** 54 LAS tiles, 18 already on disk from the atlas. 55 GB of LiDAR now on disk.
- **First build:** 34 min, 4.6 GB peak RAM. Gridding is most of that; shaping took 2.5–3 min, so it stays single-process.
- **Shaping:** 56,285 footprints shaped into 145,592 parts. 463 fell back to a single height (no usable returns). Footprints more than 100 m outside the box keep single heights (`LIDAR_MARGIN_M`).
- **Grid cache:** `data/processed/downtown_lidar_lidar_grid.npz`, 661 MB.
- **Rendering:** 304 frames in 2 min.
- **Alignment:** 260 of 261 checked frames pass.
  - `frame_09_18` (a mostly-river frame, 9,035 building px) scores IoU 0.9685 with zero shift.
  - Its 285 mismatched pixels are all 1 px edge rounding on stair-stepped outlines.
  - Reviewed and accepted; the threshold was not changed.

### Spike-rule fixes found by the first downtown run
The first drawing (kept as `redraws/qwen_joint_light8_pre_spikefix/`, tiles v1, not used) still had needles. A scan for parts under 40 m² taller than twice everything within 3 m found four.

- **City Hall's west-wing cluster (145.7 m).**
  - **Cause:** on the downtown grid's cell alignment the cluster straddled tier boundaries, and the sieve folded the pieces into the roof label while their heights stayed. It then re-formed when the tier step coarsened.
  - **Fix:** the spike check now also runs at every tier step.
  - **Test:** a real-data fixture, `tests/fixtures/cityhall_downtown_grid.npz`.
- **Three clusters at 226-30 N 2nd, 905-11 Walnut and 3900-06 Chestnut.**
  - **Cause:** their City `max_hgt` matched them. `max_hgt` is the highest LiDAR return, so the same noise set it (203 ft max vs. 59 ft typical on N. 2nd).
  - The 2024 aerials show no tower and no shadow at any of them.
  - Real steeples taper (Independence Hall rises from 20 m to 42 m in small steps), so they never needed the exemption.
  - **Fix:** the `max_hgt` exemption was removed.
- **Over-correction, caught by an aerial check.**
  - Removing all exemptions also flattened the Linc's roof canopy pieces and wings of 1514 and 1224 Chestnut, all at the City's *typical* height (`approx_hgt`).
  - Noise never matched the typical height in any confirmed case.
  - **Fix:** a region within 5 m of `approx_hgt` is exempt.
- **Tests:**
  - `test_spike_matching_an_inflated_city_record_is_still_dropped`
  - `test_cityhall_downtown_grid_has_no_stray_spire`
  - `test_tapered_steeple_is_kept` (replaces the untapered steeple test)
  - `test_region_matching_the_typical_city_height_is_kept`
  - 61 pass. Old City byte-identical.
- **Atlas:** all nine scenes rebuilt. Only City Hall and the Linc changed, and both were redrawn (~$0.30). Sheet rebuilt.
- **Downtown after the fixes:** the needle scan finds one part, a 6.5 m², 51 m piece on 905-11 Walnut. It is kept because it matches that footprint's 49 m typical height, while most of the footprint measures 13 m. The aerial is inconclusive, so it was left.

### Result: `output/downtown_lidar/tiles/v2`
- **Drawing:** 53.0 min on one H100, ~$3.49. 1,215 windows.
- **Tiles:** 2,941 tiles, 451 MB, plus the 74 MB photo layer. Viewer: `?area=downtown_lidar&v=v2`.
- **Seams** (neighbor-relative ratio, 525 frame-border segments, same method for both):
  - v3: median 1.016, 95th pct 1.45
  - LiDAR v2: median 1.013, 95th pct 1.38
- **Spot checks:**
  - City Hall's tower and William Penn are drawn, with no stray needles on the wings.
  - The Cathedral dome is drawn, with no spires next door.
  - Franklin Field's stands step down to the track.
- **Spend:** downtown_lidar ~$6.93 (two full drawings; the first was invalidated by the spike bugs). Atlas total ~$4.63.

## 2026-10-22 (night): LiDAR shape fixes after the atlas review

Stephen flagged an unrealistic spire at City Hall and asked for the errors found in the LiDAR drawings to be fixed before downtown. Tests first for each, then the fix (subagent), then verification.

### Fixes (`src/pixelphilly/lidar.py`)
- **Stray spires.**
  - **Cause:** two clusters of stray returns at 144–147 m on City Hall's 45 m wings (9.5 and 11.2 m² in the grid) rendered as needles. City Hall's 170 m height record (its tower) let them pass the noise ceiling.
  - **Rule:** a region under 40 m² that rises more than max(20 m, its surroundings) above the tallest neighboring region is flattened into the roof. It applies only when the building has a City height record and the region's top is more than 5 m below it.
  - **Tests:** `test_small_spike_far_above_its_roof_is_dropped_even_under_the_ceiling`, plus `test_steeple_that_sets_the_city_height_is_kept` to protect real steeples.
- **Shared tier heights.**
  - **Cause:** every region in a height tier got the tier-wide median, which is why both spikes read exactly 150.35 m.
  - **Fix:** each region now gets the median of its own cells.
  - **Test:** `test_separate_regions_in_one_tier_keep_their_own_heights`.
- **William Penn.**
  - **Cause:** the LiDAR has him (36 cells over 158 m, top 167.8 m), but the median filter and 6 m² speck merge erased him.
  - **Rule:** cells within 5 m of the City record are "confirmed". The tallest confirmed element on a tall part is kept down to 2 m².
  - **Result:** City Hall's tallest part is now 166.8 m (167 m published).
  - **Tests:** `test_statue_confirmed_by_city_record_is_kept`, plus `test_small_tall_region_without_a_record_still_merges`.
  - **Why only one element per building:** rescuing every confirmed cluster brought back rooftop clutter, since on ordinary buildings the record is the rooftop equipment.
- **Debugging:** `PP_LIDAR_LOG=1` prints every flattened and kept region.
- **The subagent changed three rules from the approved plan**, each needed to get the City Hall result:
  - Surroundings are measured as the tallest neighboring region, not the tallest ring cell. The speck merge folds the stray cloud's outliers into the wing roof, so the ring maximum read ~150 m.
  - The confirmation band is 5 m, not 3 m.
  - Only one confirmed element is rescued per building.

### Verification
- **Tests:** 57 pass.
- **Old City:** scene byte-identical (SHA-256).
- **Rebuilt all nine LiDAR atlas scenes.** Alignment PASS on all.
- **Flattened regions:**
  - City Hall: 2, both stray clusters.
  - Cathedral: 6, all 143–161 m clusters on 1–22 m roofs south of the cathedral, noise. (8 after the follow-up below.)
  - Citizens Bank Park: 1, a 16 m² region at 38 m on the stands. **It may be real** (a light tower or sign) and is now lost.
- **Part counts rose slightly.** For example, City Hall went from 1,663 to 1,751 parts, mostly one small rooftop element per building near its recorded height.
- **Redrawn:** all nine on the GPU. The previous drawings are kept as `redraws/qwen_joint_light8_v1shapes/`. 9 runs, ~$1.28. Atlas total so far: 30 runs, ~$4.20.
- **Sheet:** rebuilt with updated notes.

### Follow-up: spires on a building with no City height (reported by Stephen)
- **Symptom:** in the Cathedral Basilica row, the building next door (footprint 545892, "1701L Race St") drew two large spires that aren't real.
- **Cause:** its main body measures 73.7 m, but two ~7 m² clusters of stray returns sat at 159.6 and 179.6 m. The footprint has no City height record, and the spike rule only ran when there was one.
- **Fix:** the spike rule now runs for every building. The "matches the City record" exemption only applies when a record exists, since with no record nothing confirms a spire. Test first: `test_spike_is_dropped_when_the_building_has_no_city_record`.
- **Verification:**
  - 58 tests pass; Old City is byte-identical.
  - Rebuilding all nine spots changed only this building: the cathedral now has 8 flattened regions (was 6), and the other eight spots are identical.
  - The cathedral was redrawn (~$0.13). The previous drawing is kept as `qwen_joint_light8_v2shapes/`.

### Corrections
- **30th Street crop.** The atlas sheet's 30th Street crop was right after all: its center is the AIS geocode for 2955 Market St, and the station is the flat-roofed building in the lower middle. The earlier note ("the crop sits north of the station") was wrong, and so was the plan's "barrel roof".

### Known issues, not geometry (left for a training and QA round)
- Stadium outer walls are drawn with windows.
- The Independence Hall drawing turns a shaded tree area into dirt.
- Construction sites are still not addressed (the baseline Penn's Landing drawing invented a pool).

## 2026-10-22: problem atlas and LiDAR building shapes

**Question:** can the City's 2022 LiDAR give landmarks and stadiums their real shapes before we expand past downtown? (Stephen flagged landmark shapes, stadiums drawn as buildings and invented water or lawn on construction sites.)

### Built
- **Nine atlas areas** (`config/atlas_<spot>.json`, ~500 m boxes, clipped lattice, 10 frames each), each with a `_lidar` twin that adds `"building_shapes": "lidar"`.
- **`scripts/04c_fetch_lidar.py`.** Reads the PASDA tile index and downloads only the LAS tiles within 100 m of the area box: 24 tiles, ~24 GB, for all nine spots. Downloads go to `.part` files and are renamed when complete, so a stopped download restarts cleanly. Each one is recorded in `MANIFEST.json`.
- **`src/pixelphilly/lidar.py`:**
  - chunked LAS gridding to a 0.5 m surface and ground grid in the local frame, with EPSG:6565 assigned because the files carry none
  - footprint base from ground returns in a 3–10 m ring
  - stepped parts: tiers of `max(2 m, 6%)`, 6 m² speck merge, part height = median measured height, parts under 1 m left as open ground, at most 60 parts per building
- **`05_build_scene.py`:** `building_shapes: "lidar"` replaces each footprint inside the LiDAR region with its parts. Grids are cached as `data/processed/<area>_lidar_grid.npz`. Tiled areas stop with an error (not yet supported).
- **`scripts/17_atlas_sheet.py`:** before/after sheet, `output/atlas/compare.html` plus `contact.jpg`, with notes written after reviewing the crops.

### Bugs found and fixed
- **Empty LAS chunks crashed gridding** (`reduceat` on an empty array) when a tile's chunk had no points inside the area. Test first (`test_dsm_from_las_...`), then a guard.
- **LiDAR noise made needle towers.** The first City Hall render had thin spikes up to 272 m on roofs that top out at 60–160 m. The cause: clusters of class-1 returns floating far above roofs that the vendor's noise classes missed, such as ~1,200 points 80–110 m above the Ritz-Carlton residences, all from one flight line (source 18), none flagged withheld or overlap.
  - Tests first: `test_noise_above_the_city_ceiling_is_dropped_and_filled` and `test_ceiling_keeps_real_shapes_below_it`.
  - Fix: cells more than 3 m above the footprint's highest City height (`max(approx_hgt, max_hgt)`) are dropped and refilled from the surrounding roof.
  - Limitation: a building taller than its City record would be clipped.
  - The three spots drawn before the fix were redrawn. Their old drawings are kept in `redraws/qwen_joint_light8_noisy/`.
- **Rebuilt after the fix:** all nine LiDAR scenes. Alignment PASS on all 18 atlas areas. The Old City scene is byte-identical (SHA-256 checked). 52 tests pass.

### Results
- **Biggest gains: stadiums.**
  - The baseline drew the inside of the Linc and Citizens Bank Park as apartment-style window walls. With LiDAR, both are open bowls with tiered seating.
  - Franklin Field's stands now slope in tiers.
  - All three stadiums have L&I footprints (Linc 13514, CBP 17579, Franklin Field 106422), so the planned OSM outline fallback wasn't needed.
- **Landmarks:**
  - City Hall's clock tower rises in steps.
  - The Cathedral dome is a stepped dome.
  - The Art Museum's wings get roof forms.
  - Independence Hall's steeple appears but is thin.
  - 30th Street changed little.
- **City Hall height:** tallest part 150.4 m, against 167 m to the top of William Penn and a 170.1 m City `max_hgt`. The statue is under 6 m² in plan, so the speck filter merges it into the tower. (Fixed in the next entry.)
- **Construction sites: not addressed.** The baseline Penn's Landing drawing invented a swimming pool on the site. The LiDAR drawing shows dirt, but that's sampling luck.
- **Spend:** 21 Modal runs, ~$2.92 (9 baseline, 9 LiDAR, 3 redrawn after the noise fix), about 45 GPU minutes. No Gemini calls.

### Decision for Stephen
Whether to redraw downtown with LiDAR shapes before expanding. That needs LiDAR support in tiled scenes. Downtown needs 54 LAS tiles: 18 are already downloaded, and the other 36 are about 39 GB (estimated from the 1.08 GB average tile so far).

## 2026-10-21: photo toggle in the viewer (downtown v3)

- **The toggle.** Stephen asked for a toggle between the "true" photo map and the illustration.
  - The photo layer is the render the AI drew from: the 2024 aerials draped on 3D footprints, from the same camera. It lines up with the illustration pixel for pixel.
  - A plain top-down satellite map would not line up with the tilted isometric view.
- **`16_build_tiles.py --with-photo`** cuts a second pyramid from `renders/mosaic.png`.
  - Lossy WebP Q82: 67 MB vs. 446 MB for the lossless illustration.
  - Places without city imagery, and clipped lattice corners, show the background.
  - `map.json` lists both layers.
- **Built as v3.** Its illustration tiles are byte-identical to v2's (sampled SHA-256). v1 and v2 are kept.
- **Viewer:**
  - a toggle button with `aria-pressed`
  - the label, credits and credits summary switch with the layer
  - `&layer=photo` in shareable links
  - toggle contrast checked in light and dark themes
  - coordinate conversions now go through the illustration layer, since OpenSeadragon's viewport-wide conversions are ambiguous (and log warnings) with two images loaded
- **Tested in headless Chromium:**
  - toggle on and off
  - link and reload restore the photo layer
  - search still lands on the same pixel at City Hall
  - no viewer warnings

## 2026-10-21: fix for invented content where imagery is missing (downtown v2)

- **Bug** (reported by Stephen): a large cartoon person, a seaplane, a bridge and buildings appeared on the New Jersey side of the river.
- **Cause:** the city's 2024 aerial imagery ends a block or two inland in Camden. Those 350 z19 tiles return HTTP 404 and were filled with flat grey in the ground mosaic. Given a featureless input, the model invented a scene, the same failure as invented water on land.
- **Test first:** `tests/test_nodata.py` failed on the v1 output.
- **Fix** (`src/pixelphilly/nodata.py`, applied in `10_repaint_water.py` after the water repaint):
  - Pixels where the source imagery is missing, plus a 16 px margin, are set to the map background (204, 214, 227).
  - The missing area is computed from the no-coverage tile list (exact), not from grey pixels, which real roofs can also be.
  - 7,962,484 px cleared downtown.
  - Old City, Fishtown and Center City have no missing tiles, and their outputs are byte-identical (SHA-256 checked).
- **Tiles:** rebuilt as **v2** (2,941 tiles, 446 MB). v1 is kept unchanged (versions are immutable). The viewer now defaults to v2.
- **Visible side effect:** the Camden waterfront stops along a straight diagonal where the city's imagery coverage ends.
- 43 tests pass.

## 2026-10-20 (night): downtown prototype, pannable and zoomable

**Scope:** Stephen chose a downtown prototype over the full-city plan: no outside permission needed, about 30 km². Box [-75.2050, 39.9350, -75.1250, 39.9750], roughly 40th St to the Delaware and Washington Ave to Girard Ave.

### Built
- **Frame clipping** (`clip_frames_to_area`): 304 of 546 lattice frames kept. `render_ground_polygon` gives the ground they see.
- **Polygon downloads.** `fetch_area_features` sends the polygon to ArcGIS by POST, and imagery is fetched only for tiles intersecting it.
  - Data: 71,500 buildings, 41,906 trees, 43 PWD and 23 NHD water polygons, 12,151 imagery tiles.
  - 350 tiles have no coverage (HTTP 404, outside the city's imagery). They're now recorded as `.none` markers instead of crashing the download.
- **Per-tile scenes** (`render_tile_frames: 4`): 30 render tiles, each with its own ground mosaic (max 12,544 px) and UV fit, plus buildings and trees within 360 m.
  - Build time 19 min.
  - Small-area scenes are byte-identical to before (SHA-256 checked).
- **`scenes.scene_paths`.** Rendering and the alignment check loop over tile scenes. The 304 frames render in 1 min 42 s.
- **Sampler active-region mode** (`windows.active_grids`, `joint_denoise(active=...)`): only windows touching kept frames run. 2 new CPU tests.
- **`AreaSampler.joint_volume` on Modal.** Frames go through the `pp-runs` Volume, the latent is saved before decoding, and each frame is decoded with a 128 px halo.
  - Tested on Old City first, same seed as the earlier run: mean difference 3 levels (decode path plus GPU nondeterminism), seam ratio 1.08, same as before. ~$0.34.
- **Per-frame water repaint with a 32 px halo** for tiled areas. 3 min. The Old City whole-mosaic path is unchanged (byte-identical).
- **`16_build_tiles.py`:** pyvips `dzsave`, 512 px lossless WebP, versioned and immutable folders, `map.json` with the lon/lat fit.
- **Viewer** (`viewer/`): OpenSeadragon 6.1.1 (vendored), crisp pixels at ≥1:1, hash deep links, AIS address search, a persistent AI label, collapsible credits, keyboard and reduced-motion support.
- **`viewer_geo.fit_lonlat_to_px`:** a cubic lon/lat→px fit, max error 2e-7 px. `tests/test_viewer.py` checks the JS port in headless Chromium.

### Bugs found and fixed along the way
- **`05_build_scene.py` silently downsampled oversize ground textures.** It now raises. Tests first: `tests/test_scene.py`.
- **Camera far plane.** The 3 km default camera cut off downtown's far edge (frames 13_00 and 14_00, IoU 0.07 and 0.03). `camera_distance_m` (20 km for downtown) plus `05_build_scene.py --camera-only` to refresh scenes without rebuilding.
- **The alignment check filled in courtyards** (holes) and could erase overlapping buildings when drawing holes. It now uses real outlines with holes and inner walls, and draws holed polygons on separate layers.
  - Downtown min IoU 0.9755, mean 0.9918.
  - Shifts on sparse frames only fail when IoU < 0.99 too (frame_23_09: IoU 0.995 with a tied shift search).
- **Modal can't subclass a decorated class.** `AreaSampler` and `Editor` now share a plain `_QwenBase`.
- **Deprecated `shapely.ops.transform`** replaced.

### Results
- **Generation:** 54.3 min on one H100, ~$3.58. 1,215 windows, 4,860 forwards, peak 67.9 GB.
- **Seams** (neighbor-relative ratio per 1,024 px border segment, flat segments skipped):

| Borders | Render (median / 95th pct) | Joint + water (median / 95th pct) |
|---|---|---|
| Frame borders (412) | 1.00 / 1.20 | 1.015 / 1.49 |
| Render-tile borders (139) | 1.01 / 1.20 | 1.04 / 1.56 |

  The highest-scoring segments, inspected visually, are repainted open water (a near-zero denominator) or building edges on the line, with no visible joins.
- **Tiles:** 2,941 tiles, 439 MB, 16 levels, built in 1 min.
- **Viewer smoke test:** no errors. "1400 John F Kennedy Blvd" lands at City Hall; "3451 Walnut St" at Penn. Works at 320 px.

### Known limits
- City Hall's tower and other spires are stubs: one height per footprint (`approx_hgt`).
- The map edge is stair-stepped at frame granularity (no cloud band yet).
- No Gemini benchmark for downtown.
- Invented-water check not yet run on downtown.

## 2026-10-20 (evening): third neighborhood, Center City

- **Config:** `config/centercity.json`, a same-size box from City Hall to Rittenhouse Square, with Logan Circle, the Convention Center and both Comcast towers. `max_height_m` was raised to 360 for the 342 m Comcast Technology Center.
- **Data:** 14,377 buildings (17 at the default height), 13,533 trees, tallest 297 m on `approx_hgt` (roof, not spire), 118 height outliers (spires and setbacks). The lattice view reaches the Schuylkill. Alignment PASS: min IoU 0.993, every frame at (0, 0).
- **Joint generation:** Old City LoRA, Lightning 8-step, no new training. 5.1 min, ~$0.34. 30/30 frames within 2 px.
  - Seam ratio, joint + water: global 0.997 and local 0.988, against the render's 0.942 and 0.966.
- **Visual check:** the towers, untextured gray boxes in the render, came out with regular window grids, setbacks and the aerial's roof detail, including Liberty Place's crown. The LoRA had seen almost no towers in training.

## 2026-10-20 (evening): second neighborhood, Fishtown

**Question:** does the style LoRA, trained only on Old City, carry over to a neighborhood it has never seen, with no new training?

### Changes
- `load_config()` reads `PP_AREA` (default `oldcity`).
- `area_dir(cfg, ...)` puts each area's outputs under `output/<area>/`.
- Old City outputs were moved to `output/oldcity/` (git-ignored, so nothing changes in git).
- Scripts 12–14 are pinned to Old City.
- The imagery manifest key is now per area: `imagery/<area>/<service>/<z>`.
- `15_joint_sample.py --full --detach / --collect` runs long jobs detached on Modal.
- `sources.fetch_features` retries ArcGIS "HTTP 200 with an error body" failures. Fishtown's first footprint query hit one.
- New tests (`tests/test_area.py`): area selection, per-area paths, Fishtown lattice. 32 pass.

### Regression check
- Rebuilt Old City scene: no git diff.
- Old City water-repaint mosaics (Gemini v3 and joint) and the render mosaic: byte-identical SHA-256 before and after the migration.

### Fishtown
- **Box:** same size as Old City, inside the FISHTOWN polygon: Frankford Ave to the Delaware, around Girard Ave, including Penn Treaty Park.
- **Data:** 16,909 buildings (120 at the 10 m default height), 6,636 trees, tallest 102 m. Alignment check PASS (min IoU 0.981).
- **Street grid:** dominant bearing ~55°, following the river, with a secondary grid at ~9°. At the 54° camera the river-aligned blocks face the camera head-on, so they read more top-down than Old City's diamond blocks. The camera was kept at the angle the LoRA learned.
- **Joint generation:** Old City LoRA, Lightning 8-step, no new training. 5.0 min, ~$0.33. 28/30 frames within 2 px of the render; the other two are open-river frames where the alignment measure has nothing to lock onto.

| Fishtown mosaic (frame borders) | Global | Local |
|---|---|---|
| Render | 1.04 | 0.99 |
| Joint | 1.06 | 1.07 |
| Joint + water repaint | 1.07 | 1.07 |

- **Against Gemini v3 on 4 frames** (benchmark only, ~$0.54):
  - The joint model is more faithful on rowhouses: it keeps the real roof colors, where Gemini made everything salmon-tan.
  - It is cleaner on the Penn Treaty / power-station frame.
  - It adds blue-gray puddles in the I-95 interchange infield.
- **Invented water on land:**
  - A blue pond on a vacant dirt lot in the southwest blocks.
  - A check for blue, water-like pixels outside USGS water and outside buildings finds 5 blobs in Fishtown (largest 10,432 px, the pond) and 6 small ones in Old City. Each total is ~0.06% of the canvas. The Old City blobs have not been checked one by one.
  - Next step: turn the check into a flag list, and repair flagged spots by locally re-denoising them (tiny.london's repair step).

## 2026-10-20 (afternoon): phase 2, seam-free Old City with a commercially usable model

### Decisions
- **Base model: Qwen-Image-Edit-2511** (Apache 2.0) with lightx2v's Lightning LoRAs (Apache 2.0), pinned to exact commits.
  - tiny.london's base, Qwen-Image-2.1-Turbo, is under the Qwen Research License, "FOR NON-COMMERCIAL PURPOSES ONLY" (checked on Hugging Face).
- **Training targets: Gemini 3 Pro Image v3 redraws, for internal use only** (Stephen, Oct. 20).
  - The Gemini API terms bar using the service "to develop models that compete with the Services" and "replicat[ing] any component". A Philadelphia-only style LoRA arguably doesn't compete, but the terms don't define either word.
  - Legal review is required before any publication. Every target's source is recorded in `output/trainset/manifest.jsonl`.
- **GPU: Modal**, per-second billing.

### Built
- `src/pixelphilly/windows.py` and `joint_sampler.py`: MultiDiffusion-style joint denoising, tested on CPU with toy predictors.
  - Independent tiles: seam ratio 7.4. Joint: 1.004, against 1.006 for the clean image.
- `src/pixelphilly/waterpaint.py`: the water repaint, usable on any view and zoom. Moved out of `10_repaint_water.py`; the mosaic output is byte-identical to before.
- `src/pixelphilly/gemini.py`, `browser_render.py`: shared Gemini call and renderer, so arbitrary views can be rendered. The re-rendered frame is identical to before.
- `gpu/modal_app.py`:
  - inference image
  - `check_env` CPU smoke test
  - `Editor.run` for per-image edits
  - `Editor.joint` for whole-canvas joint denoising
- `gpu/train_app.py`: ai-toolkit pinned to commit 04733873, with a `check_config` CPU smoke test.
- Scripts:
  - `12_qwen_baseline.py`: Phase A
  - `13_build_trainset.py`: Phase B
  - `14_train_lora.py`: Phase C
  - `15_joint_sample.py`: Phase D
- `qa.seam_ratio_lines` and `seam_ratio_local`: seam scores at arbitrary lines, the second against neighboring lines. 28 tests pass.

### Results
- **Phase A, prompt-only Qwen, 48 edits on 6 frames** (16 min, ~$1.06).
  - Clean pixel art, mostly on-geometry.
  - It invents things: a river on the Mint's roof when the prompt said "WATER IN THIS VIEW: none", lawns in place of pavement, and buildings on the river.
  - Lightning 8-step with the short prompt was best: aligned on 6/6 frames, ~4.5 s per image.
  - Lesson: never name water in a Qwen prompt. Training captions use one fixed sentence.
- **Phase B, training set.** 141 pairs, all from lattice columns 0–3; columns 4–5 are held out.
  - Pairs: 20 lattice frames, 47 shifted views, 74 zoomed quarters.
  - Water repainted in every target; 0 QA rejections.
  - 121 new Gemini images, ~$16.21. Google's spend-based rate limit for new accounts paused the run twice; it resumed with 1 worker.
- **Phase C, LoRA.** Rank 16, 2,000 steps, bf16, H100. About 98 min, ~$6.45.
  - Held-out samples improved steadily; step 2,000 was closest to the Gemini benchmark.
  - Water in samples is a uniform dark blue (repainted afterward).
  - It still invents a landscaped lot on the riverfront pier.
- **Phase D, joint sampler.**
  - Held-out 1,792 px crop, untrained model: Lightning-8 joint 1.22 vs independent tiles 1.61; base-40 joint 1.11 vs 1.29 (render 1.01).
  - With the LoRA, independent tiles were already consistent (0.90–0.98). Joint's 1.16–1.18 came from a building edge on one window line: the neighbor-relative check shows that line is also high in the render and in the independent version.
  - VAE tiled vs. untiled decode changed the seam score by only ~0.01.
- **Full Old City, LoRA + Lightning 8-step, one joint pass.** 5.4 min, ~$0.36. 115 windows, 476 forward passes, 61 GB peak.

| Mosaic (frame borders) | Seam ratio, global | Seam ratio, local |
|---|---|---|
| Render | 1.08 | 0.99 |
| Gemini per-frame | 4.39 | 4.13 |
| Gemini per-frame + water repaint | 3.69 | 3.73 |
| **Qwen + LoRA, joint** | **1.08** | **1.10** |
| **Qwen + LoRA, joint + water repaint** | **1.09** | **1.09** |

### Problems hit and fixed
- **Missing `torchvision` in the inference image.** Qwen2.5-VL's video processor needs it. The load step crash-looped on an H100 until stopped.
  - Fix: `torchvision==0.29.1`, plus a CPU `check_env` smoke test that runs before every GPU job.
- **ai-toolkit couldn't resolve "Qwen/Qwen-Image-Edit-2511" offline.** The pinned download stores only the commit snapshot, not the "main" ref.
  - Fix: the config points at the snapshot folder. `check_config` verifies it on CPU first.
- **Training-set resume treated errored views as done.** Fixed to skip only passing views or views rejected twice.
- **The base-40 full-canvas run was cancelled after ~4 min (~$0.30).** The local background command that held the Modal call open was stopped by this environment's ~10 min limit.
  - Long runs should be spawned and detached, as training is.

### Phase 2 spend (estimates; the Modal dashboard is the authority)
- Gemini: ~$16.21
- Modal:
  - Phase A: ~$1.06
  - seam tests: ~$1.2
  - training: ~$6.45
  - full canvas: ~$0.36
  - cancelled run: ~$0.30
  - CPU and image builds: small
  - the torchvision crash loop: unknown; see the dashboard

### Results so far
- 8,380 buildings in the scene, none dropped.
  - Heights: 8,304 from `approx_hgt`, 29 from `max_hgt`, 47 from the default.
  - 50 flagged as outliers.
- 7,047 trees.
- 30 frames (6 × 5).
- Alignment: all 27 frames that contain buildings match the Python projection with zero pixel offset; minimum IoU 0.991.
- 11 unit tests pass.
