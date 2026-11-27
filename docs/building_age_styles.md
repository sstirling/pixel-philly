# Building age and style: could year built improve the map's buildings?

Investigation and proposal, Nov. 22, 2026; gap-fill research and the LiDAR roof measurement added Nov. 23. Nothing here changes the map: no renders, no new version, frozen versions (v14, v17, v18) untouched, raw data unchanged. Any change would go into v19.

**Short answer.** Yes, but year built should be a supporting signal, not the main one. The City's property records already carry a better era signal than the year: the building style code (`building_code_description_new`), with values like `ROW OLD STYLE`, `ROW PORCH FRONT`, `ROW POST WAR`, `TWIN RANCH`, `CAPE` and `ROW MODERN`. The map reads that code today but collapses it into 13 styles, and the renderer then uses the style only to set bay spacing and four on/off bands. Three-quarters of the years are assessor estimates heaped on round numbers (1925, 1920, 1950), so a year by itself mostly tells you the neighborhood, not the building. The cheapest gain is to use the style code more fully, with year as a tiebreaker inside it, and to change wall color, cornice and porch details by era. A pilot on three existing atlas spots can show whether the AI redraw keeps those details.

Contents: [1. The data](#1-the-year-built-data) · [2. How styles are chosen now](#2-how-building-styles-are-chosen-now) · [3. Philadelphia's eras](#3-philadelphias-building-eras-and-what-reads-at-map-scale) · [4. Roof forms from LiDAR](#4-roof-forms-measured-from-the-lidar) · [5. Options](#5-options) · [6. Recommended pilot](#6-recommended-pilot) · [Reproduce](#reproduce-the-numbers)

## 1. The year-built data

### Sources checked

| Source | Age field | In the repo? | Join to map footprints | License |
|---|---|---|---|---|
| Office of Property Assessment (OPA), `opa_properties_public` (Carto SQL API, [OpenDataPhilly](https://opendataphilly.org/datasets/philadelphia-properties-and-assessment-history/)) | `year_built` (text), `year_built_estimate` (`Y`, `N` or empty) | Yes: `data/raw/<area>_opa.geojson`, fetched Oct. 25, 2026, by `scripts/04f_fetch_opa.py`. Both fields are already in `OPA_COLUMNS` (`src/pixelphilly/opa.py:23-35`) | Already joined: footprint `parcel_id_num` → `pwd_parcels.brt_id` → OPA `parcel_number`, then address, then OPA point inside footprint (`src/pixelphilly/facades.py:329-366`) | City of Philadelphia License |
| L&I building footprints, `LI_BUILDING_FOOTPRINTS` ([OpenDataPhilly](https://opendataphilly.org/datasets/building-footprints/)) | None. Fields: `objectid`, `bin`, `address`, `parcel_id_num`, heights, area (checked on `data/raw/atlas_porch_fac_buildings.geojson`) | Yes | — | City of Philadelphia License |
| L&I permits, `permits` (Carto) | No year built, but `typeofwork` "New Construction" / "NEWCON" with `permitissuedate` and `opa_account_num` | No | By `opa_account_num` = OPA `parcel_number` | City of Philadelphia License |
| Philadelphia Architects and Buildings (Athenaeum; see section 3) | Dated events ("BUILT," Builders' Guide notices) for landmarks and some developer blocks; no style or roof fields | No | Address or latitude/longitude from a per-search XML export | All rights reserved; robots.txt bars AI crawlers. Needs the Athenaeum's permission |
| Philadelphia Register of Historic Places (Historical Commission) | Unknown. The OpenDataPhilly pages for historic sites and districts returned 404 on Nov. 22, 2026; an ArcGIS item titled "Philadelphia Register of Historic Places, Properties and Historic Districts" exists but lists no service URL. Not checked further | No | Spatial or address | Unknown |

Two cautions on the permits table: it is useful only for recent buildings (the online records cover roughly the last two decades, so it can check post-2007 years, which are already the best ones), and a `SELECT *` query on it returns contractor and owner names. If it is ever used, name columns explicitly, as `opa.py` does for OPA.

### How good is OPA's year built? (measured)

`scripts/44_year_built_audit.py` reads the 12 map regions' raw files, deduplicates OPA records by parcel number and footprints by object id (regions overlap), and joins footprints with the map's own join. Results are in `output/building_age/year_built_audit.json`. "Plausible" means 1682 to 2026.

**Parcels** (OPA records, excluding vacant land: 541,602):

| Measure | Count | Share |
|---|---|---|
| Plausible year | 540,170 | 99.7% |
| Missing | 432 | 0.1% |
| Year 0 | 972 | 0.2% |
| Out of range (before 1682 or after 2026; e.g., 2027) | 28 | <0.1% |
| Flagged as estimate (`Y`), of plausible | 407,733 | 75.5% |
| Flag empty, of plausible | 132,147 | 24.5% |
| Flagged not an estimate (`N`) | 290 | 0.05% |
| Year ends in 0 or 5 | — | 79.8% (a uniform spread would give 20%) |

The flag is not a quality mark. `N` is almost never used, and the empty-flag years are heaped too: 67.6% end in 0 or 5, against 83.8% for flagged estimates. Commercial and apartment codes never carry the flag (0% "estimated" for `WAREHOUSE`, `APARTMENTS - LOW RISE`, the mixed-use row codes), so their years are no more trustworthy for being unflagged.

**The most common years** (parcels, excluding vacant land): 1925 (114,786; 21.2%), 1920 (81,556; 15.1%), 1950 (45,341; 8.4%), 1915 (33,579; 6.2%), 1940 (24,102; 4.5%), 1900 (20,464; 3.8%). Median: 1925.

**Map footprints** (485,808 in the 12 regions):

| Measure | Count | Share of footprints |
|---|---|---|
| Matched to an OPA record | 484,102 | 99.6% (parcel 480,734; address 2,498; point 870) |
| With a plausible year | 476,936 | 98.2% |
| Year not flagged as an estimate | 118,928 | 24.5% |

So coverage is not the problem; precision is. Whole neighborhoods share one estimated year: 86.7% of matched footprints in Strawberry Mansion are 1915, 93.7% in Girard Estates are 1920, 66.7% in Oxford Circle are 1950, 33.1% in Fishtown–Lower Kensington are 1875. At the map's scale this behaves like a neighborhood-level era label, which is still useful (it varies smoothly and won't make neighboring houses flicker between styles), but it can't tell an 1850s house from its 1920s neighbor where the assessor gave the block one year.

**Era by building, where the year and the style code disagree.** The style code and year usually agree, but not always. Of OPA's 82,458 `ROW POST WAR` parcels, 12,892 (15.6%) have a year from 1905 to 1929, and 7,058 more from 1930 to 1944. Of 139,449 `ROW PORCH FRONT` parcels, 13,670 have a year from 1945 to 1974. `ROW OLD STYLE` (5,458) is the code most likely to mark pre-1880 houses: 1,537 of them have years before 1880.

Footprints by era (matched, plausible year): 1905–1929: 224,627 · 1945–1974: 124,966 · 1930–1944: 63,976 · 2000–2026: 23,753 · 1880–1904: 15,933 · 1975–1999: 14,430 · 1840–1879: 7,538 · before 1840: 1,713. The pre-1880 count is almost certainly too low: Society Hill, Rittenhouse and Washington Square West have years heaped on 1800, 1850, 1875 and 1900.

**Year 2000 and later is the reliable band.** `ROW MODERN` (17,894 parcels, median 2016) has only 16.2% flagged estimates and its years are spread across single years (2017, 2021, 2018 at about 6% each), as you'd expect from real construction dates. New construction is also where the map's look is most wrong today (see section 2).

### Join coverage and caveats

- The join already exists and runs on every region (`scripts/05_build_scene.py:840-910`, `attach_facades`). No new download is needed to use year built; it is in the raw files.
- The scene build keeps only the compact facade spec, not the year. A v19 change would need `facades.facade_spec` to read the year (as `modern_glass_record` already does, `facades.py:177-194`).
- OPA's year is wrong for some big public buildings (City Hall is recorded as 2015; noted at `facades.py:24-25`). Any era rule should leave landmarks, institutional and tall buildings alone or use the aerial color, as the glass rule does.
- A facade remodel doesn't change the year. Many 19th-century rows got Permastone, stucco, aluminum awnings or new storefronts in the 20th century, and many 1920s rows were refaced after 2000. Year gives the shell's age, not today's face.

## 2. How building styles are chosen now

The building's look comes from three places, and only one of them uses the property record.

**Roofs come from the aerial photo.** Roofs are flat or LiDAR-stepped prisms with the City's 2024 aerial draped on them, median-filtered about 1 m (`render/render.js:9-12`, `roofGeom` at `render/render.js:203-205`; `README.md` step 2). There are no roof-type sprites or textures and no pitched, mansard or gable geometry. A gable or mansard shows only if the LiDAR steps happen to catch it and the photo shows its slope.

**Walls come from the property record, drawn procedurally** (`src/pixelphilly/facades.py`, called from `scripts/05_build_scene.py:840-910`):

1. `style_of` (`facades.py:121-174`) turns OPA's `building_code_description_new` (or the older `building_code_description`) into one of 13 styles (`facades.py:37-38`): `row_porch`, `row_typical`, `row_postwar`, `row_modern`, `river_row`, `twin`, `detached`, `apartment_low`, `mixed_storefront`, `warehouse`, `office_tower`, `institutional`, `other`.
2. The material comes from the last word of the old code (MASONRY → brick, FRAME, STONE, METAL; `parse_building_code`, `facades.py:80-118`), else `general_construction`, else OpenStreetMap.
3. Wall color: OSM `building:colour`, else OSM material, else one of six brick reds (or stone, frame, metal, glass palettes) picked by a hash of the building id, plus ±12 per channel (`PALETTES`, `facades.py:51-58`; `facade_spec`, `facades.py:236-296`). Tall non-rowhouse masonry takes its aerial color.
4. Bands: storefront for `mixed_storefront`, porch for `row_porch`, cornice for every `row_*` style plus `river_row` and `mixed_storefront`, glass for modern towers (`facades.py:292-295`). Bay spacing per style (`SPACING_M`, `facades.py:61-63`).
5. Year built is used once: to allow glass on a high-rise office built 1975 or later by a recorded year (`GLASS_YEAR`, `facades.py:47`; `modern_glass_record`, `facades.py:177-194`).

The shader (`render/render.js:263-311`) paints a window grid, sills, storefront, porch, cornice and glass. The style id itself is used only as an on/off switch (`if (vFacade.x > 0.5)`, `render/render.js:311`); everything visible comes from color, floor height, bay spacing and the four band flags.

**What gets lost.** The 13 styles throw away era information OPA already has (from the audit's footprint counts):

- `row_typical` holds `ROW TYPICAL` (106,442), `ROW OLD STYLE` (5,342) and `DOWNTOWN ROW` (1,796): an 18th-century Society Hill house and a 1920 South Philadelphia row are drawn the same.
- `twin` holds `TWIN CONVENTIONAL` (27,858), `TWIN POST WAR` (21,284), `TWIN OLD STYLE` (11,550), `TWIN RANCH` (7,427) and smaller codes.
- `detached` holds `CONVENTIONAL`, `CAPE`, `COLONIAL`, `SPLIT LEVEL`, `OLD STYLE`, `RANCH`, `BUNGALOW`, `TUDOR`.
- `row_postwar` (67,798 footprints) and `row_modern` (14,574) get a cornice band, which postwar and new-construction rows mostly don't have, and no garage or setback.
- Every brick building draws from the same six reds, whatever its era.

**The AI redraw keeps these cues.** Comparing renders with the drawn map on the facade atlas spots (`output/atlas_passyunk_fac/` and `output/atlas_porch_fac/`, `renders/` against `redraws/qwen_joint_light8_fac1/`) shows the redraw following wall hue, window rows and porch roofs closely. That matters: a change to the procedural facade will show in the drawn map. The redraw prompt is a single sentence for everything ("Redraw this render as isometric pixel art in the pixel philly style"; `README.md` step 5), and the style LoRA was trained on 141 Old City renders (`qe2511_oldcity_r16_v1`), so it has seen few postwar or new-construction blocks.

The `output/atlas_*_fac` folders are the facade test spots, not texture atlases: `atlas_passyunk_fac` (East Passyunk rows), `atlas_porch_fac` (Allegheny West porch fronts), `atlas_twin_fac` (West Philadelphia twins), `atlas_indhall_fac` (Independence Hall and Society Hill), `atlas_cityhall_fac`, `atlas_northeast_fac` (Northeast twins and singles), `atlas_wissahickon_fac` and `atlas_airport_fac` (`config/atlas_*_fac.json`; `docs/history.md`, "Façades from property records").

## 3. Philadelphia's building eras and what reads at map scale

At 0.293 m per pixel a 16-foot rowhouse front is about 16 px wide and a two-story wall about 20 px tall on screen, and the camera looks down at 45°, so roofs take up more of the picture than walls. What can read: roof form (flat, side gable, mansard or false-front slope, deck), a cornice line, a porch roof, bays, the wall's main color, window rows and widths, setbacks and front yards. Brick bond, brackets and lintels are one or two pixels at most.

Sources were read in full by a research subagent on Nov. 22, 2026; page numbers refer to the PDFs. Short names:

- **Rowhouse Manual**: City of Philadelphia, [*Philadelphia Rowhouse Manual*](https://www.phila.gov/media/20190521124726/Philadelphia_Rowhouse_Manual.pdf) (2008). Its type table (pp. 6–8) sorts houses by era and size.
- **PHC Old City**: Philadelphia Historical Commission, [Old City Historic District inventory](https://www.phila.gov/media/20190213125332/Historic-District-Old-City.pdf) (2003), with a style-by-era narrative.
- **PHC Spring Garden**: [Spring Garden Historic District inventory](https://www.phila.gov/media/20190213131221/Historic-District-Spring-Garden.pdf) (2000).
- **PHC Girard Estate**: [Girard Estate Historic District inventory](https://www.phila.gov/media/20190213125232/Historic-District-Girard-Estate.pdf) (1999).
- **PHC Tudor East Falls**: [Tudor East Falls Historic District](https://www.phila.gov/media/20190213131230/Historic-District-Tudor-East-Falls.pdf).
- **PHC Blakemore St.**: [Blakemore Street Historic District nomination](https://www.phila.gov/media/20250813113109/Historic-District-Blakemore-St-final.pdf) (2025).
- **PHC Diamond St.**: [Diamond Street Historic District manual](https://www.phila.gov/media/20190213121705/Historic-District-Diamond-Street-Manual.pdf).
- **PHC SE Spruce Hill**: [Southeast Spruce Hill Historic District](https://www.phila.gov/media/20241023081326/Historic-District-Southeast-Spruce-Hill.pdf).
- **PHC Victorian Roxborough**: [Victorian Roxborough Historic District](https://www.phila.gov/media/20250116085445/Historic-District-Victorian-Roxborough-amended.pdf).
- **SAH**: George E. Thomas, *Buildings of Pennsylvania*, on SAH Archipedia: [Philadelphia County essay](https://sah-archipedia.org/essays/PA-02-0001) and the entries linked below.
- **EGP**: Encyclopedia of Greater Philadelphia: [Row Houses](https://philadelphiaencyclopedia.org/essays/row-houses/), [Twin Houses](https://philadelphiaencyclopedia.org/?p=35241), [Office Buildings](https://philadelphiaencyclopedia.org/?p=17467), [Northeast Philadelphia](https://philadelphiaencyclopedia.org/?p=8039), [Streetcar Suburbs](https://philadelphiaencyclopedia.org/essays/streetcar-suburbs/), [Brickmaking](https://philadelphiaencyclopedia.org/essays/brickmaking-and-brickmakers/).
- **PHMC**: Pennsylvania Historical and Museum Commission, [architectural style guide](https://www.phmc.state.pa.us/portal/communities/architecture/styles/), for general date ranges.

Not used in the first pass, because they weren't opened: Murtagh's 1957 *JSAH* article on the Philadelphia row house, HABS records, PhilaPlace. Hidden City and the Athenaeum's Philadelphia Architects and Buildings were checked in the Nov. 23 gap-fill below. Several PHC district manuals (Society Hill, Rittenhouse-Fitler, Parkside, Greenbelt Knoll) are scanned images with no text and weren't read.

**Traits common to most eras.** Most rowhouse roofs look flat but slope gently to a drain; some are pitched (Rowhouse Manual, p. 16). Masonry party walls rise above the roofline as fire breaks (EGP Row Houses), which reads as thin ridges between roofs. Brick dominates: by 1800 about 80% of houses were brick, and by 1850 the city led in pressed brick for fronts (EGP Brickmaking). Most rows sit a few steps above the sidewalk (Rowhouse Manual, p. 13).

### Era table

The last column says how the map's data could identify each era. "Year" is OPA `year_built`, whose limits are in section 1.

| Era (approx. dates) | Where | Traits that read at map scale | How the data finds it |
|---|---|---|---|
| **Georgian and Federal rows, trinities** (c. 1700–1820s) | Old City, Society Hill, Queen Village, Washington Square, Kensington; Elfreth's Alley (c. 1724–1811 per PHC Old City) | 2½–3½ stories, two or three bays; **side-gable or gambrel roof with dormers**, ridge parallel to the street; trinities about 16 ft or less on a side, often on rear courts; a **pent eave** (small shed roof between first and second floors) on earlier Georgian houses; Flemish-bond red brick, darker and mottled (glazed headers) on older houses, flatter and brighter red on Federal ones; white marble stoops and trim on Federal houses | `ROW OLD STYLE` plus year before 1840; few footprints by year (1,713 citywide), because years in these districts are heaped on 1800 and 1900 |
| **Greek Revival** (c. 1820–1850s) | Old City (about 150 buildings, many warehouses on Church and N. Front streets) | Plainer flat brick fronts, white marble water table, lintels and sills; gabled roofs with dormers on houses; warehouses 3–4 stories, 2–3 bays, stone ground floor, windows shrinking floor by floor | Year 1820–1859 with `ROW OLD STYLE`, `ROW TYPICAL` or a warehouse code |
| **Italianate, brownstone, Second Empire** (c. 1850–1885) | Spring Garden, Rittenhouse, early West Philadelphia (Sloan's twins), Old City commercial streets | **Flat roof behind a heavy bracketed wood cornice** (the strongest trait); 3 stories, 2 bays most common in Spring Garden; tall narrow windows; brownstone fronts in Rittenhouse, otherwise brownstone at the base and trim; Second Empire adds a **steep slate mansard with dormers** above the cornice; about one Spring Garden row in five is painted brick | Year 1840–1884 with a row or twin code; `ROW OLD STYLE` |
| **Late Victorian: Queen Anne, Romanesque, eclectic** (c. 1875–1905) | North Philadelphia west of Broad (Diamond Street, 1875–1900), Spruce Hill, Rittenhouse | 3 stories, 18–20 ft wide on Diamond Street; projecting bays, corner towers with conical roofs, cross gables, porches; mixed materials read as color bands; brownstone, serpentine (green), marble fronts; Spruce Hill twins in **yellow-tan and purplish-brown brick** with pressed-metal cornices and porch fronts | Year 1875–1904; `TWIN OLD STYLE` in West Philadelphia |
| **Two-story workers' rows and porch fronts** (c. 1870s–1925) | South, North, West Philadelphia, Manayunk; porch fronts in West Philadelphia, Strawberry Mansion, Girard Estate (1906–1916) | **2-story flat-roofed brick front with a pressed-metal cornice strip**, light lintels, low stoop; porch fronts raised a few feet with a full-width porch roof and often a second-floor bay; many porches enclosed; **orange, "Pompeiian" and buff brick** join red (Girard Estate) | Already in the map: `ROW TYPICAL`, `ROW PORCH FRONT`, `TWIN CONVENTIONAL`; year mostly 1905–1929 (224,627 footprints) |
| **Interwar Tudor and Colonial Revival rows, early garage rows, "daylighters"** (c. 1914–1940s) | Cobbs Creek (1914), Garden Court, East Falls (1929–31), Mount Airy (1926–27), Mayfair, Lawndale, Northwood (1920s–early '30s) | **False-front sloped roof** (slate "mansard" or hip across the front over a flat roof) on Tudor rows; stepped parapet gables; brick or fieldstone fronts, some stucco and half-timber; **setbacks with small front lawns**; garages at the rear or under the house from an alley | Year 1925–1944 with `ROW PORCH FRONT`, `ROW TYPICAL`, `TWIN CONVENTIONAL`; not separable by code |
| **Postwar Airlites, garage rows and twins** (1945–1970) | Near Northeast (Oxford Circle, Rhawnhurst, Lawndale), Far Northeast (Bustleton, Somerton, late 1950s–70s), Southwest, Roxborough, East Mount Airy | **Two-story brick rows with an elevated front yard and entry**, a one-car garage at the lower level (usually reached from a rear alley; some 1960s twins faced garages to the street); Far Northeast Cape Cods and ranches with their own yards. Brick colors and roof forms for these rows weren't found in a citable source | `ROW POST WAR` (82,458 parcels), `TWIN POST WAR`, `TWIN RANCH`, `CAPE`, `RANCH`, `SPLIT LEVEL`; year 1945–1974 |
| **Industrial lofts and warehouses** (1830s–1930) | Old City, Callowhill | 19th century: 3–5 stories, narrow, stone ground floor; c. 1900–1929 "Red & White Industrial": red brick on a concrete frame with **white terra-cotta trim and large industrial windows**; 1910–1930 "Tapestry Brick": brown, buff or orange brick with a **shaped central parapet** | `WAREHOUSE`, industrial codes; year (unflagged, often heaped) |
| **Early skyscrapers, Art Deco** (1890s–1930s) | Center City (Land Title 1898, Widener 1914; Art Deco on the 1400–1600 blocks of Walnut) | Flat roofs, piers and spandrels, masonry and terra cotta, 6–20 stories; Art Deco stepped setbacks | Mostly tall: the map already keeps their aerial color; LiDAR gives the setbacks |
| **Modernism and Brutalism** (PSFS 1932; 1950s–70s) | Penn Center (from 1952), Society Hill Towers (1962–64), 1700 Market (1968), Centre Square (1973) | Flat roofs, horizontal window bands, smooth gray or buff concrete; slab towers on plazas; Pei's brick townhouses with concrete window heads in Society Hill | Year 1930–1974 with apartment, office or condo codes; tall ones are already aerial-colored |
| **Glass towers** (1987 on) | West Market Street (One Liberty Place 1987 onward), Comcast Center (2008), Cira Centre | Glass curtain wall | Already handled: `modern_glass_record`, year ≥ 1975, recorded year |
| **New-construction infill rows** (2000s–2020s) | Fishtown, Point Breeze, Graduate Hospital, Northern Liberties, Francisville (by the audit: 15–42% of footprints built 2000 or later) | 3–4 stories, often **a story above older neighbors**; wood frame clad in **metal, vinyl, stucco or composite panel**, brick mostly as trim; **full-height boxy bays**; **roof decks** with railings and stair penthouses; some outlying infill with front garages | `ROW MODERN` (median year 2016; only 16.2% estimates); `RES CONDO ... MAS+OTH` with year ≥ 2000 |
| **Northwest stone** (1700s–1930s) | Germantown, Chestnut Hill, Mount Airy, Roxborough | **Gray Wissahickon schist** (mica-flecked) instead of red brick; stone houses in gardens; stuccoed stone and porches in Roxborough | Neighborhood plus OPA material `STONE`; the map already has a stone palette |

Era sources, in table order: Rowhouse Manual pp. 6–8, 10–11, 13–14, 16–17; PHC Old City pp. 1–11 and its 20th-century commercial sections; SAH [Elfreth's Alley](https://sah-archipedia.org/buildings/PA-02-PH2) and [200 block of Delancey](https://sah-archipedia.org/buildings/PA-02-PH20); PHMC [Georgian](https://www.phmc.state.pa.us/portal/communities/architecture/styles/georgian.html), [Federal](https://www.phmc.state.pa.us/portal/communities/architecture/styles/federal.html), [early Classical Revival](https://www.phmc.state.pa.us/portal/communities/architecture/styles/early-classical-revival.html); PHC Spring Garden; SAH [Rittenhouse](https://sah-archipedia.org/essays/PA-02-0001-0010), [West Philadelphia neighborhoods](https://sah-archipedia.org/essays/PA-02-0001-0016), [21st and Spruce](https://sah-archipedia.org/buildings/PA-02-PH90); PHMC [Italianate](https://www.phmc.state.pa.us/portal/communities/architecture/styles/italianate.html), [Second Empire](https://www.phmc.state.pa.us/portal/communities/architecture/styles/second-empire.html); PHC Diamond St. pp. 4–5; PHC SE Spruce Hill; SAH [North of Rittenhouse](https://sah-archipedia.org/essays/PA-02-0001-0011); PHMC [Queen Anne](https://www.phmc.state.pa.us/portal/communities/architecture/styles/queen-anne.html), [Romanesque Revival](https://www.phmc.state.pa.us/portal/communities/architecture/styles/romanesque-revival.html); PHC Girard Estate pp. 2–3; EGP Twin Houses and Streetcar Suburbs; PHC Tudor East Falls; PHC Blakemore St. p. 15; SAH [East Falls](https://sah-archipedia.org/essays/PA-02-0001-0014); EGP Northeast Philadelphia; WHYY on [Callowhill](https://whyy.org/articles/gritty-callowhill-recognized-national-historic-district); PHMC [Commercial](https://www.phmc.state.pa.us/portal/communities/architecture/styles/commercial.html), [Art Deco](https://www.phmc.state.pa.us/portal/communities/architecture/styles/art-deco.html), [International](https://www.phmc.state.pa.us/portal/communities/architecture/styles/international.html); EGP Office Buildings; SAH [West of Broad](https://sah-archipedia.org/essays/PA-02-0001-0009), [PSFS](https://sah-archipedia.org/buildings/PA-02-PH46), [Penn Center](https://sah-archipedia.org/essays/PA-02-0001-0012), [Society Hill Towers](https://sah-archipedia.org/buildings/PA-02-PH22); WHYY, ["We don't build them like we used to"](https://whyy.org/segments/we-dont-build-them-like-we-use-to-why-new-houses-arent-made-of-brick/) (2019); Billy Penn, [on new rowhomes](https://billypenn.com/2016/08/30/how-i-got-to-be-ok-with-phillys-ugly-new-rowhomes-commentary/) (2016); SAH [Germantown](https://sah-archipedia.org/essays/PA-02-0001-0017), [Chestnut Hill](https://sah-archipedia.org/node/5684); PHC Victorian Roxborough.

**Gaps.** No source found uses "Wissahickon style" for a rowhouse type, so this report doesn't. "Airlite" and "daylighter" are used for 1920s houses (PHC Blakemore St.) and for a type SAH says peaked in the 1950s, so the term spans both eras. The Rowhouse Manual's "Porchfront" entry describes a lower-level garage, like its postwar entry; that looks like an error in the manual and isn't relied on here. No citable text source gave brick colors or roof forms for postwar Northeast rows; the Nov. 23 gap-fill below found roof forms in dated photos, but not colors.

**Remodels.** The Rowhouse Manual (pp. 11, 13, 14, 17) shows Permastone and stucco over brick, aluminum-wrapped or removed cornices, aluminum awnings and enclosed porches across all eras. PHC inventories record Tapestry Brick fronts added to early-1800s buildings and slate replaced by asphalt. Year built describes the original shell; an era look will be wrong for a share of every era, and nothing in the City's data says which.

### Gap-fill research (Nov. 23, 2026)

A second pass looked for the gaps above in other sources. Text sources on postwar roofs and colors are still thin. The best new evidence is dated, captioned *Evening Bulletin* photos (1951–1980) in Temple University Libraries' digital collections (collection `p15037coll3`; item pages are `https://digital.library.temple.edu/digital/collection/p15037coll3/id/<ID>`). Temple's rights note limits them to private study and research, so they are cited here, not reproduced; captions that name private sellers or buyers are left out. Roof readings from these photos are interpretation of black-and-white pictures, about two dozen of them, not a sample. Two were checked by eye for this report (IDs 42403 and 90729).

**Roofs on 1920s–1960s Northeast rows and twins: a slope across the front over a flat roof.**
- A 1978 photo captioned "Airlite rowhouse" (Ashville Street, Mayfair; ID 42403) shows a two-story brick front with a **shingled slope across the top of the front wall**, broken by **light party-wall caps** between houses, over a raised basement and a front lawn with a hedge.
- A 1973 aerial of Northeast rows (ID 90729) shows **long rows of dark, flat roofs** with small vents, **front lawns and walks on one side and paved rear drives lined with parked cars on the other**.
- The same front-slope pattern appears in Mayfair, Oxford Circle, Olney, Rhawnhurst, Parkwood and Morrell Park photos from 1974–1980 (IDs 7589, 43636, 7471, 24197, 43191, 7514 and others), sometimes with a front gable or dormers, sometimes wrapping a corner house's side.
- Interwar Mayfair and Olney rows also show **clay-tile pent roofs over box bays**, **stucco upper stories over brick**, and stone first floors (IDs 7586, 42393, 43812).
- A late-1960s Korman Corp. townhouse model (Chalfont Drive and Academy Road, 1969) has **no front slope**: a flat or low roof with a plain fascia.
- An 1894–95 precedent supports drawing ornamental fronts over flat roofs: the PHC [Gardiner-Poth nomination](https://www.phila.gov/media/20220824151527/Historic-District-Gardiner-Poth.pdf) says its Flemish gables are ornamental and all the roofs are flat.

This matters for the map. Seen from 45° above, a front slope is a visible strip along the front edge of every roof in a row, and it would set Northeast and interwar blocks apart from South Philadelphia's flat-cornice rows. It is also mostly a roof-edge detail, not a new roof shape, so it's cheaper than full roof geometry (see section 5). Section 4 tests it against the LiDAR.

**Singles and twins in the Far Northeast.** The City Planning Commission's [Far Northeast technical memos](https://www.phila2035.org/_files/ugd/32cb1b_db44d3afca034813b497bc47d6bd40cb.pdf) (August 2016, p. 84) describe the district as mostly detached and semi-detached homes with front-loading garages. From 2010–2014 ACS 5-year estimates (no margins of error given), the memo reports a median year built of 1967 for the district against 1944 citywide. The PHMC postwar field guide gives roof forms: [ranches](https://www.phmc.state.pa.us/portal/communities/pa-suburbs/field-guide/ranch.html) have long, low hipped or gabled roofs with an attached garage or carport; [split-levels](https://www.phmc.state.pa.us/portal/communities/pa-suburbs/field-guide/split-level.html) have low-pitched roofs, a garage in the lowest level, and often brick below and siding above; [Cape Cods](https://www.phmc.state.pa.us/portal/communities/pa-suburbs/field-guide/cape-cod.html) have steep roofs with dormers. Bulletin photos show a twin ranch with a hipped roof and stone front (Solly Avenue, 1978) and Rhawnhurst twins with shingled front-and-side slopes, gables in siding and stone-veneer fronts (1972–73). The Encyclopedia's [Automobile Suburbs](https://philadelphiaencyclopedia.org/essays/automobile-suburbs/) essay notes split-levels with front garages and driveways in Sun Valley.

**Garages and setbacks by era.**

| Era | Garage | Front | Sources |
|---|---|---|---|
| 1910s–1920s auto suburbs (Cobbs Creek, Garden Court) | Rear alley, under the house or detached | Enclosed sunporches in front at Garden Court | EGP [Automobile Suburbs](https://philadelphiaencyclopedia.org/essays/automobile-suburbs/); [PhillyHistory blog on Garden Court](https://blog.phillyhistory.org/index.php/2015/12/clarence-siegels-garden-court-the-rowhouse-meets-the-automobile/) (2015) |
| 1920s–1950s rows (Mayfair, Oxford Circle, Cedarbrook) | Rear alleys and drives | Raised stoops, lawns | Hidden City, [field guide part one](https://hiddencityphila.org/2012/09/field-guide-to-new-row-house-construction-part-one/) (2012); Bulletin aerial (1973) |
| Late 1950s–1970s rows (Parkwood, Morrell Park, Far Northeast) | **Front garage at grade under a raised entry** | Low brick planter walls, small lawns | Bulletin photos (1973–78); City Planning Commission memo |
| Far Northeast singles | Attached, side or under-house | Own lawn all around | PHMC field guide |
| New construction | Front garages discouraged on most streets | — | Hidden City field guide; Penn's [Rowhouse City](https://www.design.upenn.edu/sites/default/files/uploads/Rowhouse%20City%20Program_web.pdf) program (2022) mentions garage conversions in Queen Village |

Hidden City's [architecture of Wissahickon](https://hiddencityphila.org/2012/01/wissahickon-urban-suburban-midcentury-victorian/) piece (2012) dates the Airlite type to the 1920s–1960s: earlier examples had alleys, later ones put garages up front, and both had generous front yards. That matches the photos. Setback depth in feet isn't in any source found; it can be measured from footprints and parcels.

**Wall materials.** No text source names brick colors for postwar rows, and the photos are black and white. They show stone fronts or stone first floors across eras (Oxford Circle, Rhawnhurst, Olney, East Mount Airy), cast-stone trim (Mayfair), stucco upper stories (Olney, Mayfair), siding gables, and **aluminum awnings on most Northeast houses**. Postwar brick hue has to come from current photos or the 2024 aerial. For new construction, Hidden City reports [black and charcoal brick](https://hiddencityphila.org/2015/04/many-ways-to-skin-a-row-house/), standing-seam metal and zinc upper floors ([field guide part four](https://hiddencityphila.org/2012/11/field-guide-to-new-row-house-construction-part-four/), 2012).

**Northwest stone.** The PHC [Awbury Historic District nomination](https://www.phila.gov/media/20241211152902/Historic-District-Awbury.pdf) (East Germantown) notes mostly gabled roofs and local stone; a tally of its 2006 inventory gives 25 stone, 3 brick and 3 stucco walls, and mostly asphalt roofs where recorded (slate is now rare). The *Chestnut Hill Local* ([2020](https://chestnuthilllocal.com/stories/in-celebration-of-international-rock-day,14662)) describes Wissahickon schist as glittery gray to brown. East Mount Airy twins in 1974 Bulletin photos have stone fronts, half-timbered Tudor front gables and front lawns.

**Terms.** "Airlite": see above; Bulletin captions use it for Mayfair houses in 1978. "Daylighter": no source beyond the PHC Blakemore St. nomination. "Straight-through": no reliable definition found. "Wissahickon" is a neighborhood and a stone, not a house type in any source found.

**New-construction roofs.** The City's zoning FAQ [PZ_020](https://www.phila.gov/media/20221221095545/PZ_020_FAQ_Height-and-Area-Limitations-for-Rooftop-Structures.pdf) (December 2022) lists roof decks with railings and access structures among rooftop exceptions; the code text itself (amlegal) returned 403, so setback and height limits weren't confirmed.

**Still open.**
- How many postwar and interwar rows have a front slope versus a plain flat eave. The LiDAR should show it: a front slope is a 1–2 m band along the street edge that sits lower than a parapet would.
- Postwar brick colors.
- Original roof materials (slate, asbestos-cement or asphalt shingles).
- Not read: PHC nominations for Overbrook Farms, French Village, Gates Street and 6633 Ardleigh Street (over the fetch tool's size limit; a direct download got a 403), the City's Greenbelt Knoll PDF (scanned), NPS NPGallery files for Garden Court and the Cobbs Creek Automobile Suburb district (placeholders only).

### Philadelphia Architects and Buildings (PAB)

[PAB](https://www.philadelphiabuildings.org/pab/), run by the Athenaeum of Philadelphia, was checked on Nov. 23, 2026 (about 25 pages, opened one at a time).

- **What it records:** who designed or built a project, where and roughly when. Its home page lists more than 267,734 projects, 26,795 architects, engineers and contractors, and more than 164,996 images. A project record has building type, client, address, architects, a chronology of dates with sources (for example "c. 1916 BUILT, source: PHMC") and citations. **It has no style, material, roof or story fields** in any record opened ([example](https://www.philadelphiabuildings.org/pab/app/pj_display.cfm/276426)).
- **Search and export:** no style, date or neighborhood filter. Each results page can be exported as XML, with project id, type, dated events, address and latitude/longitude (some geocoded only to an intersection). There is no bulk download or API.
- **Rights:** "All rights reserved"; images belong to the contributing institutions and reuse needs their permission. PAB's [robots.txt](https://www.philadelphiabuildings.org/robots.txt) blocks ClaudeBot and other AI crawlers from the whole site and asks for reference use only, with no AI training. **Any automated use for Pixel Philly would need the Athenaeum's permission first** (contact on the [About page](https://www.philadelphiabuildings.org/pab/about.cfm)).
- **Postwar builders:** [Korman Corporation](https://www.philadelphiabuildings.org/pab/app/ar_display.cfm/118069) has one project, [Parkwood Manor](https://www.philadelphiabuildings.org/pab/app/pj_display.cfm/917054) ("housing development, 2200 rowhouses," c. 1962), and [35 photo holdings from 1968–70](https://www.philadelphiabuildings.org/pab/app/ar_display_projects.cfm/118069) in the Athenaeum's Lawrence S. Williams, Inc. Collection (Oxford Homes, Brookwood, Penrose Park and others). Those photos are the best visual evidence in PAB for late-1960s roofs and brick, but they are view-only (high resolution by $40-a-year subscription) and not reusable. [Orleans Builders](https://www.philadelphiabuildings.org/pab/app/ar_display.cfm/757190) has no projects listed; [A. P. Orleans](https://www.philadelphiabuildings.org/pab/app/ar_display_projects.cfm/164145) and [Hyman Korman](https://www.philadelphiabuildings.org/pab/app/ar_display_projects.cfm/159031) have only 1935–1940 Builders' Guide notices.
- **Interwar builders:** [E. Allen Wilson](https://www.philadelphiabuildings.org/pab/app/ar_display.cfm/104605) (1874–1940; biography by Sandra L. Tatman) has 38 projects and 658 references, mostly West Philadelphia block ranges with PHMC "built" dates. [John H. McClatchy](https://www.philadelphiabuildings.org/pab/app/ar_display_projects.cfm/159567) and [Clarence R. Siegel](https://www.philadelphiabuildings.org/pab/app/ar_display_projects.cfm/107567) (Garden Court) have a few records each. None describe roofs or materials.
- **A linked source with descriptions:** PAB's Builders' Guide citations link to the Athenaeum's scanned, full-text-searchable [*Philadelphia Real Estate Record and Builders' Guide*](https://philageohistory.org/BuildersGuide/), January 1886 to November 1940. Its weekly notices are where stories, brick and porches would be described for pre-1941 developments. It stops before the postwar era, and its searches weren't tested.
- **Checking OPA years:** only in spots. PAB has dates for landmarks and some developer blocks, often "c." and for a whole block range; Builders' Guide dates are plan or contract dates, so they are lower bounds. Useful for a sample check of the pilot spots, not citywide.

**Verdict:** PAB helps footnote who built a block and when, and its photo holdings could guide a person picking a palette. It isn't usable as a data source for the map.

## 4. Roof forms measured from the LiDAR

Measured Nov. 23, 2026, with `scripts/45_roof_forms.py` (pitch and front type for every footprint) and `scripts/46_roof_front_profiles.py` (averaged front-to-back profiles). Both read only the cached 0.5 m surface grids the scene builder already made from the City's 2022 LiDAR (`data/processed/<area>_lidar_grid.npz`; PASDA 7154, flown March 29, 2022, leaf-off) and the raw footprint, OPA and street files. Outputs are in `output/building_age/`: one CSV per area (object id, OPA code, year, measurements, class; no addresses), `roof_forms_summary_regions.json`, `roof_forms_summary_atlas.json` and `roof_front_profiles.json`. These are measurements of the 2022 surface, not a survey; the thresholds are listed in the scripts and were checked by eye on sample sheets, not tuned against ground truth.

**Method.**
- **Pitch.** A plane is fit to every 2.5 m patch of roof (inside the footprint, 0.6 m in from the walls). Patches that fit well are flat (under 8°) or sloped (15° to 60°). Patches that don't fit are steps, parapets or rooftop equipment, and they're left out. A first version counted steep cells directly, and the step from a rowhouse's main roof down to its rear ell made 35% of East Passyunk's rows look partly pitched. A roof is "pitched" when at least 55% of its planar patches slope.
- **Front.** On the street-facing side, the band 0.25–1.75 m behind the front wall is compared with the roof 2.75–6 m back. A story-high drop is "lower front" (usually a porch roof). A front band 0.3 m or more higher is "raised" (a cornice or parapet).
- **Alignment check.** In every region, the median measured roof height is within 0.24–0.82 m below the City's recorded `approx_hgt`, so grids and footprints line up.

**Coverage.** 468,231 of the 12 regions' 485,808 footprints (deduplicated) fall inside the grids. Of the 450,540 with a measurable roof, **82.8% are flat, 2.9% mixed and 14.2% pitched (64,131 buildings)**. The rest are unclear (12,173), under 2 m tall (5,230) or too small (288).

**Pitched roofs follow the OPA style code closely.**

| OPA code | Footprints | Pitched | | OPA code | Footprints | Pitched |
|---|---|---|---|---|---|---|
| COLONIAL | 4,598 | 91.4% | | ROW MODERN | 13,941 | 21.2% |
| SPLIT LEVEL | 4,097 | 91.2% | | ROW OLD STYLE | 5,279 | 18.3% |
| CAPE | 5,511 | 84.8% | | TWIN RANCH | 7,376 | 12.8% |
| RANCH | 3,716 | 84.7% | | ROW POST WAR | 67,755 | 6.5% |
| OLD STYLE (detached) | 3,749 | 70.9% | | ROW TYPICAL | 102,615 | 6.0% |
| CONVENTIONAL (detached) | 8,283 | 66.6% | | TWIN POST WAR | 20,761 | 5.5% |
| ROW RIVER ROW | 3,476 | 52.3% | | ROW PORCH FRONT | 116,287 | 0.5% |
| TWIN OLD STYLE | 10,937 | 33.1% | | | | |
| TWIN CONVENTIONAL | 26,177 | 21.7% | | | | |

By map style, pitched roofs are mostly on `detached` (22,590), `twin` (12,322), `apartment_low` (7,945), `row_typical` (7,197) and `row_postwar` (4,374).

By neighborhood, the most pitched are:
- Bustleton 56.6%, Chestnut Hill 55.8%, Society Hill 52.4%, Torresdale 50.6%, Somerton 49.2%, Mount Airy West 47.3%, Queen Village 42.9%, Washington Square West 42.0%.

The least pitched are Lower Moyamensing and West Passyunk (0.1% each) and Mayfair (0.7%).

Society Hill, Queen Village and Washington Square West are where the Georgian and Federal side gables are (section 3). Sample sheets of Northeast "pitched" roofs show clear gable and hip planes on most. A few were tree branches over the roof, and those count as errors. `ROW MODERN` at 21% pitched wasn't checked by eye; roof-deck railings and stair penthouses may be read as slopes there.

**Front slopes are real but at the LiDAR's limit.** Per-building "front slope" calls came out at 8–14% in Northeast neighborhoods against 1–2% in South Philadelphia, but single-building sheets for "slope" and "level" roofs look alike. Averaging profiles over thousands of flat-roofed houses separates them. The "dip" test asks whether the roof 0.5–1 m behind the front wall sits at least 0.3 m below the roof behind it:

| Group (flat roofs) | Houses | Median height 0.5–0.75 m behind front, vs. roof 3–6 m back | Front dips ≥ 0.3 m | Front higher |
|---|---|---|---|---|
| Mayfair, `ROW POST WAR` | 3,852 | −0.50 m | 52.4% | 24.9% |
| Parkwood Manor, `ROW POST WAR` | 3,700 | −0.52 m | 53.3% | 15.2% |
| Oxford Circle, `ROW POST WAR` | 3,909 | −0.25 m | 47.4% | 26.7% |
| Rhawnhurst, `TWIN POST WAR` | 1,339 | −0.16 m | 47.4% | 26.1% |
| Morrell Park, `ROW POST WAR` | 2,178 | −0.06 m | 42.1% | 21.2% |
| Lower Moyamensing, `ROW TYPICAL` | 3,971 | +0.19 m | 25.8% | 62.4% |
| Point Breeze, `ROW TYPICAL` | 3,980 | +0.22 m | 20.7% | 69.3% |
| Strawberry Mansion, `ROW TYPICAL` | 3,855 | +0.23 m | 21.3% | 73.6% |

South and North Philadelphia rows are higher at the front: flat roofs that drain to the rear, behind a cornice or parapet. Postwar Northeast rows and twins dip at the front, which matches the shingled slopes in the Bulletin photos. The dip is about one cell deep, though, and about a fifth of plain rows "dip" from noise alone. So the LiDAR supports the pattern for groups, not house by house. A rough reading is that the slope is on somewhere between a fifth and a half of postwar Northeast rows. That is an inference from the gap over the noise rate, not a count.

**Porches are visible.** A story-high drop at the front (a porch roof) shows on 56.5% of `row_porch` footprints with a measured front, against 8.7% of `row_typical`. In averaged profiles, porch-front rows in Olney, Cobbs Creek and Mayfair sit 3.2–3.4 m lower for the first 1–1.25 m behind the front. That is a useful independent check of OPA's porch-front code.

**What this means for the options.**
- **Pitched roofs can come from the LiDAR building by building.** Year built isn't needed. That covers about 14% of buildings, concentrated in singles and twins in the Far Northeast and Northwest and in old rows in Society Hill, Queen Village and Washington Square West.
- **Front slopes have to come from the property code and neighborhood**, mainly `ROW POST WAR` and `TWIN POST WAR` (88,516 footprints together). The LiDAR can only confirm them by group, and the pilot's visual review would have to judge them.
- **About 83% of buildings have flat roofs.** For those, the era cues stay at the roof edge and on the walls: a cornice or parapet, a front slope, a porch roof.

## 5. Options

The map isn't built from sprites: a three.js render with procedural walls is redrawn by Qwen-Image-Edit with one style LoRA. So "era-specific sprite sets" translates to era-specific facade recipes in the render, or era-aware prompting and training in the redraw. Every option below targets v19 and leaves v14, v17 and v18 untouched. A citywide rebuild would cost roughly what the first one did (an estimate) (README: $129.95 of GPU time for drawing and redrawing the map); a pilot on three 11-frame atlas spots costs well under $1 at the region runner's $0.011 per frame estimate.

### Tier 1: short-term, render-side, no retraining

**1a. Stop collapsing OPA's era codes.** Split `row_typical` into a `row_old` style for `ROW OLD STYLE` (5,342 footprints) and for row codes with a year before 1880; split `twin` into old-style, conventional and postwar/ranch; split `detached` into old style, Cape, ranch and split level. Year acts only as a tiebreaker inside a code, and only in eras where it's sharp enough (before 1880 in districts with recorded years; 2000 on). *Effort:* a day, in `facades.py` (`STYLES`, `style_of`, `SPACING_M`) and `tests/test_facades.py`. *Risk:* low; it changes labels, not drawing, until 1b and 1c use them.

**1b. Era wall palettes.** Replace the six all-purpose brick reds with palettes keyed to style and era, using only colors the sources name:
- Before 1840: darker, mottled red (handmade brick with glazed headers), with white marble trim.
- 1840–1884: red brick, plus a brownstone palette for Rittenhouse-type fronts (brownstone is in OPA only as "MASONRY," so this needs a neighborhood or OSM cue).
- 1875–1904: add yellow-tan and purplish-brown (Spruce Hill).
- 1905–1929: add orange, "Pompeiian" and buff (Girard Estate, Tapestry Brick).
- 2000 on (`row_modern`): gray, white and dark panel or stucco, not brick.
- Postwar: no sourced color; keep current reds until checked against photos.

*Effort:* a day or two. *Risk:* low to medium. Neighborhood-wide estimated years mean whole blocks change together, which is right for rows built by one developer and wrong where old and new mix. OSM color still wins where mapped.

**1c. Era details in the wall shader.** Turn bands on and off by era instead of by style alone:
- No cornice on `row_postwar` and `row_modern` (today every `row_*` gets one).
- A heavier, darker cornice band on 1840–1904 rows (bracketed wood or pressed metal).
- A new pent-eave line between the first and second floors on pre-1840 rows (a one-pixel shelf).
- Bay spacing and window proportions per era (tall second-floor windows on Greek Revival and Italianate rows).

*Effort:* two to four days. It needs new band bits in `facades.compact` and the shader (`render/render.js:219-311`), plus tests like `test_render_facades.py`. *Risk:* medium. The shader is shared by every facade area, so areas without the new config flag must stay byte-identical, as `test_no_facade_data_renders_exactly_as_before` already checks for facades.

**1d. Front roof slopes on interwar and postwar rows.** The gap-fill photos show most 1920s–1960s Northeast and interwar rows with a shingled slope across the front of a flat roof, divided by party-wall caps; a few late-1960s rows have a plain flat eave instead. From 45° above that slope is a strip along the front edge of every roof in the row, so it may be the cheapest change with the biggest effect on how those neighborhoods read. It is a thin sloped prism along the street-facing wall's top (the street side is already known from `front_dirs`), drawn in a shingle gray-brown, with light caps at party walls. *Effort:* about a week: geometry in `05_build_scene.py` or `render.js`, kept out of the building mask or added to the mask check. *Risk:* medium. It adds geometry, so alignment and masks must be rechecked, and rows without the slope would get one by mistake. Before building it, measure from the LiDAR how many rows have it (a front band 1–2 m deep sitting lower than the roof behind; see "Still open" in section 3) and which OPA codes and years go with it. Section 4 did that measurement: the slope shows up as a group pattern on postwar Northeast rows and twins but can't be confirmed house by house, so draw it by OPA code and neighborhood.

**Not recommended in tier 1:** drawing a garage on postwar rows. The sources put most of those garages at the rear, off an alley, and `front_dirs` finds the street side, not the alley.

### Tier 2: larger

**2a. Pitched roofs from the LiDAR.** The roof is where era shows most from 45° above, and the map has no pitched roofs. LiDAR parts are cut into flat tiers 2 m apart (`tier_step`, `src/pixelphilly/lidar.py:193-196`), so a gable rising 2–3 m becomes one flat box or a box with a strip on top. Section 4 shows the LiDAR can tell pitched roofs building by building (64,131 of them, 14.2%; 85–91% of Capes, ranches, split levels and Colonials). So this option no longer depends on year built: fit a ridge line and two or four planes (gable or hip) to each pitched roof and extrude that instead of flat tiers. Era and OPA code serve only as a tiebreak (side gable with dormers for `ROW OLD STYLE` before 1840; hip for `RANCH` and `TWIN RANCH`). Mansards (Second Empire) and roof decks with stair penthouses (new construction) are later steps. *Effort:* two to four weeks: plane fitting in `lidar.py`, sloped geometry in `05_build_scene.py` and `render.js`, and the white building mask and alignment check (`09_check_alignment.py`) must agree with the new shapes. *Risk:* medium to high. Geometry errors draw as invented buildings, and trees over roofs read as slopes in some samples. The aerial is draped on top, so a slope fitted in the wrong direction fights the photo; the fit should be checked against the aerial's shading.

**2b. Era-aware prompts.** Add an era phrase to the redraw prompt per window ("Federal brick rowhouses with dormers"). *Effort:* about a week in `joint_sampler.py`. *Risk:* high. Windows overlap and are averaged every step, and different text per window could bring seams back. The Oct. 26 landmark-reference test, which also gave windows different conditioning, damaged seven landmarks while improving one (`docs/history.md`).

**2c. Retrain the style LoRA on a mix of eras.** The LoRA saw only Old City (141 renders). Adding Spring Garden, Northeast postwar and new-construction blocks would teach it those looks. *Effort:* one to two weeks; training runs are cheap (README: $12.78 for two LoRAs). *Risk:* high, and partly editorial. The current training targets were Gemini 3 Pro Image redraws, and the README already flags that the Gemini API terms restrict using outputs to develop models. A new set would need a different source of target images, and the three Gemini-free styles tried so far were noisier.

**Recommendation (updated Nov. 23 after the LiDAR measurement).** For the most visible change:
1. 1a, era classification. Everything else builds on it.
2. 1b and 1c, era walls.
3. 1d, front slopes on `ROW POST WAR` and `TWIN POST WAR`, drawn by code and neighborhood.
4. 2a, LiDAR-fitted gables and hips for the 14% of buildings that are pitched.

All four go into one v19 candidate behind a config flag, tested on the pilot below. Steps 1 to 3 are render-side and cheap. Step 4 is the largest single visual change for the Far Northeast, the Northwest and Society Hill, but it does nothing for the 83% of buildings with flat roofs. Leave 2b and 2c alone unless the pilot shows the redraw erasing render-side cues.

## 6. Recommended pilot

Use three existing facade atlas spots, plus one new one for front slopes (11 frames, well under $1), so results compare directly with the drawings already made of them (`redraws/qwen_joint_light8_fac1/`). Each spot is 11 frames.

| Spot | Why | Era mix (matched footprints, by OPA year) | Estimated years |
|---|---|---|---|
| `atlas_indhall_fac` (Independence Hall, Society Hill edge; 1,888 footprints) | Widest mix: colonial to postwar renewal to new infill | Before 1840: 319 · 1840–1879: 248 · 1880–1904: 496 · 1905–1929: 170 · 1945–1974: 271 · 1975–1999: 135 · 2000–2026: 153 | 47.6% |
| `atlas_northeast_fac` (Northeast twins and singles; 2,792) | Postwar test: today's styles here are `twin` (1,887) and `detached` (678) | 1945–1974: 2,301 · 1930–1944: 225 · 1975–1999: 165 | 60.1% |
| `atlas_passyunk_fac` (East Passyunk rows; 9,579) | Control: one era, so little should change except the 2000s infill | 1905–1929: 8,416 · 1880–1904: 400 · 2000–2026: 281 | 72.4% |
| New: a Mayfair or Parkwood Manor spot (`atlas_mayfair_fac`, to be set up like the others) | Front slopes: the strongest group signal in section 4 (Mayfair `ROW POST WAR`: 52.4% dip; Parkwood Manor: 53.3%). The existing Northeast spot's twins showed plain flat roofs in the aerial | Mayfair is 77% 1945–1974 by OPA year (section 1's audit) | 90.4% (Mayfair) |

(Counts from a one-off run of the audit's join on each spot's raw files, Nov. 22, 2026. Most of the Independence Hall spot's 1945–1974 buildings are probably Society Hill's urban-renewal era, but that hasn't been checked building by building.)

**Steps**

1. Add a config flag (for example `"facade_eras": true`) and new run names, so existing atlas outputs and all regions stay byte-identical. Add a test that proves it.
2. Implement 1a–1d in `facades.py`, the scene builder and the shader, with unit tests for the era classification. Then 2a as a second pass on the same spots (the Northeast spot is 37% pitched by the LiDAR; Independence Hall has Society Hill's gables). Include the OPA code and year in the scene's per-building debug output so a reviewer can see why each building got its look.
3. Render the spots and run the alignment check (`09_check_alignment.py`). Walls are paint only, but 1d and 2a add geometry, so the building mask must be regenerated and checked.
4. Redraw them with the map's settings (Qwen-Image-Edit-2511, Lightning 8 steps, `qe2511_oldcity_r16_v1`, seed 0).
5. Compare with `08_compare_page.py`: render vs. drawing, and old drawing vs. new.

**Checks before any citywide change**

- **Does the redraw keep the cue?** For each era class, measure the wall-color difference between render and drawing on street-facing walls (masks give the walls), and whether cornice and porch bands survive. If the drawing pulls everything back to the Old City reds, render-side changes aren't enough.
- **Is it right?** Sample about 20 buildings per spot, stratified by era, and check each against the 2024 aerial and current street-level photos. Score the old and new look as right, neutral or wrong, without knowing which version is which. Pay attention to remodeled fronts and buildings with estimated years.
- **Did it break anything?** The existing invented-color and seam measures should not get worse, and the control spot (East Passyunk) should change only at `ROW MODERN` infill and pre-1880 houses.
- **Editorial check.** Era styling shouldn't stand in for condition or value. Keep `exterior_condition` out, as now, and don't style by `quality_grade`, which is fetched but unused.

**What would justify going citywide.** The new look wins the blind review in Independence Hall and the Northeast, the control barely moves, and seams and invented color hold. Then build v19 region by region with the region runner's usual QA gates and freeze it as a new version.

## 7. Pilot results

The approved plan is `docs/building_age_plan.md`. Each test spot has two configs with identical boxes and cameras: `config/atlas_<spot>_eb.json` (baseline, no new options) and `config/atlas_<spot>_ea.json` (the era options, turned on phase by phase). Spots: `indhall`, `northeast`, `passyunk` (copies of the `_fac` atlas spots) and `mayfair` (new: bbox [-75.07097, 40.02876, -75.06511, 40.03326], the 500 m box in the Mayfair neighborhood with the most `ROW POST WAR` footprints, 1,021). Renders aren't stored per run, so each phase's renders, masks, scene and QA are copied before the next phase overwrites them: `output/atlas_<spot>_ea/renders_eraA/`, `masks_eraA/`, `data/processed/atlas_<spot>_ea_scene_eraA.json`, and likewise `_eraB`.

### Phase 0: baselines (Nov. 23, 2026)

All four `_eb` spots built, rendered and passed the alignment check (1 px tolerant IoU 0.9998–1.0, no shift) with no needles; facade match rates 0.985–0.999. Drawn as run `qwen_joint_light8_eb` (Lightning 8, `qe2511_oldcity_r16_v1`, seed 0, the standard prompt), then water-repainted: 2.0–2.1 GPU minutes per spot, about $0.14 each (estimate, `output/gpu_runs.jsonl`).

### Phase A: era classes, palettes and bands (`"facade_eras": true`)

What it does (`src/pixelphilly/facades.py`): `era_of` assigns an era from the OPA style code first and the year second (section 1 explains why); four new styles (`row_old`, `twin_old`, `twin_postwar`, `detached_postwar`) are appended so existing style ids don't change; era palettes use only colors named in section 3's sources; two paint-only bands: a pent eave on pre-1840 rows (bit 16) and a heavier cornice on 1840–1904 rows (bit 32). Postwar buildings keep today's palette (no source names postwar colors) and lose the cornice. Off by default; `tests/fixtures/facade_spec_golden.json` (181 real cases, no addresses or parcel numbers) proves the output is unchanged without the flag, and `tests/fixtures/render_golden.json` stores checksums of the plain test scene's render, so the byte-identical check outlives the commit.

Era counts from the scene QA (all footprints in each spot):

| Spot | Eras | Year estimated |
|---|---|---|
| Independence Hall | late_victorian 507, postwar 361, georgian_federal 316, mid19 245, new 164, streetcar 161 | 46.5% |
| Northeast | postwar 2,484, interwar 121, late20 91 | 59.9% |
| East Passyunk | streetcar 8,332, late_victorian 429, new 338, interwar 253 | 72.2% |
| Mayfair | postwar 3,410, interwar 421 | 92.1% |

Drawn as run `qwen_joint_light8_eraA` (same settings; about $0.14 per spot, estimate). A first look by eye said the redraw model pulled Independence Hall's darker early reds back to its Old City reds; the Phase D measures (below) show that's true mainly for the earliest eras. Overall the drawings keep 76–92% of the wall-color change, but Georgian and Federal walls keep 66% and 1840–1879 walls 46%. The drawings also differ in places the render didn't change (trees appeared on an Independence Hall lawn in the era drawing), so the blind review has to allow for run-to-run noise.

### Phase B: front slopes on postwar rows (`"front_slopes": ["ROW POST WAR", "TWIN POST WAR"]`)

What it does (`src/pixelphilly/roofs.py`, `add_front_slopes` in `scripts/05_build_scene.py`): each marked building is cut into a full-height main block and a strip 0.75 m deep along its street wall, 0.6 m lower, with a shingled slope over the strip from 0.15 m past the wall up to the main roof's edge. The sizes come from the Mayfair LiDAR profile in section 4 (median 0.5 m low at 0.5 m from the front, 0.09 m at 0.75 m, level beyond); the drop at the wall itself is extrapolated. Shingle colors are an assumption, not sourced. Both pieces stay ordinary prisms colored from the whole footprint; the slope triangles go in a new scene key, `roof_facets`, which `render/render.js` lights like the walls and `scripts/09_check_alignment.py` projects.

A planned detail was wrong and was changed before rendering: the plan put the slope under the flat roof's top edge, where the roof would have hidden it. Two problems found on the first Mayfair build (30% of marked parts cut) were also fixed:
- LiDAR parts are traced on the 0.5 m grid, so on Mayfair's diagonal streets their fronts are staircases, and they often stop short of the street wall, probably because the slope itself is lower than the roof the parts trace. The street wall now comes from the City footprint, and the strip from the City outline, for any part within 1.5 m of the wall.
- Many Mayfair outlines step about 0.5 m across the front (a vestibule or bay). Front walls are found on the outline simplified at 0.6 m.

| Spot | Marked parts | Cut | Refused (reasons) |
|---|---|---|---|
| Mayfair | 3,351 | 2,374 (71%) | short wall 420, odd front 290, height 181, not at front 86 |
| Northeast | 1,006 | 822 (82%) | short wall 84, not at front 45, odd front 34, height 21 |
| Independence Hall | 276 | 236 | short wall 21, not at front 14, other 5 |
| East Passyunk | 42 | 32 | 10 |

All four spots pass the alignment check (1 px tolerant IoU 0.9998–1.0, no shift) with no needles. In the renders the slope is a dark band two or three pixels deep along the street edge of each roof: right for a 0.9 m feature at 0.29 m per pixel, but subtle. Drawn as run `qwen_joint_light8_eraB` (same settings; 2.1 GPU minutes and about $0.14 per spot, estimate).

**Does the redraw keep the slope?** Measured on all 10 frames per spot: the pixels where the slope made the render at least 15 gray levels darker (the Phase A render against the Phase B render), and how much darker the Phase B drawing is than the Phase A drawing at those pixels. As a noise baseline, the same drawing difference on building pixels at least 4 px from any render change. (A one-off measurement in the session; it belongs in `scripts/47_era_compare.py`, Phase D.)

| Spot | Slope pixels | Render darker by (mean, gray levels) | Drawing darker by (mean / median) | Drawing change elsewhere on buildings (mean, sd) |
|---|---|---|---|---|
| Mayfair | 86,294 | 54.2 | 31.1 / 19.0 | -0.4, 8.7 |
| Northeast | 33,971 | 60.1 | 40.7 / 29.0 | -0.3, 6.0 |
| Independence Hall | 9,239 | 64.2 | 49.3 / 41.0 | 0.2, 5.8 |
| East Passyunk | 1,837 | 50.9 | 34.0 / 21.0 | 0.0, 4.0 |

So 57–77% of the slope's darkening survives the redraw, far above the noise. By eye, the drawings show a darker band along each roof's street edge; at this scale it reads more as a heavier roof edge than as a visible slope. Whether that looks right is for the blind review.

### Phase C: gables and hips fitted to the LiDAR (`"roof_fit": "lidar"`)

What it does (`src/pixelphilly/roofs.py`; `lidar_shaped` in `scripts/05_build_scene.py`): for a footprint the pitch test calls pitched (the test from section 4, moved from `scripts/45_roof_forms.py` into `roofs.roof_pitch`; the script's outputs are byte-identical after the move), the roof is fit as z = eave + k x (distance to the nearest eave side of the footprint's minimum rotated rectangle). Eleven side sets are tried: gable (long sides), cross gable (short ends), hip (all four), half hip (three sides: one half of a twin under a hip over the pair) and single slope (one side: a twin half whose pair's ridge is the party wall). Before fitting, the footprint is registered to the raised LiDAR cells (shifts up to 1.5 m); many clean gables on the Northeast spot failed only because the roof sat up to a meter off the City outline. A fit is kept when at least 70% of roof cells lie within 0.35 m of it, its pitch is 15–55°, and it fits at least 25 points more of the roof than a flat roof. The 70% was set from a sheet of LiDAR surfaces next to their fits: above it the forms matched by eye; below it wrong forms became common. A fitted building becomes one part with a `roof3d` record (ring heights, roof triangles); `render/render.js` builds walls up to the roof at each ring vertex (gable ends rise to the ridge) and roof triangles that take the aerial; `scripts/09_check_alignment.py` projects the same numbers. Cornice bands are dropped on these buildings (they follow the wall top and would paint whole gable ends). Deviation from the plan: the code lives in `roofs.py`, not `lidar.py`.

| Spot | Pitched footprints | Fitted | Forms | Refused |
|---|---|---|---|---|
| Northeast | 324 | 80 (25%) | gable 31, cross gable 25, single slope 13, hip 6, half hip 5 | no fit 122, not simple 99, flat 22 |
| Independence Hall | 89 | 6 | cross gable 3, other 3 | no fit 54, not simple 29 |
| East Passyunk | 52 | 6 | | no fit 38, not simple 7 |
| Mayfair | 3 | 1 | | |

All four spots pass the alignment check (1 px tolerant IoU 0.9998–1.0, no shift) with no needles. Most refusals are compound roofs (T and L gables, porch roofs, dormers) or footprints that aren't near-rectangles; in Independence Hall, rowhouses whose gabled front block shares a footprint with a flat rear ell. One model per footprint can't fit those; fitting per LiDAR part is a possible extension. In the renders, fitted houses read as houses: gable ends rise to the ridge and hip walls stop at the eave, where before they were flat-topped boxes with the roof photo on top. Drawn as run `qwen_joint_light8_eraC` (2.0–2.3 GPU minutes and about $0.13–0.15 per spot, estimate).

**Does the redraw keep the roofs?** Where the fitted roofs changed the render by more than 15 gray levels (Phase B render against Phase C render), the drawing also changed by more than 15 levels at 71% of those pixels in the Northeast, 81% in Independence Hall, 70% in East Passyunk and 65% in Mayfair (1,026 pixels there). On building pixels away from any render change, the drawings changed at 1–2%. By eye, fitted hips and gables come through as hipped and gabled roofs with ridges, where the earlier drawings showed stepped flat tops. (A one-off measurement in the session; it belongs in `scripts/47_era_compare.py`, Phase D.)

### Phase D: measures and blind review

`scripts/47_era_compare.py` writes `output/era_pilot/metrics.json` and `report.md`, and the blind review page `output/era_pilot/review/index.html` (tests: `tests/test_era_compare.py`). Drawings are read after the water repair. For each step (base to A, A to B, B to C), on the pixels where the render changed: **retention** = how much of the render's color change the drawing made too (1.0 all, 0 none; sum of dD·dR over sum of dR·dR), **followed** = share of those pixels where the drawing also changed, and **noise** = share of building pixels away from any render change where the drawing changed anyway. Base and A are different areas with the same box and camera, so their noise is higher (1–6%).

| Spot | Era walls (base to A) | Front slopes (A to B) | Fitted roofs (B to C) |
|---|---|---|---|
| Independence Hall | 0.81 (followed 73%) | 0.69 (77%) | 0.82 (84%) |
| Northeast | 0.76 (74%) | 0.64 (74%) | 0.65 (78%) |
| East Passyunk | 0.80 (78%) | 0.56 (68%) | 0.80 (73%) |
| Mayfair | 0.92 (61%) | 0.52 (72%) | 0.70 (74%) |

Era-wall retention by era (base to A, Independence Hall): late Victorian 0.81, Georgian and Federal 0.66, 1840–1879 0.46, new 0.87. Era labels come from projected silhouettes painted far to near, so they can be wrong where buildings overlap. Seam ratio (1.02–1.09), flat share, invented color (0.02% or less), registration shift (0 px) and invented water (none) are about the same for every variant in every spot: none of the options made the drawings worse on those checks. In the East Passyunk control, the era-wall change touched far more pixels than planned (875,841; most of the spot is 1905–1929 rows, which the era palette changes), so the control's "should change only at infill and pre-1880 houses" check doesn't hold. The palette, not the redraw, is what moves it.

The review page has 80 buildings, 20 per spot, sampled from the C scene round-robin over roof classes (fitted, front slope, flat) and then eras (largest first, unknown left out), with a fixed seed. Each shows a north-up crop of the raw 2024 imagery tiles and the base and C drawings in random order as A and B. The page holds only opaque ids; `output/era_pilot/review_key.json` says which side is which. Scores save in the browser and download as `era_review.json`; `uv run python scripts/47_era_compare.py --score <file>` unblinds them into `output/era_pilot/review_results.json`.

### Pixel-scale test (Nov. 25, 2026)

Midway through the blind review, Stephen said he wasn't seeing much difference between the pairs, and he asked whether finer pixels would help. At 0.293 m/px a 5 m rowhouse is about 17 px wide and the front slope about 2.5 px deep, so most of the pilot's changes are a few pixels each. The test redrew two spots with Phase C's settings at half the scale, 0.1465 m/px: `config/atlas_{mayfair,indhall}_px15.json`, the `_ea` configs with only `meters_per_pixel` and the name changed. Raw data was fetched again under the new names on Nov. 25. The aerial is still the zoom-19 tiles (about 0.23 m on the ground), so roofs and ground are slightly upsampled. Run `qwen_joint_light8_px15`, same model, LoRA, prompt and seed as Phase C. About $0.26 for Mayfair and a similar amount for Independence Hall (estimates). `scripts/48_scale_test.py` writes same-ground sheets and these measures to `output/scale_test/`:

| Spot | Scale (m/px) | Frames | Seam | Flat share | Invented color | Max shift | Invented water blobs |
|---|---|---|---|---|---|---|---|
| Mayfair | 0.293 | 10 | 1.029 | 0.494 | 0.00% | 0 px | 0 |
| Mayfair | 0.2 | 12 | 0.931 | 0.542 | 0.01% | 0 px | 0 |
| Mayfair | 0.1465 | 21 | 1.000 | 0.579 | 0.10% | 1 px | 1 (repaired) |
| Independence Hall | 0.293 | 10 | 1.079 | 0.394 | 0.02% | 0 px | 0 |
| Independence Hall | 0.2 | 12 | 0.890 | 0.480 | 0.01% | 0 px | 0 |
| Independence Hall | 0.1465 | 21 | 0.981 | 0.544 | 0.02% | 0 px | 1 (repaired) |

By eye, on the sheets:
- **Sharper:** window grids are crisp and regular, outlines are thinner relative to the buildings, and the front slopes and roof vents stay visible.
- **More faithful in places:** at Independence Hall, a gray tower that the Phase C drawing turned brown stays gray. More of the era palette's variety survives in Mayfair's walls.
- **Worse:** pavement and yards break into flat gray patches (flat share up 8–15 points), and bare winter trees in the aerial become odd gray shapes on lawns. In Mayfair, one block of white roofs was drawn orange.
- **Not pixel art in the chunky sense:** the art pixels are smaller relative to the buildings, so the look is closer to a clean illustration.

**Middle scale (Nov. 26):** the same test at 0.2 m/px (`config/atlas_{mayfair,indhall}_px20.json`, run `qwen_joint_light8_px20`, about $0.15 per spot, estimate; rows added to the table above). By eye it keeps most of the building gains: crisp window rows, visible front slopes, and the gray tower stays gray. It has fewer of the ground problems: the ground is less patchy (flat share between the other two scales) and the bare trees don't turn into gray shapes. In Mayfair the white roofs stayed white. One new error: in the Independence Hall park, bare winter trees came out with brown crowns, like autumn trees. A seam ratio under 1 means frame borders are smoother than the frames' insides. `48_scale_test.py` now puts all three scales side by side on the same ground.

Frame count per area scales with 1/scale², so a region rebuild at 0.1465 m/px would take about four times the frames, GPU time and storage of v18, and one at 0.2 m/px about 2.1 times (estimates). The two spots show only about twice as many frames because their edge frames are mostly empty.

## Reproduce the numbers

```bash
uv run python scripts/44_year_built_audit.py
```

```bash
uv run python scripts/45_roof_forms.py                       # the facade atlas spots, ~10 s
uv run python scripts/45_roof_forms.py --tag regions --areas south_lidar north_lidar upper_north_lidar west_lidar west_north southwest germantown east_riverfront roxborough lower_northeast northwest upper_northeast   # ~10 min
uv run python scripts/46_roof_front_profiles.py              # needs 45's region CSVs, a few minutes
```

`44` reads only files already in `data/raw/` (listed in `data/raw/MANIFEST.json`; get them with `scripts/00_get_data.py`), writes `output/building_age/year_built_audit.json`, and runs in about 30 seconds. The JSON holds parcel- and footprint-level summaries, a breakdown by OPA style code, era by map style, the OPA codes inside each map style, and a per-neighborhood table (neighborhood boundaries: `data/raw/philadelphia-neighborhoods.geojson`, CC BY 4.0, credit Robert Cheetham). The era bins in the script (before 1840, 1840–1879, 1880–1904, 1905–1929, 1930–1944, 1945–1974, 1975–1999, 2000–2026) are this report's approximations, not official periods. `45` and `46` also need the cached LiDAR grids in `data/processed/<area>_lidar_grid.npz`, which `scripts/05_build_scene.py` builds from the LAS tiles (several GB per region; not in the data snapshot). Regions overlap, so section 4's citywide figures deduplicate the per-area CSVs by object id.
