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

**License note.** OpenDataPhilly lists these under a "City of Philadelphia License" whose full text we could not find. Before publishing anything derived from them, email maps@phila.gov and confirm both commercial publication and AI-derived works are allowed.

## Known data limits

- **PWD water layer.** Covers only the Pennsylvania half of the Delaware; the city boundary follows the state line mid-river. Per-frame water shares are a lower bound near New Jersey. It still drives the prompt's water sentence, so prompts stay identical to those already sent; the repaint uses NHD.
- **Tree inventory.** Covers street and park trees the city maintains. Private trees are missing.
- **Building heights.** `approx_hgt` and `max_hgt` sometimes disagree badly. See the height rule in the main README and the outlier list in `processed/oldcity_qa.json`.
- **Imagery.** It is not a true orthophoto. Tall buildings lean away from the photo center, so their roofs can sit a little off their footprints.
- **Missing structures.** Bridges and elevated highways are not in the footprint layer.

## Processed files

| File | Made by | Contents |
|---|---|---|
| `processed/oldcity_ground.jpg` | `05_build_scene.py` | Aerial mosaic, 12,800 × 12,544 px, git-ignored |
| `processed/oldcity_scene.json` | `05_build_scene.py` | Buildings (local meters, height, wall color), trees, camera, frame lattice, texture mapping |
| `processed/oldcity_qa.json` | `05_build_scene.py` | Height sources, outliers, dropped records, texture-fit error |
