# Pixel Philly

An isometric pixel-art map of all of Philadelphia, drawn by an AI image model from City of Philadelphia open data. A project by Stephen Stirling.

**See it:** https://pixelphilly.sstirling.com (current version: **v18**, frozen Nov. 9, 2026)

The map is an **AI-generated illustration**, not a photograph or a survey. Buildings, streets and water come from public data, but an image model drew every pixel, and it gets details wrong. The drawing style was trained on images made with Google's Gemini 3 Pro Image model; see [Licensing and disclosure](#licensing-and-disclosure).

The idea comes from [tiny.london](https://tiny.london) and [isometric.nyc](https://isometric.nyc). Both start from renders of Google Photorealistic 3D Tiles. Google's Maps Platform terms bar that use: §3.2.3 (a)–(c) forbid storing or caching the content, creating content from it, and using it "to train, test, validate or fine-tune" AI models ([terms](https://cloud.google.com/maps-platform/terms), last modified Aug. 26, 2026). Pixel Philly builds its own 3D city from public data instead.

**Contents**
- [How it was made](#how-it-was-made)
- [Scale and cost](#scale-and-cost)
- [Map versions](#map-versions)
- [Live transit layer](#live-transit-layer)
- [Live weather](#live-weather)
- [Neighborhood prints](#neighborhood-prints)
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
| v17 | Nov. 9, 2026 | v14 plus ship fixes (v15) and bridge-deck fixes (v16, v17). Local only since Nov. 19, 2026 (taken off the hosted bucket to stay in R2's free 10 GB) | `?v=v17` |
| v14 | Nov. 4, 2026 | The first full-city map. Local only, plus an offline copy | `?v=v14` |

Each frozen version has a manifest, `output/philly/FROZEN_<version>.json`. Check one with `uv run python scripts/26_freeze_map.py --name philly --version v18 --verify`. Don't rebuild or edit a frozen version; **the next version is v19.** A change for v19 usually means: fix the scene data or a reviewed config list, rerender the affected region, redraw only the frames that changed ("Fix passes" below), merge and repaint, then build v19. Versions before v14 were working builds; the CHANGELOG describes each.

## Live transit layer

The viewer draws SEPTA vehicles on the map: buses, trolleys and Regional Rail trains from SEPTA's live feeds, and Market-Frankford El trains from the timetable. It's a layer over the map, so the map image and version don't change. It runs on v18 only, because it uses v18's building masks.

**How it works**

```
SEPTA TransitViewAll + TrainView ──(every 15 s)── Cloudflare Worker (worker/septa-live.js, cron)
                                                        │ writes
                                         R2: live/vehicles.json  (~31 KB, ~9 KB gzipped)
                                                        │ each viewer polls every 15 s
viewer/transit.js ── snaps vehicles to route shapes, glides them along, hides them behind buildings and trees
```

- **Why a Worker:** SEPTA's live feeds send no CORS header, so a browser on this domain can't read them. The Worker fetches them 4 times a minute and writes one small file to the map's bucket. SEPTA sees 4 requests a minute however many people are watching, and viewers read a cached static file.
- **The El has no live data.** On Nov. 14, 2026, routes L1 (El) and B1–B3 (Broad Street Line) were missing from TransitView, GTFS-RT vehicle positions and GTFS-RT trip updates. El trains are placed from SEPTA's GTFS timetable and labeled "scheduled." The Broad Street Line is underground in the city and isn't drawn.
- **Snapping:** each vehicle is snapped onto its route's GTFS shape (in map pixels). Between updates it glides there along the shape from where it is drawn, so the display runs about one update (15 s) behind. A vehicle prefers the shape it is already moving forward on, which tells a route's two directions apart. A bus or trolley more than 60 map px (about 18 m) from every shape (detours, garages) is drawn where SEPTA reports it. In a test on Nov. 14, 93% of bus and trolley reports were within 60 px of a shape.
- **Trains only on track:**
  - A Regional Rail train snaps within 120 px (about 35 m), onto any line's track, preferring its own line.
    - TrainView positions sat a median 29 px from the track, and a quarter were more than 51 px off (Nov. 18).
    - Trains run through Center City onto other lines, and TrainView's line label can name the line a train runs next.
  - When a train moves onto another shape on the same track, it keeps gliding along the track. A small step backward (GPS jitter) holds it still.
  - A train that can't be put on any track isn't drawn: it is never shown as a straight-line move, which would collapse it into one car facing across the track.
  - Six lines' shapes start at 30th Street. Each rail shape is extended back along the track that leads into it, so a train there keeps its trailing cars.
- **TrainView's placeholder:** TrainView reports trains it can't locate at one fixed point in Suburban Station (39.9538889, -75.1677778), even when their current stop is miles away. The Worker, the local feed and the viewer all drop those reports. This was observed in the feed and isn't documented by SEPTA.
- **Hiding behind buildings:** every frame was also rendered as a building mask (`06_render.py --mode mask`). `36_build_occlusion.py` joins those masks into a pyramid that lines up with v18. Vehicles run at street level, so wherever a building pixel covers a vehicle, the building is in front, and the viewer erases the vehicle there.
- **Ground level:** elevated track (the El deck, rail viaducts) isn't modeled in the scene; it comes from the aerial photo draped flat. Vehicles sit at ground level, which is where the track is drawn.
- **Tunnels:** OpenStreetMap rail tunnels, matched by railway type and direction, mark the stretches of each rail and trolley shape where vehicles aren't drawn.
  - Each car is hidden on its own, so a train goes into a tunnel car by car.
  - OSM maps the underground stations (Suburban, Jefferson, the El's and the trolley tunnel's) as stations, not tunnel. A gap of under 250 m between two tunnel stretches on the same shape is treated as tunnel.
- **SEPTA shape glitches:** a few GTFS shapes go a few meters out and straight back over the same points (Wilmington/Newark shape 007201 near University City, and 11 bus and trolley routes). `35_build_transit.py` removes out-and-back stretches under 50 m.
- **Hiding behind trees:** the trees on the map were drawn by the image model, so `40_build_tree_mask.py` finds them in the v18 tiles themselves. It uses the crowns' cool green and their dark outlines, which tell them from lawns and turf.
  - Each canopy pixel stores how far below it its trunk stands. The map looks down at 45°, so a canopy hangs over whatever is just behind it on screen. A tree hides a vehicle only when its trunk is at or below the vehicle's ground point: a bus under a near-side street tree is hidden, and one passing a far-side tree stays in front.
  - It's a color estimate. Some dark or yellow-green crowns are missed or only partly caught, and a few meadow patches beside woods are included.
  - Trees are applied zoomed in (0.3 screen px per map px or closer).
- **Sprites:** boxes at real size (approximate published dimensions), drawn with the map's own camera in 72 headings, every 5° (`37_vehicle_sprites.py`). Vehicles appear only zoomed in (0.12 screen px per map px or closer, where a bus is about 5 px long). There are no citywide dots: the layer is meant to be come across, not to drive the map.
- **Laying vehicles on the track:** the camera foreshortens the ground (1 m is 2.4 to 3.4 map px depending on direction), so the viewer works in ground meters. Each car is its real length, with 1 m between cars, measured along the track. It rests on two trucks (axles, for a bus) on the route shape, faces along the line between them and is drawn at their midpoint. Cars stay uniform and bend through curves, and a bus turning a corner faces between the two streets. Vehicles glide at a steady ground speed. Off-route vehicles face SEPTA's GPS heading.
- **Offline copy and other versions:** the layer is off. `?live=off` turns it off on the hosted site.

**Build the static files**

```bash
uv run python scripts/04r_fetch_transit.py        # SEPTA GTFS (pinned release) + OSM rail tunnels -> data/raw/
uv run python scripts/35_build_transit.py         # -> output/philly/transit/v202611010/ (routes, shapes, El timetable, 1.3 MB)
uv run python scripts/36_build_occlusion.py       # -> output/philly/overlays/v18/ (building masks, 37,039 tiles, 47 MB)
uv run python scripts/37_vehicle_sprites.py       # -> output/philly/transit/sprites.png + sprites.json
uv run python scripts/40_build_tree_mask.py       # -> output/philly/overlays/v18/trees/ (tree canopy and trunk depth, 11,770 tiles, 39 MB)
```

**Work on it locally:** run `uv run python scripts/38_live_feed.py` next to the local web server. It writes `output/live/vehicles.json` every 15 s, and the viewer reads that file when it's served from `localhost` or `127.0.0.1` (or with `?live=local`).

**When SEPTA publishes a new timetable** (every few weeks; the current one, `v202611010`, covers Nov. 1, 2026, through Feb. 20, 2027): set `GTFS_RELEASE` in `scripts/04r_fetch_transit.py`, run it and `35_build_transit.py`, set `GTFS_RELEASE` in `viewer/transit.js`, and upload the new `transit/<release>/` folder before the viewer. Past the timetable's end, the viewer keeps running El trains from the last matching weekday and says so in the status line.

**Publish** (after the files above are built):

```bash
rclone copy output/philly/transit r2:pixel-philly/output/philly/transit --s3-no-check-bucket --header-upload "Cache-Control: public, max-age=3600"
rclone copy output/philly/overlays/v18 r2:pixel-philly/output/philly/overlays/v18 --transfers 32 --checkers 64 --s3-no-check-bucket \
  --header-upload "Cache-Control: public, max-age=31536000, immutable"
rclone copy viewer r2:pixel-philly/viewer --s3-no-check-bucket --header-upload "Cache-Control: public, max-age=300"   # last
```

**Set up the Worker** (Cloudflare dashboard, once; no Node or build step). The dashboard's labels change from time to time; these were written Nov. 14, 2026.
1. **Workers & Pages → Create application → Start with Hello World!** (not "Import a repository," which needs Git). Name it `pixel-philly-live` and select **Deploy**.
2. **Edit code** (top right of the Worker's page). Delete everything in `worker.js`, paste in all of `worker/septa-live.js` and select **Deploy**.
3. **Bindings → Add binding → R2 bucket:** variable name `BUCKET`, bucket `pixel-philly`. Save and deploy.
4. **Settings → Trigger Events → Add → Cron Triggers:** schedule `* * * * *` (every minute; each run polls 4 times, 15 s apart). Cron changes can take up to 15 minutes to start.
5. **Check:** the Worker's own `*.workers.dev` URL reports `ok: live/vehicles.json has N vehicles, fetched N s ago`. It only reads; it never polls SEPTA or writes. https://pixelphilly.sstirling.com/live/vehicles.json should show a `fetched` time that changes every 15 s. If something fails, **Observability → Logs** on the Worker shows the error (the Worker logs each failed poll).
6. **Caching:** sstirling.com → **Caching → Cache Rules → Create rule:** custom filter, hostname equals `pixelphilly.sstirling.com` AND URI path starts with `/live/`; cache eligibility **Eligible for cache**; edge TTL **Use cache-control header if present**. Cloudflare doesn't cache `.json` by default, so without this rule every viewer poll is an R2 read.

Cost (estimates): about 173,000 R2 writes a month (free tier: 1 million) and one Worker run a minute (free tier: 100,000 requests a day). The free plan allows 10 ms of CPU per run; parsing SEPTA's 183 KB response four times should fit. If the Worker's logs show CPU-limit errors, Workers Paid is $5 a month. If a feed fails, the Worker keeps the last good file, and the viewer warns once it's more than two minutes old.

## Live weather

When it's raining or snowing in Philadelphia, the viewer draws falling pixel rain or snow over the map, with a faint wash (cool gray for rain, pale for snow). When it isn't, it draws nothing, and its animation loop doesn't run. A small badge in the top-right corner shows the airport's current temperature.

- **Data:** the National Weather Service's latest observation at Philadelphia International Airport (station KPHL, `https://api.weather.gov/stations/KPHL/observations/latest`, public domain). KPHL reports about hourly, plus special reports when the weather changes.
- **Pipeline:** the transit Worker (`worker/septa-live.js`) fetches it every 5 minutes and writes `live/weather.json`:
  ```
  {"fetched", "observed" (unix s), "station", "kind": "snow"|"rain"|"mix"|null, "intensity": "light"|"moderate"|"heavy"|null, "text",
   "temp_c" (as reported, unrounded, or null), "night": true|false|null, "thunder": true|false}
  ```
  `temp_c` is null when NWS has no value or its quality control marks it failed (`X`). `night` comes from the day or night folder in NWS's icon URL; it's kept as data, but the badge doesn't use it (see below). `thunder` is true when any report has the `TS` descriptor (`TSRA`, `+TSRA`, `TS`), but not a storm in the vicinity (`VCTS`); `weather_thunder()` and `weatherThunder()` are tested to agree.
  The weather service then gets 12 requests an hour however many people are watching. A weather failure never touches `vehicles.json`. Locally, `scripts/38_live_feed.py` writes `output/live/weather.json` the same way.
- **Which weather counts:** the observation's METAR codes (`presentWeather[].rawString`).
  - **Snow:** `SN`, `SG` and `PL` (ice pellets).
  - **Rain:** `RA`, `DZ` and `UP`, including showers, thunderstorms and freezing rain or drizzle.
  - **Mix:** rain and snow together.
  - **Intensity:** from the `-` and `+` prefixes.
  - **Ignored:** fog, mist, haze, thunder without rain, weather "in the vicinity" (`VC`) and blowing snow (`BL`, `DR`: snow lifted off the ground, not falling).
  - `weather_kind()` (Python) and `weatherKind()` (Worker) are tested to agree (`tests/test_weather.py`).
- **Viewer:** `viewer/weather.js` draws in screen space (the same at every zoom). Particles per 1920 x 1080 window: light 220, moderate 450, heavy 850. An observation more than 2 hours old is ignored. Nothing animates with reduced motion. The status line names the weather while it's precipitating, and the credits add the National Weather Service.
- **Thunderstorms:** a darker wash, plus a pixel lightning bolt every 6 to 16 seconds (shown 160 ms) with a soft brightening of the screen that fades in about half a second. That's far below WCAG 2.3.1's limit of three flashes a second. Thunder without rain gets the dark wash and lightning but no raindrops.
- **Temperature badge:** `renderTemp()` in `viewer/weather.js` draws the temperature in whole degrees Fahrenheit, "PHL" and a 9 x 9 icon (sun or moon, cloud, rain, snow, fog) as SVG squares. The digits are a hand-made 3 x 5 bitmap font, so there's no font download and it stays crisp at any screen density. The icon follows thunder first (cloud and bolt), then the rain or snow animation, then the NWS description ("Cloudy", "Overcast", "Fog" and so on). Clear weather shows a sun or a moon from the sun's position at the airport right now (`sunIsDown()`, standard low-precision solar formulas, sun below -0.833 degrees), not from NWS: its reports sometimes come without the day/night icon, and one can be 2 hours old. The badge hides when there's no temperature or the observation is more than 2 hours old. Hovering shows the full reading, and screen readers get it as text. It sits in its own box in the top-right corner on wide screens. Below 880 px, `viewer.js` moves it into the top bar's title row, without the box or "PHL" and at two-thirds size (CSS variables `--temp-icon-px` and `--temp-text-px`), so it adds nothing over the map; on the narrowest phones it wraps under the title.
- **Try it locally:** `?weather=snow`, `?weather=rain`, `?weather=mix` or `?weather=storm`, optionally with `&intensity=light` or `&intensity=heavy`, shows it without data. `?weather=off` turns it off. The offline copy has no weather.
- **Worker update:** paste the current `worker/septa-live.js` into the Worker (**Edit code**, replace everything, **Deploy**). No new binding or trigger is needed: the same bucket and one-minute cron are used, and the existing `/live/` Cache Rule covers `live/weather.json`. Until then, the viewer finds no weather file and draws nothing.

## Neighborhood prints

`viewer/neighborhoods.html` offers every Philadelphia neighborhood, cut from v18, as free images for personal use (not for sale; Stephen's terms, Nov. 19, 2026). It's linked from a small link next to the title in the map's top bar, the map's credits and the about page.

- **Boundaries:** `data/raw/philadelphia-neighborhoods.geojson`, 159 neighborhoods from [OpenDataPhilly](https://opendataphilly.org/datasets/philadelphia-neighborhoods/), CC BY 4.0, credit Robert Cheetham. Areas are measured from the boundaries: the file's own `Shape_Area` is out of date by more than 2% for 9 neighborhoods, and missing for 1.
- **The cut-out (`src/pixelphilly/neighborhoods.py`):** the map looks down at 45°, so tall things are drawn up from their base, and a plain boundary would slice towers. The mask is:
  - the ground inside the boundary;
  - **buildings:** whole, assigned by the center of their footprint, using the render scenes' footprints and heights in `data/processed`, drawn back to front so each building pixel goes to the building actually drawn there. Without the scenes, a column-run rule is the fallback, but it lets slivers of towers behind low buildings through.
  - **trees:** assigned by their trunk (the tree mask's depth, capped at 36 px), then smoothed by a majority vote within 6 px.
- **Outputs (`scripts/41_neighborhood_prints.py`),** in `output/philly/prints/v18/<slug>/`:
  - `print.jpg`: full resolution, 1 map px per image px, on the map's backdrop (`#ccd6e3`) with a 6% margin;
  - `desktop.jpg`: 5,120 x 2,880, the whole neighborhood fitted inside;
  - `phone.jpg`: 1,290 x 2,796, a crop of the full map that fills the screen. It's the largest phone-shaped rectangle inside the neighborhood's bounds, centered on its center of mass, and never upscaled, so it can show bits of neighboring areas at its edges.
  - `thumb.webp`: 600 px, for the page.
  - `preview.webp`: 1,920 x 1,080, from the desktop image, for the page's click-to-enlarge view (`--previews` remakes only these).
  - The name and site address are on every image but the thumbnail, small, lower left. JPEGs are quality 92 with no chroma subsampling.
  - `index.json` lists every neighborhood's sizes and bytes.
- **Build:** `uv run python scripts/41_neighborhood_prints.py --all` (or `--only "Rittenhouse,Chestnut Hill"`; `--force` rebuilds). It needs the v18 tiles, the building and tree masks, and the render scenes in `data/processed`.
- **Publish:**
  ```bash
  rclone copy output/philly/prints r2:pixel-philly/output/philly/prints --transfers 16 --s3-no-check-bucket --header-upload "Cache-Control: public, max-age=86400"
  ```
  Then upload `viewer/` as usual. The R2 free tier is 10 GB; check `rclone size r2:pixel-philly` before adding more.

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

**The data.** The vector downloads the map was built from (478 files, about 1.6 GB) are a snapshot attached to a GitHub release, not stored in git. This downloads it (about 190 MB), checks every file against `data/raw/SHA256SUMS` and unpacks it into `data/raw/`:

```bash
uv run python scripts/00_get_data.py
```

The LiDAR tiles and aerial imagery aren't in the snapshot (about 1 GB per LiDAR tile); the region runner and `04c_fetch_lidar.py`/`03_fetch_imagery.py` download them as needed. To start from live data instead, run the fetch scripts (`01`–`04q`); the City's layers may have changed since the map was drawn.

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
| `scripts/00_get_data.py` | Downloads and checks the raw-data snapshot (see "One-time setup") |
| `scripts/01`–`04r` (a few numbers are shared by two scripts, such as `23` and `25`; use the full file name) | Data downloads (buildings, trees, imagery, water, LiDAR, highways, rail, property records, OSM, streets, pools, parks, wetlands, city limits, golf, piers, bridges). `04m` prunes LiDAR tiles (dry run by default) |
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
| `scripts/39_transit_promo` | Promo video of the live transit layer, filmed from the viewer (needs the local server and `38_live_feed.py`); `--vertical` for TikTok/Reels |
| `scripts/29_trace_vessels`–`33` | Ship and bridge review: vessel tracing, crops and contact sheets |
| `scripts/34` | Favicon, touch icon and social preview cut from the tiles |
| `scripts/41_neighborhood_prints` | Neighborhood print, desktop and phone images for `viewer/neighborhoods.html` (see "Neighborhood prints") |
| `scripts/42_weather_prints_promo` | 14-second promo of live weather (simulated snow and rain, labeled on screen) and the prints page, filmed from the local site; `--vertical` for TikTok/Reels |
| `scripts/04r`, `35`–`38`, `40` | Live transit layer: SEPTA timetable and tunnels, route shapes and El timetable, building-mask pyramid, vehicle sprites, local feed, tree mask (see "Live transit layer") |
| `worker/` | The Cloudflare Worker that copies SEPTA's live feeds to the bucket |
| `src/pixelphilly/` | The library: `projection.py` (the single source of truth for the camera), `lidar.py`, `facades.py`, `lawns.py`, `golf.py`, `vessels.py`, `bridges.py`, `water.py`/`waterpaint.py`, `regions.py`, `joint_sampler.py`, `region_runner.py`, `qa.py`/`qa_scan.py`, `viewer_geo.py` and others |
| `render/` | The three.js page that draws scenes (three.js r169, vendored, MIT) |
| `gpu/` | Modal apps: `modal_app.py` (drawing) and `train_app.py` (LoRA training) |
| `viewer/` | The map page (`viewer.js`; the live transit layer in `transit.js` and `transit_core.js`), about page, OpenSeadragon 6.1.1 (vendored) and site images |
| `prompts/` | Versioned prompts from the Gemini pilot |
| `tests/` | pytest suite |
| `data/raw/`, `data/processed/` | Downloads (immutable, logged in `MANIFEST.json`, checksums in `SHA256SUMS`; the files themselves come from `00_get_data.py`) and derived files |
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

- **Code.** MIT ([`LICENSE`](LICENSE)). The vendored OpenSeadragon (BSD 3-Clause) and three.js (MIT) keep their own licenses, next to each library. Data, and images derived from it, keep their sources' terms below and in `data/README.md`.
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
