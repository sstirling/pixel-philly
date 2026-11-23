# Building age and style: could year built improve the map's buildings?

Investigation and proposal, Nov. 22, 2026. Nothing here changes the map: no renders, no new version, frozen versions (v14, v17, v18) untouched, raw data unchanged. Any change would go into v19.

**Short answer.** Yes, but year built should be a supporting signal, not the main one. The City's property records already carry a better era signal than the year: the building style code (`building_code_description_new`), with values like `ROW OLD STYLE`, `ROW PORCH FRONT`, `ROW POST WAR`, `TWIN RANCH`, `CAPE` and `ROW MODERN`. The map reads that code today but collapses it into 13 styles, and the renderer then uses the style only to set bay spacing and four on/off bands. Three-quarters of the years are assessor estimates heaped on round numbers (1925, 1920, 1950), so a year by itself mostly tells you the neighborhood, not the building. The cheapest gain is to use the style code more fully, with year as a tiebreaker inside it, and to change wall color, cornice and porch details by era. A pilot on three existing atlas spots can show whether the AI redraw keeps those details.

Contents: [1. The data](#1-the-year-built-data) · [2. How styles are chosen now](#2-how-building-styles-are-chosen-now) · [3. Philadelphia's eras](#3-philadelphias-building-eras-and-what-reads-at-map-scale) · [4. Options](#4-options) · [5. Recommended pilot](#5-recommended-pilot) · [Reproduce](#reproduce-the-numbers)

## 1. The year-built data

### Sources checked

| Source | Age field | In the repo? | Join to map footprints | License |
|---|---|---|---|---|
| Office of Property Assessment (OPA), `opa_properties_public` (Carto SQL API, [OpenDataPhilly](https://opendataphilly.org/datasets/philadelphia-properties-and-assessment-history/)) | `year_built` (text), `year_built_estimate` (`Y`, `N` or empty) | Yes: `data/raw/<area>_opa.geojson`, fetched Oct. 25, 2026, by `scripts/04f_fetch_opa.py`. Both fields are already in `OPA_COLUMNS` (`src/pixelphilly/opa.py:23-35`) | Already joined: footprint `parcel_id_num` → `pwd_parcels.brt_id` → OPA `parcel_number`, then address, then OPA point inside footprint (`src/pixelphilly/facades.py:329-366`) | City of Philadelphia License |
| L&I building footprints, `LI_BUILDING_FOOTPRINTS` ([OpenDataPhilly](https://opendataphilly.org/datasets/building-footprints/)) | None. Fields: `objectid`, `bin`, `address`, `parcel_id_num`, heights, area (checked on `data/raw/atlas_porch_fac_buildings.geojson`) | Yes | — | City of Philadelphia License |
| L&I permits, `permits` (Carto) | No year built, but `typeofwork` "New Construction" / "NEWCON" with `permitissuedate` and `opa_account_num` | No | By `opa_account_num` = OPA `parcel_number` | City of Philadelphia License |
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

Not used, because they weren't opened: Murtagh's 1957 *JSAH* article on the Philadelphia row house, HABS records, PhilaPlace, the Athenaeum's Philadelphia Architects and Buildings, Hidden City. Several PHC district manuals (Society Hill, Rittenhouse-Fitler, Parkside, Greenbelt Knoll) are scanned images with no text and weren't read.

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

**Gaps.** No source found uses "Wissahickon style" for a rowhouse type, so this report doesn't. "Airlite" and "daylighter" are used for 1920s houses (PHC Blakemore St.) and for a type SAH says peaked in the 1950s, so the term spans both eras. The Rowhouse Manual's "Porchfront" entry describes a lower-level garage, like its postwar entry; that looks like an error in the manual and isn't relied on here. No citable source gave brick colors or roof forms for postwar Northeast rows; check those against the 2024 aerial and street-level photos before choosing a palette.

**Remodels.** The Rowhouse Manual (pp. 11, 13, 14, 17) shows Permastone and stucco over brick, aluminum-wrapped or removed cornices, aluminum awnings and enclosed porches across all eras. PHC inventories record Tapestry Brick fronts added to early-1800s buildings and slate replaced by asphalt. Year built describes the original shell; an era look will be wrong for a share of every era, and nothing in the City's data says which.

## 4. Options

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

**Not recommended in tier 1:** drawing a garage on postwar rows. The sources put most of those garages at the rear, off an alley, and `front_dirs` finds the street side, not the alley.

### Tier 2: larger

**2a. Roof forms.** The roof is where era shows most from 45° above, and the map has no roof forms: side gables with dormers (Georgian, Federal, Greek Revival), mansards (Second Empire), false-front slopes (interwar Tudor), and roof decks with stair penthouses (new construction). These could come from LiDAR (ridge detection inside each footprint) with era as a prior, or from era alone. *Effort:* two to four weeks: new geometry in `lidar.py` and `05_build_scene.py`, and the white building mask and alignment check (`09_check_alignment.py`) must agree with the new shapes. *Risk:* high. Geometry errors draw as invented buildings. The aerial is still draped on top, so a wrong slope fights the photo.

**2b. Era-aware prompts.** Add an era phrase to the redraw prompt per window ("Federal brick rowhouses with dormers"). *Effort:* about a week in `joint_sampler.py`. *Risk:* high. Windows overlap and are averaged every step, and different text per window could bring seams back. The Oct. 26 landmark-reference test, which also gave windows different conditioning, damaged seven landmarks while improving one (`docs/history.md`).

**2c. Retrain the style LoRA on a mix of eras.** The LoRA saw only Old City (141 renders). Adding Spring Garden, Northeast postwar and new-construction blocks would teach it those looks. *Effort:* one to two weeks; training runs are cheap (README: $12.78 for two LoRAs). *Risk:* high, and partly editorial. The current training targets were Gemini 3 Pro Image redraws, and the README already flags that the Gemini API terms restrict using outputs to develop models. A new set would need a different source of target images, and the three Gemini-free styles tried so far were noisier.

**Recommendation.** Do 1a–1c together as one v19 candidate, behind a config flag, on the pilot below. Consider 2a only if the pilot shows the redraw keeps wall-level cues but the map still reads as one era from above. Leave 2b and 2c alone unless 2a fails.

## 5. Recommended pilot

Use three existing facade atlas spots, so results compare directly with the drawings already made of them (`redraws/qwen_joint_light8_fac1/`). Each spot is 11 frames.

| Spot | Why | Era mix (matched footprints, by OPA year) | Estimated years |
|---|---|---|---|
| `atlas_indhall_fac` (Independence Hall, Society Hill edge; 1,888 footprints) | Widest mix: colonial to postwar renewal to new infill | Before 1840: 319 · 1840–1879: 248 · 1880–1904: 496 · 1905–1929: 170 · 1945–1974: 271 · 1975–1999: 135 · 2000–2026: 153 | 47.6% |
| `atlas_northeast_fac` (Northeast twins and singles; 2,792) | Postwar test: today's styles here are `twin` (1,887) and `detached` (678) | 1945–1974: 2,301 · 1930–1944: 225 · 1975–1999: 165 | 60.1% |
| `atlas_passyunk_fac` (East Passyunk rows; 9,579) | Control: one era, so little should change except the 2000s infill | 1905–1929: 8,416 · 1880–1904: 400 · 2000–2026: 281 | 72.4% |

(Counts from a one-off run of the audit's join on each spot's raw files, Nov. 22, 2026. Most of the Independence Hall spot's 1945–1974 buildings are probably Society Hill's urban-renewal era, but that hasn't been checked building by building.)

**Steps**

1. Add a config flag (for example `"facade_eras": true`) and new run names, so existing atlas outputs and all regions stay byte-identical. Add a test that proves it.
2. Implement 1a–1c in `facades.py` and the shader, with unit tests for the era classification. Include the OPA code and year in the scene's per-building debug output so a reviewer can see why each building got its look.
3. Render the three spots and confirm alignment and masks are unchanged (`09_check_alignment.py`; facades are paint only).
4. Redraw them with the map's settings (Qwen-Image-Edit-2511, Lightning 8 steps, `qe2511_oldcity_r16_v1`, seed 0).
5. Compare with `08_compare_page.py`: render vs. drawing, and old drawing vs. new.

**Checks before any citywide change**

- **Does the redraw keep the cue?** For each era class, measure the wall-color difference between render and drawing on street-facing walls (masks give the walls), and whether cornice and porch bands survive. If the drawing pulls everything back to the Old City reds, render-side changes aren't enough.
- **Is it right?** Sample about 20 buildings per spot, stratified by era, and check each against the 2024 aerial and current street-level photos. Score the old and new look as right, neutral or wrong, without knowing which version is which. Pay attention to remodeled fronts and buildings with estimated years.
- **Did it break anything?** The existing invented-color and seam measures should not get worse, and the control spot (East Passyunk) should change only at `ROW MODERN` infill and pre-1880 houses.
- **Editorial check.** Era styling shouldn't stand in for condition or value. Keep `exterior_condition` out, as now, and don't style by `quality_grade`, which is fetched but unused.

**What would justify going citywide.** The new look wins the blind review in Independence Hall and the Northeast, the control barely moves, and seams and invented color hold. Then build v19 region by region with the region runner's usual QA gates and freeze it as a new version.

## Reproduce the numbers

```bash
uv run python scripts/44_year_built_audit.py
```

It reads only files already in `data/raw/` (listed in `data/raw/MANIFEST.json`; get them with `scripts/00_get_data.py`), writes `output/building_age/year_built_audit.json`, and runs in about 30 seconds. The JSON holds parcel- and footprint-level summaries, a breakdown by OPA style code, era by map style, the OPA codes inside each map style, and a per-neighborhood table (neighborhood boundaries: `data/raw/philadelphia-neighborhoods.geojson`, CC BY 4.0, credit Robert Cheetham). The era bins in the script (before 1840, 1840–1879, 1880–1904, 1905–1929, 1930–1944, 1945–1974, 1975–1999, 2000–2026) are this report's approximations, not official periods.
