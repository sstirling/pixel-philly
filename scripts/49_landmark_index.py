"""Build the landmark list for v19's 3D landmarks and a page to review it.

Phase 0 of docs/landmarks_plan.md. Inputs:
- data/landmarks/manifest.json (scripts/19_landmark_refs.py): 40 landmarks
  with Wikidata coordinates cross-checked against the City's AIS geocoder,
  and license-filtered reference photos.
- config/landmarks/selection.json (hand-made): the proposed kit for each of
  them, plus the additions (bridges, Saint Joseph's buildings) with Wikidata
  IDs, and the criticism each entry answers.
- Wikidata coordinates (P625) for the additions, fetched once with --fetch
  into data/raw/landmarks_wikidata_additions.json (recorded in MANIFEST).
- output/review/bridges/inventory.json (33_bridge_crops.py --inventory):
  each bridge's crossing from the City street centerlines and OSM, used to
  cross-check Wikidata's bridge point.

Each structure is owned by the first v18 region, in the precedence order of
output/philly/FROZEN_v18.json, whose kept frame lattice contains its ground
point. That is the region the v18 build took its pixels from; a bbox test
alone gets Girard Point and Tacony-Palmyra wrong (they sit on or past bbox
edges that the frame lattice extends beyond).

Writes config/landmarks/index.json and output/landmarks/selection/
(index.html plus crops): for each entry, the v18 illustration, the v18 photo
layer and the first approved reference photo with its credit.

Usage: uv run python scripts/49_landmark_index.py --fetch   # once; network
       uv run python scripts/49_landmark_index.py           # index + page
"""

import argparse
import ast
import html
import json
import math
from pathlib import Path

from PIL import Image

from pixelphilly.landmark_dossier import BRIDGE_KITS
from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.sources import RAW, get_with_retry, record

SELECTION = REPO_ROOT / "config" / "landmarks" / "selection.json"
MANIFEST = REPO_ROOT / "data" / "landmarks" / "manifest.json"
WIKIDATA_RAW = RAW / "landmarks_wikidata_additions.json"
INVENTORY = REPO_ROOT / "output" / "review" / "bridges" / "inventory.json"
INDEX = REPO_ROOT / "config" / "landmarks" / "index.json"
FROZEN = REPO_ROOT / "output" / "philly" / "FROZEN_v18.json"
TILES = REPO_ROOT / "output" / "philly" / "tiles" / "v18"
OUT = REPO_ROOT / "output" / "landmarks" / "selection"
TILE, LEVEL = 512, 17  # v18 deep-zoom tiles; level 17 is full resolution
CROP = 900  # v18 crop side, px: about 264 m at v18's 0.293 m/px (bridges get twice that)


def fetch_wikidata(qids):
    """{qid: {label, lon, lat}} from Wikidata's P625 (coordinate location)."""
    out = {}
    for i in range(0, len(qids), 40):
        chunk = qids[i:i + 40]
        r = get_with_retry("https://www.wikidata.org/w/api.php",
                           params={"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims|labels",
                                   "languages": "en", "format": "json"}).json()
        for q, ent in r["entities"].items():
            claims = ent.get("claims", {}).get("P625", [])
            coord = claims[0]["mainsnak"]["datavalue"]["value"] if claims else None
            out[q] = {"label": ent.get("labels", {}).get("en", {}).get("value"),
                      "lon": coord["longitude"] if coord else None, "lat": coord["latitude"] if coord else None}
    return out


def haversine_m(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def nearest_inventory(inventory, name, lon, lat, near=None):
    """The inventory crossing with this name nearest the point (or `near`)."""
    ref = near or (lon, lat)
    cands = [c for c in inventory if c["name"] == name]
    if not cands or ref[0] is None:
        return None
    c = min(cands, key=lambda c: haversine_m(ref[0], ref[1], c["lon"], c["lat"]))
    return {"name": c["name"], "id": c["id"], "lon": c["lon"], "lat": c["lat"], "area": c["area"],
            "distance_m": round(haversine_m(ref[0], ref[1], c["lon"], c["lat"]), 1)}


class Owner:
    """Which v18 region's frame lattice holds a point (precedence order)."""

    def __init__(self, regions):
        self.setups = []
        for name in regions:
            cfg = load_config(name)
            frame, cam, frames = area_setup(cfg)
            self.setups.append((name, frame, cam, {(f.col, f.row) for f in frames}, frames[0]))

    def __call__(self, lon, lat):
        for name, frame, cam, have, f0 in self.setups:
            ox, oy = f0.x0 - f0.col * f0.size, f0.y0 - f0.row * f0.size
            e, n = frame.to_local(lon, lat)
            sx, sy = cam.world_to_screen(e, n, 0.0)
            cell = (int((float(sx) - ox) // f0.size), int((float(sy) - oy) // f0.size))
            if cell in have:
                return name
        return None


def build_index(selection, manifest, wikidata, inventory, owner):
    entries = []
    by_slug = {lm["slug"]: lm for lm in manifest["landmarks"]}
    missing = sorted(set(by_slug) - set(selection["manifest"]))
    if missing:
        raise KeyError(f"manifest landmarks without a selection entry: {missing}")
    for slug, sel in selection["manifest"].items():
        lm = by_slug[slug]
        over = lm.get("coord_override") or {}  # {lon, lat, source, note}: a reviewed fix of Wikidata's point
        lon, lat = over.get("lon", lm["lon"]), over.get("lat", lm["lat"])
        e = {"slug": slug, "name": lm["name"], "wikidata": lm["wikidata"], "lon": lon, "lat": lat,
             "coord_source": over.get("source", lm.get("coord_source")),
             "ais_distance_m": (lm.get("ais") or {}).get("distance_to_wikidata_m"),
             "from": "manifest", "manifest_status": lm.get("status"),
             **{k: v for k, v in sel.items() if k not in ("inventory", "inventory_near")}}
        if sel.get("inventory"):  # bridges in the photo manifest: same crossing cross-check as additions
            inv = nearest_inventory(inventory, sel["inventory"], lon, lat, sel.get("inventory_near"))
            if inv:
                e["inventory_match"] = inv
        entries.append(e)
    for add in selection["additions"]:
        wd = wikidata.get(add["wikidata"]) if add.get("wikidata") else None
        lon, lat = (wd["lon"], wd["lat"]) if wd else (None, None)
        src = "Wikidata P625" if wd and lon is not None else None
        inv = None
        if add.get("inventory"):
            inv = nearest_inventory(inventory, add["inventory"], lon, lat, add.get("inventory_near"))
        if add.get("coord"):  # a reviewed, sourced fix (Wikidata missing or off the structure)
            lon, lat, src = add["coord"]["lon"], add["coord"]["lat"], add["coord"]["source"]
            if add.get("inventory"):
                inv = nearest_inventory(inventory, add["inventory"], lon, lat, add.get("inventory_near"))
        if lon is None and inv:
            lon, lat, src = inv["lon"], inv["lat"], "bridge inventory (City street centerlines / OSM)"
        e = {k: v for k, v in add.items() if k not in ("inventory", "inventory_near", "coord")}
        if add.get("coord", {}).get("note"):
            e["coord_note"] = add["coord"]["note"]
        e.update({"lon": lon, "lat": lat, "coord_source": src, "from": "addition",
                  "wikidata_label": wd["label"] if wd else None})
        if inv:
            e["inventory_match"] = inv
        entries.append(e)
    for e in entries:
        e["region"] = owner(e["lon"], e["lat"]) if e["lon"] is not None else None
    return entries


def v18_px(fit, lon, lat):
    """viewer/projection.js lonLatToPx (the cubic from viewer_geo.py)."""
    u, v = (lon - fit["lon0"]) / fit["su"], (lat - fit["lat0"]) / fit["sv"]
    t = [1, u, v, u * u, u * v, v * v, u ** 3, u * u * v, u * v * v, v ** 3]
    return sum(a * b for a, b in zip(fit["cx"], t)), sum(a * b for a, b in zip(fit["cy"], t))


def tile_crop(layer, x0, y0, w, h, bg=(204, 214, 227)):
    out = Image.new("RGB", (w, h), bg)
    for ty in range(int(y0 // TILE), int((y0 + h) // TILE) + 1):
        for tx in range(int(x0 // TILE), int((x0 + w) // TILE) + 1):
            p = TILES / f"{layer}_files" / str(LEVEL) / f"{tx}_{ty}.webp"
            if p.exists():
                with Image.open(p) as t:
                    out.paste(t.convert("RGB"), (int(tx * TILE - x0), int(ty * TILE - y0)))
    return out


def reference(lm):
    """First reviewed reference: the primary pick, else backup, else any."""
    refs = [r for r in (lm or {}).get("references", []) if r.get("reviewed")]
    for want in ("primary", "backup", None):
        for r in refs:
            if r.get("pick") == want and Path(REPO_ROOT / r["local_path"]).exists():
                return r
    return None


def write_page(entries, manifest):
    OUT.mkdir(parents=True, exist_ok=True)
    meta = json.loads((TILES / "map.json").read_text())
    fit = meta["fit"] if isinstance(meta["fit"], dict) else ast.literal_eval(meta["fit"])
    by_slug = {lm["slug"]: lm for lm in manifest["landmarks"]}
    rows = []
    for e in entries:
        cells = []
        if e["lon"] is not None:
            x, y = v18_px(fit, e["lon"], e["lat"])
            side = CROP * (2 if e["kit"] in BRIDGE_KITS else 1)
            box = (x - side / 2, y - side * 0.65, side, side)  # tall things rise up the screen
            for layer in ("map", "photo"):
                im = tile_crop(layer, *box)
                if side != CROP:
                    im = im.resize((CROP, CROP), Image.LANCZOS)
                name = f"{e['slug']}_{layer}.jpg"
                im.save(OUT / name, quality=85)
                cells.append(f'<figure><img src="{name}" alt="v18 {layer} layer around {html.escape(e["name"])}">'
                             f"<figcaption>v18 {'illustration' if layer == 'map' else 'photo layer'}</figcaption></figure>")
        ref = reference(by_slug.get(e["slug"]))
        if ref:
            with Image.open(REPO_ROOT / ref["local_path"]) as im:
                im = im.convert("RGB")
                im.thumbnail((CROP, CROP))
                im.save(OUT / f"{e['slug']}_ref.jpg", quality=85)
            cells.append(f'<figure><img src="{e["slug"]}_ref.jpg" alt="Reference photo of {html.escape(e["name"])}">'
                         f'<figcaption>{html.escape(ref["credit"])}</figcaption></figure>')
        else:
            cells.append('<figure class="none"><div>No reviewed reference photo yet</div></figure>')
        facts = [f"<b>kit</b> {html.escape(e['kit'])}", f"<b>region</b> {html.escape(str(e['region']))}"]
        if e.get("criticism"):
            facts.append(f"<b>criticism</b> {html.escape(e['criticism'])}")
        if e.get("note"):
            facts.append(f"<b>note</b> {html.escape(e['note'])}")
        if e.get("inventory_match"):
            facts.append(f"<b>Wikidata vs. inventory</b> {e['inventory_match']['distance_m']} m")
        rows.append(f'<section><h2>{html.escape(e["name"])} <small>{e["slug"]}</small></h2>'
                    f'<p>{" · ".join(facts)}</p><div class="row">{"".join(cells)}</div></section>')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Landmark Selection</title>
<style>
:root{{--bg:#fafafa;--fg:#1d1d1f;--muted:#5f6368;--card:#fff;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151517;--fg:#ececee;--muted:#a3a3ab;--card:#1f1f23;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:1.4rem}} h2{{font-size:1.1rem;margin:0 0 4px}} small{{color:var(--muted);font-weight:400}}
section{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:0 0 16px}}
.row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px}}
figure{{margin:0}} img{{width:100%;height:auto;display:block;border-radius:4px}}
figcaption{{color:var(--muted);font-size:.8rem}} .none div{{border:1px dashed var(--line);padding:40px 8px;text-align:center;color:var(--muted)}}
</style></head><body><h1>Landmark Selection for v19</h1>
<p>{len(entries)} structures. Kits are proposals, to be confirmed from each structure's sources. Source: config/landmarks/index.json; criticism paraphrased from Crossing Broad (Nov. 13, 2026).</p>
{''.join(rows)}</body></html>"""
    (OUT / "index.html").write_text(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="fetch Wikidata coordinates for the additions")
    ap.add_argument("--no-page", action="store_true")
    args = ap.parse_args()
    selection = json.loads(SELECTION.read_text())
    manifest = json.loads(MANIFEST.read_text())
    if args.fetch:
        qids = sorted({a["wikidata"] for a in selection["additions"] if a.get("wikidata")})
        data = fetch_wikidata(qids)
        WIKIDATA_RAW.write_text(json.dumps(data, indent=2) + "\n")
        record(WIKIDATA_RAW.name, {"source": "https://www.wikidata.org/w/api.php (wbgetentities, P625)",
                                   "license": "CC0 1.0 (Wikidata)", "items": len(data),
                                   "description": "Coordinates for the landmark additions in config/landmarks/selection.json"})
        print(f"{len(data)} Wikidata items -> {WIKIDATA_RAW}")
    wikidata = json.loads(WIKIDATA_RAW.read_text())
    inventory = json.loads(INVENTORY.read_text())
    owner = Owner(json.loads(FROZEN.read_text())["regions_in_precedence_order"])
    entries = build_index(selection, manifest, wikidata, inventory, owner)
    INDEX.write_text(json.dumps({"about": "Built by scripts/49_landmark_index.py from config/landmarks/selection.json, "
                                          "data/landmarks/manifest.json and Wikidata; do not edit by hand.",
                                 "entries": entries}, indent=2) + "\n")
    modeled = [e for e in entries if e["kit"] not in ("context", "suspension")]
    print(f"{len(entries)} entries, {len(modeled)} to model -> {INDEX}")
    for e in entries:
        flag = "" if e["region"] else "  NO REGION"
        inv = f"  inventory {e['inventory_match']['distance_m']} m" if e.get("inventory_match") else ""
        print(f"  {e['slug']:28s} {e['kit']:18s} {str(e['region']):16s}{inv}{flag}")
    if not args.no_page:
        write_page(entries, manifest)
        print("->", OUT / "index.html")


if __name__ == "__main__":
    main()
