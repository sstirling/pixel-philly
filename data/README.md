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
| `raw/lidar/Philadelphia_<Id>.las` (git-ignored, ~1 GB each) | 2022 classified LiDAR point cloud, [PASDA dataset 7154](https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=7154); tile index `Philadelphia_Tiles.shp` in `raw/lidar/index/`. Fetched by `scripts/04c_fetch_lidar.py`, only tiles within 100 m of an area's box. | City of Philadelphia via PASDA | Flown March 29, 2022 (leaf-off), ~40 points/m² | Metadata: "Use_Constraints: None." Credit "City of Philadelphia via PASDA." |

**License note.** OpenDataPhilly lists these under a "City of Philadelphia License" whose full text we could not find. Before publishing anything derived from them, email maps@phila.gov and confirm both commercial publication and AI-derived works are allowed.

## Known data limits

- **PWD water layer.** Covers only the Pennsylvania half of the Delaware; the city boundary follows the state line mid-river. Per-frame water shares are a lower bound near New Jersey. It still drives the prompt's water sentence, so prompts stay identical to those already sent; the repaint uses NHD.
- **Tree inventory.** Covers street and park trees the city maintains. Private trees are missing.
- **Building heights.** `approx_hgt` and `max_hgt` sometimes disagree badly. See the height rule in the main README and the outlier list in `processed/oldcity_qa.json`.
- **Imagery.** It is not a true orthophoto. Tall buildings lean away from the photo center, so their roofs can sit a little off their footprints.
- **Missing structures.** Bridges and elevated highways are not in the footprint layer. Neither are ships, cranes and container stacks.
- **Leaf-off aerial.** The 2024 aerial was flown in March: lawns under bare trees are brown-tan and the drawing model draws dirt. With `"lawn_correct": true`, dormant-grass pixels (hue 35-65, saturation 0.22-0.60, value 0.30-0.72, measured on the Mall, Independence Square and Washington Square) inside park polygons, minus building footprints, are shifted toward green with their brightness (texture) kept (`src/pixelphilly/lawns.py`). Paths, paving, shadows and clay infields fall outside the band. Risk: bare dirt with grass-like color inside a park also turns green.
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

**Storage.** The LiDAR tiles on disk are now 85 GB (113 tiles). They are git-ignored and can be downloaded again from PASDA with `04c_fetch_lidar.py`. The cached height grids in `processed/*_lidar_grid.npz` are what the scene builder reads, so the LAS files can be deleted once an area's grid is built (rebuilding the grid would need them again).
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
