# Plan: era-aware buildings, pilot for v19

## Context

Stephen asked whether building styles could improve using the year each building was built. The investigation (`docs/building_age_styles.md`) found the following:

- **Year built is weak.** OPA's `year_built` covers 98% of footprints, but 75% of the years are estimates heaped on round numbers.
- **The style code is the better era signal.** OPA's style code (`ROW OLD STYLE`, `ROW POST WAR`, `CAPE`, `RANCH`, `ROW MODERN`) carries era better, but `facades.py` collapses it into 13 styles.
- **The LiDAR sees roof forms.** It measures pitched roofs building by building: 64,131 buildings (14.2%) are pitched, including 85–91% of Capes, ranches, split levels and Colonials, while the map draws every roof flat. It also shows a shingled front slope on postwar Northeast rows, but only as a group pattern.

Stephen wants the change with the greatest visible impact. This plan builds four changes behind config flags and tests them on four small test spots before any citywide work:

1. **Era classification**
2. **Era walls**
3. **Front slopes on postwar rows**
4. **LiDAR-fitted gables and hips**

The outcome is evidence for or against a v19 rebuild. The frozen versions v14, v17 and v18 and the 12 region areas are not touched. `viewer/` is not touched either, because another session is working there.

**Not parallelizable:** all four steps edit the same files (`facades.py`, `05_build_scene.py`, `render/render.js`, `qa.py`), so they run in order in this session.

## Ground rules for every phase

- **Off by default.** Each feature has its own config flag, and the JSON scene gets new fields only when a flag is on. Scenes without the flags must render byte-identically.
- **Tests first.** Write the failing tests first, then the code (CLAUDE.md workflow), and run the full `uv run pytest` before each render.
- **Permanent byte-identical check.** Replace the compare-against-`git HEAD` check in `tests/test_render_facades.py` with a stored golden checksum of the plain test scene's color and mask renders. The current check stops proving anything once the change is committed.
- **Code comments say why:** data source, thresholds, and how each threshold was chosen.
- **Docs:** results go into `docs/building_age_styles.md`, `CHANGELOG.md` and `data/README.md` (new fetches). `README.md` changes only if a flag ships.
- **No commits** unless Stephen asks.

## Phase 0: test spots and baselines (about half a day; GPU about $0.60, estimate)

Renders aren't versioned by run name, so re-rendering an existing spot would overwrite the renders its old drawings came from. Each pilot spot therefore gets two new configs with identical bbox and camera:

- **`atlas_<spot>_eb`**, the baseline: current settings, all new flags off.
- **`atlas_<spot>_ea`**, the era version: the new flags turned on phase by phase.

The four spots:

| Spot | bbox | Why |
|---|---|---|
| `indhall` | copy `config/atlas_indhall_fac.json` | Widest era mix; Society Hill gables |
| `northeast` | copy `config/atlas_northeast_fac.json` | Postwar twins and singles; 37% pitched |
| `passyunk` | copy `config/atlas_passyunk_fac.json` | Control: one era, flat rows |
| `mayfair` | new, about 500 m square (0.00586° × 0.0045°) | Front slopes; Mayfair `ROW POST WAR` showed the strongest front dip (52%) |

- **Mayfair bbox:** chosen inside the Mayfair neighborhood polygon as the 500 m square with the most `ROW POST WAR` footprints (computed from `output/building_age/roof_forms_lower_northeast.csv`). Add `lawn_correct` as in the Northeast spot.
- **Fetch:** the recipe in `docs/history.md:504-509` (`01`–`04k` with `PP_AREA`). The fetches append to `data/raw/MANIFEST.json` with today's date. Existing raw files are unchanged.
- **Build and check:** `05_build_scene.py`, `06_render.py`, `06_render.py --mode mask`, `09_check_alignment.py`, `18_qa_scan.py`.
- **Draw the baselines:** `15_joint_sample.py --full --volume --detach --name qwen_joint_light8_eb` with the map's settings (Lightning 8, `qe2511_oldcity_r16_v1`, seed 0, the standard prompt), then `--collect` and `10_repaint_water.py`. Four drawings at about $0.14 each, per `output/gpu_runs.jsonl` history.
- **Continuity check:** the three existing spots' `_eb` drawings should look like their Oct. 28 `qwen_joint_light8` drawings. A difference would mean data drift since Oct. 25 or a code change, and must be explained before going on.

## Phase A: era classification and era walls (options 1a–1c; about 3–4 days)

Flag: `"facade_eras": true`.

**`src/pixelphilly/facades.py`**
- **`era_of(rec) -> str`:** OPA style code first, year second. Keys: `georgian_federal` (before 1840), `mid19` (1840–1879), `late_victorian` (1880–1904), `streetcar` (1905–1929), `interwar` (1930–1944), `postwar` (1945–1974), `late20` (1975–1999), `new` (2000 on), `unknown`.
  - Code overrides: `ROW POST WAR`, `TWIN POST WAR`, `TWIN RANCH`, `RANCH`, `CAPE`, `SPLIT LEVEL` → `postwar`; `ROW MODERN` → `new`; `ROW OLD STYLE` uses its year but never later than `late_victorian`.
  - The estimate flag doesn't change the era, because heaped years still mark the neighborhood's era. It is recorded in QA stats.
- **Split styles:** append `row_old`, `twin_old`, `twin_postwar`, `detached_postwar` to the end of `STYLES`, so existing style ids don't change.
  - Only `style_of(..., eras=True)` returns the new styles.
  - New styles get `SPACING_M` entries and are added to `ROW_STYLES` as appropriate.
- **`ERA_PALETTES`:** only colors named in the report's sources.
  - `georgian_federal`: darker mottled red.
  - `mid19`: red, plus brownstone where OSM or the material says so.
  - `late_victorian`: adds yellow-tan and purplish-brown.
  - `streetcar` and `interwar`: add orange, "Pompeiian" and buff.
  - `new`: gray, white and charcoal panel.
  - `postwar`: keeps current `PALETTES["brick"]`, because no source names postwar colors.
  - OSM color and the tall-building aerial rule keep precedence.
- **New band bits:** `BAND_PENT = 16` (pent eave shelf between floors 1 and 2, for `georgian_federal` rows) and `BAND_HEAVY_CORNICE = 32` (for `mid19` and `late_victorian` rows).
  - No cornice on `row_postwar`, `row_modern`, `twin_postwar` or `detached_postwar` when eras are on.
- **`facade_spec(..., eras=False)` and `compact()`:** unchanged output when `eras=False`. When on, add the bits and a debug era code `e`, which the renderer ignores.

**`scripts/05_build_scene.py`**
- `attach_facades` (lines 840–910) passes `eras=cfg.get("facade_eras", False)`.
- `part_facade` (970–986) forwards the flag.
- QA gets `facade_eras` (counts by era, by era × style, and estimated-year share).

**`render/render.js`**
- In the shader `facadeColor` (lines 269–305): bit 16 draws a 1-pixel-scale dark shelf with a light line under it at the top of floor 1, on street-facing walls only. Bit 32 draws a cornice about twice as deep and darker than bit 4.
- No change when the bits are absent.

**Tests**
- `tests/test_facades.py`:
  - `era_of` cases: code beats year; estimated years; `ROW OLD STYLE` 1925 → `late_victorian`.
  - `facade_spec(eras=False)` equals today's output on a fixture of about 50 real OPA records copied from `data/raw/atlas_*_fac_opa.geojson`, columns limited to `OPA_COLUMNS`.
  - The new styles leave existing style ids unchanged.
- `tests/test_render_facades.py`:
  - Bits 16 and 32 change only wall pixels.
  - Mask unchanged.
  - Plain scene matches the golden checksum.

**Render and draw:** render the four `_ea` spots and draw run `qwen_joint_light8_eraA` (about $0.60).

## Phase B: front slopes on postwar rows (option 1d; about 1 week)

Flag: `"front_slopes": ["ROW POST WAR", "TWIN POST WAR"]`, a list of OPA codes. Interwar codes can be added later if the review supports it.

- **Geometry (new `src/pixelphilly/roofs.py`):** `front_slope_facets(footprint, h, front_dir, seed)` returns triangles in local `[e, n, z]`.
  - A sloped strip along the street-facing top edge, as wide as that edge.
  - Outer edge 0.15 m beyond the wall at `h − 0.8` m; inner edge 0.6 m inside at `h + 0.05`. That matches the LiDAR profiles: about 0.5 m deep and about 0.5 m lower at the front.
  - A light cap 0.25 m wide at each end where the edge meets a neighbor (party-wall cap).
  - Shingle color is a gray-brown palette, jittered per building.
- **Which buildings:**
  - The OPA code is in the list and `facades.front_dirs` finds a street side.
  - The roof wasn't fitted as pitched in Phase C.
  - The footprint is under 20 m tall.
- **Scene:** a top-level `roof_facets: [{"t": [[e,n,z]×3, …], "c": [r,g,b]}]`, written only when present. 05 calls this after `lidar_shaped` and records QA (count, share of eligible).
- **`render/render.js`:** build one merged mesh from `roof_facets`, lit like walls, added only when present (same pattern as `tubes`, lines 326–351). Mask mode draws it white automatically.
- **`src/pixelphilly/qa.py` `silhouettes()` (lines 35–63):** union in each projected facet triangle (`cam.world_to_screen` with z), so `09_check_alignment.py` agrees with the render.
- **Tests:**
  - Facet geometry: depth, heights, which edge is used.
  - A render test where a synthetic row with a facet has mask IoU ≥ 0.99 against the Python silhouette.
  - Plain scene matches the golden checksum.
- **Render and draw:** run `qwen_joint_light8_eraB` (about $0.60).

## Phase C: gables and hips fitted from the LiDAR (option 2a; 2–4 weeks)

Flag: `"roof_fit": "lidar"`. It needs `"building_shapes": "lidar"`.

**Classify, in `src/pixelphilly/lidar.py`**
- Move the plane-fit pitch test from `scripts/45_roof_forms.py` (`plane_fit` and the classification in `measure`) into a library function `roof_pitch(fp, dsm, ground, origin, res)`, so the script and the scene use one implementation.
- 45 then imports it, and its summary numbers must not change. That is a regression test.

**Fit `roof_model(fp, dsm, origin, res)`, for pitched roofs on simple footprints only**
- Eligible footprints: area / minimum-rotated-rectangle area ≥ 0.85, LiDAR gives one or two parts, and under 25 m tall.
- Try a gable along each rectangle axis and a hip. The surface is z = eave + tan(pitch) × (distance from the nearest eave edge), capped at the ridge. Eave height, pitch and ridge come from robust LiDAR percentiles.
- Keep the best model only if its rms residual is under 0.35 m and it beats a flat fit by a clear margin. Otherwise keep today's tiers.
  - This rejects most tree-covered roofs, because trees don't fit planes.
  - The 0.35 m threshold is checked on the sample sheets from the investigation.

**Geometry**
- Split the footprint polygon along the ridge and hip lines (`shapely.ops.split`) and triangulate each planar piece (`shapely.constrained_delaunay_triangles`, available in the repo's Shapely 2.2.0).
- Set each vertex's z from the model, and insert ridge vertices into the outline, so gable-end walls rise to the ridge.
- Scene: the building gets `roof3d: {"ring_z": [...], "t": [[i,j,k], …], "v": [[e,n,z], …]}` in place of a flat top. Written only when the flag is on.

**`render/render.js`**
- For a building with `roof3d`, build its walls manually from the ring and `ring_z`, as quads or triangles with the same facade attributes. `facadeTop` becomes the per-vertex eave z.
- Put the roof triangles in `roofParts`. `setUVsFromPosition` (lines 59–68) already drapes the aerial correctly on sloped triangles.
- Front slopes and the cornice band are skipped on these buildings.

**`qa.py` `silhouettes()`:** per-vertex top z for wall quads plus projected roof triangles, from the same `roof3d` data. Python and JS read the same explicit triangles, so they can't drift apart.

**Tests**
- `roof_model` on synthetic DSMs: a gable, a hip, a flat roof, and noise like a tree. It must pick the right model or refuse.
- A synthetic gable building renders a mask with IoU ≥ 0.99 against the Python silhouette.
- Plain scene matches the golden checksum.
- `45_roof_forms.py` atlas summary unchanged after the refactor.

**QA stats:** fitted, refused (by reason), gable versus hip, residuals.

**Render and draw:** run `qwen_joint_light8_eraC` (about $0.60).

## Phase D: comparison and review (about 2–3 days plus Stephen's review time)

**New `scripts/47_era_compare.py`**
- Generalizes `scripts/24_style_compare.py`, which has hard-coded spots and runs and overwrites `output/style/`. The new script takes spots and runs as arguments and writes `output/era_pilot/`. It reuses 24's metric helpers, imported rather than copied:
  - `border_seam`
  - `qa.flat_share`
  - `trainset_clean.invented_color_share`
  - `qa.registration_shift`
  - invented-water counts
- New cue-retention metrics:
  - Per era class, the mean wall-color difference between render and drawing on street-facing wall pixels. Wall pixels come from the render mask minus a roof mask rendered with walls hidden.
  - For Phases B and C, whether the roof-edge strip and the gable shading survive in the drawing.

**Blind review page** (local HTML in `output/era_pilot/review/`)
- About 20 buildings per spot, stratified by era and roof class.
- Each shows a crop of the 2024 aerial plus the baseline and era drawings in random order, labeled only A and B.
- Stephen scores each pair: better, same or worse. Scores are saved in the browser's local storage and exported as JSON to `output/era_pilot/review.json`.
- Crops show buildings, never addresses.

## Verification and acceptance

**Automated, every phase**
- `uv run pytest` passes, including the golden byte-identical checks.
- `09_check_alignment.py` passes on all eight spot configs.
- `18_qa_scan.py` shows no new needles.

**Data checks**
- Phase A QA era counts match `44_year_built_audit.py` for the same footprints.
- Phase C fitted-roof shares are within a few points of the `45_roof_forms.py` pitched shares for each spot.

**Drawing checks** (from `47_era_compare.py`)
- Seam ratio and invented color are no worse than the `_eb` baselines.
- The Passyunk control changes only at `ROW MODERN` infill and pre-1880 houses.

**Acceptance for a citywide v19 proposal**
- The era drawings win the blind review in Independence Hall, the Northeast and Mayfair.
- Cue retention shows the redraw keeps the new walls, slopes and gables, not snapping them back to Old City reds and flat tops.
- No automated check regresses.

If accepted, a separate plan would cover the v19 region rebuild (about $130 of GPU time, estimate), freezing, and hosting. If walls fail retention but roofs pass, ship roofs only. If everything fails retention, the redraw model is the bottleneck, and the next question is the style LoRA (option 2c).

**Costs and time (estimates):** GPU about $2.50 (16 drawings at about $0.14 each, plus container startup). LiDAR for Mayfair is 1–4 tiles of 0.5–1.7 GB each. Engineering is roughly 4–6 weeks across the phases, most of it Phase C.

## Critical files

- `src/pixelphilly/facades.py`
- `src/pixelphilly/lidar.py`
- new `src/pixelphilly/roofs.py`
- `src/pixelphilly/qa.py`
- `scripts/05_build_scene.py`
- `render/render.js`
- `scripts/45_roof_forms.py` (refactor)
- new `scripts/47_era_compare.py`
- new `config/atlas_{indhall,northeast,passyunk,mayfair}_{eb,ea}.json`
- `tests/test_facades.py`, `tests/test_render_facades.py`, new `tests/test_roofs.py`
- docs: `docs/building_age_styles.md`, `CHANGELOG.md`, `data/README.md`
