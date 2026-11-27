# v19 landmarks: dossiers and sources

The v19 landmarks and bridges are modeled in 3D by hand, the way v18 modeled the Ben Franklin and Walt Whitman bridges (see `docs/landmarks_plan.md` for why). Each model is built from a dossier, `config/landmarks/<slug>.json`, which records everything the model needs and where each value came from. This file explains the format, how the measured values are made, and the sources for each structure.

## Dossier format

| Key | What it holds |
|---|---|
| `slug`, `name`, `wikidata`, `kit` | Identity. `kit` must match `config/landmarks/index.json`. |
| `about` | What the model covers, what it leaves to the LiDAR, and which sources lead. |
| `footprint` | `polygon` (or `polygons`, one per building) in lon/lat, the outline the model replaces, with its `source` and the L&I footprint IDs and OSM ways it `replaces`. |
| `dims` | Every dimension, as `{value, unit, source, note}` or `{value, unit, estimate: true, reason}`. |
| `colors` | `{rgb, source, method, ...}`. A color from a reference photo names the file and pixel box (`photo`); a color from the aerial names the outline it was sampled in (`aerial`); a color nobody published is an estimate with a reason. |
| `kit_params` | The kit's inputs: stages, pavilions, houses, field, roof and so on. A value is a record like those in `dims`, the name of a `dims` key (any key ending in `_m` must be one), or a plain description. |
| `credits` | Credit lines for OSM, the LiDAR, the aerial, footprints and reference photos. |
| `review` | Open questions for Stephen or for Phase 1. |

The rules are enforced by `pixelphilly.landmark_dossier.check()` and `tests/test_landmark_dossiers.py`:

- No bare numbers in `dims` or `kit_params`: every number sits in a record with an `https://` source or an estimate flag and a reason of more than 10 characters, the same rule as `config/bridge_structures.json`.
- The footprint is closed, valid and within 150 m of the index point (800 m for bridge kits).
- Each kit's required values are present (`KIT_REQUIRED` in `landmark_dossier.py`).
- Every color read from a photo is recomputed from its file and box, and every color read from the aerial is compared with the measurement output (within 1 of each channel).

Feet are converted at 0.3048 m and stored in meters to three decimals; the published figure is kept in the note.

## Measured values

`scripts/50_landmark_measure.py <slug>...` measures each structure on two City datasets and writes `output/landmarks/measure/<slug>.json`:

- **2022 LiDAR** (PASDA 7154, gridded at 0.5 m in `data/processed/<area>_lidar_grid.npz`). For every L&I footprint and OSM building or `building:part` outline within a radius of the structure: the 50th, 90th and 99th percentile and maximum surface height above ground, where ground is the median classified-ground return in a 3-15 m ring around the outline. Single-cell maxima are noisy (spikes past 200 m beside City Hall), so dossiers cite percentiles.
- **2024 City aerial** (3-inch tiles, cached at zoom 19). The median color inside each outline after dropping the darkest quarter of pixels (shadows).
- **Stadiums** (`bowl_stats`): the field as the low, flat region at the bowl's center, with its rectangle, compass bearing, center and level relative to the street; stand heights in twelve 30-degree sectors; the maximum height per 2 m along the field's half-axes (the seating rake).
- **Arena** (`dome_stats`): the roof as the connected region above 70% of the outline's 99th-percentile height, with its rectangle, crown (99th percentile), eave and cross-section.
- **Bridges**: median and maximum height per 10 m along each OSM bridge way, within 6 m of it.

A value measured this way cites the dataset (PASDA for the LiDAR, the City imagery service for the aerial) and names the script and the output in its note. The measurement output isn't in git; rerunning the script rebuilds it.

Dimension sources, in order of preference: HABS/HAER measured drawings and reports (`data/landmarks/drawings.json`; none exist for the pilot eight), owners' and official pages, National Park Service nominations, OSM tags (ODbL), the LiDAR, and secondary pages, with Wikipedia last and marked as such. Reference photos (`data/landmarks/manifest.json`, license-checked) are used only for colors and counts, never fed to the drawing model.

## Pilot structures (Nov. 26, 2026)

### City Hall (`mansard_tower`)

- **Heights:** the 548 ft total, 337 ft masonry tower, 37 ft statue, 486 by 470 ft plan and seven stories come from the [ASCE landmark page](https://www.asce.org/about-civil-engineering/history-and-heritage/historic-landmarks/philadelphia-city-hall). Stage heights (clock story 67 ft 8 in, dome 105 ft 7 in), tower base (90 ft square), dome octagon (56 ft), clock centers (361 ft), courtyard (200 ft), story heights and pavilion sizes come from the Turner booklet, *Illustrated Description of Philadelphia's New City Hall* (1901-09), read in the Library of Congress copy's OCR text on [Internet Archive](https://archive.org/details/illustrateddescr00phil). The stage sum closes on the published total within 0.1 m.
- **LiDAR checks:** the tower top measures 166.7 m above ground against 167.0 m published. The pavilion roof peaks measure about 10 m above the booklet's pavilion heights, which probably stop at the roof bases, so the dossier records both and the kit uses the LiDAR for the peaks.
- **Estimates:** the clock-stage width (from the OSM tower part's area) and the dome's top width.
- **Weaker figures:** the 26 ft clock diameter is from Wikipedia; the booklet's digit is garbled in the OCR.
- **Colors:**
  - Marble, granite, mansard, dome, statue and dial colors come from a HABS color photo.
  - The dial is dark teal by day. Lit at night, it was yellow until the LED conversion and is now "creamy white" ([Inquirer, 2018](https://inquirer.com/philly/opinion/commentary/philadelphia-lighting-public-spaces-20180706.html)).
  - Mansard and terrace roofs come from the aerial.
- **Open:** the NPS NHL nomination is a scan nobody has OCR'd yet. It should be checked for the clock diameter and the masonry top.

### One Liberty Place (`tower_stages`)

- **Scope:** One Liberty only; Two Liberty stays as LiDAR.
- **Heights:**
  - 945 ft to the tip ([PhillyVoice](https://phillyvoice.com/30-years-ago-one-liberty-place-reshaped-the-philadelphia-skyline-for-all-time/); CTBUH via Wikipedia agrees).
  - 883 ft to the roof and 784 ft to the top floor ([SkyscraperPage](https://skyscraperpage.com/b133), marked unconfirmed there).
  - A 146 ft crown of four gabled setbacks and a 47 ft mast (Wikipedia, citing a 1987 Inquirer article).
- **Stages:** the stage heights and outlines are OSM's tagged parts: podium 9.65 m, shaft 185 m, gabled setbacks at 220, 228, 240 and 250 m, and the spire base. The LiDAR agrees up to about 255 m; the mast is too thin for it.
- **Colors:** glass and mast colors from a CC BY 3.0 photo by Massimo Catarinella. OSM's `building:colour=#44606D` is recorded too.

### Lincoln Financial Field (`stadium_bowl`)

- **Field:** dimensions and markings from the [2026 NFL Rulebook](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf), Rule 1. That gives a football field, which answers the soccer-lines complaint.
- **Stadium facts:**
  - Footprint and front-row distance from the [stadium facts page](https://www.lincolnfinancialfield.com/stadium-facts/).
  - End-zone video boards from the [Eagles](https://www.philadelphiaeagles.com/news/stadium-revitalization-additional-facts-10306468).
  - Sideline canopies and open end zones from [SAH Archipedia](https://sah-archipedia.org/buildings/PA-02-PH200).
- **Measured on the LiDAR** (no height was published):
  - The field-level area is 135.6 by 91.8 m, about 1 m below the street, with its long axis at 171 degrees.
  - The sideline sectors reach 52.4 m (the canopies) and the end-zone sectors about 42 m.
- **Colors:** turf from the aerial; seats, canopy and facade panels from a CC BY 2.0 aerial photo by Ron Reiring.

### Citizens Bank Park (`stadium_bowl`)

- **Published figures:** fence distances and heights, field depth (23 ft below the street), concourse and roof heights, light towers and scoreboard all come from the Phillies' [Facts, Figures and Fun Features](https://www.mlb.com/phillies/ballpark/information/facts-figures-fun-features).
- **Liberty Bell sign:** 50 ft tall per [Ballparks of Baseball](https://www.ballparksofbaseball.com/ballparks/citizens-bank-park/); Wikipedia says 52 ft.
- **LiDAR:** stand heights by sector. Its field level is about 2.5 m shallower than the published figure, because the ground ring is lower than the street the Phillies measure from.
- **Field:** the diamond stays as the aerial shows it.
- **Colors:**
  - The seats are "Sapphire blue" per the Phillies, sampled from a public-domain photo.
  - Brick, dirt and wall colors come from the same photo.

### Xfinity Mobile Arena (`arena_dome`)

- **Published figures:** no source gives the arena's height or plan. The [2023 renderings release](https://www.xfinitymobilearena.com/news/detail/new-wells-fargo-center-building-renderings) gives the LED boards (just under 35 ft, three of them).
- **Measured on the LiDAR:** the roof is a barrel, 143.7 by 114.4 m with its long axis about 9 degrees east of north. It runs flat at 37.4 m along its length and curves across its width down to about 31 m at the edges.
- **Colors:**
  - Roof from the aerial.
  - Facade colors from a 2019 CC BY 3.0 photo by Jen Smith, which predates the 2024 LED boards and the 2025 purple Xfinity logo.
  - The logo color is an estimate.

### Philadelphia Museum of Art (`colonnade_portico`)

- **Published figures:** none of the sources read gives the plan, heights or column sizes. What they do give:
  - 640 ft breadth ([Billy Penn](https://billypenn.com/2021/05/30/philadelphia-art-museum-gehry-renovations-ghost-station-rocky-steps-energy-efficient/)).
  - 72 steps ([museum press FAQ](https://press.philamuseum.org/faqs)).
  - The north pediment, 12 by 70 ft ([Association for Public Art](https://www.associationforpublicart.org/artwork/north-pediment)).
  - Three-foot blue-glazed roof tiles (*The Mentor*, 1928, [reproduced at quondam.com](https://quondam.com/19/1928.htm)).
- **LiDAR:** gives the roof heights above the terraces.
- **Columns:** eight Corinthian columns are counted in a public-domain photo. Their height (about 20.7 m) and diameter are estimates, scaled from that photo against the LiDAR roof peak.
- **Footprint question:** the L&I outline spans 172.6 m, short of the 640 ft (195 m) corridor. It should be checked for missing wing ends.
- **Open:** the museum archive's 1923 scale drawing of the main-entrance column would replace the estimates.

### Boathouse Row (`gabled_row`)

- **Houses:** 12 buildings covering houses #2-#15. Each has its club, date, architect, style, materials, story count and roof form from the [NHL nomination](https://npgallery.nps.gov/GetAsset/9506b040-fe2b-4eb2-b28b-292c298648e7) (NPS, 1985), with stone types from [HABS PA-1650](https://tile.loc.gov/storage-services/master/pnp/habshaer/pa/pa1100/pa1118/data/pa1118data.pdf).
- **Measured:** body and ridge heights from the LiDAR and roof colors from the aerial. The LiDAR agrees that #9 (Malta) is the tallest, as the nomination says.
- **Outlines:** OSM where it splits the houses, L&I for #2-3 and #7-8.
- **Missing house:** #1 (Plaisted Hall) has no outline near the Row in either dataset and is left out for now.
- **Colors:** wall and trim colors from a CC BY 2.5 photo by Jeffrey M. Vinocur.
- **Outline lights:** their color is an estimate.

### Tacony-Palmyra Bridge (`arch_bascule`, new kit)

- **Kit:** changed from `bridge_tbd` in `selection.json`.
- **Published figures:** total length 3,659 ft, 38 ft width, and 61 ft and 54 ft clearances from the [Burlington County Bridge Commission](https://www.bcbridges.org/tacony-palmyra-bridge/). Eight spans, a 240 ft clear channel and a double-leaf Scherzer rolling lift on stone piers from [NJDOT's historic bridge data](https://www.nj.gov/transportation/works/environment/pdf/Historic_BR_Burlington.pdf), p. 78.
- **Conflicting span lengths:** these come only from secondary sources, which disagree.
  - Arch: 558 ft (Wikipedia, uncited) or 523 ft (PhillyRoads). OSM's arch way is 167.9 m (551 ft), with LiDAR rib returns along all of it.
  - Bascule: 247.5 ft or 260 ft.
- **Measured on the LiDAR** (lower_northeast grid; the east_riverfront grid stops short of the bridge):
  - The arch crown is at 58.74 m NAVD88 and the deck at 22.75 m, a 36.0 m rise.
  - The bascule was closed during the flight.
- **Open:**
  - The bascule's position along the bridge.
  - The paint color: both manifest photos show other subjects, so the steel and pier colors are estimates until a correct photo is picked.
  - A HAER record, if there is one (the automated LoC search was blocked).

## Credits

- OpenStreetMap data © OpenStreetMap contributors, [ODbL 1.0](https://www.openstreetmap.org/copyright).
- LiDAR: City of Philadelphia 2022 classified LiDAR via [PASDA](https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=7154).
- Aerial: City of Philadelphia 2024 3-inch imagery.
- Footprints: City of Philadelphia L&I building footprints (OpenDataPhilly).
- Reference photos are credited in each dossier's `credits`: HABS (public domain), Massimo Catarinella (CC BY 3.0), Ron Reiring (CC BY 2.0), Phillyfan0419 (public domain), Jen Smith (CC BY 3.0), Rgordon6 (public domain) and Jeffrey M. Vinocur (CC BY 2.5).
