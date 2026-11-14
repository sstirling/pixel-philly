# Changelog

## 2026-11-13: promo video and GIF

Stephen asked for a video or GIF that slowly pans across parts of the city to promote the map.

The promo camera paths (`config/flyover/promo*.json`) and the videos (`output/flyover/`) are git-ignored and stay local (Nov. 14). The script features and tests below are tracked.

- **`scripts/29_flyover.py` gained four shot options and two flags.** The preview path renders the same 885 frames as before (tested).
  - `cut`: jump to a new scene with a crossfade.
  - `by`: pan by a fixed number of map pixels.
  - `offset`: aim beside a lon/lat point, such as onto a bridge deck.
  - `caption`: a scene name in the lower left.
  - `--size` renders other shapes from the same path (square, vertical). `--gif WIDTH` also writes a looping GIF with one shared palette.
  - The credit text is now sized from the frame's short side, so it fits a vertical frame.
- **`config/flyover/promo.json`** (v18, 68.5 s). It opens on the Center City towers ("Pixel Philly"). It then pans across seven more scenes joined by 1-second crossfades: the Ben Franklin Bridge, Eastern State Penitentiary, the Art Museum to Boathouse Row, South Philadelphia rowhouses, the sports complex and Manayunk. It ends with a pull-back to the whole city captioned with the site address. Scenes were picked by eye from a contact sheet of the v18 tiles.
- **`config/flyover/promo_loop.json`**: a 7-second pan along the Ben Franklin Bridge at 800 x 450. It fades back to its first frame, so the GIF loops without a jump.
- **Credit line:** "AI-generated illustration. Data: City of Philadelphia, USGS, © OpenStreetMap contributors."
- **Outputs** (in `output/flyover/`, not tracked):
  - `promo.mp4`, 1920 x 1080, 104.6 MB;
  - `promo_1080x1080.mp4`, 64.5 MB;
  - `promo_1080x1920.mp4`, 101.4 MB;
  - `promo_loop.gif`, 14.0 MB.
  - Each video renders in about 18 seconds, with no GPU.
- **Tests:** `tests/test_flyover.py` (10). The full suite passes (488).
- **Shorter cut and a Center City GIF.** Stephen asked for a 10–15 second video and a GIF over Center City.
  - **`config/flyover/promo_short.json`**: 14 s in all.
    - A 4.5-second pan across the Center City towers, captioned "Pixel Philly."
    - A 0.7-second crossfade to a 4-second pan along the Ben Franklin Bridge.
    - A 3.5-second pull-back to the whole city captioned with the site address, then a 1.3-second hold.
    - Output: `output/flyover/promo_short.mp4`, 1920 x 1080, 29.4 MB.
  - **`promo_loop.json` now pans across the Center City towers.**
    - 640 x 360 at scale 3, the social preview's zoom.
    - A 5-second pan, then a 0.8-second fade back to the start.
    - The GIF is 10 fps, 12.1 MB.
    - Any pan changes every pixel in every frame, so GIF size grows fast. At 800 px wide and 15 fps it was 32.5 MB.
- **TikTok/Reels cut with the link on screen.** Stephen asked for a TikTok/Instagram version labeled with the map's link.
  - **`config/flyover/promo_vertical.json`**: the 14-second cut at 1080 x 1920.
    - "pixelphilly.sstirling.com" stays on screen the whole time, near the top.
    - The scene captions sit under it: "Center City," "Ben Franklin Bridge," "All of Philadelphia, as pixel art."
    - The credit line sits at the bottom of the safe box.
    - Output: `output/flyover/promo_vertical.mp4`, 32.9 MB.
  - **Safe box.** The apps cover the frame's edges with buttons and captions, so all text stays inside a box:
    - 270 px from the top, 672 px from the bottom and 65 px from the left. These are Meta's published Reels ad margins (14%, 35%, 6%), as summarized by third-party tools.
    - 150 px from the right, which clears TikTok's button column.
    - Sources disagree, and the numbers are ad guidance, so preview each upload in the app.
  - **New config options in `scripts/29_flyover.py`:**
    - `label`: always-on text that doesn't fade with the scenes.
    - `safe`: the margins in px. With it, text is centered in the safe box, and the caption sits in a fixed slot under the label.
    - Text drawing is now one function, `draw_overlays`.
  - **Tests:** 2 more in `tests/test_flyover.py`, covering that all text stays inside the safe box and that the label and caption don't overlap.
- **Single-sweep promo.** Stephen asked for one sweep from the Art Museum across Center City to Old City, then back out to the full map.
  - **New `via` shot in `scripts/29_flyover.py`.** It is one continuous move through several points, with no stop at each.
    - The path is a Catmull-Rom curve that passes through every point.
    - Frames are spaced by distance along the curve, so the speed is steady.
    - It eases in and out over the first and last 25% of the time (`ramp`), so the top speed is 1.33x the average (smoothstep's is 1.5x).
    - Each point's caption takes over halfway to it.
  - **`config/flyover/promo_sweep_vertical.json`** (TikTok/Reels, 1080 x 1920, 15 s), with the address pinned and the same safe box as `promo_vertical.json`:
    - a 10.5-second sweep at scale 3 (the social preview's zoom), from the Art Museum through City Hall to Old City at the Ben Franklin Bridge;
    - a 3-second pull-back to the whole city, then a 1.5-second hold.
    - Captions in order: "Philadelphia Museum of Art," "Center City," "Old City," "All of Philadelphia, as pixel art."
    - Output: `output/flyover/promo_sweep_vertical.mp4`, 101.3 MB.
  - **`config/flyover/promo_sweep.json`**: the same path at 1920 x 1080, captioned "Pixel Philly" at the start and with the site address at the end. Output: `output/flyover/promo_sweep.mp4`, 99.6 MB.
  - The files are about three times the size of the 14-second cut: a fast sweep changes most of the frame every frame.
  - **Tests:** 3 more:
    - the sweep passes through every point and ends on the last;
    - its speed stays steady through the middle point;
    - captions switch once each, in order.
    - The first version of the speed test set a 1.3x limit, below the ramp's own 1.33x peak. The test was wrong, not the code, and was corrected.
- **Slower sweep; TikTok/Reels and Instagram feed versions.** Stephen asked for a slightly slower sweep and Instagram/TikTok versions.
  - **Slower:** the sweep now takes 13.5 s instead of 10.5 s, about 22% slower. Each video is 18 s.
  - **`config/flyover/promo_tiktok_reels.json`** (1080 x 1920) replaces `promo_sweep_vertical.json`. One file works for both apps.
    - Top margin 290 px, which clears four limits:
      - Meta's 269 px Reels margin;
      - TikTok's 130–240 px;
      - the 285 px Instagram trims from the top when it shows a Reel in the main feed as a centered 4:5 crop (1080 x 1350);
      - with bottom 672 px, left 65 px and right 150 px as before.
    - Checked on frames: all text sits inside both the safe box and the 4:5 crop.
    - Output: `output/flyover/promo_tiktok_reels.mp4`, 117.1 MB.
  - **`config/flyover/promo_instagram_feed.json`**: a 1080 x 1350 (4:5) feed post with the same path and text, and 60 px margins. Output: `output/flyover/promo_instagram_feed.mp4`, 78.5 MB.
  - **`promo_sweep.json` (16:9)** was slowed to match.
  - **Sources:** the margins come from third-party summaries, and they disagree, so preview each upload in the app.
- **Credit line dropped from the sweep promos.** Stephen asked to drop the source line from the promo.
  - `promo_tiktok_reels`, `promo_instagram_feed` and `promo_sweep` no longer have a `credit`.
  - `scripts/29_flyover.py` now treats `credit` as optional.
  - The "AI-generated illustration" label went with that line. The map's own credits and the about page still carry it.
  - Re-rendered: 118.9, 79.3 and 115.9 MB. The other flyover configs keep their credit lines.

## 2026-11-11 (later): repo prepared for public release

Stephen plans to make the repository public. A security review of every file in all 14 commits found no credentials: no API keys, tokens, private keys, Cloudflare account IDs or rclone settings (matches were checked masked). Changes he asked for:
- **Personal project:** removed every reference to Stephen's employer: the City-data User-Agent (`src/pixelphilly/sources.py`), the Wikimedia User-Agent and contact (`scripts/19_landmark_refs.py`) and a hosting note in `docs/history.md`. Both User-Agents now give the repo URL and Stephen's personal email as contact.
- **License:** MIT (`LICENSE`), with the vendored libraries' own license texts added beside them (`viewer/vendor/LICENSE-openseadragon.txt`, BSD 3-Clause; `render/vendor/LICENSE-three.txt`, MIT), both fetched from the projects' repos at the vendored versions. `pyproject.toml` gained the author and license.
- **Raw data out of git:** the 478 raw downloads (1.6 GB) are now one archive, `pixel-philly-data-raw-2026-11-11.tar.xz` (189.6 MB, SHA-256 `92c7284c…742f`), for the GitHub release `data-2026-11-11`. `data/raw/SHA256SUMS` (tracked) lists every file's checksum; `data/raw/MANIFEST.json` stays tracked. New `scripts/00_get_data.py` downloads the archive, checks it and every file, unpacks safely and never overwrites a raw file that differs. Tests: `tests/test_get_data.py` (8). Check: unpacked into an empty folder, all 478 files were byte-identical to `data/raw`. The first archive was refused by the script's own check because macOS `tar` had added hidden `._` metadata files; it was rebuilt with metadata off.
- **History:** the raw data and the old employer references were removed from all past commits with `git filter-repo`, after a full backup bundle (`output/backup/`). See the next steps in the README's "One-time setup" for getting the data.

## 2026-11-11: README rewritten as an overview; build notebook moved to docs/history.md

Stephen asked to clean up the documentation "so that people understand how this was put together." The README had grown as a dated lab notebook still titled "Old City pilot," and its "Reproduce it" section rebuilt only the pilot.
- **New `README.md`:** what the map is and where to see it; how it was made, in 10 plain-language steps; scale and cost; map versions; how to rebuild v18 (one-time setup, the 12 regions in drawing order with their known neighbors and budgets, fix passes, build, freeze and hosting); repository layout; design decisions; known issues; licensing and disclosure.
- **Rebuild steps are reconstructed** from each region's `joint/qwen_joint_light8_fac/call.json`, `region_report.json` and `region_run.log`, the v18 pipeline script and this changelog. Where a command line wasn't saved (the `22_run_region.py` calls, the R2 uploads), the README says so and gives the form. Every flag was checked against each script's `--help`.
- **Gaps now documented rather than hidden:** merging a redraw pass into the base run is a manual copy with no script in the repo; `26_freeze_map.py` writes a generic "talk map" purpose that was hand-edited for v17 and v18; some `qwen_joint_light8_fac_*` folders listed in the v18 manifest contribute no frames (they were checked by hash against the base drawings).
- **Corrected:** stale statements, including the pilot status, the photo toggle (removed Nov. 5), "pending review" for ships and bridges, "v18 once accepted" under hosting, the Oct. 24 seam figure (v18: median 2.45 over 335 join edges, worst 10.32), and "legal review is required" (superseded by the Nov. 2 disclosure decision).
- **`docs/history.md`:** the old README's build sections, unchanged except a short introduction, three "(superseded: ...)" notes and American spellings.
- **Trimmed (Stephen: the README "should be instructive, but it doesn't have to be a blow-for-blow recreation"):** removed who-decided-what and when, the talk reference, region start dates, notes on which command lines weren't saved, and "accepted in v17/v18" tags. That history stays in this changelog and `docs/history.md`.
- **Spelling:** British spellings in prose changed to American AP style in `docs/history.md`, `data/README.md` and this file ("colour," "labelled," "grey"); OSM tag names such as `building:colour` are unchanged. `data/README.md` gained a pointer to the README's overview.

## 2026-11-10: favicon and social preview

Stephen asked for a favicon and a social preview showing the map. Both are crops of the frozen v18 tiles, not new drawings.
- **Script:** `scripts/34_site_images.py` (`--version`, default v18) cuts them with `Pyramid.window` from `scripts/29_flyover.py`. Crops were picked by eye from contact sheets in `output/review/site_images/`.
- **Social preview:** `viewer/og-image.jpg`, 1,200 x 630 px, the Center City skyline from Logan Square to the Comcast towers at 3 map px per image px.
- **Icons:** `viewer/favicon.ico` (16, 32 and 48 px) and `viewer/apple-touch-icon.png` (180 px), both the top of City Hall's tower. A street scene turned to mush at 32 px; the white tower is the one shape that still reads. At 16 px it is only a light smudge.
- **Pages:** `viewer/index.html` and `viewer/about.html` gained `<link rel="icon">`, `<link rel="apple-touch-icon">`, Open Graph tags (absolute URLs on pixelphilly.sstirling.com, with image size and alt text) and `twitter:card` `summary_large_image`. The map page's `og:url` is the short address, https://pixelphilly.sstirling.com/.
- **Hosted:** the three images went to `r2:pixel-philly/viewer/` (Cache-Control one day), `favicon.ico` also to the bucket root (browsers ask for `/favicon.ico`), and both pages re-uploaded (five minutes). `rclone check` on `viewer/`: 0 differences. All four image URLs return 200 with the right types.
- The offline copy (`scripts/27_offline_copy.py`) copies the whole `viewer/` folder, so it gets the icons too. Its social tags point at the hosted site, which is harmless offline.

## 2026-11-09 (late): v18 accepted, frozen, made the viewer default and hosted

Stephen accepted v18 and committed the work ("Talk map", 95a454f), then asked to make it the default on R2 and in general.
- **Frozen:** `output/philly/FROZEN_v18.json` (`scripts/26_freeze_map.py --name philly --version v18`): 75,367 files, 5.54 GB, tree SHA-256 `18d3fdedb1cbb67ef6a526ed9b8925ebdbeb34c1f917b50d614834e19bc712b7`; `--verify` passed. Don't rebuild or edit `output/philly/tiles/v18/`; the next version is v19.
- **Viewer default:** `viewer/viewer.js` now defaults to v18; `viewer/about.html` says "Map version v18, frozen Nov. 9, 2026." v17 stays at `?v=v17`, v14 at `?v=v14`.
- **Hosted:** v18's illustration layer uploaded to R2 under `output/philly/tiles/v18/` next to v17, then the viewer re-uploaded (log `output/philly/r2_upload_v18.log`). v17 stays in the bucket.

## 2026-11-09: Ben Franklin and Walt Whitman bridges modeled in 3D (philly v18)

Stephen (Nov. 9) said the Ben Franklin Bridge and the bridge south of it, the Walt Whitman, "look awful," and that "the southern bridge has buildings on the roadway." After the first two fixes he said both still "look terrible" and asked for both towers, the suspension cables and clean roadways. GPU cap $5. v14 and v17 stay frozen, and v17 stays the viewer default until Stephen accepts v18.

**Results:** v18 built Nov. 9 at 10:54 p.m. (`output/philly/build_v18.log`): 37,681 tiles per layer. 326 of 28,188 full-resolution tiles differ from v17. Seams are identical to v17 on all 22 region pairs (`output/philly/join_seams_v18.log`). The tan band under the cables is gone after the members-zone repaint fix. Crops: `output/review/bridges/nj/final_v18/` (v17 vs v18) and `output/review/bridges/crops_None/` (bridge sheet, 105 crops). The build first stopped on the stale-cell guard: southwest's `water_band/south_lidar/` copies of 11 redrawn frames predated the redraw; southwest was re-repainted (`output/southwest/repaint_v18.log`) and the build rerun. Not the viewer default until Stephen accepts it.

### Causes
- **Buildings on the roadway:** the 2022 LiDAR sees each deck from above. Where a deck crosses a footprint (the Packer Ave Marine Terminal under the Walt Whitman's Pennsylvania approach), the LiDAR shaping turned the deck into roof parts 10 m to 40 m tall, and the model drew them as buildings on the road. Next to the Walt Whitman's PA tower, the LiDAR also caught two container gantry cranes and shaped them into a cluster of high-rises (footprints 14875 and 326703: 85 parts of 34 m to 57 m, plus eight slivers of 18.4 m to 19.1 m).
- **Shadow slab:** in the 2024 aerial, each bridge's shadow lies on the river as a near-black band. The render passed it to the model as texture, and the model drew it as a dark slab beside the deck.
- **Missing towers and invented spans:** the 2024 aerial sees each tower only from above, and the render had no raised deck, cables or towers. The model guessed the structure: it drew one tower on the Ben Franklin and none on the Walt Whitman, and later invented slabs, a truss and a yellow gantry across the span.

### Iteration 1: drop the deck parts, fill the shadows, cap the cranes (run `qwen_joint_light8_fac_bridges`, 16 frames, ~$0.74)
- **Deck parts** (`bridges.deck_corridors`, `drop_deck_parts`; `"bridge_decks": true`): OSM motorway and trunk bridge ways (`raw/<area>_bridges.json`) are buffered by their lane width plus 8 m (`DECK_PAD_M`), which reaches the full 39 m Ben Franklin deck with PATCO and the walkways. A LiDAR-shaped footprint part at least 10 m tall and at least half inside a corridor is the deck, not a building, and is dropped. The footprint's other parts stay. The corridors are also masked out of the LiDAR structure search, as highways and rail already were.
- **Crane cap** (`config/part_caps.json`, `reviewed.drop_capped_parts`): entry `walt_whitman_pa_cranes`. Footprint parts within 45 m of the reviewed point and taller than 13 m are dropped. The warehouse roof is 10.9 m and the tallest real roof part in range is 12.1 m. A first cap of 25 m left the 18 m to 19 m slivers standing.
- **Anchorage stub** (`config/structure_exclusions.json`, `ben_franklin_pa_anchorage_stub`): LiDAR structure s585 (48 m², 52 m to 53 m) was left over at the Ben Franklin's PA anchorage after the corridor removed the rest. Alone, it drew as a thin 52 m pole on the approach. Dropped.
- **Shadow fill** (`bridges.clear_water_shadows`, `05_build_scene.py bridge_shadow_ground`; `"bridge_shadows": true`): in the ground texture, on mapped water within 300 m of a deck's over-water span, river pixels darker than 0.62 of the zone's median river brightness are shadow. Mid-dark pixels (under 0.95, `SHADOW_WEAK_RATIO`) connected to them go too, because the Ben Franklin's hanger shadows measured about 0.92. The mask is grown 4 px and closed over 40 px (`SHADOW_CLOSE_PX`), since hangers fall about 40 px apart and filling only the lines left a faint lattice. It is filled with a smooth field of the surrounding river color. An earlier version added the river's ripples back over the fill; that traced the tower, cable and hanger edges into the fill, so it was removed. Vessels and piers are never filled.
- **Result:** the deck buildings and the shadow slab were gone. But the model drew one Ben Franklin tower and no Walt Whitman towers (`output/review/bridges/nj/gpu_test/final_bfb.jpg`, `final_wwb.jpg`).

### Iteration 2: simple two-leg towers (run `qwen_joint_light8_fac_bridges2`, 17 frames, ~$0.75; three single-frame reseeds, ~$0.13 each)
- **Towers** (`bridges.tower_legs`, `05_build_scene.py add_bridge_towers`; `"bridge_towers": true`; `config/bridge_towers.json`): each tower's outline is its OSM way (`scripts/04q_fetch_bridge_towers.py`, `raw/south_lidar_bridge_towers.json`, ODbL). The outline is a strip across the deck, drawn as two square legs, one at each end. Heights are published: Ben Franklin 116.4 m (382 ft, DRPA), Walt Whitman 115.2 m (378 ft, CBS Philadelphia and PhillyYIMBY). Leg size and paint colors are estimates; the Walt Whitman's 3.3 m strips are widened to 5 m (`min_leg_m`, an estimate). Legs carry a fixed paint color instead of the aerial, which sees only the tower top.
- **Result:** the towers drew, but the model still invented the span. Across seeds 0 to 3 for `frame_33_12` it drew slabs, a truss and a yellow gantry between the towers.

### Iteration 3: the full suspension structure in the render (run `qwen_joint_light8_fac_bridges3d`, 30 frames, ~$1.17)
The render now shows the model what the bridge is, so it doesn't have to guess. All of it is in `bridges.suspension_structure` (`config/bridge_structures.json`, `"bridge_structures": true`). Every dimension there is either sourced (value, unit, source URL) or marked as an estimate with a reason.
- **Raised deck** (`bridges.lidar_profile`): the deck runs along the line between the two towers' centers, from the back of one anchorage to the back of the other, in 10 m segments. Its height is the median 2022 LiDAR surface within 5 m of that line, in 20 m bins, minus mean high water. Where the LiDAR has no returns (the Walt Whitman's New Jersey end is outside the City's coverage), a symmetric vertical curve through the published channel clearance stands in. Over water, and over land inside the suspended spans, the deck floats on its thickness (an estimate: 5.3 m on the Ben Franklin, 6.1 m on the Walt Whitman). Dashed lane lines follow MUTCD spacing (10 ft dashes, 30 ft gaps), and PATCO's two track beds sit outside the Ben Franklin's trusses.
- **Towers and crossbeams:** legs from iteration 2. Crossbeam heights are scaled from public-domain photos onto the LiDAR (estimates): four struts with X-bracing on the Ben Franklin (Tichnor Brothers postcard), one deep top strut and no bracing on the Walt Whitman (NARA 552709). The top strut's top surface is measured from the LiDAR on both.
- **Cables** fit to the LiDAR: each runs from the anchorage to the tower top, then along a parabola with the given sag. Side spans use the main span's sag scaled by (side span / main span)². Hangers hang from the cables to the deck at 6.25 m spacing (published on the Ben Franklin, an estimate on the Walt Whitman). The Ben Franklin gets its 8.53 m Warren stiffening truss above the deck.
- **Approaches** (`bridges.approach_decks`): past each anchorage the deck follows the OSM deck ways at the LiDAR deck height, on estimated piers every 50 m, until it is within 2 m of the ground, the OSM bridge ways end, or the carriageways spread more than 40 m apart.
- **Renderer** (`render/render.js`): prisms take an optional `z0` (raised base) and `roof_rgb` (flat, unlit top color). A raised underside is painted like the walls, not with the aerial. A new scene key, `tubes`, draws cables (Catmull-Rom curves through their points), hangers and truss members, lit like walls, and white in the mask pass. Scenes without these keys render the same as before. `05_build_scene.py` writes `tubes` per render tile (`tubes_in_reach`), and `09_check_alignment.py` projects raised prisms from `z0`.
- **Photo deck painted out** (`bridges.deck_plan`, `paint_out_decks`, `05_build_scene.py bridge_deck_ground`): the flat deck in the aerial is filled from the river over water and from the ground over land, 5 m past the modeled deck's plan. 2 m left the Walt Whitman's lit railing outside the fill, because the aerial isn't a true orthophoto: a deck 50 m up sits 3 m to 4 m off its plan position.
- **Repaint protection** (`bridges.structure_corridor`, `structure_zones`, `refine_members`; `10_repaint_water.py never_repaint`, `bridge_water`, `paint_water`): the water-level bridge band and hard deck mask are wrong for a deck 30 m to 50 m up, so the modeled bridges' lines are clipped out of them (deck width plus 10 m). The modeled structure takes over in two zones:
  - **Solid** (deck, approach, piers, anchorages, crossbeams, tower legs, each swept from `z0` to its top): never repainted. Render-mask pixels near it grow 8 px (`STRUCTURE_GROW_PX`) instead of 2, since the drawn deck sits a few pixels off the render's.
  - **Thin members** (cables buffered 10 px, hangers and truss members 4 px, plus the quads between hangers): mostly open river seen between thin tubes. The repaint takes pixels the drawing drew in river colors and keeps strokes connected to something it keeps. The mask grows only 1 px here (`MEMBER_GROW_PX`): 8 px kept a tan band of raw river between each cable and the deck, and 2 px left a rim along each hanger. Kept strokes count as water for the shore band, so hangers don't get dark frames.
  - The invented-water scan and the single-mosaic repaint treat the whole structure as one object (`structure_protect`).
- **Result:** one GPU pass of 30 bridge frames drew both bridges correctly: two towers each, cables, hangers and clean roadways.

### What the LiDAR showed
Heights above mean high water. MHW is 0.972 m NAVD88 at NOAA station 8545240, Philadelphia (MHW 3.082 m minus NAVD88 2.110 m, epoch 1983-2001; https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/8545240/datums.json).
- **Tower tops:** Ben Franklin 116.0 m to 116.1 m (published 116.4 m); Walt Whitman 114.4 m to 114.5 m (published 115.2 m). The scene uses the published heights.
- **Cable sag** (parabola fit to the LiDAR returns along both cables): Ben Franklin 60.4 m, rms 0.3 m (design sag 61.0 m); Walt Whitman 60.5 m, rms 1.2 m (no published figure found, so the fit is used).
- **Deck tops:** Ben Franklin 32.8 m to 46.4 m; Walt Whitman 40.1 m to 51.8 m.
- **OSM vs. LiDAR:** the Ben Franklin's New Jersey tower in OSM sits about 9 m west of the LiDAR tower top. OSM was kept, so the towers, cables and deck all share one source.

### Sources
- No Historic American Engineering Record (HAER) exists for either bridge.
- **Ben Franklin:** the Board of Engineers' design report to the Delaware River Bridge Joint Commission (https://archive.org/details/ReportToTheDelawareRiverBridgeJointCommission) for the cable sag and diameter, hanger panels, leg spacing and truss depth; DRPA (https://drpa.org/bridges/ben-franklin-bridge.asp) for spans, clearance, widths and lanes.
- **Walt Whitman:** DRPA (https://www.drpa.org/bridges/walt-whitman-bridge.asp), Bridgemeister (https://w.bridgemeister.com/bridge.php?bid=211) and PhillyRoads figures (https://industrialscenery.blogspot.com/2022/01/195719982017-i-74-walt-whitman-bridge.html).
- **Reference photos for the crossbeams** (public domain): Tichnor Brothers postcard (https://commons.wikimedia.org/wiki/File:Delaware_River_Bridge,_between_Philadelphia,_Pa._and_Camden,_N._J_(61748).jpg) and NARA 552709 (https://commons.wikimedia.org/wiki/File:WALT_WHITMAN_BRIDGE_CROSSES_THE_DELAWARE_RIVER_AT_SOUTH_PHILADELPHIA,_LEADS_TO_NEW_JERSEY_SUBURBS_-_NARA_-_552709.jpg).
- **Stylized, thicker than life** so they read at 0.293 m/px: cables 0.75 m radius (real: 0.38 m on the Ben Franklin, 0.29 m on the Walt Whitman), hangers 0.3 m radius, lane lines 0.4 m wide (real: about 0.1 m to 0.15 m).

### Known flaws, accepted
- The Ben Franklin's Philadelphia anchorages render and draw as blue blocks. The real ones are stone. Stephen (Nov. 9): skip it.
- A thin brown strip, about 8 px, runs along the deck's lower edge, from the solid zone's 8 px grow.
- The Ben Franklin's PA approach ends about 8 m up near 5th St, where OSM's bridge way ends.
- The New Jersey approaches use estimated fallback grades (3.1% and 2.1%) and end in the air, mostly in the area with no imagery.
- The second Packer Ave crane cluster, about 330 m south of the Walt Whitman (39.899 to 39.902 N), still draws as a high-rise. Not addressed.

### Tests
Written before each change. New: 36 tests in `tests/test_bridges.py`, plus `tests/test_bridge_wiring.py` (scene builder and repaint wiring) and `tests/test_render_features.py` (`z0`, `roof_rgb` and tubes in the renderer). `tests/test_reviewed.py` covers the part caps. 470 pass.

### GPU (estimates, from each run's own report in `output/gpu_runs.jsonl`)
| Run | Frames | Cost |
|---|---|---|
| `qwen_joint_light8_fac_bridges` | 16 | ~$0.74 |
| `qwen_joint_light8_fac_bridges2` | 17 | ~$0.75 |
| `_bridges3`, `_bridges_s2`, `_bridges_s3` (single-frame reseeds) | 1 each | ~$0.13 each, ~$0.39 |
| `qwen_joint_light8_fac_bridges3d` | 30 | ~$1.17 |
| `qwen_joint_light8_fac_v18rest` (the other 17 changed frames) | 17 | ~$1.27 (19.3 min) |

Total: ~$4.32 of the $5 cap (estimates from each run's own report).

### Backups (v17 state, before the bridge work)
- `output/south_lidar/redraws/qwen_joint_light8_fac_pre_bridges/`: the v17 drawings of all 47 redrawn frames.
- `output/south_lidar/renders_pre_bridges/`, `output/south_lidar/masks_pre_bridges/`.
- `data/processed/south_lidar_pre_bridges/`, `data/processed/south_lidar_qa_pre_bridges.json`, `data/processed/south_lidar_tiles_pre_bridges.json`.
- The v17 water outputs: `output/south_lidar/postprocessed/<run>/water_pre_bridges_v18/`.

### Review crops
`output/review/bridges/nj/`: `render_v4/`, `render_v5/` and `final_3d/` show v17 and the new drawing side by side. The aerial checks for the crane cap and anchorage stub are `aerial_ww_block.jpg` and `aerial_bfb_anch.jpg`.

### v18
- **Build:** `16_build_tiles.py --areas <12 areas> --name philly --prompt qwen_joint_light8_fac --version v18 --with-photo`, then `25_join_seams.py`, then `33_bridge_crops.py --before v17 --after v18`. Log: `output/philly/v18_pipeline.log`.
- **Results:** v18 built Nov. 9 at 10:54 p.m. (`output/philly/build_v18.log`): 37,681 tiles per layer. 326 of 28,188 full-resolution tiles differ from v17. Seams are identical to v17 on all 22 region pairs (`output/philly/join_seams_v18.log`). The tan band under the cables is gone after the members-zone repaint fix. Crops: `output/review/bridges/nj/final_v18/` (v17 vs v18) and `output/review/bridges/crops_None/` (bridge sheet, 105 crops). The build first stopped on the stale-cell guard: southwest's `water_band/south_lidar/` copies of 11 redrawn frames predated the redraw; southwest was re-repainted (`output/southwest/repaint_v18.log`) and the build rerun. Not the viewer default until Stephen accepts it.
- v18 is not the viewer default until Stephen accepts it. v14 and v17 stay frozen.

## 2026-11-09: v17 hosted on Cloudflare R2; visit counter

- **Upload:** v17's illustration layer (37,682 tiles, 4.34 GiB) and `viewer/` went to the Cloudflare R2 bucket `pixel-philly` in about 7 minutes. The photo layer was not uploaded. `rclone check` found 0 differences. Log: `output/philly/r2_upload_v17.log`.
- **URL:** https://pixelphilly.sstirling.com/viewer/index.html. A Cloudflare dashboard Redirect Rule sends `/` to `/viewer/index.html`.
- **Credentials:** the rclone remote `r2` lives in `~/.config/rclone/rclone.conf`, outside the repo. Never commit or print it.
- **Address search** works from the new origin: the City's AIS API sends `access-control-allow-origin: *`.
- **Aerial imagery:** Stephen (Nov. 9): "We're good on the aerial imagery." The open item to confirm with maps@phila.gov is closed.
- **Visit counter:** at Stephen's request, `viewer/index.html` and `viewer/about.html` load a GoatCounter counter (his account, no cookies). `scripts/27_offline_copy.py` strips it from the offline copy, which promises no remote requests, and fails if any is left.

## 2026-11-09: v17 accepted, frozen and made the viewer default

Stephen (Nov. 9): "Accept v17." The known flaws were accepted: shadow strips along some decks (W Roosevelt Blvd), plus the Platt Bridge rectangles and outline.
- **Frozen:** `output/philly/FROZEN_v17.json` (75,367 files, 5.54 GB, tree SHA-256 `047eec68…a5b5c0`). `--verify` passed. A re-verify of v14 also passed, so v14 is untouched.
- **Manifest purpose:** `26_freeze_map.py` hard-codes "talk map". It was edited by hand to describe v17 as the accepted map. The manifest sits outside the version folder, so the hash isn't affected.
- **Viewer:** the default is now `v17` (`viewer/viewer.js`). v14 stays available at `?v=v14`. The about page footer now reads "Map version v17, frozen Nov. 9, 2026." The hero image is still the v14 City Hall crop.
- **Not done:** no offline copy of v17 (`output/philly_offline_v14/` is still v14) and no commit.

## 2026-11-05 to 11-08: bridges (philly v16 and v17; v17 accepted Nov. 9)

Stephen (Nov. 5): "several of the bridges don't look correct... water is bleeding onto the roads." This entry was written Nov. 8, after the session that built v16 was cut off before it was logged. Times below come from file timestamps.

### Cause
A bridge deck in the render is flat aerial texture. Its asphalt and shadows often pass the river color test (South Philly: within 68 levels of [108, 101, 64]), and the drawing puts the deck and truss a few pixels off the render's deck. The repaint then painted deck, truss and railing pixels blue: the Ben Franklin's truss and the Platt and Walt Whitman decks, among others.

### Fix (`pixelphilly.bridges`, `tests/test_bridges.py`)
- **Bands:** where a City street centerline, expressway or rail line, or an OSM bridge way, crosses NHD or PWD water for at least 8 m. The over-water stretch is extended 6 m past the shore and buffered by a half width by street class. On screen it is swept from 25 m below to 12 m above the water. Method and sources are in `data/README.md`.
- **Inside a band**, the repaint only takes pixels the raw drawing drew in the river's own colors (`refine`). These are sampled from water at least 48 px away from any band.
- **Hard deck mask:** the deck where the render has it (80% of the half width, no sweep) is never repainted.
- **OSM bridges** (`scripts/04p_fetch_bridges.py`, `raw/<area>_bridges.json`, ODbL) add the New Jersey halves of the Delaware bridges, which the City layers don't cover.
- **Opt-out:** `"bridge_bands": false` in an area config.
- **Review tools:** `scripts/32_stage_crops.py` (render, raw drawing and finished drawing for one spot) and `scripts/33_bridge_crops.py` (v15 vs v16 for every bridge, `output/review/bridges/crops_v16/`, five contact sheets).

### Repaints and v16
- **All 12 areas** were repainted with bridge bands, Nov. 5 at 11:03 p.m. through Nov. 6 at 1:05 a.m. (`output/<area>/repaint_bridges.log`). philly v16 was built at 1:17 a.m. (`output/philly/join_seams_v16.json`).
- **Code check (Nov. 8):** `bridges.py` was last edited at 12:39 a.m., after eight areas had been repainted. To test whether those areas were stale, the current code was rerun on south_lidar's 63 deck frames and compared pixel by pixel:
  - 0 of 1,270,484 deck pixels differ.
  - The only differences, 5,124 px in two frames, are the two invented-water repairs the rerun skipped.
  - Result: the earlier repaints match the current code, so no repaint was needed for that reason.
- **Tests:** 412 pass.

### Found in review (Nov. 8): river inside the bands is left unpainted
Bridge decks no longer bleed. But inside the bands, river the raw drawing drew in other tones keeps those raw colors (teal, olive, brown) instead of the repaint blue. Visible at Walnut St (a teal block with straight frame edges), W Roosevelt Blvd (darker strips along both bridges) and the Platt Bridge (dark rectangles under the deck, plus a drawn outline left on the water). Logged with the current code on south_lidar's bridge frames:
- **Fallback, 6 frames** (`frame_09_13`, `10_12`, `10_14`, `11_13`, `12_16`, `12_17`, the Schuylkill crossings near Center City). The only water in view is inside bands, so the ring has 0 px. `refine` then returns `water & ~band`, and the whole band keeps the raw drawing.
- **Fallback census, all areas** (an estimate from mapped water rather than the full water mask; it matches the logged south_lidar run exactly): 12 frames.
  - south_lidar: 6.
  - southwest: 2 (`frame_17_01`, `17_02`, the same Schuylkill strip from its side).
  - north_lidar: 1 (`frame_05_13`).
  - lower_northeast: 1 (`frame_25_13`).
  - upper_northeast: 1 (`frame_27_26`).
  - germantown: 1 (`frame_20_06`).
- **Shadow strips, other frames:** thin strips of drawn shadow along the deck edges stay raw, plus drawn river where the hard deck mask sits off the drawn deck (up to about 20 px in `frame_10_13`). Counts outside the deck mask:
  - `frame_10_13`: 16,475 px;
  - `frame_18_05`: 4,254;
  - `frame_01_12`: 2,532;
  - `frame_19_05`: 1,062.
- **No safe color rule for the shadows:** Lab rules were tested on four frames (chroma within 8 to 16 of the palette, lightness down to 50 below it). The ones that caught most leftover shadow also matched 20% to 55% of the drawn deck, truss and pier pixels in the bands, which is the original bug. Not changed.
- **Status:** v16 should not replace v14 or v15 until the fallback is fixed. v14 stays frozen and the viewer default.

### Fallback fix and philly v17 (Nov. 8; not frozen; viewer default stays v14)
- **Fix:** tests first. Three new tests in `tests/test_bridges.py` failed, then passed after the change; 415 pass in all.
  - `bridges.ring_sample` returns the drawn-river sample.
  - `refine(..., sample=)` can use a sample from elsewhere.
  - `bridges.SampleBank` keeps up to about 4,000 drawn-river pixels per frame and returns the samples from the nearest frames, up to 4 frames away.
  - In `10_repaint_water.py`, frames with no drawn river outside their bands are set aside and repainted after the main pass with nearby colors, in both the main loop and region runs' `repaint_band`. Frames with no band also add to the bank, so a fallback frame next to bridge-free frames still finds colors.
  - `report.json` records `"bridge_fallback"`.
- **Why nearby colors and not one palette per area:** south_lidar's palette would be dominated by the brown Delaware and lose the teal Schuylkill.
- **Unchanged elsewhere:** a scratch rerun on south_lidar's 63 deck frames changed only the 6 fallback frames; every other frame was identical.
- **Repaints:** all 12 areas, Nov. 8, 8:47 to 11:05 p.m. (`output/<area>/repaint_bridges2.log`).
  - 19 frames used nearby colors, and none lacked a nearby sample.
  - Against a copy-on-write snapshot of the v16 water outputs, 16 frame files changed across 9 areas. All are fallback frames or their overlap copies. The rest are byte-identical.
  - The snapshot is in the session scratchpad, not the repo.
- **v17:** `16_build_tiles.py --areas <12 areas> --name philly --prompt qwen_joint_light8_fac --version v17 --with-photo`.
  - 15 of 28,188 full-resolution tiles differ from v16.
  - Seams are identical to v16 on all 22 pairs.
  - Bridge crops: `output/review/bridges/crops_v17/` (v16 vs v17).
- **Fixed:** Walnut St. The straight-edged teal block is gone.
- **Still not right (unchanged from v16):**
  - **Shadow strips** stay raw along deck edges: W Roosevelt Blvd, and a small sliver under Walnut St.
  - **Platt Bridge** has dark rectangles under the deck, plus a three-box outline on the water at the band's lower edge. The raw drawing has a frame seam there, with stray blue pixels that don't match the brown palette, and the repaint outlines those holes like shoreline. Neither is in v15.

## 2026-11-05: ships (philly v15, for review; v14 stays frozen and the viewer default)

Stephen (Nov. 5): fix ships, building v15. GPU cap $5. No commits, no LiDAR prune. A read-only diagnosis by another agent found four problems: the water repaint ate hulls and piers; most 2024 vessels had no 3D geometry; same-berth ships were fragmented, with moored hulls standing on pier ground; and the carrier read as a building.

### Repaint protection (tests first; `pixelphilly.vessels`, `tests/test_vessels.py`)
- **Choice:** option (i), reviewed outlines (`config/vessels.json`) plus OSM piers (`raw/<area>_piers.json`, `scripts/04o_fetch_piers.py`). Both are swept from the water up to 4 m, grown 3 px, and added to the mask the repaint and the invented-water fix never touch.
- **Why not option (ii)** (a drawing-aware "clearly not water" rule): in the raw drawings the model paints the river brown, olive and teal, the same colors as decks and piers. A color rule would either keep patches of drawn river or eat hulls again. Raised hulls are scene geometry and were already protected by the building masks, so the outlines only need to cover the deck level.
- **Opt-in:** `"vessels": true` in south_lidar, east_riverfront and southwest. The region runner fetches piers and treats vessels.json as a scene input. Old City is unchanged.
- **Result:** the USS New Jersey's deck and brick pier, the reserve fleet nests, the Olympia and Moshulu are no longer punched through. Open river still repaints blue: the repaint shows no brown or green patches on open water in the full Delaware and Schuylkill vessel frames.
- **Crops:** before/after (v14 vs the step-1 repaint) for every vessel group in `output/review/vessels/crops_step1/`, with a contact sheet.

### Vessel outlines (`config/vessels.json`; provenance in `data/README.md`)
- **Tracing:** `scripts/29_trace_vessels.py` finds decks in the 2024 aerial: brighter than the river, not a pier. Shadows and dark hull sides can't be told apart by color, since both pick up blue skylight, so decks are traced and grown back over the edge.
- **Review:** every group's trace sheet was reviewed (`output/review/vessels/trace_*.jpg`). The decisions (merge, split nests, shape fixes, rejects, flat) are recorded in `"review"`. `scripts/30_build_vessels.py` builds the outlines (`output/review/vessels/hulls_*.jpg`).
- **Counts:** 59 accepted hulls (53 with 3D, 6 flat), 20 protect-only traces, 23 rejected (quay edges, dock walls, cranes, the shipyard's gantry).
- **Nests:** nested hulls are split along the dark lines between them (N1, N4, S2).
- **Flat:** N11 (under way) and P2's tug are protected but get no 3D. So are the two N3 inner nests, whose trace also covered the pier edge.

### Whole hulls (`vessels.vessel_parts`, `drop_fragments`)
- **Shape:** each accepted hull is one structure at the water level (0 m NAVD88). A dry-dock hull (N10) uses its ground instead.
- **Heights from the LiDAR:** where the 2022 LiDAR saw the same hull (30% of its cells 2 m or more above the water), its class-1 heights shape the hull after gaps are filled. This keeps photo_agrees's job of dropping moved ships, because the 2024 outline decides where a hull is.
- **Assumed heights:** where the LiDAR didn't see the hull, the hull is flat at an assumed height by vessel kind (`kind_defaults_m`, labeled "default (assumed by kind)"). Shadow-length estimates were not attempted.
- **Fragments:** LiDAR structure regions at least half inside a hull give way to it. Cranes and piers that only touch a hull stay (tested).
- **Counts:**
  - south_lidar: 44 hulls (18 LiDAR-shaped), 33 fragment regions replaced;
  - southwest: 18 hulls (8), 6 replaced;
  - east_riverfront: 4 hulls (3), 1 replaced.
- **Walls:** structure walls already used deck color × 0.85.

### Atlas test and redraws (GPU $2.13 of $5)
- **Atlas test** ($0.28): `test_ships_navyyard` and `test_ships_pier82`. The new hulls drew as ships: the carrier with its deck and island, the amphibious ships, and the SS United States with its funnels.
- **south_lidar:** 20 changed frames (96 with the ring), $1.44.
- **Per-frame review:**
  - **Kept, 19 frames:** the reserve fleet, carrier, amphibious ships, SS United States, New Jersey, the Packer Ave container ships and the barges read better.
  - **Reverted, frame_20_08** (Moshulu and Olympia): the LiDAR-shaped Moshulu's masts came out as tall towers. The frame keeps its step-1 (protected, flat) drawing.
- **east_riverfront:** 3 frames, $0.25, kept (T1's bulk carrier).
- **southwest:** 2 frames, $0.16, not used. They had no vessel, and the changes were small render differences.
- **Repaints:** each area was repainted with protection after its merge, one at a time, so the stale-known guards stayed satisfied.

### Invented water on the 75 vessel frames (repaired blobs, before → after)
- south_lidar: 5 blobs / 6,322 px → 2 / 918 px.
- east_riverfront: 0 → 0.
- southwest: 0 → 0.

### Map: philly v15 (`?area=philly&v=v15`; not frozen; viewer default stays v14)
- **Size:** 37,681 tiles per layer.
- **Seams:** identical to v14 except south_lidar|east_riverfront p90 3.16 → 3.15 and south_lidar|southwest max 8.85 → 8.84.
- **Crops at 2×:** v14 vs v15 for every vessel group in `output/review/vessels/crops_v15/`, with `contact_sheet.jpg`.
- **Place checks:** `output/review/places_v15/` (the Navy Yard, Penn's Landing, FDR Park, Penn Treaty, Chestnut Hill, the airport).
- **Still not right:**
  - The carrier's hull side and the SS United States's midships still carry window-like vertical lines (the model reads tall walls as façades).
  - The N10 dry dock is drawn with teal water.
- **Checks:** v14's freeze still verifies (`43fe09fa…`). 406 tests pass. Old City's SHA is unchanged.

## 2026-11-05 (evening): map bar and opening view

Stephen asked for three changes to the map page:

- **The "AI-generated illustration" badge is gone from the top bar.** The AI note stays in the credits footer and on the about page.
- **The "Show photo" toggle is gone, and the photo layer no longer loads.** That saves the second set of tile requests. The photo tiles stay in v14, which is unchanged and frozen. The about page's pointer to the toggle is removed.
- **The map opens close in.** With no `#x/y/z` link, it starts on City Hall at 4 map px per screen px, about 2 km of Center City across a laptop screen (`START_VIEW` in `viewer/viewer.js`). Shared links still open where they point, and the home button still shows the whole city.
- **Checked with Playwright** at 1440×900 and on a 390 px phone: no console errors, and the screen is filled with map.
- **The offline copy** gets the same files, keeping its `data-offline` flag.

## 2026-11-05 (later): about page fixes

- **The page couldn't scroll** (Stephen): it loaded `viewer.css`, whose `html, body { overflow: hidden }` lets the map own the mouse wheel. The page was cut off at the bottom.
  - **Fix:** the about page has its own `viewer/about.css`, and the about rules are removed from `viewer.css`.
  - **Checked with Playwright:** desktop, 360 px phone and dark mode all scroll to the bottom, with no horizontal scroll.
- **Restyled:** a sticky "Back to the map" bar, and a 1:1 pixel-art hero of City Hall's tower from v14 (`viewer/about-hero.webp`, with alt text). Serif body text, and sources as a two-line list (name, then what it's used for). Light and dark themes.
- **Text changes:**
  - the slideshow link (https://sstirling.github.io/prezis/presentations/worldplanningday/);
  - "foundational knowledge on GIS and data" (Stephen dropped "the").
- **The offline copy** gets the new files.

## 2026-11-05: about and credits page

- **New `viewer/about.html`, linked from the map's credits footer.** It opens with Stephen's two paragraphs. In the first, he approved three edits: the talk title in AP title case, "every building, street tree and piece of land cover", and Gemini described as making the style's training examples, not base images. The second paragraph is about vibe coding, with the repo link. The technical sections below it come from `data/README.md` and `README.md`:
  - how the map was made;
  - what to keep in mind;
  - every data source, with links where the docs record them;
  - the AI models and software, including the Gemini-trained style;
  - inspiration (tiny.london, isometric.nyc);
  - the frozen version.
- **Styles** are added to `viewer/viewer.css`. Checked at 1,280 px and 360 px wide, with no horizontal scroll.
- **Open before publishing:**
  - the slideshow link is a placeholder (`#slides-link`);
  - wording points are raised with Stephen (the talk title's capitalization, "every tree", "building base images");
  - the offline copy needs the new viewer files.
- **Not changed:** the footer's short credit (`map.json` `credits`) sits inside the frozen v14 folder, so it is left as is.

## 2026-11-05: preview flyover video

Stephen asked for a short video panning over the map at high zoom, as a preview.

- **New `scripts/29_flyover.py`.** It cuts each video frame straight from the frozen v14 Deep Zoom tiles, with no GPU and no browser. It pipes the frames to ffmpeg (the static binary from the new `imageio-ffmpeg` dependency, installed in the venv only). It renders the 30-second, 1080p cut in about 12 seconds.
- **Camera path in `config/flyover/preview.json`:**
  - Hold on City Hall's tower at 1:1.
  - Pan down Broad St to Washington Ave over 14 s at 1:1.
  - Pull back to the whole city over 10 s, then hold.
- **Pixel-art choices:**
  - Close-ups use nearest-neighbor at whole-number scales, and the pan keeps a constant scale, so pixels stay square and don't shimmer.
  - The zoom-out uses the coarser pyramid levels with a box filter.
  - Zooms interpolate scale geometrically and move the center in step with the zoom, so the pull-back stays anchored on Broad St.
- **Waypoints take an optional height (`z`, meters).** The first test aimed at City Hall's ground point, and the frame showed only the towers south of it, because in the isometric view those towers hide City Hall's base. Aiming at 110 m centers the tower.
- **A provisional credit line is burned in at the bottom right.** It will be replaced by the wording Stephen writes for the credits page.
- **Output:** `output/flyover/preview.mp4` (885 frames, 104.7 MB, H.264, yuv420p, faststart) and `output/flyover/preview_10s.mp4` (the first test, from the ground-point start).

## 2026-11-04 (night): fixes, then v14 frozen as the talk map; offline copy; hosting plan

Stephen (Nov. 4) asked for three things before freezing the map: fix West Fairmount Park, bring the four tree-border seams back down, and stop the lawn correction on the Cobbs Creek park strip. The GPU cap for these fixes was $4. Then freeze v14, make an offline copy, and plan hosting. He is writing the credits page, so it isn't written here. No commits, no LiDAR prune.

### Causes found, fixed test-first
- **Stale known pixels (pipeline bug).**
  - The tree redraws ran in parallel. Roxborough's redraw (launched 5:32) read germantown's band frames while germantown's own redraw was merged but not yet repainted (done 5:43). North and upper_north read each other mid-redraw the same way.
  - Band overrides went stale too. A later area's `water_band/` re-repaint of an earlier area's frame isn't rerun when that frame is redrawn. West_lidar's overrides kept 5 cells of south and north drawings from before the trees, and v13 showed those old drawings.
  - **New guards:**
    - `regions.stale_known` refuses known pixels older than their drawing.
    - `regions.in_flight_runs` refuses a known area that is still drawing.
    - Both are in `15_joint_sample.py`. `16_build_tiles.py` also refuses to build when any cell is older than its drawing.
    - Test: `test_stale_known_flags_frames_redrawn_after_their_repaint`.
  - The guards caught three stale states during this work. Each was fixed by repainting the affected area first.
- **West Fairmount box (not a pipeline bug).**
  - The light-green box was one whole cell, west_north frame_16_04 from the tree redraw. The model drew it lighter than the north_lidar cells above and to its right, which were known. North's frames were final when it ran (03:31 < 03:48).
  - It isn't a repair-strip artifact (that strip is 200 px; the box is the whole frame) or a water-repaint one (the repaint changed 0.1% of the frame). Fixed by redrawing the border frames.
  - The gray-blue cricket field (Belmont Plateau) is in frames 16_04 and 16_05. The model drew the dark, mown turf gray-blue. Redrawing 16_05 alone left a seam through the field, so 16_04 and 16_05 were redrawn together. The field is green now.
- **Cobbs Creek park strip:**
  - PPR's "Cobbs Creek Golf Course" property counts as a course (PPR "Golf" names), and 26% of it lies outside OSM's construction outlines. That part, the meadow between Olde and Karakung, got the golf correction.
  - New rule (`golf.ppr_construction`; test `test_ppr_golf_property_over_a_construction_course_is_construction`): a PPR golf property lying at least half over reviewed construction courses is construction as a whole.
  - west_north and west_lidar were rebuilt and re-rendered. 15 + 2 frames changed by 5,000 px or more and were redrawn. In the render, the strip now matches the 2024 aerial (beige meadow and earth), with no pale edges.
  - Two other approaches were tried and dropped. Closing the course outlines doesn't reach the meadow, which opens to the north. The courses' convex hull also swallowed the Samuel Rose Recreation Center.

### Redraws ($2.90 of the $4 cap)
| Run | Frames | Cost (est.) | Why |
|---|---|---|---|
| roxborough `_border` | 20 (81 with ring) | $1.26 | germantown and upper_north borders |
| west_lidar `_cobbs2` | 2 | $0.13 | Cobbs strip render |
| west_north `_fix14` | 25 (70 with ring) | $1.04 | north and upper_north borders, the West Fairmount box, the Cobbs strip |
| west_north `_fix14b` | 1 | $0.08 | wasted: roxborough has no cell in west_north's canvas, so it couldn't be known |
| roxborough `_fix14c` | 1 | $0.09 | the frame across from the redrawn west_north 12_02 (that seam had risen to 5.07) |
| west_north `_fix14d`, `_fix14e` | 1, then 2 | $0.13 + $0.17 | the cricket field |

- **Invented water** in the new drawings: roxborough 8 blobs (10,922 px), west_north 1 (2,491 px) and west_lidar 0.
- **Four real pools held** in roxborough (`config/invented_water_holds.json`).
- **Teal scan:** no teal lakes.

### Map: philly v14 (frozen)
- **Size:** 37,681 tiles per layer (illustration 4,656 MB, photo 883 MB).
- **Seams** (`output/philly/join_seams_v14.json`), medians v13 → v14 (v12 or earlier in parentheses):

| Pair | v13 | v14 |
|---|---|---|
| germantown\|roxborough | 4.03 | 2.77 (2.60) |
| upper_north\|roxborough | 4.01 | 2.56 (2.51) |
| north\|west_north | 4.80 | 2.48 (3.44) |
| upper_north\|west_north | 3.81 | 2.89 (2.63); max 7.26, the redrawn rail yard across the Schuylkill |
| west_north\|roxborough | 2.55 | 2.24 |

- All other pairs are unchanged.
- **Crops, before and after at 1:1** (`output/review/fix_v14/`): `seam_*.jpg`, `west_fairmount_box_1to1.jpg`, `cobbs_strip_map_v13_v14.jpg` and `cobbs_strip_photo_v13_v14.jpg`.
- **Place checks:** `output/review/places_v14/`, the same 11 places plus a Cobbs construction crop.
- **Freeze:**
  - `output/philly/FROZEN_v14.json`: 75,367 files, 5.54 GB. Tree SHA-256 `43fe09fa806d5d092a64c955e0dae5e9a6808e7017e4e2043dc0bd64c35e42bd`. It also lists the regions, run, prompt, LoRA and merged redraw runs.
  - Check it with `scripts/26_freeze_map.py --verify`.
  - The viewer now opens `philly` v14 by default. Older versions are kept.

### Offline copy
- **Folder:** `output/philly_offline_v14/` (5.4 GB), built by `scripts/27_offline_copy.py`. It holds the viewer, vendored OpenSeadragon, both v14 layers, the manifest, start scripts (macOS, Linux, Windows; `python -m http.server` on 127.0.0.1) and a README.
- **Search:** address search uses the City's online AIS API, so the offline copy turns it off and shows a message instead.
- **Check** (`scripts/28_check_offline.py`, Playwright Chromium with every host but 127.0.0.1 unresolvable):
  - It made 112 requests, 104 of them tiles.
  - None went off the machine, and none failed.
  - The request log is `output/review/fix_v14/offline_requests.json`; the screenshot is `offline_check.png`.

### Hosting plan (research only; README "The talk map")
- **Recommendation:** Cloudflare R2 behind a custom domain, likely $0/month at this size. Steps, rclone commands, CORS and caching headers are in the README.
- **Ruled out:** GitHub Pages (1 GB site cap), Cloudflare Pages free (20,000 files), Vercel (15,000 files per deploy).
- **License flags for public hosting:**
  - The City's 2024 aerial ("retains all rights") is in the photo layer and under the illustration. Confirm with maps@phila.gov.
  - OSM attribution should cover golf courses as well as façades.
  - The Gemini-trained LoRA must be disclosed.

### Other
- `viewer/index.html`: the description and alt text now say Philadelphia, not downtown.
- **Tests:** 398 pass. The Old City scene SHA is unchanged (`eaca1872…eaac4`).

## 2026-11-04 (later): tree-canopy woods and golf everywhere, Batch C drawn, the whole city in one map (philly v13)

Stephen (Nov. 3–4): tree-canopy woods everywhere (cap $25 for the redraws), the golf correction folded into the same redraws (cap $4 on top), Batch C (northwest, upper_northeast; cap $15), then a merged map of all 12 regions. The LiDAR prune is **not** approved: raw tiles kept, no `--apply`. No commits.

### Repaint fixes (tests first; detail in `data/README.md`)
- **Mapped water outside NHD** (`waterpaint.body_models`, `body_water`): each City (PWD) water polygon outside NHD, and each OSM golf water hazard, gets its own color model (median of its eroded interior; threshold capped at 40; at least 60% of the interior must match). The Manayunk Canal is now water. A "water" polygon over mixed lawn and paving (a dry basin) gets no model.
- **Tree canopies left out** of those models and of the repaint (`waterpaint.tree_discs`, `tree_mask`), so a creek polygon under woods doesn't learn canopy green.
- **Pond rings:** the invented-water repair grows each blob through its connected shore band (up to 12 px) and fills holes that are water-colored, ripple dashes or under 64 px, so a repaired pond no longer leaves a blue ring (roxborough's field pond).

### Golf (Stephen, Nov. 3; tests in `tests/test_golf.py`)
- `"golf_correct": true` in all 12 city region configs; off by default, so Old City is unchanged.
- `scripts/04n_fetch_golf.py` (Overpass, full geometry) → `data/raw/<area>_golf.json`. Courses: OSM `leisure=golf_course` without driving ranges, courses under 5 ha or disused ones, plus PPR properties named "Golf" (Walnut Lane). Cobbs Creek "Olde" and Karakung are reviewed construction sites (`config/golf.json`) and get no lawn correction.
- `lawns.correct_golf`: band hue 30–75, S 0.15–0.70, V 0.30–0.92. Fairways, greens and tees go to hue ~82 and 4% lighter; rough goes to the park target (hue 88). Bunkers and water hazards are left out, and wooded rough stays woods. No mow stripes.
- **Union League:** OSM names the Torresdale course (way/485880727) "Union League Golf Club". That name is unverified, so don't use it in captions without a source.
- **Before/after crops** (`output/review/golf/golf_before_after_<course>.jpg`; aerial, render, drawing; v12 vs v13): Byrne, Saint Martin's (bleached fairways now read as grass), Bala (the clubhouse pond survives as water), Juniata, Walnut Lane, Union League (new in v13), Cobbs Creek Olde and Karakung (left as graded earth).
- **Invented water on course frames** (redrawn frames, raw drawings, blob centers within 100 px of a course): 4 blobs / 37,274 px before, 4 / 32,404 px after. No rise.

### Tree-canopy woods everywhere
- `"woods_trees": true` in all 12 city region configs. Treetops from the neighboring regions' LiDAR grids (same projection origin) fill the area past a region's own LiDAR box (`lawns.merge_canopy_trees`, `05_build_scene.woods_trees`), so the woods don't stop in a straight line at region borders. Aligning the 7 m blocks across grids was tried and reverted, to keep the frames already redrawn consistent.
- **Redraws:** frames whose render changed by 5,000 px or more were redrawn with a 1-cell ring of finished frames held fixed (`--redraw ... --context 1`), run `qwen_joint_light8_fac_trees`, then merged into the main run (originals kept in `redraws/qwen_joint_light8_fac_pre_trees/`) and repainted with the holds.

| Region | Frames redrawn | GPU cost (est.) |
|---|---|---|
| germantown (two passes: own grid, then neighbor-grid trees; 46 distinct frames) | 46 | $2.26 + $0.39 |
| south_lidar | 47 | $3.04 |
| north_lidar | 37 | $0.97 |
| upper_north_lidar | 55 | $1.58 |
| west_lidar | 24 | $0.96 |
| west_north (+ 2 frames for the Cobbs lake, below) | 49 + 2 | $1.55 + $0.16 |
| southwest | 57 | $2.14 |
| east_riverfront | 10 | $0.83 |
| roxborough | 15 | $0.63 |
| lower_northeast | 85 | $3.20 |
| **Total** | **427** | **$17.71** (cap $25; golf was folded in, with no separate spend) |

- **Invented water in the redrawn frames** (raw drawings, before the repair): 54 blobs / 264,010 px before, 47 / 130,443 px after. Germantown's woods fell from 182,327 px to 35,668 px. Without germantown, 81,683 px before and 94,775 px after (+16%), mostly small blobs the repair fixes.
- **Review on the 2024 aerial** (`output/review/trees_invented_water_review.jpg`, `trees_invented_water_review_drawings.png`). New holds in `config/invented_water_holds.json`: a creek in the woods near the city line and a covered backyard pool (west_north), a covered courtyard pool (north_lidar), and the south fill-area channel box extended south. The three areas were repainted.
- **Missed by the scan, found by eye: a teal lake on the Cobbs Creek construction site** (west_north frames 14_17 and 14_18; `output/review/west_north_cobbs_lake_before_redraw.png`). The model drew the pale lawn-corrected park strip between the construction courses as a ~275,000 px lake at hue ~165°, outside the scan's water hue band (185–215°). Redrawn ($0.16); the redraw has no lake (`west_north_cobbs_lake_redraw.jpg`). A dry scan with the band widened to 160° found no other invented lakes: its other hits are real basins (the port and the wastewater plant) and pools, so the band was **not** widened (README open issues).

### Batch C ($15 cap)
| Region | Frames (new) | Gates | GPU | Cost (est.) | Invented water repaired / exempt (incl. holds) |
|---|---|---|---|---|---|
| northwest (trees) | 244 (35) | pass; 1 stadium excluded (8700 Ridge Ave, second footprint) | 41.9 min | $2.76 | 6 / 10 |
| upper_northeast (trees) | 697 (544) | pass after review; 3 stadium candidates excluded | 115.4 min | $7.60 | 123 / 69 |

- **Spend:** Batch C $10.36.
- **Reviewed on the 2024 aerial** (crops in `output/review/`):
  - **Stadium exclusions:** Fox Chase Cancer Center (7701R Burholme Ave), Jefferson Torresdale Hospital (10800 Knights Rd) and Philadelphia Mills (4301 Byberry Rd): not stadiums. The scene was rebuilt before drawing.
  - **Kept as real:** upper_northeast's largest LiDAR structures s1789, s374 and s2860, warehouses missing from the footprint layer.
  - **No needles.**
- **Invented-water holds:**
  - northwest: a garden pond and five backyard pools;
  - upper_northeast: two stormwater basins, three ponds, a pond in a meadow, a dark detention basin (likely wet; unverified) and an L-shaped pool.
  - Blobs under ~1,300 px were not reviewed one by one.

### Map: philly v13 (`?area=philly&v=v13`)
- **Coverage:** all 12 regions, 3,254 cells, 37,681 tiles (map 4,655 MB, photo 883 MB). Precedence (first listed owns shared cells): south, north, upper_north, west, west_north, southwest, germantown, east_riverfront, roxborough, lower_northeast, northwest, upper_northeast.
- **Join seams** (`output/philly/join_seams_v13.json`, 22 pairs), medians: 1.68–2.76 for most pairs.
- **Higher than before**, where redrawn woods meet a border:
  - germantown|roxborough 4.03 (was 2.60; max 9.87, the same lawn-tone step through a city block as in v12);
  - upper_north|roxborough 4.01 (was 2.51; the Schuylkill's color shifts at one edge);
  - north|west_north 4.80 (was 3.44);
  - upper_north|west_north 3.81 (was 2.63);
  - new pairs: lower_northeast|upper_northeast 2.49, roxborough|northwest 3.14, germantown|northwest 2.06.
- **Crops:** `output/review/join_seams_v13_worst_and_median.jpg`.
- **Place checks** (`output/review/places_v13/`; aerial, render, drawing):
  - **Read well:** Chestnut Hill's Germantown Ave, the Wissahickon at Valley Green (creek blue, woods as trees), Pennypack Park at Verree Rd and at Frankford Ave, Northeast Philadelphia Airport (runways, hangars), Philadelphia Mills (its stormwater pond blue), FDR Park (both lakes blue), Tacony Creek Park and Penn Treaty Park.
  - **Cobbs Creek Park:** the crop box fell mostly outside the city; the golf crops cover the Cobbs Creek corridor.
- **Defects found and not fixed:**
  - **West Fairmount Park at the north|west_north join** (-75.2088, 39.9966; worst seam, 9.36): part of the woods is drawn as flat green inside a straight-edged box, though the render has trees there. Nearby, a turf field is drawn gray-blue (`output/review/join_north_west_north_v13_render_vs_drawing.jpg`). A redraw of the frames on both sides of the join would cost ~$0.20.
  - **Cobbs Creek construction site:** with the construction courses excluded, the park strip between them is still lawn-corrected. Its pale green now ends in straight lines against the uncorrected graded earth (`output/review/golf/cobbs_construction_render_v12_v13.jpg`). This is the strip the model drew as a lake.

### Other
- **README:** the region-runner notes now cover trees everywhere, golf, and the invented-water review. The stale note that `s1762-0` was unreviewed is fixed (it has been in `config/qa_exceptions.json` since Oct. 28). New open issue: teal invented water.
- **Tests:** all pass. Old City scene SHA-256 is unchanged: `eaca18728d36a5de80ccb29fdc1e6b776be4d522434faa787cdd9a89802eaac4`.

## 2026-11-04: Batch B drawn: roxborough (woods as trees) and lower_northeast (philly v12)

Stephen (Nov. 3): hold roxborough and draw its woods as LiDAR tree canopies; lower_northeast with woods as in v9. No commits, no LiDAR prune.

### Tree canopies (tests first)
- **Option:** `"woods_trees": true` (or `"lidar"`), with `lawns.canopy_trees` and `05_build_scene.woods_trees`. Woods get the street-tree canopy geometry at LiDAR treetops, one per 7 m block.
- **Edge thinning:** density fades from 0 at the woods-mask edge to full ~15 m in (`TREE_EDGE_M`), deterministically, so the forest doesn't end in a wall.
- **Unchanged without it:** the other configs don't set it, and Old City's SHA is unchanged.
- **Test spot** (`test_wissahickon_trees`, ~$0.26 in all):
  - with thinning, 5,375 canopies;
  - invented water: 1 blob (2,731 px), against 4 blobs (8,990 px) unthinned and 0 in the current drawing;
  - the blue patch is on golf-course rough with no water in the aerial, so the repair handles it;
  - crops: `output/review/trees_test_thin_compare.jpg`, `trees_test_edge_1to1.png`.

### Reviewed data (all checked on the 2024 aerial; crops in `output/review/`)
- **New `config/structure_exclusions.json`** (`reviewed.drop_excluded_structures`, tested; a scene-build input in the runner): a 42,345 m², 21 m LiDAR "structure" on the Manayunk Canal strip is a rubble field in 2024. Dropped.
- **Stadium exclusions:** 8700 Ridge Ave (a care-home campus) and 8201 Torresdale Ave (Holmesburg Prison).
- **Needle exception:** 21880-1 at 5245 Bleigh Ave, a real elevated water tower (40.6 m, City record 137 ft).
- **Kept as real:** roxborough s1299 (a 46 m office tower past City Line Ave), lower_northeast s1485 (a 100,000 m² warehouse missing from the footprint layer) and s1618 (a rail and bus depot building).

### Bug fixed (test first)
- `10_repaint_water.py`: the band repaint read a known area's halo cell that area never drew (its own band, owned by a third area). It crashed on lower_northeast (upper_north_lidar frame_22_04). Missing frames now read as empty context (`existing_only`).

### Batch B ($15 cap)
| Region | Frames (new) | Gates | GPU | Cost (est.) | Invented water repaired / held |
|---|---|---|---|---|---|
| roxborough (trees) | 319 (190) | pass; 1 stadium excluded, 1 structure dropped | 55.0 min | ~$3.62 ($3.51) | 25 / 11 |
| lower_northeast | 539 (473) | needle gate stopped it; reviewed: water tower; prison excluded | 93.1 min | ~$6.13 ($5.93) | 17 / 8 |

- **Spend:** Batch B about $9.75. A roxborough run was stopped during its scene build, before any GPU spend.
- **Holds:**
  - roxborough: the Wissahickon Creek outside the water polygons, plus nine swimming pools;
  - lower_northeast: the Baxter Water Treatment Plant basins, a park pond, a dark basin, a creek in the woods, and four pools.
- **Map:** `philly` v12 (`?area=philly&v=v12`): 2,675 cells, 31,650 tiles.
- **Join seams** (`output/philly/join_seams_v12.json`), medians:

| Pair | Median |
|---|---|
| upper_north\|lower_northeast | 2.12 |
| germantown\|lower_northeast | 2.31 |
| east_riverfront\|lower_northeast | 2.40 |
| upper_north\|roxborough | 2.51 |
| west_north\|roxborough | 2.55 |
| germantown\|roxborough | 2.60 (max 9.87, a lawn-tone change in a city block) |

### Seen in the place checks
- **Wissahickon at roxborough|germantown:** roxborough's tree canopies stop in a straight line at the region boundary, and germantown's woods are v9-style brown blotches (`output/review/place_wissahickon_roxborough_germantown.png`). Trees on germantown's woods would fix it.
- **Manayunk Canal:** drawn as a grass strip. Its olive-green water likely misses the water repaint's color match against the brown river (`place_manayunk_main_st_canal.png`, `place_manayunk_aerial.jpg`).
- **Invented-water repair is partial on larger blobs:** the center is refilled but a blue ring stays (roxborough's field pond, frame_15_09).
- **Read well:** Frankford Transportation Center (the El terminal and curve) and the Wissahickon inside roxborough.

## 2026-11-03 (later): forest woods reverted (philly v11 = v9); tree-canopy test

Stephen (Nov. 3): revert the forest woods, run Batch B, and test tree canopies.

### Revert
- **Why forest mode failed:** a smooth, near-uniform green ground is read by the model as water. Invented water rose 4.7 times in the redrawn frames.
- **Drawings:** the pre-forest drawings were restored for west_north (53 frames), germantown (84) and southwest (83), all byte-identical to the saved originals. The three were re-repainted with the holds.
- **Configs:** the eight region configs no longer set `lawn_woods_mode`.
- **Code:** the woods feather now applies only in forest mode (`woods_grid(..., feather_m=0)` by default, tested). With that, the rebuilt scenes reproduce v9's render inputs bit for bit: west_north 210/210, germantown 294/294, southwest 404/404 and east_riverfront 227/227 frames identical.
- **Kept:** forest mode code and tests, off by default.
- **Map:** `philly` v11 (`?area=philly&v=v11`). All 16,872 deepest-level tiles are byte-identical to v9, and seams are identical (`output/philly/join_seams_v11.json`). v10 is kept for reference. The forest redraws cost ~$7.71 and are not used.

### Tree-canopy test (report only, not applied; ~$0.13)
- **`"woods_trees": "lidar"`** (`lawns.canopy_trees`, tested): woods get the street-tree canopy geometry at LiDAR treetops, one per 7 m block where the woods weight is over 0.5.
- **Test spot:** `config/test_wissahickon_trees.json`, identical to `atlas_wissahickon_fac` except the option. 5,933 canopies added (646 street trees before).
- **Drawn** in the original style. The woods read as dense trees, the creek stays blue, and there are no lakes in the woods.
- **Invented water:** 4 small blobs (8,990 px) on open ground at the golf-course edge, against 0 in the baseline.
- **Crops:** `output/review/trees_test_renders.jpg`, `trees_test_drawings.jpg`, `trees_test_drawings_1to1.png`.
- **Limit:** no trees beyond the area's LiDAR box (bbox + 100 m).

## 2026-11-03: forest-green woods tried and redrawn (philly v10); it invents lakes, so Batch B was not started

Stephen approved a forest-green woods fix with a redraw of the affected frames (cap $8), then Batch B. Batch B was **not** started: see the result below. No commits, no LiDAR prune.

### Built (tests first)
- **`"lawn_woods_mode": "forest"`** (`lawns.forest`): woods are shifted toward the renderer's tree-canopy green (hue 108°, saturation 0.55), with brightness remapped into 0.26–0.56, so the texture is kept and shadows can't go black.
  - **Skipped:** paving, mapped water and footprints (+1 m).
  - **Scope:** all woods, not only parks. Limiting it to park polygons made a hard edge at Cobbs Creek.
  - **Tests:** real aerial fixtures (Wissahickon, West Fairmount, Washington Square).
- **Feather:** woods weight feathered over ~16 m (`WOODS_FEATHER_M` 8 m, two box passes), tested. It softened the forest edge seen in `output/review/forest_westfairmount_join_nofeather.jpg`.
- **Configs:** set on all eight citywide regions.
- **Crops:** `output/review/forest_wissahickon.jpg`, `forest_westfairmount_join.jpg`, `forest_cobbs_creek.jpg` (`_nofeather` versions kept).

### Redraw (`15_joint_sample.py --redraw`, 1-cell known ring, original style)
| Region | Frames redrawn (ring) | GPU | Cost |
|---|---|---|---|
| west_north | 53 (118) | 25.8 min | ~$1.70 |
| germantown | 84 (215) | 47.3 min | ~$3.11 |
| southwest | 83 (202) | 44.0 min | ~$2.90 |
| east_riverfront | 20 (79) | not drawn | ~$1.15 projected; it would have passed the $8 cap |

- **Spend:** about $7.71. Redraws cost about $0.0145 per run frame, not $0.011 (the repair pass and ring).
- **Merge:** originals in `redraws/qwen_joint_light8_fac_pre_forest/`; repainted with holds.
- **Map:** `philly` v10 (`?area=philly&v=v10`). 897 deepest-level tiles differ from v9.

### Result: worse in places
- **Invented water in redrawn frames:** about 264,000 → 1,250,000 px, and blobs over 20,000 px went from 2 to 14. The model draws the smooth forest-green ground as lakes and rivers (`output/review/forest_invented_water/contact_sheet.png`).
- **After repair:** the fix repaints those blobs from the render, leaving flat pale-green areas that still carry some ripple dashes and pieces of blue lake (`output/review/forest_iw_germantown_frame_08_18.jpg`). A creek the old drawing showed is drawn as a dark gray stripe.
- **north|west_north join:** median 3.44 → 3.32, not the hoped-for 2.2–2.6. North's side was greened as lawn, west_north's side is now forest green, and the tone change still shows at 1:1 (`output/review/join_north_westnorth_after_forest_marked.png`).
- **v10 seams (medians):** north|west_north 3.32, upper_north|germantown 2.43, west|west_north 2.48, south|southwest 2.61, west|southwest 1.73. East_riverfront pairs unchanged.
- **Recommendation:** keep v9 as the current map. The pre-forest drawings can be restored at no GPU cost. Options for woods are in the report (for example, LiDAR-placed tree canopies in the render instead of a ground tint).

## 2026-11-02 (night): Batch A finished: reviewed data fixes, east_riverfront drawn, holds (philly v9)

Stephen approved the fixes below on Nov. 2. Original style throughout. No commits, and no LiDAR prune (`--apply` isn't approved).

### Reviewed data fixes (tests first: `tests/test_reviewed.py`)
- **`src/pixelphilly/reviewed.py`** is applied in `05_build_scene.py`. Unlisted footprints are untouched; Old City's SHA is unchanged.
- **`config/height_overrides.json`:** footprint 478499, 5458 Tacony St, is recorded at 138 ft. The aerial shows a small round tank in a scrapyard with almost no shadow, so the record is a data error.
  - Mode `neighbor`: the median height of footprints within 25 m, here 10.67 m from one neighbor. The footprint is kept out of LiDAR shaping.
  - The needle gate now passes on corrected data, not on an exception (`output/review/needle_478499_before_after.jpg`).
- **`config/stadium_exclusions.json`:** four non-stadiums that passed the seating-row rule, all checked on the 2024 aerial:
  - 8500 Essington Ave, the airport terminal and garages;
  - 4101 N Delaware Ave, Richmond Generating Station;
  - 3622-40 G St, a sawtooth-roof plant;
  - 3001 E Allegheny Ave, a pier warehouse.
- **Airport result:** southwest was rebuilt with the exclusion. All 404 renders are bit-identical to the ones drawn, because the footprint has a property-record facade and the seating-row wall color isn't rendered. So the redraw was skipped ($0), and the drawing stands as is.
  - Crops: `output/review/airport_render_before.jpg`, `airport_drawn_before.jpg`.
  - `renders_v1/` and `masks_v1/` keep the earlier renders and masks.
- **Runner:** the scene build now depends on both lists, so a change to either rebuilds scenes.
- **`15_joint_sample.py --redraw frames --context N`:** redraws a few frames of a drawn area, with the frames around them held at their finished pixels (`regions.redraw_plan`, tested). It's built and tested but wasn't needed this time.

### east_riverfront
- **Drawn:** 227 frames (193 new). Gates pass: no needles, no stadiums, facade match 0.996, alignment clean.
- **Cost:** 41.3 min of GPU, about $2.72 (estimated $2.50).
- **Batch A total:** about $13.28 of the $15 cap (west_north $2.53, germantown $3.37, southwest $4.66, east_riverfront $2.72).

### Invented-water holds (`config/invented_water_holds.json`; aerial review in `output/review/`)
- **southwest:** three boxes:
  - wet mud by a warehouse;
  - flooded refinery ditches and lots (three blobs);
  - standing water by a basin.
- **Repaired, not held:** sw_32_16 (a grass field), sw_11_11 (forest floor) and germantown 05_13 (a dry skate bowl, not a pool).
- **east_riverfront:** five boxes:
  - two warehouse detention basins;
  - a pond by Frankford Creek;
  - an I-95 stormwater basin;
  - water-treatment aeration tanks;
  - another warehouse basin.
- **Repaints:** both areas were re-repainted with `--invented-water fix`. Held: southwest 5 blobs, east_riverfront 8. The previous outputs are kept in `water_before_holds/`.

### Joins (`output/philly/join_seams_v9.json`), medians
| Pair | Median |
|---|---|
| south\|east_riverfront | 1.68 |
| west\|southwest | 1.84 |
| north\|east_riverfront | 2.17 |
| upper_north\|east_riverfront | 2.44 |
| upper_north\|germantown | 2.46 |
| west\|west_north | 2.60 |
| south\|southwest | 2.61 |
| upper_north\|west_north | 2.63 |
| north\|west_north | **3.44** |

- **north|west_north (3.44):** it runs through West Fairmount Park's woods. north_lidar's side was drawn before the woods rule, with everything greened. west_north leaves leaf-off woods as aerial, and the model drew them dark brown to near black.
  - Crops: `output/review/join_north_westnorth_worst_marked.png`, `join_north_westnorth_overview.jpg`.
  - This is a style question for Stephen: keep the woods rule, or turn it off or soften it and redraw the affected frames.

## 2026-11-02 (later): Batch A drawn in the original style; woods kept out of the lawn correction (philly v8)

Style: `qe2511_oldcity_r16_v1`, prompt "Redraw this render as isometric pixel art in the pixel philly style.", Lightning 8, run `qwen_joint_light8_fac`, the same as the four drawn regions. Those four were not rebuilt or redrawn. No commits.

### Woods in the lawn correction (tests first)
- **Problem:** leaf-off forest floor falls in the dormant-grass band; `atlas_wissahickon_fac` greened 42% of its park pixels.
- **Fix:** new config `"lawn_skip_woods": true` (set on the eight citywide regions only). The correction fades out where LiDAR canopy (cells > 2.5 m above ground, buildings excluded) covers 65–75% or more of the ground within 30 m (`lawns.woods_grid`, `sample_grid`; `05_build_scene.load_lidar_grid`, `woods_for`, `texture_local`). Calibration in `data/README.md`.
- **Tests:** real 200 m fixtures (Wissahickon, Washington Square, Clark Park) plus synthetic grids. On the fixtures' centers, the woods weight averages 0.875 for Wissahickon, 0.019 for Washington Square and 0.022 for Clark Park.
- **Crops:** `lawn_woods_*.jpg` in the session scratchpad. Inside the Wissahickon grid, corrected pixels fall 47% (the golf course stays green). Washington Square and Clark Park are essentially unchanged (−1.3%, −3.9%).

### Bugs found running the regions (each with a test first, except the sheet)
- `05_build_scene.py`: a clipped render tile's frames can form two pieces, so `reach.exterior` crashed (southwest). Fixed with `projection.outline_coords`.
- `18_qa_scan.py`: a needle on an unshaped footprint has an integer id, so `rsplit` crashed (east_riverfront). Fixed with `qa_scan.footprint_id`.
- `10b_scan_invented_water.py`: the contact sheet asked for known-band frames the region never drew (southwest). It now reads only drawn frames. New `--from-redraws` scans the drawings before the repaint and its fix.
- New `scripts/25_join_seams.py` and `regions.owner_edges`: seam ratio per border between regions in the merged layout. On v7 it reproduces the earlier join medians (2.17–2.50).

### Batch A (`scripts/22_run_region.py`, gates on, $15 cap)

| Region | Frames (new) | Gates | GPU | Est. | Invented water repaired / exempt |
|---|---|---|---|---|---|
| west_north | 210 (108) | pass | 38.4 min, ~$2.53 | $2.31 | 15 / 4 |
| germantown | 294 (254) | pass | 51.2 min, ~$3.37 | $3.23 | 26 / 10 |
| southwest | 404 (255) | pass | 70.7 min, ~$4.66 | $4.44 | 15 / 15 |
| east_riverfront | 227 (193) | **stopped: needle** | not drawn | $2.50 | |

- **Spend:** about $10.56 (estimated from server time). Actual cost ran 5–10% above the $0.011-per-frame estimate.
- **east_riverfront's needle:** footprint 478499, 5458 Tacony St: 38 m², 42.1 m, City record 138 ft. It's outside the LiDAR box, so it has a single height. The aerial shows a small round structure, possibly a tank or stack, and is inconclusive (`output/review/needle_478499_5458_tacony_st.jpg`). It awaits review.
- **QA to review:**
  - southwest: "stadium" 8500 Essington Ave is the airport terminal and garage complex, a likely false positive (`output/review/southwest_stadium_8500_essington.jpg`).
  - east_riverfront: three "stadiums" (4101 N Delaware Ave, 3622-40 G St, 3001 E Allegheny Ave).
- **Join seams** (`output/philly/join_seams_v8.json`), medians: west_lidar|southwest 1.84, upper_north|germantown 2.46, west_lidar|west_north 2.60, south|southwest 2.61, upper_north|west_north 2.63, north|west_north 3.44.
  - The worst edge, 8.75 (south|southwest, a rail yard by the Schuylkill), looks continuous at half scale (`output/review/worst_join_south_southwest.jpg`).
- **Invented water (dry run on the raw drawings):** `output/review/batchA_invented_water/contact_sheet.png` (20 largest). No holds were added; the candidates are listed in the report.
- **LiDAR prune:** `--apply` was refused by the permission system (irreversible deletion needs Stephen). A dry run would free 210 tiles (142.8 GB) and keep the 57 that the Batch B regions need.
## 2026-11-02: clean-style retraining stopped; the map keeps the original style

- **v2 retraining:** the first test of a full-quality clean style (Qwen-Image-Edit-2511, 40/24 steps, CFG 4, negative prompt; four settings on six stress frames, ~$1.02; `output/trainset_clean_v2/sweep/`).
  - **Better:** almost no invented cars and crisp outlines.
  - **Worse:** much flatter and simpler than the original. Rowhouse texture is lost, woods turn to empty lawn, colors go cartoonish, and a concrete tower turned glass-blue.
- **Decision (Stephen):** "demonstrably worse … use the original method." Retraining stopped before mass generation.
- **Clean-style spend in total:** ~$14.58 (Phase 1 ~$13.56, v2 sweep ~$1.02).
- **The citywide drawing** continues in the original style (`qe2511_oldcity_r16_v1`, run `qwen_joint_light8_fac`).
- **README licensing note** updated: the Gemini-derived style is disclosed and the decision recorded.
- **Clean-style code kept for reference:**
  - `src/pixelphilly/trainset_clean.py`, `scripts/23_build_clean_trainset.py`;
  - the v2 sweep and palette scripts;
  - `scripts/14_train_lora.py --profile clean`.

## 2026-11-02: clean style v2, steps 1-2 (sweep and palette; waiting for approval)

- **Context:** Stephen called Phase 1's A and B "huge steps back". v2 aims at a look he likes, with no Gemini or old-LoRA anything.
- **Code:** `scripts/25_clean_v2.py` (sweep, palette, palette-compare); `src/pixelphilly/palette.py` with tests first in `tests/test_palette.py` (8).
- **Sweep:** 6 stress frames (the v1 views where prompt-only Qwen invented the most color; one each of rowhouse, tower, woods, port, stadium, industrial) x 4 settings.
  - Settings: full Qwen-Image-Edit-2511, no Lightning, true CFG with a negative prompt (cars, people, text, clutter, noise, photo, 3d render...).
  - Uses the deployed `Editor.run` unchanged; nothing redeployed.
  - GPU: $1.02; 33.6 s per image at 40 steps, 20.3 s at 24.
  - Sheets: `output/trainset_clean_v2/sweep/sheet.jpg` and `detail.jpg`.
- **Result:**
  - Prompt P1 invents far fewer specks than P2 (mostly 0.1-1.3% vs. 1.2-4.5%); P2 turned a rail line into a blue river.
  - 24 steps look like 40.
  - **Problems:** leaf-off woods drawn as empty flat lawn; one roof drawn as a light-blue pool; ground colors shift strongly toward cartoon green.
- **Palette:** k-means k=56 with a fixed seed.
  - **Renders-only palette** (`palette.json`): too drab. Glass goes beige, lawns olive, the canal gray.
  - **Option palette from our own P1 targets** (`palette_targets.json`): keeps the look.
  - Compared in `palette/palette_options.jpg`.
- **Speck removal:** sieve the snapped index image (components of 40 px or less), remove only where the render lacks that color within 5 px, and only blobs at least 3 px thick, so mullions, lane lines and outlines survive.
- **No mass generation yet.** No commits.

## 2026-10-28 (night): clean-style Phase 1, A vs. B (no Gemini)

- **Goal:** replace the Gemini-trained style LoRA. Two candidates were drawn on 8 atlas spots against the old style. No config or doc was switched; the old LoRA is untouched.
- **Candidate A** (`qwen_joint_light8_nolora`): no style LoRA, prompt "Redraw this render as isometric pixel art."
  - `15_joint_sample.py` needed no change for this.
- **New terrain spots:** `atlas_wissahickon_fac`, `atlas_airport_fac`, `atlas_northeast_fac`.
  - Same pattern as the `_fac` spots, plus `"lawn_correct": true`.
  - Data fetched with 01–04k and 04c LiDAR (8 tiles). The airport's footprint query returned HTTP 400 once and worked on retry.
  - All three passed the alignment check, with 0 needles. Northeast had 8 LiDAR single-height fallbacks.
  - **Lawn correction at Wissahickon:** it shifted 13.4M of 31.6M park pixels, so the leaf-off forest floor is tinted green-yellow. The whole valley is parkland.
  - **Northeast:** OPA says 73% twins (post-war, ranch, conventional, bi-level) and 16% singles.
  - Old style and A drawn on all three.
- **Old style repaint:** the 5 facade spots now also have `--invented-water fix` outputs (they had never been repainted), so all variants are compared after the same post-processing.
- **Candidate B training set:**
  - New: `src/pixelphilly/trainset_clean.py`, `scripts/23_build_clean_trainset.py` and `tests/test_trainset_clean.py` (30 tests, written first).
  - **Filters:**
    - registration shift;
    - invented water;
    - flat share on land, 0.26–0.72;
    - invented color (saturated non-green specks) ≤ 1.2%;
    - near-copy: mean difference ≥ 13;
    - no-data gray ≤ 15%;
    - tone outliers;
    - speck median clean-up.
  - **Fixes during the build:**
    - flat share and tone are measured on land only, because the water repaint turned brown rivers blue and tripped both;
    - the no-data check now matches the renderer's exact (128, 128, 128); flat white roofs had been flagged;
    - the seed separator `__s` collided with `__south_lidar` and was replaced by `.seed<N>`;
    - the near-copy rule was added after a contact sheet showed the color filter favoring near-copies.
  - **Result:** 228 pairs kept from 523 tries on 332 views. The manifest is clean of Gemini, `redraw_v3` and old-LoRA references.
- **Training:** `14_train_lora.py --profile clean` (the old run stays the default). Run `qe2511_clean_r16_v1`: rank 16, 2,000 steps, samples every 1,000 on 3 held-out atlas renders. `check_config` passed first: 228 pairs, offline model path.
- **Candidate B drawings:** `qwen_joint_light8_cleanlora` on all 8 spots, plus the repaint fix.
- **Comparison:** `scripts/24_style_compare.py` writes `output/style/compare.html`, `.jpg`, `metrics.json` and `notes.json`.
  - **B v1 is worse than A on every spot:** more invented cars and colored specks (1.0–1.8% vs. 0.2–0.8%) and blockier texture.
  - **A** draws clean geometry but invents cars, confetti, apron planes and lawns on paving.
- **GPU** (`output/gpu_runs.jsonl`):
  - A drawings $0.64
  - old style and A on the new spots $0.77
  - trainset pilot, seed 0 and seed 1: $0.34, $1.68, $1.17
  - training $6.33
  - B drawings $1.07
  - estimated container overhead $1.56
  - **Total ~$13.56** (cap $14).
- **Tests:** full suite 344 pass (`tests/test_trainset_clean.py` 30 of them). No commits.

## 2026-10-28: Phase 2 follow-ups (Stephen's decisions)

- **Retired configs:** `downtown_lidar` and the 18 early atlas configs (`atlas_{franklinfield,30thst,artmuseum,cathedral,linc,cbp,cityhall,indhall,pennslanding}` and their `_lidar` twins).
  - **Where they went:** `config/retired/`, with their LiDAR tile lists in `data/raw/lidar/retired/`. Their outputs stay on disk.
  - **Why:** South Philly's map covers downtown, and the `_fac` atlas spots replace the old ones.
  - **Tests:** the landmark tests now use `atlas_cityhall_fac` (same box).
- **LiDAR pruned:**
  - first pass: 76 tiles, 49.7 GB, blocked by nothing;
  - after retiring: 45 more tiles, 44.4 GB.
  - Raw LiDAR on disk: 164 GB before, now about 65 GB. Deletions are recorded in `data/raw/MANIFEST.json`, with PASDA URLs to re-download.
- **Southwest region:** keeps its east edge at -75.189, covering the 2.4%-city cell at the Schuylkill mouth (~$0.60).
- **QA exceptions:**
  - added `s1762-0`, a truss portal on the elevated Walt Whitman Bridge approach (46 m, 7 m²), checked on the 2024 aerial;
  - the crane note `s1459-0` was corrected (it hadn't been in the CHANGELOG): a Delaware terminal bulk-unloading crane, 41 m, checked on the aerial Oct. 27.
- **Tests:** 340 pass.

## 2026-10-28: Phase 2 infrastructure for citywide runs (no GPU, no commits)

Test-first throughout; 336 tests pass (254 before). No GPU spend. Downloads: the city-limits polygon only.

### Clipping to the city line
- **New:** `scripts/04l_fetch_city_limits.py` fetches City `City_Limits/FeatureServer/0` (one polygon, Planning and Development) to `data/raw/city_limits.geojson`, recorded in the manifest.
- **`"clip_to_city": true`:** `projection.area_setup` passes bbox ∩ city to `frame_lattice(ground=...)`, which keeps only frames that intersect that ground swept up to `max_height_m` (`swept_screen_polygon`: the outline, the outline lifted, and each edge's quad, which is exact for a concave outline where a convex hull isn't). The rectangle and frame indices still come from the bbox.
- **Fetch extents:** `projection.is_clipped` now decides polygon fetches in `sources.fetch_area_features`, `03_fetch_imagery.py`, `nodata.py` and `05_build_scene.py`. `render_ground_polygon` follows the kept frames.
- **Tests:** `tests/test_city_clip.py`, 15 tests on synthetic polygons: whole bbox = plain clipping, triangle and two-piece grounds, height sweep, missing file, re-read on change, and the four existing regions' frame counts pinned.
- **Unchanged without the flag:** Old City scene rebuilt, SHA-256 `eaca18728d36a5de80ccb29fdc1e6b776be4d522434faa787cdd9a89802eaac4`. Frame lists, extents and ground polygons are identical for every existing config, including `south_lidar` (672 frames).

### LiDAR pruning
- **New:** `scripts/04m_prune_lidar.py` and `src/pixelphilly/lidar_tiles.py`. It's a dry run unless given `--apply`.
- **Rule:** a tile is deleted only when every area listing it is a LiDAR config with a grid holding `struct`, which is what `05_build_scene.py` needs to skip the LAS files. Tiles that LiDAR configs not yet fetched will need, by the PASDA index, are kept.
- **Records:** each deletion goes in `MANIFEST.json`: path, bytes, `deleted_at`, re-download URL, and the grids that replaced it.
- **04c changes:** `04c_fetch_lidar.py` now shares the tile selection, verified identical on six areas' saved lists, and skips downloading when the area's grid is cached.
- **Tests:** `tests/test_lidar_prune.py`, 12 tests.
- **Dry run today:** 196 tiles on disk (164.3 GB). It would delete 76 tiles (49.7 GB) and keep 120 (114.6 GB):
  - 54 are held by `downtown_lidar`, whose Oct. 22 grid predates `struct` (a tile can have several blockers);
  - 75 (70.3 GB) are needed by the new regions;
  - the rest by old atlas tile lists and `atlas_wissahickon_fac`.
  - Before the region configs existed, the same run found 132 tiles (100.3 GB).
  - 45 tiles (44.4 GB) are held only by `downtown_lidar` and the old atlas lists. Not applied.

### Region runner
- **New:** `scripts/22_run_region.py <area>` with `src/pixelphilly/region_runner.py`.
- **What it runs:** every fetch, build and check, then the stop gates, the detached GPU draw with known areas, the collect loop, the repaint with `--invented-water fix`, the 10b dry-run report and `output/<area>/region_report.json`.
- **Resumable:** steps are skipped by output freshness; the GPU launch is never repeated.
- **Gates:** alignment (the 09 rule, moved into `qa.alignment_failed`; same verdicts on all 1,354 existing report rows), needles vs. `config/qa_exceptions.json` (new: the 905-11 Walnut piece and crane `s1459-0`), facade match ≥ 0.95, and frames × $0.011 ≤ `--budget-usd`.
- **Tests:** `tests/test_region_runner.py`, 29 tests with a fake executor.
- **Checked against real data:**
  - `--plan` on `west_lidar` finds every step through the repaint already done.
  - Gates on the four drawn regions: North, Upper North and West pass. South stops on `s1762-0` (46.2 m, 7 m², near the Packer Ave terminal), which isn't reviewed yet.

### Regions
- **Configs:** eight new region configs, copied from `west_lidar` plus `"clip_to_city": true`.
- **Pre-flight:** `scripts/23_preflight_regions.py` with `src/pixelphilly/coverage.py` (4 tests). Table in the README.
- **Box changes:** from the first proposal, to close gaps found by the coverage check:
  - `lower_northeast` east to -74.970 (7.5 km² of Holmesburg–Torresdale riverfront was uncovered);
  - `west_north` south to 39.963 and west to -75.285 (the Cobbs Creek strip, 1.8 km²);
  - `east_riverfront` to -75.045 and 39.960;
  - `southwest` to -75.285, 39.865 and -75.189 (Schuylkill mouth);
  - `germantown` north to 40.082;
  - `northwest` to -75.245 and -75.170;
  - `roxborough` west to -75.270.
- **Result:**
  - Coverage: 0 uncovered cells out of 3,091.
  - Size: 2,934 run frames (2,052 new), about $32 at $0.011 per run frame, about 8.3 GPU hours.
  - LiDAR: 446 tiles to fetch, about 374 GB.
  - No region exceeds 700 new frames (largest: `upper_northeast`, 544 new, 697 in the run).

## 2026-10-27 (later): turf field and City Hall courtyard fixed (philly v7)

- **Turf field fill** (South Philly; it had come out gray-teal).
  - **Cause:** the "drawn green" band (hue 70–170, saturation 0.15) accepted a teal-gray pixel from the blob's edge.
  - **Fix:** the band is now hue 75–140, saturation ≥ 0.25, value 0.30–0.85. When the ring around a blob has no lawn, the fill uses the window's drawn lawn color.
  - **Test first:** `test_turf_fill_uses_a_real_lawn_green`.
  - **Result:** the field is now green, with its markings kept.
- **Invented lawn in City Hall's paved courtyard** (`invented_water.courtyard_lawn`, applied in the same `--invented-water fix` pass).
  - **First version:** open ground enclosed by buildings. It flagged 207 rowhouse block interiors, real backyards drawn green (dormant brown in the March aerial). Rejected.
  - **Rule now:** a courtyard is open ground overlapping a hole in ONE building's City footprint. It's flagged only where the aerial there is paving (saturation < 0.18). Then every greenish pixel within 25 m of the hole is repainted with the surrounding non-green paving color.
  - **Tests first:** the courtyard is found; a green or dormant-grass courtyard is left alone; a rowhouse block interior is not a courtyard; the whole patch is repaired, shaded grass included; a park across the street from a courtyard open to it stays green.
  - **Citywide dry run:** exactly one flag, the City Hall courtyard (7,036 px), now dark paving matching the aerial.
- **Map:** `philly` v7. Tests: 254 pass. No GPU cost, no commits.

## 2026-10-27: four regions redrawn with facades (philly v5), invented water fixed (philly v6)

- **Redraw:** all four regions redrawn with property-record facades, the evidence-based glass rule, OSM colors and the dormant-lawn correction (run `qwen_joint_light8_fac`).
  - **Order:** South first, then North (known South), then Upper North (known North) and West (known South + North) in parallel.
  - **GPU, ~$15.19:** South $7.42, North $2.96, Upper North $2.93, West $1.88.
  - **Merged map:** `philly` v5.
- **v4 → v5:**
  - **Improved:**
    - the Liberty Place and Market St towers are now blue glass;
    - Independence Hall's tower reads as brick with a white steeple;
    - parks are green instead of dormant brown;
    - rowhouse fronts are crisper.
  - **New problem:** the AI drew green grass in City Hall's shadowed courtyard, where v4 had invented a pool. The courtyard isn't in any park polygon, so the lawn fix didn't cause it.
- **Invented-water fix:** `10_repaint_water.py --invented-water fix`.
  - **Hold list:** reviewed blobs that can't be confirmed as invented are left as drawn and logged as "held" (`config/invented_water_holds.json`, `invented_water.apply_holds`, test first). Held:
    - the lower South Philly basins and mudflats (wet mud in the aerial, not in NWI);
    - a vegetated channel area and an olive mud patch in South Philly;
    - a sports court that is blue in the aerial;
    - an Upper North light-blue roof (building missing from the scene);
    - a pale West Philly basin.
  - **Repaired:** South 31, North 10, Upper North 10, West 11. Held: 15, 1, 1, 1.
  - **Spot checks:**
    - railroad cuts drawn as canals are now ground;
    - a West lot's blue patch blends in;
    - the held mudflats are unchanged;
    - the turf field drawn as a pool is now flat gray-teal: better, but not field green.
  - **Map:** `philly` v6, 12,186 tiles, 1.75 GB plus a 346 MB photo layer.
- **Tests:** 249 pass. No commits.

## 2026-10-26: landmark references in the joint sampler (Track 3, test only)

### Built
- `src/pixelphilly/landmarks.py`, tested in `tests/test_landmarks.py`:
  - Approved landmarks (status "ok", the primary photo; a hand-checked `coord_override` beats Wikidata's coordinate) are projected to canvas pixels.
  - Each point is lifted to half the height of its building: the tallest LiDAR part sharing the footprint id of the nearest scene footprint. That gives City Hall 166 m (its tower), where a plain 30 m radius gave 49 m.
  - Each landmark gets one window per grid: the window containing it whose center is nearest. Conflicts are assigned greedily. Without one window per grid, a landmark would see its reference on only half the steps.
  - Also new: a safety check (`check_frame`, experiment A's rule).
- `AreaSampler.joint_volume` gained an optional `landmarks` argument. Flagged windows are conditioned as a 2-image edit: [reference, render crop], with img_shapes [output, reference, render], as QwenImageEditPlusPipeline does. Reference encodings are cached once per landmark. All other windows, and the call without `landmarks`, are unchanged.
- `check_env` gained `_landmark_window_smoke`, which checks the token layout on a CPU. Deployed Oct. 26 with no tasks running.
- `scripts/15_joint_sample.py`:
  - `--landmarks` and `--landmark-baseline` (off by default) upload the reference photos and pass the window map.
  - call.json and result.json record the landmarks, windows, credits and timing.
  - On `--collect`, each landmark's frame is checked; a rejected frame is replaced by the baseline drawing and kept in `joint/<run>/rejected/`.
- `scripts/21_landmark_joint_compare.py`: `output/landmarks/joint_compare.jpg` and `.json`, including frame-border seam ratios.
- `data/landmarks/manifest.json`: Fairmount Water Works got `coord_override` from AIS. Its Wikidata point sits on the art museum, 56 m from the museum's own point. Script 19 now preserves `excluded_reason` and `coord_override`.

### Test run (qwen_joint_light8_landmarks; settings identical to qwen_joint_light8)
- Four atlas spots (City Hall, art museum, 30th St, Independence Hall): 17 landmarks in 32 windows. GPU ~$0.61 (4 x 124–147 s).
- Cost: a reference window takes 0.88–0.90 s per predict against 0.55 s plain (+61%). A reference adds ~4,000–4,200 tokens, about one more render crop. Peak memory is unchanged at 66.8 GB.
- Automatic check: 16 of 17 accepted; Eastern State was rejected (photo pasted in, central shift (54, 178)) and fell back.
- By eye: 1 better (Union League), 2 slightly better (the Comcast towers' glass), 6 unchanged, 1 minor artifact and 7 harmful, 6 of which the check accepted:
  - PSFS's "SFS" sign floats in its frame and in the Convention Center's
  - photo-like patches are pasted into PAFA, Merchants' Exchange and the Water Works river
  - Christ Church's window restyles a neighbor
- Frame-border seam ratios shift by −0.17 to +0.23; the Eastern State fallback frame rose 1.29 to 1.52.
- Conclusion: not safe to turn on. Experiment A's rule catches whole-frame photo copies but not local pastes or sign leakage.

## 2026-10-25: landmark references and experiment A (Track 3)

### Built
- `scripts/19_landmark_refs.py` and `data/landmarks/manifest.json`. The manifest covers 40 landmarks inside the mapped regions, with 102 reference photos:
  - 18 from LoC HABS/HAER (public domain)
  - 84 from Wikimedia Commons: 46 public domain, 11 CC0, 27 CC BY 2.0–4.0
  - no CC BY-SA. The license filter rejects it along with "No restrictions" and every other license.
  - Coordinates are from Wikidata P625. Where there is a street address they are checked against AIS: median gap ~40 m, max 225 m (the Convention Center, which covers several blocks).
  - Cathedral Basilica, Liberty Place and Old St. Joseph's have no acceptable photo; every candidate is CC BY-SA.
  - Photo choice is a keyword heuristic, and several picks are off-subject (paintings and documents in museum categories, game-day photos). Only the 4 photos used in experiment A are marked `reviewed`. The script keeps hand-set `reviewed` flags across rebuilds.
- `Editor.run` (`gpu/modal_app.py`): optional `style` and `references` job fields. References go before the render (`image=[*refs, render]`) because diffusers sizes the output from the last image. With neither field set, the call is identical to before. The result only gains `n_references` when references were used. `check_env` gained `_multi_image_smoke`, which confirms the pipeline still labels images "Picture N". It ran green on Modal. Deployed Oct. 25; no tasks were running on the app. Calls already in flight keep the container image they started with, so a deploy doesn't disturb them.
- `scripts/20_landmark_experiment_a.py`: experiment A, its scores, accept/reject rule and comparison sheet.

### Reference review (Oct. 25)
- Every candidate photo was checked by eye. Each one now carries `reviewed`, `pick` (primary, backup or null) and a `review_note`, and each landmark carries a `status` (ok, weak or needs_ref). Rerunning the script keeps all of these, along with references added during review and hand-fixed authors (`author_checked`).
- Result: 31 landmarks have a good primary photo and 5 have a weak one (Franklin Institute and Wanamaker's are postcards; Cathedral Basilica shows the dome only; Academy of Natural Sciences shows the entrance bay only; Citizens Bank Park is a distant strip). 4 have none: Reading Terminal, Navy Yard, Penn Museum, Old St. Joseph's.
- 9 photos were added from Commons searches, at most 2 searches per landmark and under the same license rule.
- Fixed attribution on two picks whose Commons Artist field was empty: the PMA photo (PD-self, Rgordon6) and the Union League photo (Beyond My Ken; we use the CC BY 2.5 option of its triple license).
- Outputs: `output/landmarks/picks.jpg` and `output/landmarks/picks.md`.

### Experiment A
- Inputs: City Hall and the art museum, as 1,024 px atlas crops. Settings: seed 0, style LoRA `qe2511_oldcity_r16_v1`, Lightning 8. Each landmark got 1 no-reference output and 2 references x 2 prompts.
- GPU: 137 s on an H100, ~$0.15 estimated. Weight load took 37 s, and each image took 5–8 s at a 64.3 GB peak.
- Accepted 8 of 10. The two rejects are prompt p2 with the first reference, where both landmarks were replaced by a restyled copy of the photo. The whole-frame registration shift caught only one of them (City Hall: −459, −165). The art museum's read (0, −1) because the bottom of the frame kept the render. The center shift and edge correlation caught both.
- See the README section for what improved.

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

## 2026-10-24 (overnight): Upper North and West Philly, merged map philly v4

Stephen authorized an unattended run: Upper North, then West Philly, with a $15 GPU cap, a stop on anything troubling and no commits. **Spent: ~$4.92** (two join tests $0.27, Upper North $2.80, West $1.85).

### Built
- **Multiple neighbors** (subagent, tests first), so West could be held against South and North at once:
  - `--known-area a,b` in precedence order;
  - known pixels taken from the merged map's own sources, including water-band overrides (`regions.cell_sources`, `known_sources`);
  - per-owner `water_band/<owner>/` re-repaints;
  - ripples placed in the root area's (South's) coordinates through the chain (`ripple_root`);
  - unions of N areas in `16_build_tiles.py`;
  - `15_joint_sample.py --plan-only`.
  - 118 tests pass.

### Upper North (`config/upper_north_lidar.json`, Allegheny Ave to ~Wingohocking St)
- **Size:** 235 frames, 200 new and 35 held from North. 36 new LiDAR tiles.
- **Build:** 28 min, 4.75 GB. 40,344 footprints shaped. 740 structures, the largest checked on the aerial (all real: a hospital-scale building, a school, industrial buildings and a garage missing from the footprint layer, one construction site, a trailer row).
- **Checks:** no needles, no stadiums. Alignment PASS (tolerant IoU min 0.9998).
- **Join test:** 2.05–2.41. Full drawing 42.5 min, ~$2.80.

### West Philly (`config/west_lidar.json`, 40th St to Cobbs Creek, Baltimore Ave to Girard Ave)
- **Size:** 158 frames, 132 new; held: 24 from South, 2 from North (plus 3 South cells re-repainted by North). 20 new LiDAR tiles.
- **Build:** 22 min, 4.3 GB. 43,948 footprints shaped. 702 structures, the largest checked on the aerial.
  - All are real buildings. Most sit just past the city line in Upper Darby, where the City has no footprints, so LiDAR structures stand in for them up to where City imagery ends (past that, no-imagery clearing applies, as on the New Jersey side).
- **Checks:** alignment PASS. Join test 2.02–2.36, plus one 4.42 edge that wasn't visible at 1/3 scale.
- **Drawing:** 28.1 min, ~$1.85.

### Merged map `philly` v4 (`?area=philly&v=v4`; v3 = without West)
- **Size:** 1,202 cells (South 672, North 198, Upper North 200, West 132). 12,186 tiles, 1.7 GB plus the 289 MB photo layer.
- **Search:** "3601 Market St", "4000 N Broad St", "1020 Pattison Ave" and "5200 Market St" all map inside.
- **Seam ratios by edge type** (frame edges; 1.0 = invisible):

| Edges | Count | Median | p90 | Max |
|---|---|---|---|---|
| Inside each region | 233–1,100 | 0.99–1.01 | 1.17–1.27 | |
| South / North | 28 | 2.27 | | 4.23 |
| North / Upper North | 28 | 2.45 | 4.62 | 5.90 |
| South / West | 14 | 2.30 | | 4.60 |
| North / West | 3 | | | 6.94 (corner, see below) |

  - **Worst joins**, all land on large flat surfaces: a grass-texture change across a ball field, faint lines through parking lots.
  - **The most visible (6.94):** at the North/West corner in a park, a pool is drawn dark navy on one side and light blue on the other.
  - All are recorded in the README "Open issues" table.

### Storage
- LiDAR on disk is now 153 GB (git-ignored). The cached height grids would allow deleting the raw LAS files for finished regions.

## 2026-10-24: North Philly, the first region drawn next to an existing one (philly v2)

Stephen chose North Philly next, built with region machinery so the city can grow past one canvas (~1,300 frames, the 4-hour GPU cap).

### Built
- **Shared projection.** `"projection_origin"` in configs (`projection.local_frame`). Test first: the same lon/lat lands on the same screen pixel in both areas, and frames sit on one 1,024 px lattice.
- **Known-band conditioning.**
  - `joint_denoise(..., known=(x0_known, mask), start=...)`: RePaint in flow-matching form. CPU tests check exact reproduction of known cells, unchanged output with no band, and the repair invariants.
  - `AreaSampler.joint_volume(..., known_frames, repair_width_px, repair_sigma)` VAE-encodes the neighbor's drawn frames. `15_joint_sample.py` adds `--known-area`, `--only-near-known` (boundary test), `--repair-*` and `--known-ramp`.
  - `regions.py` holds the mask, union and placement helpers.
- **Join tests on a 3 × 3-frame patch at Broad St** (~$0.12–0.16 each; seam ratio across the join, 1.0 = invisible):

| Variant | Join | Inside the region | Notes |
|---|---|---|---|
| Ramped mask (8 cells) | 6.4–8.3 | ~1.0–1.6 | Latent blending made an olive smear: rejected |
| Hard mask | 2.0–2.8 | | |
| Hard mask + repair (σ 0.64, 200 px) | 1.6–2.5 | | Straddling roof reconciled. Chosen |
| Repair σ 0.83, 300 px | 1.55–2.8 | | No better |

  - An image-space crossfade measured 0.12, but only by blurring the join. Rejected for pixel art.
- **Rail mask (`04e_fetch_rail.py`):** SEPTA Highspeed Lines route L (the El, 8 m buffer) and City Railroad Lines fcode 1700 (5 m), researched first. Test first (`test_rail_mask_buffers_the_el_and_surface_track`).
- **Alignment check:** now judged on a 1 px tolerant IoU (`tolerant_iou`, test first).
  - **Why:** North's dense rowhouse frames scored raw IoU 0.966 with zero shift. The cause is the Python rasterizer drawing each vertical wall 1 px wider than WebGL.
  - A real 4 px offset still fails. Raw IoU stays in the report.
- **Structures, vegetation false positives** (found in North's QA scan, checked on the aerial).
  - **Cause:** cemetery trees, a roadside tree line and a ring of trees around a field passed the roughness test, because only flat cells become candidates.
  - **Fix:** a solidity floor of 0.6 (trees 0.32–0.52, real objects 0.70–0.99). Five real-data fixtures; subagent.
  - **Cost:** some lacy real clusters (a shed, container groups) now stay flat, as before structures existed.
- **Water repaint for region runs (bugs found running North).**
  - **Crash:** it expected drawings for the 41 band frames. It now writes only drawn frames, reads South's finished frames as halo context and uses South's ripple coordinates.
  - **Dark line at the join:** a hard dark line in the Schuylkill at the join (seam 7.61). South's repaint had drawn a shore band along its old lattice edge.
  - **Fix:** South's band frames are re-repainted with North as context (`water_band/`). Changes are confined to water: 2,096 px in one frame.
- **Merged maps:** `16_build_tiles.py --areas ... --name philly` builds the union pyramid with band overrides. The fit stays at 1.4e-6 px over the union, and the viewer is unchanged.

### North Philly
- **Area:** bbox [-75.205, 39.975, -75.125, 40.005]. 239 lattice frames: 198 new, 41 band.
- **Data:** 71,986 footprints, 41 LiDAR tiles (27 new).
  - The USGS NHD service stalled. The NHD and LiDAR downloads were restarted in parallel (NHD with 12 one-minute retries).
- **Build:** 27 min, 3.8 GB.
  - 57,969 footprints shaped.
  - 612 structures kept after the vegetation fix. The largest are East Park Reservoir's covered tanks and buildings missing from the footprint layer.
  - No needles, no stadiums.
- **Alignment:** PASS (tolerant IoU).
- **Drawing:** 44.8 min, ~$2.95. Region total including boundary tests ~$3.48.
- **Merged map `philly` v2:** 870 cells (South 672, North 198), 9,290 tiles, 1,164 MB plus a 195 MB photo layer. v1 has the water line and is not used.
- **Join seams on v2:**

| Edges | Median | p90 | Max |
|---|---|---|---|
| Join, 28 edges | 2.36 | 2.99 | 4.31 |
| Inside North | 1.02 | 1.29 | 2.22 |
| Inside South near the join | 1.02 | 1.23 | 1.73 |

  - The worst remaining join edges are all land, where the regions drew straddling content slightly differently: a grass-texture change in the park and a faint line through a parking lot. Invisible at browsing zoom; in the README "Open issues".
- **Tests:** 113 pass. Old City byte-identical.

## 2026-10-23 (night): LiDAR structures (ships, containers) with a highway mask and photo check

Stephen flagged ships and cranes at the Navy Yard and port. Neither is in the footprint layer, so they were flat aerial texture.

### Built (tests first; subagent)
- **`dsm_from_las(..., with_struct=True)`:** a class-1-only surface grid (bridge class 17, water, ground and noise excluded). Caches without it are regridded.
- **`lidar.structures()`:** flat LiDAR objects with no footprint.
  - Rules: 2.5–90 m tall, outside footprints by 1.5 m, ≥ 60 m², median 3×3 roughness < 0.3.
  - Roughness measured: containers 0.02, ship 0.03, roofs 0.06, tree canopy 1.4–1.9.
  - Each region is shaped with the existing stepped parts. Ids are `s<region>-<part>`.
  - Walls take the object's aerial color ×0.85, with no brick tint.
  - Ships are protected from the water repaint automatically (its mask comes from rendered silhouettes).
- **Highway mask.**
  - **Why:** the vendor labeled most of I-95's deck class 1, not bridge class 17 (one ramp: 186,515 vs. 12 points), so the viaducts came through as structures.
  - **Fix:** a new `scripts/04d_fetch_highways.py` fetches City `Street_Centerline` with `CLASS` 1 (expressway), 9 and 10 (ramps). Buffers are 14 m for mainlines and 7 m for ramps.
  - `fetch_features` gained a `where` parameter (default unchanged).
  - North Philly will also need a rail layer for the El.
- **2022 LiDAR vs. 2024 photo check (`photo_agrees`).**
  - A structure is dropped when ≥ 50% of its pixels match the ground ring around it (within 25 RGB levels), or over water when ≥ 90% are one color.
  - Calibrated on real regions:

| Region | Same as ring | Result |
|---|---|---|
| Carrier | 0.03 | kept |
| Ship gone by 2024 | 0.97 | dropped |
| Containers | 0.18–0.29 | kept |
| Empty pavement | 0.63–1.00 | dropped |

  - Known miss: a plain roof matching the pavement around it is dropped (one small Navy Yard building without a footprint).
- **ArcGIS count query:** it now retries error bodies (`query_json`; failed twice Oct. 23). Test first, separate subagent.
- **QA scan:** reports the structure count and the 20 largest.

### Atlas test (`output/atlas/structures_compare.jpg`)
- **Spots:** `atlas_navyyard_lidar`, `atlas_packer_lidar`, `atlas_i95_lidar`, plus `atlas_indhall_lidar` as the tree regression. All four PASS alignment. GPU ~$0.54.
- **Navy Yard:**
  - The mothballed carrier (19 m, 15,381 m²) and two pier ships are 3D hulls.
  - The ship gone by 2024 is dropped.
  - The drawing model draws the carrier as a gray multistory building with windows, so it has volume but doesn't read as a ship.
- **Packer Ave terminal:**
  - The I-76 viaduct is masked, and empty 2022 container spots are dropped.
  - Container blocks keep their colors, but the change from v1 is modest.
- **I-95:** no viaduct walls. The kept structures are rows of parked trailers, which are in the 2024 photo.
- **Washington Square:** no structures.
- **Missing footprint:** a 79 m building near Independence Hall with no City footprint is now drawn.
- **Cranes:** still not addressed (their lattice booms are too sparse).
- **Tests:** 80 pass. Old City byte-identical.
- **Not yet applied** to downtown_lidar or south_lidar.

## 2026-10-23 (evening): downtown + South Philly, one canvas (south_lidar v1)

Stephen chose South Philly and the stadiums as the next ring, drawn with downtown as one combined canvas so there's no seam, and including the Navy Yard.

### Pre-flight
- **Area:** bbox [-75.205, 39.880, -75.125, 39.975], ~72 km².
- **Frames:** 672 (plan limit 900). 58 render tiles.
- **Viewer lon/lat fit:** max error 8.6e-7 px, so the cubic still holds.
- **LiDAR:** 113 tiles (60 on disk, 53 new).

### Data
- 115,885 footprints, 53,072 trees, 124 PWD and 26 NHD water polygons, 26,215 z19 imagery tiles (13,426 new). Fetched Oct. 23.
- The PWD fetch failed once with `KeyError: 'count'`: the count query returned an ArcGIS error body, and that path doesn't use the error-body retry. It succeeded on rerun. The count query should get the same retry (to do).
- LiDAR on disk is now 85 GB.

### Build and checks
- **Scene build:** 69 min, 3.9 GB peak RAM (less than the 9–10 GB estimate). 104,846 footprints shaped into 232,853 parts; 1,107 single-height fallbacks. Grid cache 1.46 GB.
- **Alignment:** 472 of 476 checked frames pass. The four exceptions (`frame_11_16`, `frame_31_23`, `frame_30_24`, `frame_35_15`; IoU 0.944–0.965) all have zero shift.
  - Their diff images show 210–790 mismatched pixels, all one-pixel fringes on rows of small structures (port and Navy Yard).
  - Reviewed and accepted. Downtown's earlier `frame_09_18` exception doesn't recur, because the lattice differs.
- **New QA gate:** `scripts/18_qa_scan.py` (`src/pixelphilly/qa_scan.py`, test-first in `tests/test_qa_scan.py`), plus a `lidar_stadiums` QA key in `05_build_scene.py`.
  - Stadiums: exactly the Linc, Citizens Bank Park and Franklin Field. The Wells Fargo Center (roofed) correctly does not pass.
  - Needles: only the known 905-11 Walnut St piece.

### Drawing
- **Time and cost:** 119.6 min on one H100, ~$7.87. 2,594 windows, 69.3 GB peak.
- **Seams:** median 1.009, 95th pct 1.38 (1,100 frame-border segments). Downtown v4 was 1.003 / 1.43.
- **Tiles:** v1 is 6,535 tiles (854 MB) plus the 141 MB photo layer. Viewer: `?area=south_lidar&v=v1`.
- **Spot checks:**
  - The Linc and CBP: open bowls with tiered seating.
  - The Wells Fargo Center: a roofed arena.
  - The Navy Yard: Central Green and offices.
  - The Packer Ave terminal: car lots.
  - East Passyunk and Italian Market rowhouse grids: clean.
  - City Hall: tower and William Penn.
  - The refinery-edge water was checked against the 2024 aerial; the basins and causeway are real.
- **Address search:** "1020 Pattison Ave", "1 Citizens Bank Way" and "1400 John F Kennedy Blvd" map inside the canvas through the viewer fit.
- **Tests:** 71 pass. Old City byte-identical.

### Known issues carried forward
- **New (Stephen): ships and cranes at the Navy Yard look unusual.** Neither is in the footprint layer.
  - Ships are flat aerial texture on the water, partly painted over by the water repaint.
  - Cranes are flat smears with their shadows.
  - Containers at the Packer Ave terminal extrude as brick-tinted buildings.
  - Now in the README's "Open issues" table.
- Construction sites.
- Stadium outer walls drawn with windows.
- Franklin Field's lower deck under the overhang.
- The CBP scoreboard cap.
- The Walnut St piece.

**Spend:** south_lidar ~$7.87.

## 2026-10-23 (afternoon): Penn's Quadrangle regression fixed, downtown_lidar v4

- **Bug:** in v3, Penn's Quadrangle (490261, 3600 Spruce St) passed the "wraps a field" test (its lawns are over 5,000 m²). Two pitched-roof strips were colored as seat risers, and its brick east wing drew gray and striped.
- **Test first:** a real-data fixture, `tests/fixtures/penn_quad_grid.npz`. `test_penn_quad_is_not_a_stadium_but_franklin_field_is` failed first.
- **Fix:** `stand_terraces` requires both a wrapped field and at least `MIN_STAND_ROWS` seating rows.
  - The subagent set it to 10. That still caught the Rivers Casino garage (1001-99 N Delaware Ave, 12 low split-level decks, confirmed on the 2024 aerial) and the Art Museum's stepped wings (12).
  - Raised to 20. The three stadiums have 30–42 rows.
  - Downtown now has 30 seating-row parts, all at Franklin Field.
- **Checks:** 67 tests pass, and Old City is byte-identical.
- **Atlas:** the Linc, Citizens Bank Park and Art Museum were re-rendered and redrawn (~$0.39), since their scenes had changed with the base and part-cap fixes. Sheet notes updated.
- **downtown_lidar v4:**
  - **Drawing:** 50.9 min, ~$3.35.
  - **Seams:** median 1.003, 95th pct 1.43.
  - **Alignment and needle scan:** unchanged (only the reviewed `frame_09_18` and the 905-11 Walnut piece).
  - **Spot checks:** the Quad is brick again, Franklin Field keeps its gray seating rows, and the casino is unchanged.
  - **Viewer:** `?area=downtown_lidar&v=v4`. v1–v3 are kept and not used.
- **Spend:** downtown_lidar total ~$13.64 (four full drawings). Atlas total ~$5.32.

## 2026-10-23 (later): Franklin Field stands, stadium base, downtown_lidar v3

Stephen: Franklin Field is open-air with two cascading decks, and the drawing showed a flat-roofed building. Tests first for each fix, then the fix (subagent), then verification.

### Causes and fixes (`src/pixelphilly/lidar.py`, `scripts/05_build_scene.py`)
- **Wrong base.**
  - **Cause:** the base came from ground in a ring outside the footprint. At Franklin Field the ring dips into the rail cut (base 7.0 m vs. the field at 11.7 m), so every part sat 4.7 m high and the field was a 4.7 m slab.
  - **Fix:** footprints with ≥ 500 m² of their own ground returns use the median of that ground, clamped between the ring's 10th percentile and its median. Interior ground can only lift a base that dipped into a cut, never above the street.
  - **Side effects:**
    - **Cira Centre:** now 133.0 m, matching its published 437 ft. It was ~5 m too tall.
    - **2301 Market:** now 130.7 m (City record 124.7–127.8 m). It was ~7.6 m higher.
    - **Citizens Bank Park:** the sunken field set its old base, which is now street level, and the tallest element (likely the scoreboard) is capped at 50.5 m instead of 71 m.
- **Seating rows merged.**
  - **Cause:** the 60-part cap coarsened Franklin Field's tiers until the upper deck's 15–19 m rows vanished.
  - **Fix:** the cap is now `max(60, built area / 100 m²)`.
- **Seat risers drew as brick.**
  - **Cause:** the 2 m faces between rows got the brick wall tint.
  - **Fix:**
    - `terrace_parts` marks mid-cascade strips (< 8 m wide, a same-building part 1–4 m above and another 1–4 m below).
    - Their walls take the seats' aerial color instead of the tint.
    - Applied only to footprints that wrap ≥ 5,000 m² of open area (`encloses_field`). Without that gate, pitched roofs on 163 ordinary buildings matched.
- **Tests:** a real-data fixture, `tests/fixtures/franklinfield_grid.npz`. 66 pass. Old City byte-identical.

### Option 2 (inferring the hidden lower deck) not done
- Aerial LiDAR can't see under the upper deck. The lower deck shows only as its exposed front rows.
- Inferring it needs raised parts in the renderer and would be geometry not in the data. Stephen chose to ship option 1 first.

### downtown_lidar v3
- **Rebuild:** 146,534 parts (63 seating-row parts). Alignment unchanged: only the reviewed edge-rounding frame `frame_09_18`. Needle scan: only the 905-11 Walnut piece.
- **Drawing:** 51.1 min, ~$3.36. Tiles `v3`.
- **Seams:** median 1.006, 95th pct 1.39 (525 frame-border segments).
- **Franklin Field:** the north stand now draws as gray stepped seating rows instead of a brick building.
- **Regression found: Penn's Quadrangle (3600 Spruce St).**
  - It wraps lawns over 5,000 m², so it passed `encloses_field`.
  - Its pitched-roof strips were marked as seating rows, and its long east wing lost its brick color (gray with vertical stripes).
  - Other footprints passing the field test downtown: the Art Museum, 1600 Warfield St, 1001-99 N Delaware Ave, and three Penn's Landing/Columbus Blvd footprints.
  - Not yet fixed.
- **Spend:** downtown_lidar total ~$10.29 (three full drawings). Franklin Field atlas tests ~$0.30.

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
- **Cause:** the city's 2024 aerial imagery ends a block or two inland in Camden. Those 350 z19 tiles return HTTP 404 and were filled with flat gray in the ground mosaic. Given a featureless input, the model invented a scene, the same failure as invented water on land.
- **Test first:** `tests/test_nodata.py` failed on the v1 output.
- **Fix** (`src/pixelphilly/nodata.py`, applied in `10_repaint_water.py` after the water repaint):
  - Pixels where the source imagery is missing, plus a 16 px margin, are set to the map background (204, 214, 227).
  - The missing area is computed from the no-coverage tile list (exact), not from gray pixels, which real roofs can also be.
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

## 2026-10-25: Property-record façades (track 1)

- **Data:** `scripts/04f_fetch_opa.py` fetches OPA property records (`opa_properties_public`, Carto SQL) with explicit columns, and `pwd_parcels` (parcelid, brt_id only). `src/pixelphilly/opa.py` refuses owner, mailing, sale, tax and exemption fields and `exterior_condition`, in the query and again on the downloaded file (tested). Editorial rule: condition and vacancy are never encoded.
- **Join and spec** (`src/pixelphilly/facades.py`): parcel key, then address (condo majority), then point in footprint. Each footprint gets a style (row_porch, row_typical, twin, mixed_storefront, warehouse, office_tower, …), material, stories, floor height, wall and window colors (a fixed palette per material with a small per-building variation) and bands (storefront, porch, cornice, glass). Unit-tested on real OPA strings.
- **Scene:** opt-in per config (`"facades": "opa"`); LiDAR parts inherit their building's façade; unmatched footprints and structures keep plain walls. Without the option scenes are byte-identical (Old City SHA and `atlas_indhall_lidar` unchanged).
- **Renderer:** a procedural wall shader (`render/render.js`, `onBeforeCompile`): window grid per floor and bay, glass storefront, porch roof band, cornice, curtain wall. No textures or UVs; masks unaffected. Headless tests: windows on walls, not roofs; identical output to the previous renderer without façade data.
- **Atlas spots** (`atlas_*_fac`): East Passyunk, an Allegheny West porch-front block, a West Philadelphia twin block, plus façade copies of Independence Hall and City Hall. Join match 98.0–99.9%, mostly by parcel. Alignment PASS, QA scan clean. Known limit: "MASONRY" covers limestone and terra cotta, so pale downtown towers render as brick (track 2, OSM colors, targets this).

## 2026-10-26: Invented water and dormant lawns (review before enabling)

- **Invented water** (`src/pixelphilly/invented_water.py`, `scripts/10b_scan_invented_water.py` dry run, `10_repaint_water.py --invented-water fix`): finds water-colored blobs (hue 185-215, saturation 0.18-0.60, value 0.44-0.85; ≥ 400 px) on open ground outside mapped water and building silhouettes; exempts blobs where the aerial is water-colored or a City pool (`PPR_Swimming_Pools`, `04i_fetch_pools.py`) is within 25 m; fills flat with the surrounding drawing's color. The value floor came from the first dry run's false positive (shaded blue-gray pavement). Off by default.
- **Dormant lawns** (`src/pixelphilly/lawns.py`, `"lawn_correct": true`): inside City park properties and the NPS Independence NHP boundary (`04j_fetch_parks.py`), dormant-grass pixels of the ground texture shift toward green, brightness kept; roofs excluded. Areas without the flag are byte-identical.
