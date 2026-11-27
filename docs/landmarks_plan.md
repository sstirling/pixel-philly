# Plan: hand-modeled landmarks and bridges for v19

## Context

Crossing Broad's Nov. 13 walkthrough of the map (https://www.crossingbroad.com/news/trending/the-inquirers-data-editor-made-a-hyper-detailed-pixel-version-of-philly-you-can-scroll-through/) named these problems:
- City Hall is a "tiny Empire State Building," with no Penn statue and no yellow clock.
- One Liberty Place has no spire.
- Lincoln Financial Field's outside is covered in windows, and its field is marked for soccer.
- The Art Museum looks like a mall.
- Boathouse Row looks like small brick schools.
- The Tacony-Palmyra lift span looks broken.
- Saint Joseph's Barbelin Hall looks like a regular building.
- The arena is plain.

The v18 crops show the same three causes everywhere:
1. **Box shapes.** The LiDAR extrudes into flat-topped stepped boxes, so mansards, colonnades and grandstands read as stacked office blocks.
2. **Windows everywhere.** The facade shader paints a window grid on every OPA-matched footprint (`render.js:369`), stadium terraces included. Where it doesn't, the model invents windows on tall blank walls.
3. **Missing parts.** Tower stages, clock faces, statues, spires, canopies, light towers, columns and lift spans aren't in the render, and the drawing model can't add geometry that isn't there (experiment A, Oct. 25).

Feeding photos to the drawing model was tested and failed: on Oct. 26 it damaged 7 landmarks and fixed 1. What worked was the v18 bridge method: model the structure in 3D with every dimension sourced or labeled as an estimate, and use photos only as references for the modeling.

Stephen chose about 50 well-known structures plus all the bridges named in this session, done before the other visual improvements (era work, the 0.2 m/px rebuild). v14, v17 and v18 stay frozen. `viewer/` isn't touched.

## What exists to reuse

- **`src/pixelphilly/bridges.py`.** It has the patterns this plan needs:
  - sourced-dims config with a test that enforces sources (`tests/test_bridges.py:592`);
  - LiDAR profile helpers (`lidar_profile`, `npz_window`);
  - removing the parts a model replaces (`drop_deck_parts`, `config/structure_exclusions.json`, `config/part_caps.json`);
  - structures added after `attach_facades` with `fixed_color` and no `facade` key, so they get no windows;
  - repaint protection (`structure_zones`, `structure_protect`).
- **Scene primitives.**
  - Prisms with `z0`, `roof_rgb` and `fixed_color`.
  - `roof3d`, a 2.5D cap.
  - `tubes`.
  - `roof_facets`, arbitrary colored triangles, already projected by `09_check_alignment.py` and filtered per tile by `facets_in_reach`.
- **`data/landmarks/manifest.json`.** 40 landmarks with checked coordinates, AIS cross-checks and license-filtered reference photos: Library of Congress HABS/HAER, or Commons CC0, public domain or CC BY. `src/pixelphilly/landmarks.py` has `canvas_point`, `frame_at` and `landmark_windows`.
- **Crop tooling.**
  - `32_stage_crops.box_for(area, lon, lat, half_m)`.
  - `31_vessel_crops.MapSource` and `AreaSource`.
  - `33_bridge_crops.py`, including `--inventory`, which lists 105 water crossings.
  - `scripts/48_scale_test.py`, for same-ground comparisons.
- **Atlas-spot workflow.** Fetch, `05`, `06`, `09`, `18`; the user runs `15_joint_sample.py`; then `--collect` and `10_repaint_water.py`. The 0.2 m/px configs from the scale test can serve as templates.

## Phase 0: the list and the sources (about 2–3 days; no GPU)

1. **Final list of about 50 structures** in a new `config/landmarks/index.json`. Each entry has a slug, name, Wikidata ID, lon/lat, owning region (frame lattice, not just bbox: Tacony-Palmyra and Girard Point straddle regions), kit type (below), the criticism it answers (if any) and its status.
   - **Manifest landmarks (40).** They keep their manifest status. The 10 marked `excluded` were excluded for lack of a usable photo, not as landmarks.
   - **Article additions.** Barbelin Hall (Saint Joseph's) and Hagan Arena for context. One Liberty Place is the manifest's `liberty_place`.
   - **Bridges, every one Stephen named.**
     - Delaware: Betsy Ross, Tacony-Palmyra (bascule and arch).
     - Schuylkill: Girard Point, Platt, plus the Schuylkill crossings, selected from the `33_bridge_crops.py` inventory as named road and rail crossings. The candidates are Falls, Strawberry Mansion, Girard Ave, Spring Garden, Market, Chestnut, Walnut, South, University Ave, Grays Ferry, Passyunk Ave, Columbia and the Connecting Railroad bridges.
     - The Ben Franklin and Walt Whitman are done.
   - **Review step.** A contact sheet with a v18 crop, a photo-layer crop and a reference photo for each entry goes to Stephen to confirm or trim the list before modeling starts.
2. **Measured drawings.** `scripts/19_landmark_refs.py` currently drops HABS/HAER measured drawings on purpose (`loc_candidates`, :192). Add a `--drawings` mode that records drawing sheets: public domain, with sheet title, scale and URL. They are the best dimension source for City Hall, Independence Hall, 30th Street and others. Also fix the stale `mapped_areas()`, which only reads `*_lidar.json`.
3. **More OSM fields.** `scripts/04g_fetch_osm.py` fetches only buildings with a colour or material tag. Add a landmark-box fetch of all `building:part` within each landmark's box, with `height`, `min_height`, `roof:shape` and `roof:colour`. These are ODbL, credited like the bridge towers.
4. **One dossier per structure,** `config/landmarks/<slug>.json`. It holds every dimension as `{value, unit, source}` or `{value, estimate: true, reason}`, the same schema the bridges use, enforced by a test. Colors are measured from the 2024 aerial roof (City; aerial use is cleared) or read from reference photos, with the photo cited.

## Phase 1: the framework (about 1 week; tests first; no GPU)

**New `src/pixelphilly/landmarks3d.py`, behind the region or atlas flag `"landmarks3d": [slugs]`.** Off by default; scenes without it stay byte-identical (the stored render checksums in `tests/test_render_facades.py` cover this).
- **`replace(cfg, buildings, slug)`.** Removes the footprints and LiDAR parts the model replaces. The polygon is listed in the dossier and checked against L&I footprint IDs, and removed parts are counted in QA. This generalizes `drop_deck_parts`.
- **Parts emitted after `attach_facades`,** like the bridges, so they get no windows unless the dossier asks for them:
  - prisms (`z0`, `h`, `fixed_color`, `roof_rgb`), reusing `bridges.add_box` / `add_tube` semantics;
  - meshes: colored triangle groups for pitched roofs, mansards, domes, pediments, canopies, bowls and spires. These go through the existing `roof_facets` render and alignment path, renamed in a general way (a `facets` key, with `roof_facets` read for old scenes) so it isn't front-slope-specific;
  - tubes for spires, antennas, cables, truss members and light towers.
- **Kit generators,** each a function from dossier values plus a LiDAR window to parts, so about 50 structures don't mean 50 bespoke scripts:
  - `tower_stages` (stacked prisms, chamfers, a spire or antenna; City Hall, One Liberty, PSFS);
  - `mansard` and `hip` blocks (City Hall's main block, Second Empire buildings);
  - `colonnade_portico` (columns as thin prisms, entablature, pediment; Art Museum, 30th Street, Second Bank, Merchants' Exchange, Girard College);
  - `stadium_bowl` (seating rakes from the LiDAR profile, colored seat bands, concourse ring, canopy, light towers, scoreboard; the Linc, Citizens Bank Park, the arena);
  - `gabled_row` (Boathouse Row);
  - `church` (nave, steeple, spire; Christ Church, Gloria Dei, Barbelin Hall);
  - bridge kits: `girder`, `truss`, `arch`, `bascule` (Tacony-Palmyra) and `stone_arch` (the Schuylkill rail bridges), built on the existing deck, pier and approach code in `bridges.py`.
- **Detail paint** for features too small for geometry at 0.2 m/px (about a 1 m minimum): clock faces, stone coursing lines, window rows only where the dossier says so. These are colored facet quads on the wall plane, offset 2 cm.
- **Field markings** as a ground decal painted into the ground texture inside the field polygon. Football lines for the Linc come from the NFL rulebook's field dimensions, cited. The baseball diamond is already in the aerial.
- **Alignment.** Add `tubes` to `09_check_alignment.py` silhouettes, which aren't projected today. Every landmark must pass 09 at the usual threshold.
- **Repaint protection.** Add landmark meshes and prisms to `structure_zones` for structures over water: bridges, Boathouse Row, the Water Works.
- **Shape check against the LiDAR.** A new `landmark_fit` QA records the rms height difference between the model's top surface and the 2022 LiDAR first returns inside the footprint, per part. It's reported, not a gate, because spires and statues are thinner than the LiDAR grid.
- **Tests.** Schema and sources enforcement, each kit on synthetic inputs, part removal, render-vs-projection masks for meshes and tubes, the decal, protection zones, no-op without the flag.

## Phase 2: pilot on the eight most-criticized (about 2 weeks; GPU about $3, estimate)

The pilot structures are City Hall, One Liberty Place, Lincoln Financial Field, Citizens Bank Park, the arena, the Art Museum, Boathouse Row and Tacony-Palmyra.
- Each gets a 0.2 m/px atlas spot (`config/atlas_lm_<slug>.json`, about 500 m square) and runs through build, 09 and 18, then a drawing run you start (about $0.15 each, estimate).
- **Review sheet per landmark** (new `scripts/51_landmark_review.py`, reusing `48_scale_test.py`'s placer and `32_stage_crops.box_for`): v18 crop, new render, new drawing, reference photo and credit, and `landmark_fit` numbers.
- **Gate.** Stephen reviews the eight. Iterate on kits; a second drawing round is about $1.20 (estimate). Phase 3 doesn't start until the pilot is accepted.

## Phase 3: the rest (about 3–4 weeks; GPU about $8, estimate)

The remaining structures go in batches by kit type: classical buildings, towers, churches and campus buildings, then bridges. Same spot, review sheet and gate per batch. Results are logged in a new `docs/landmarks.md` with method, sources, estimates and review outcomes. The CHANGELOG and `data/README.md` are updated per batch.

## Phase 4: into the regions (part of the v19 plan, not this one)

Turn on `"landmarks3d"` in the owning region configs (mostly `south_lidar`). The final drawing happens in the v19 rebuild at 0.2 m/px, which gets its own plan covering cost (about $280, estimate), freezing and hosting. Until then nothing changes in the regions.

## Verification

- `uv run pytest` passes, excluding `tests/test_inertia.py`.
- Byte-identical render checksums hold for scenes without the flag.
- Every landmark spot passes `09_check_alignment.py`, including tubes, and `18_qa_scan.py`.
- Every dossier value is sourced or an estimate with a reason (test).
- Per-landmark review sheet approved by Stephen.
- Quality measures from `48_scale_test.py` (seam ratio, invented color, registration shift, invented water) are no worse than the same spot drawn without the landmark.
- Credits: CC BY photo authors used as references and OSM (ODbL) are listed in the map credits and `docs/landmarks.md`.

## Critical files

- New: `src/pixelphilly/landmarks3d.py`, `config/landmarks/`, `scripts/51_landmark_review.py`, `tests/test_landmarks3d.py`, `docs/landmarks.md`, `config/atlas_lm_*.json`
- Changed: `scripts/05_build_scene.py` (call after `add_bridge_structures`), `render/render.js` (generalized facets key, ground decal), `scripts/09_check_alignment.py` (tubes, facets key), `src/pixelphilly/bridges.py` (shared deck and pier helpers for new bridge kits; `structure_zones` reads landmark parts), `scripts/19_landmark_refs.py` (`--drawings`, region fix), `scripts/04g_fetch_osm.py` (landmark-box parts fetch), `scripts/10_repaint_water.py` (protection inputs)

## Costs and time (estimates)

- **GPU:** about $11 for test spots across all phases.
- **Engineering:** about 6–8 weeks. The pilot comes first, so the approach can be checked after about 3 weeks.
- **No new paid data.** HABS/HAER drawings are public domain; OSM is ODbL; photos are CC0, public domain or CC BY only.
