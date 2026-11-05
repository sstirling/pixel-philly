# Data provenance

Files are prefixed with their area: `oldcity_*` and `fishtown_*`. Every area uses the same sources, queries and fetch scripts, run with `PP_AREA=<area>`. The table below describes the Old City files; the Fishtown files are identical in kind, fetched Oct. 20, 2026 for the Fishtown lattice extent. The Fishtown core box comes from the Azavea/OpenDataPhilly neighborhoods layer (Robert Cheetham, CC BY 4.0): the FISHTOWN polygon's bbox is [-75.1367, 39.9609, -75.1132, 39.9848], about 3.1 km². The test box is a same-size-as-Old-City core inside it, [-75.1338, 39.9663, -75.1213, 39.9768].

Every raw download is recorded in `raw/MANIFEST.json` with:
- its exact query URL
- the bbox it was fetched for
- the feature or tile count
- a UTC fetch timestamp

Raw files are never edited. All transformations write to `processed/`.

Imagery tiles (`raw/imagery/`) are git-ignored because of their size. `scripts/03_fetch_imagery.py` re-downloads them.

The fetch extent is the ground seen by the whole frame lattice, which is larger than the Old City bbox. For the 54° camera it is about 3 km across. The exact bbox is in the manifest.

## Sources

| File | Source | Publisher | Vintage | License / terms |
|---|---|---|---|---|
| `raw/oldcity_buildings.geojson` | L&I building footprints, ArcGIS `LI_BUILDING_FOOTPRINTS/FeatureServer/0` ([OpenDataPhilly](https://opendataphilly.org/datasets/building-footprints)) | City of Philadelphia, Dept. of Licenses & Inspections | Updated weekly; fetched Oct. 20, 2026. Heights from city LiDAR. | City of Philadelphia License (see note) |
| `raw/imagery/CityImagery_2024_3in/19/` | 2024 3-inch aerial imagery tile service `CityImagery_2024_3in` (TIFFs on [PASDA dataset 7001](https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=7001)) | City of Philadelphia | Flown 2024 (leaf-off) | City of Philadelphia License. The imagery page says the city "retains all rights." |
| `raw/oldcity_trees.geojson` | PPR tree inventory 2025, ArcGIS `ppr_tree_inventory_2025/FeatureServer/0` | Philadelphia Parks & Recreation | 2025 | City of Philadelphia License |
| `raw/oldcity_water.geojson` | Hydrographic features (polygons), ArcGIS `Hydrographic_Features_Poly/FeatureServer/1` | Philadelphia Water Department | Live layer; fetched Oct. 20, 2026 | City of Philadelphia License |
| `raw/oldcity_water_nhd.geojson` | National Hydrography Dataset, "Area - Large Scale" (layer 9), `hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer` | U.S. Geological Survey | Live service; fetched Oct. 20, 2026 | Public domain (U.S. federal data). Covers both banks of the Delaware. Used for the water repaint only. |
| `raw/<area>_opa.geojson` | Property records, `opa_properties_public` on the City's Carto SQL API (`phl.carto.com/api/v2/sql`), explicit columns only: parcel_number, location, the_geom (property point), category_code_description, building_code_description, building_code_new, building_code_description_new, general_construction, number_stories, year_built, year_built_estimate, quality_grade. Fetched by `scripts/04f_fetch_opa.py` for areas with `"facades": "opa"` | City of Philadelphia, Office of Property Assessment | Nightly; fetched Oct. 25, 2026 | City of Philadelphia License |
| `raw/<area>_pwd_parcels.json` | Water Department parcels, `pwd_parcels` on Carto: `parcelid` and `brt_id` (= OPA parcel_number) only, no geometry. Joins footprints' `parcel_id_num` to OPA | City of Philadelphia, Water Department | Fetched Oct. 25, 2026 | City of Philadelphia License |
| `raw/<area>_osm.json` | OpenStreetMap buildings and `building:part` shapes that carry `building:colour` or `building:material`, with all their tags, Overpass API (`overpass-api.de`). (The first atlas spots fetched every building; a whole region can exceed Overpass's time limit, and only tagged shapes are used.) Fetched by `scripts/04g_fetch_osm.py` for façade areas | OpenStreetMap contributors | Live; fetched Oct. 26, 2026 | Open Database License (ODbL) 1.0; credit "© OpenStreetMap contributors" |
| `raw/<area>_streets.geojson` | Street centerlines, all classes, ArcGIS `Street_Centerline/FeatureServer/0`. Fetched by `scripts/04h_fetch_streets.py`; used to find street-facing walls (porches, storefronts) | City of Philadelphia, Streets Department | Fetched Oct. 26, 2026 | City of Philadelphia License |
| `raw/<area>_pools.geojson` | Swimming pools, ArcGIS `PPR_Swimming_Pools/FeatureServer/0` (points). Fetched by `scripts/04i_fetch_pools.py`; exempts real pools from the invented-water repair | Philadelphia Parks & Recreation | Fetched Oct. 26, 2026 | City of Philadelphia License |
| `raw/<area>_parks.geojson` | Park properties, ArcGIS `PPR_Properties/FeatureServer/0` (polygons). Fetched by `scripts/04j_fetch_parks.py` for the dormant-lawn correction | Philadelphia Parks & Recreation | Fetched Oct. 26, 2026 | City of Philadelphia License |
| `raw/<area>_nps_parks.geojson` | National Park Service unit boundaries, `NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer/2` (services1.arcgis.com/fBc8EJBxQRMcHlei). Federal parkland the City layer lacks (Independence NHP) | National Park Service | Fetched Oct. 26, 2026 | Public domain (U.S. federal data) |
| `raw/<area>_wetlands.geojson` | National Wetlands Inventory polygons, `fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0`. Fetched by `scripts/04k_fetch_wetlands.py`; exempts possibly-real water from the invented-water repair | U.S. Fish and Wildlife Service | Fetched Oct. 26, 2026 | Public domain (U.S. federal data) |
| `raw/<area>_highways.geojson` | Street centerlines, ArcGIS `Street_Centerline/FeatureServer/0`, `where class IN (1,9,10)`: CLASS 1 = expressway mainline ("NB DELAWARE EXPY", "WB SCHUYLKILL EXPY"), 9 and 10 = ramps ("PACKER AVE RAMP", "DELAWARE EXPY RAMP H"). Fetched by `scripts/04d_fetch_highways.py` | City of Philadelphia, Streets Department | Live layer; fetched Oct. 23, 2026 | City of Philadelphia License |
| `raw/city_limits.geojson` | City limits, ArcGIS `City_Limits/FeatureServer/0` (services.arcgis.com/fLeGjb7u4uXqeF9q; one polygon, [metadata](https://metadata.phila.gov/#home/datasetdetails/5543868820583086178c4f89/)). Fetched by `scripts/04l_fetch_city_limits.py`; configs with `"clip_to_city": true` keep only frames that see the city, and `scripts/23_preflight_regions.py` checks that the regions cover it | City of Philadelphia, Dept. of Planning and Development | Last edited Oct. 7, 2025 (service `lastEditDate`); fetched Oct. 28, 2026 | City of Philadelphia License |
| `raw/lidar/Philadelphia_<Id>.las` (git-ignored, ~1 GB each) | 2022 classified LiDAR point cloud, [PASDA dataset 7154](https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=7154); tile index `Philadelphia_Tiles.shp` in `raw/lidar/index/`. Fetched by `scripts/04c_fetch_lidar.py`, only tiles within 100 m of an area's box. | City of Philadelphia via PASDA | Flown March 29, 2022 (leaf-off), ~40 points/m² | Metadata: "Use_Constraints: None." Credit "City of Philadelphia via PASDA." |

**Reviewed corrections (Nov. 2).** City footprint heights and our stadium rule are both occasionally wrong. Corrections are reviewed lists in `config/`, applied in `scripts/05_build_scene.py` (`src/pixelphilly/reviewed.py`); each entry records the reason, the aerial checked and the date. `config/height_overrides.json`: footprint 478499 (5458 Tacony St) is recorded at 138 ft (42 m), but the 2024 aerial shows a small round tank in a scrapyard with almost no shadow; it is drawn at the median height of the footprints within 25 m (10.67 m). `config/stadium_exclusions.json`: footprints that pass the seating-row rule but aren't stadiums (8500 Essington Ave, the airport terminal and garages; 4101 N Delaware Ave, Richmond Generating Station; 3622-40 G St, a sawtooth-roof plant; 3001 E Allegheny Ave, a pier warehouse). `config/structure_exclusions.json` (Nov. 3): a 42,345 m², 21 m LiDAR "structure" on the strip between the Schuylkill and the Manayunk Canal is a demolition and rubble field in the 2024 aerial; it is dropped. More reviewed entries: 8700 Ridge Ave (a care-home campus) and 8201 Torresdale Ave (Holmesburg Prison) are not stadiums, and the 40.6 m part at 5245 Bleigh Ave is a real elevated water tower (`config/qa_exceptions.json`). Raw data stays unchanged.

**Golf courses (Nov. 4).** `raw/<area>_golf.json`: OpenStreetMap courses and golf features (`scripts/04n_fetch_golf.py`, Overpass, `out geom`). License: ODbL 1.0, credit "© OpenStreetMap contributors".
- **What's fetched:** leisure=golf_course (plus disused:/was: courses, so they can be excluded) and golf=fairway, green, tee, bunker, rough, water_hazard, lateral_water_hazard.
- **Not courses:** driving ranges (by name, or under 5 ha) and disused courses.
- **Construction sites:** Cobbs Creek "Olde" and Karakung are reviewed as the 2024 construction site (`config/golf.json`) and get no lawn correction. A PPR golf property lying mostly (at least half its area) over those courses is construction as a whole (`golf.ppr_construction`, Nov. 4). PPR's "Cobbs Creek Golf Course" property also covers the meadow and creek notches between Olde and Karakung: graded earth and dormant meadow in the 2024 aerial. Before this rule that strip got the golf correction and turned pale green with straight edges.
- **Also courses:** PPR properties with "Golf" in their name, since Walnut Lane isn't a course in OSM.
- **Golf lawn correction:** inside courses, `lawns.correct_golf` uses a wider band, hue 30–75, saturation 0.15–0.70, value 0.30–0.92. It catches saturated fairways (Byrne, S ~0.61) and bleached ones (Saint Martin's, V ~0.86, S ~0.21).
  - Fairways, greens and tees go to hue 82, 4% lighter; rough goes to the lawn target (88). Brightness (texture) is kept.
  - Bunkers, water hazards and buildings are excluded; wooded rough keeps the woods treatment.
- **Water hazards:** they join the water repaint's per-body pass and the invented-water exemptions.
- **Unverified name:** OSM names the Torresdale course (way/485880727) "Union League Golf Club". Don't use it in captions without a source.

**Mapped water outside NHD (Nov. 4).** The water repaint used USGS NHD polygons only, so City (PWD) water such as the Manayunk Canal was never a candidate and was drawn as grass. Each PWD polygon outside NHD (and each OSM golf water hazard) now gets its own color model, sampled from its eroded interior with buildings and rendered tree canopies left out (`waterpaint.body_models`, `body_water`, `tree_discs`).
- **Guard:** a body is used only if at least 60% of its pixels are within its own threshold (capped at 40 levels). A dry basin or a polygon over lawn and paving is skipped.
- **Kept:** pixels off the body's color (boats, bridges) stay as drawn.

**License note.** OpenDataPhilly lists these under a "City of Philadelphia License" whose full text we could not find. Before publishing anything derived from them, email maps@phila.gov and confirm both commercial publication and AI-derived works are allowed.

## Known data limits

- **PWD water layer.** Covers only the Pennsylvania half of the Delaware; the city boundary follows the state line mid-river. Per-frame water shares are a lower bound near New Jersey. It still drives the prompt's water sentence, so prompts stay identical to those already sent; the repaint uses NHD.
- **Tree inventory.** Covers street and park trees the city maintains. Private trees are missing.
- **Building heights.** `approx_hgt` and `max_hgt` sometimes disagree badly. See the height rule in the main README and the outlier list in `processed/oldcity_qa.json`.
- **Imagery.** It is not a true orthophoto. Tall buildings lean away from the photo center, so their roofs can sit a little off their footprints.
- **Missing structures.** Bridges and elevated highways are not in the footprint layer. Neither are ships, cranes and container stacks.
- **Leaf-off aerial.** The 2024 aerial was flown in March: lawns under bare trees are brown-tan and the drawing model draws dirt. With `"lawn_correct": true`, dormant-grass pixels (hue 35-65, saturation 0.22-0.60, value 0.30-0.72, measured on the Mall, Independence Square and Washington Square) inside park polygons, minus building footprints, are shifted toward green with their brightness (texture) kept (`src/pixelphilly/lawns.py`). Paths, paving, shadows and clay infields fall outside the band. Risk: bare dirt with grass-like color inside a park also turns green.
  - **Woods (Nov. 2).** Leaf-off forest floor falls in the same color band; in `atlas_wissahickon_fac` the correction greened 42% of park pixels. With `"lawn_skip_woods": true` (the eight citywide regions), the correction fades out where the LiDAR says woods: the share of 0.5 m cells more than 2.5 m above ground (buildings excluded) within 30 m, ramped from 0.65 to 0.75 (`lawns.woods_grid`).
    - **Calibration over whole park polygons** (share of cells above 0.7): Wissahickon Valley Park 80%; Washington Square 2.3%; Independence NHP 4.4%; Clark Park 11%; Malcolm X Park 1.1%; West Fairmount Park lawns 0%; Cobbs Creek Park 36% (a wooded creek valley plus lawns).
    - **Why a 30 m share:** per cell, canopy alone doesn't separate them; 59% of Washington Square's cells and 78% of Wissahickon's are over 2.5 m.
    - **Effect:** inside the Wissahickon atlas grid, corrected pixels fall by 47% (the golf course stays corrected). Washington Square and Clark Park lose 1.3% and 3.9%.
    - **Limit:** ground beyond the area's LiDAR box (bbox + 100 m) has no grid, so it is still corrected there.
    - **Existing regions:** the four drawn regions don't set the flag and are unchanged.
  - **Forest mode (Nov. 3).** Left as aerial, leaf-off woods came out of the model dark brown to near black (north|west_north join, seam median 3.44). With `"lawn_woods_mode": "forest"` (all eight citywide regions), woods are shifted toward forest green instead (`lawns.forest`).
    - **Target:** the renderer's own tree-canopy tint (render/render.js, HSL h 0.27–0.33, s 0.35–0.50, l 0.30–0.38), set at hue 108° and saturation 0.55. That's 20° bluer than mowed lawn (88°).
    - **Brightness:** remapped linearly into 0.26–0.56, so texture keeps its order and shadows can't go black.
    - **Exclusions:** paving (saturation < 0.12, value ≥ 0.22), mapped water (PWD and NHD, which the water repaint matches by render color) and building footprints (+1 m).
    - **Scope:** all woods, not only park polygons. A park line through continuous woods made a hard edge at Cobbs Creek.
    - **Feather:** the woods weight is feathered over ~16 m (two box passes, `WOODS_FEATHER_M` 8 m), so the forest green fades in rather than starting at a line.
    - **Limit:** open woods and tree rows below the 0.65 canopy share stay as aerial, a thin brown fringe at the woods' edge.
    - **Result (Nov. 3): not recommended.** Redrawn with forest mode, the model drew much of the smooth forest-green ground as lakes (invented water 4.7 times as much in the redrawn frames). See CHANGELOG.
    - **Reverted (Nov. 3):** the eight region configs no longer set `lawn_woods_mode`, and the woods feather only applies in forest mode, so lawn_skip_woods scenes are as drawn in v9. The code and tests stay, off by default.
  - **Tree-canopy experiment (Nov. 3, `"woods_trees": "lidar"`, not applied to any region).** Woods get the street-tree canopy geometry at LiDAR treetops instead of a ground tint (`lawns.canopy_trees`).
    - **Placement:** one tree per 7 m block at the block's highest cell over 5 m, where the woods weight is over 0.5; crown radius 3–5 m.
    - **Test spot:** `config/test_wissahickon_trees.json`, a copy of `atlas_wissahickon_fac` with the option, 5,933 canopies added.
    - **Result:** woods drawn as dense trees, creek kept, no lakes in the woods; 4 small blue patches (8,990 px) on open ground at the golf-course edge, against 0 in the baseline drawing (`output/review/trees_test_drawings.jpg`, `trees_test_drawings_1to1.png`).
- **Invented water.** The drawing model sometimes paints water on open ground (a pool beside City Hall, railroad cuts drawn as canals, a turf field drawn as a pool). `scripts/10b_scan_invented_water.py` finds water-colored blobs (≥ 400 px) outside mapped water (NHD, PWD, grown 24 px) and building silhouettes; blobs where the aerial is itself water-colored, or near a City pool, are exempt. Also exempt: blobs 20% or more inside an NWI wetland, pond or lake (`04k_fetch_wetlands.py`), and flat light rectangles in the aerial (rectangularity ≥ 0.78, value > 0.55, low texture, gray: a roof the scene is missing, e.g. an Upper North gym). `10_repaint_water.py --invented-water fix` fills the rest flat with the surrounding drawing's color (its green where the aerial is clearly green, e.g. turf) and logs each in report.json. Off by default. Known limits: lower South Philly basins and mudflats are not in NWI and stay flagged; the roof rule also exempts some flat light ground surfaces (a sports court drawn as a pool).
- **Property records (façades).** The OPA table also holds owner names, mailing addresses, sale, tax and exemption figures. None of it is fetched: queries name their columns, and `src/pixelphilly/opa.py` refuses owner\*, mailing\*, sale\*, taxable\*, exempt\*, market_value, homestead\*, book_and_page, registry_number, cross_reference and recording_date, both in the query and in the downloaded file. `exterior_condition` is excluded too, by editorial rule: the map does not encode vacancy or condition, which would stigmatize blocks.
  - **Join** (`src/pixelphilly/facades.py`): footprint `parcel_id_num` → `pwd_parcels.brt_id` → OPA `parcel_number` (95% of Old City), then address (97%; condos repeat an address, the majority style wins), then OPA points inside the footprint. Unmatched footprints keep plain walls.
  - **OpenStreetMap:** `building:colour` (hex or CSS name) and `building:material` win over the property record where an OSM shape and a footprint (or LiDAR part) overlap each other by half or more; `building:part` shapes before buildings. Coverage is thin outside Center City (atlas spots: 176 footprints at Independence Hall, 22 at City Hall, 1 or none in the rowhouse spots). ODbL: maps using it must credit "© OpenStreetMap contributors".
  - **Tall buildings:** OPA "MASONRY" includes limestone and terra cotta. Non-rowhouse buildings above 20 m with no OSM colour keep their own colour sampled from the aerial instead of the brick palette.
  - **Limits:** `general_construction` is undocumented (A ≈ masonry, C/D ≈ frame, E/J ≈ stone, inferred) and used only when the building code names no material. `number_stories` is often null for big buildings (height ÷ 3.2 m then). `year_built` is unreliable for big public buildings; it only separates modern glass towers from pre-war masonry ones. Codes 41-47 have no style description. Façades are drawn procedurally from these records (window grid, storefront, porch and cornice bands): they are a typology, not a survey of each façade.
- **LiDAR structures.** Objects with no footprint are drawn from the LiDAR when they are flat and clear the ground (`structures()` in `src/pixelphilly/lidar.py`). The rule:
  - **Grid.** A class-1-only max-Z grid (`struct` in `processed/<area>_lidar_grid.npz`). Bridges (17), water (9) and ground (2) are left out.
  - **Height.** Cells 2.5-90 m above local ground, or above the water level (0 m NAVD88, approximate: the rivers are tidal) where there is no ground.
  - **Location.** Outside every footprint by 1.5 m.
  - **Size and flatness.** Regions of at least 60 m² with median 3x3 roughness under 0.3 m. Measured: containers 0.02, a ship 0.03, roofs 0.06, tree canopy 1.4-1.9. A bus is about 30 m².
  - **Highways.** I-95's decks are mostly class 1, not bridge class 17, so expressway and ramp centerlines (`raw/<area>_highways.geojson`) are buffered (14 m mainline, 7 m ramps) and masked out. SEPTA's elevated rail isn't a street; North Philly will need a rail layer.
  - **2022 LiDAR vs. 2024 aerial.** Ships leave and container stacks move between the two. A structure is kept only if the 2024 photo shows something there: it is dropped when half or more of its pixels are within 25 RGB levels of the median color of the 3-15 m ground ring around it, or, over water, when 90% or more of its pixels are one color. Calibration: kept regions 0.03-0.29, empty ones 0.63-1.00.
  - **Known misses.** A plain roof that matches the pavement around it is dropped too (one small building at the Navy Yard). Rows of parked truck trailers come through as structures.
- **LiDAR.** The files carry no CRS record; they are PA State Plane South, US survey feet (EPSG:6565), heights NAVD88 feet, assigned in `src/pixelphilly/lidar.py`. There is no building class: buildings and trees are both class 1, so the footprints decide what is a building. Thin features under 6 m² in plan (antennas, stray returns) are merged into the part below them, unless the City's recorded height confirms them (within 5 m): that keeps City Hall's William Penn statue. Small clusters that more than double the roof around them are treated as stray returns and flattened, unless they match the City's typical height (`approx_hgt`). The City's `max_hgt` is itself the highest LiDAR return and is sometimes set by the same stray points (226-30 N 2nd St: 203 ft max vs. 59 ft typical), so it is not used as evidence. `downtown_lidar_*` footprints were fetched Oct. 22, 2026, two days after the original downtown set.

## Processed files

| File | Made by | Contents |
|---|---|---|
| `processed/oldcity_ground.jpg` | `05_build_scene.py` | Aerial mosaic, 12,800 × 12,544 px, git-ignored |
| `processed/oldcity_scene.json` | `05_build_scene.py` | Buildings (local meters, height, wall color), trees, camera, frame lattice, texture mapping |
| `processed/oldcity_qa.json` | `05_build_scene.py` | Height sources, outliers, dropped records, texture-fit error |
| `processed/<area>_lidar_grid.npz` | `05_build_scene.py` (areas with `"building_shapes": "lidar"`) | 0.5 m max-Z surface and min-Z ground grids in meters (NAVD88), local frame, over the area box plus 100 m. Git-ignored cache; delete it to rebuild from the LAS tiles |
| `processed/south_lidar_*`, `processed/south_lidar/tiles/` | `05_build_scene.py` | Downtown + South Philly (`config/south_lidar.json`). Footprints (115,885), trees (53,072), PWD water (124) and NHD water (26) fetched Oct. 23, 2026; 26,215 z19 imagery tiles (13,426 new); 113 LiDAR tiles. LiDAR grid cache ~1.4 GB |

**Storage and pruning (Oct. 28).** The LiDAR tiles on disk are 164 GB (196 tiles). They are git-ignored and can be downloaded again from PASDA. The cached height grids in `processed/*_lidar_grid.npz` are what the scene builder reads, so raw tiles can be deleted once every area that lists them has a grid that holds the class-1 `struct` grid (older grids without it are rebuilt from the LAS files). `scripts/04m_prune_lidar.py` does this, as a dry run unless given `--apply`:
- A tile is deleted only when every area listing it (`raw/lidar/<area>_tiles.txt`) is a `"building_shapes": "lidar"` config with a valid grid. Tiles that LiDAR configs not yet fetched will need (by the tile index) are kept.
- Each deletion is recorded in `raw/MANIFEST.json` under `lidar/<tile>`: `path`, `bytes`, `deleted_at`, the PASDA `url` to re-download, and the `grids` that replaced it.
- `04c_fetch_lidar.py` no longer downloads tiles for an area whose grid is cached. To get tiles back, delete the grid and rerun 04c.
| `processed/north_lidar_*`, `processed/north_lidar/tiles/` | `05_build_scene.py` | North Philly (`config/north_lidar.json`, projection origin shared with south_lidar). Footprints (71,986), trees (21,074), PWD water (89), NHD water (1), highways (38), El (1) and surface track (739) fetched Oct. 23–24, 2026; 9,684 z19 imagery tiles; 41 LiDAR tiles |

**Rail sources** (`04e_fetch_rail.py`):
- **The El:** SEPTA Highspeed Lines, route L (`services2.arcgis.com/9U43PSoL47wawX5S/.../SEPTA_-_Highspeed_Lines/FeatureServer/0`).
  - No formal license on the item; OpenDataPhilly lists SEPTA data as "Public Use; Free". Credit: SEPTA. Confirm with planning@septa.org before publication.
  - The line also runs underground under Market St, where masking is harmless.
- **Surface track:** City of Philadelphia Railroad Lines, fcode 1700 (City of Philadelphia License).
  - Traced from aerials, updated 2004.
  - The fcode values are undocumented: 1700 matched surface track and 1701 the underground Broad Street Line when compared with SEPTA's lines (Oct. 23, 2026).

## Landmark reference photos (`landmarks/`)

`landmarks/manifest.json` is written by `scripts/19_landmark_refs.py`. It records every reference photo's source page, direct image URL, license, author and credit line. The photos themselves (`landmarks/refs/`) are git-ignored and re-downloaded by the script.

| Source | License | Use |
|---|---|---|
| Library of Congress, Historic American Buildings Survey / Historic American Engineering Record ([rights statement](https://www.loc.gov/rr/print/res/114_habs.html)) | Public domain (US government work) | Credit "Historic American Buildings Survey, Library of Congress Prints and Photographs Division" |
| Wikimedia Commons, files whose LicenseShortName is CC0, public domain or CC BY | As recorded per file | CC BY requires the credit line in the manifest |
| Wikidata (QIDs, P625 coordinates) | CC0 | — |
| City of Philadelphia AIS geocoder (`api.phila.gov/ais/v1/search/`) | City of Philadelphia | Coordinate cross-check only |

CC BY-SA files and Commons files marked "No restrictions" are excluded. A share-alike obligation would not be compatible with redistributing the derived map tiles under our own terms.
