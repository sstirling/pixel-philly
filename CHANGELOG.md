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
