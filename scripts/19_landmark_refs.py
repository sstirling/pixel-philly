"""Track 3: a reference photo set for Philadelphia landmarks, openly licensed only.

For each landmark in LANDMARKS this script records:
  - coordinates from Wikidata (P625), cross-checked against the City of
    Philadelphia's Address Information System (AIS) when we have a street
    address; the distance between the two is stored so a bad match is visible
  - which mapped areas (config/*_lidar.json bboxes) contain it
  - up to 3 reference photos, ONLY from:
      (a) Library of Congress HABS/HAER surveys: works of the US government,
          public domain (https://www.loc.gov/rr/print/res/114_habs.html)
      (b) Wikimedia Commons files whose LicenseShortName is CC0, public
          domain or CC BY (any version). CC BY-SA and everything else is
          rejected, so no share-alike obligation can reach the outputs.
and downloads the chosen photos to data/landmarks/refs/<slug>/ (git-ignored).

Photo choice is a keyword heuristic on captions and file names (prefer
"general view", "perspective", "exterior"; reject interiors, details,
drawings). It is not a judgment of quality: look at the photos before using
them, and set "use" in the manifest by hand if a better candidate exists.

Rate limits: one request at a time with a pause (LoC asks for a slow crawl;
Commons and Wikidata ask for a descriptive User-Agent, set below).

Writes:
  data/landmarks/manifest.json
  data/landmarks/refs/<slug>/<n>_<source>.jpg   (not committed)

Usage:
  uv run python scripts/19_landmark_refs.py              # all landmarks
  uv run python scripts/19_landmark_refs.py --no-download
"""

import argparse
import html
import json
import math
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from pixelphilly.projection import REPO_ROOT

UA = "pixel-philly (https://github.com/sstirling/pixel-philly; stephenstirling@gmail.com)"
OUT = REPO_ROOT / "data" / "landmarks"
PAUSE = {"loc": 3.0, "wiki": 0.5, "ais": 0.3}

# slug, name, Wikidata QID, AIS address (None = no single address, Wikidata
# coordinates only), LoC HABS/HAER item ids. QIDs were found with Wikidata's
# wbsearchentities / SPARQL and checked by label and description.
LANDMARKS = [
    ("city_hall", "Philadelphia City Hall", "Q1138183", "1400 JOHN F KENNEDY BLVD", ["pa4092"]),
    ("independence_hall", "Independence Hall", "Q390028", "520 CHESTNUT ST", ["pa0939"]),
    ("art_museum", "Philadelphia Museum of Art", "Q510324", "2600 BENJAMIN FRANKLIN PKWY", ["pa1065"]),
    ("30th_street_station", "30th Street Station", "Q224214", "2955 MARKET ST", []),
    ("reading_terminal", "Reading Terminal", "Q339098", "1115 MARKET ST", ["pa3514", "pa1051"]),
    ("eastern_state", "Eastern State Penitentiary", "Q489417", "2027 FAIRMOUNT AVE", ["pa1207"]),
    ("psfs", "PSFS Building (Loews Philadelphia Hotel)", "Q1548457", "1200 MARKET ST", ["pa1068"]),
    ("comcast_center", "Comcast Center", "Q1113808", "1701 JOHN F KENNEDY BLVD", []),
    ("comcast_technology_center", "Comcast Technology Center", "Q16958963", "1800 ARCH ST", []),
    ("boathouse_row", "Boathouse Row", "Q2907541", None, ["pa1118"]),
    ("franklin_institute", "Franklin Institute", "Q339484", "222 N 20TH ST", []),
    ("cathedral_basilica", "Cathedral Basilica of Saints Peter and Paul", "Q5052192", "1723 RACE ST", []),
    ("christ_church", "Christ Church", "Q979481", "20 N AMERICAN ST", ["pa1152"]),
    ("carpenters_hall", "Carpenters' Hall", "Q1093592", "320 CHESTNUT ST", ["pa1131"]),
    ("girard_college", "Girard College", "Q3768575", None, ["pa0731"]),
    ("baptist_temple", "Baptist Temple (Temple University)", "Q131404802", "1837 N BROAD ST", []),
    ("college_hall", "College Hall (University of Pennsylvania)", "Q5146410", None, []),
    ("lincoln_financial_field", "Lincoln Financial Field", "Q1052370", None, []),
    ("citizens_bank_park", "Citizens Bank Park", "Q912770", None, []),
    ("xfinity_mobile_arena", "Xfinity Mobile Arena (formerly Wells Fargo Center)", "Q818735", "3601 S BROAD ST", []),
    ("navy_yard", "Philadelphia Naval Shipyard (Navy Yard)", "Q1548690", None, []),
    ("divine_lorraine", "Divine Lorraine Hotel", "Q5284100", "699 N BROAD ST", []),
    ("academy_natural_sciences", "Academy of Natural Sciences", "Q2822400", "1900 BENJAMIN FRANKLIN PKWY", []),
    ("parkway_central_library", "Parkway Central Library", "Q48977201", "1901 VINE ST", []),
    ("rodin_museum", "Rodin Museum", "Q1321619", "2151 BENJAMIN FRANKLIN PKWY", []),
    ("pafa", "Pennsylvania Academy of the Fine Arts", "Q1952033", "118 N BROAD ST", []),
    ("liberty_place", "Liberty Place", "Q1449747", "1650 MARKET ST", []),
    ("wanamakers", "Wanamaker's (Wanamaker Building)", "Q3503499", "1300 MARKET ST", []),
    ("union_league", "Union League of Philadelphia", "Q16238498", "140 S BROAD ST", []),
    ("second_bank", "Second Bank of the United States", "Q2263849", "420 CHESTNUT ST", []),
    ("merchants_exchange", "Merchants' Exchange Building", "Q3642743", "143 S 3RD ST", []),
    ("elfreths_alley", "Elfreth's Alley", "Q3050836", None, []),
    ("ben_franklin_bridge", "Benjamin Franklin Bridge", "Q817485", None, []),
    ("fairmount_water_works", "Fairmount Water Works", "Q5430659", "640 WATER WORKS DR", []),
    ("fisher_fine_arts_library", "Fisher Fine Arts Library", "Q5454798", "220 S 34TH ST", []),
    ("penn_museum", "Penn Museum", "Q1285902", "3260 SOUTH ST", []),
    ("convention_center", "Pennsylvania Convention Center", "Q3374781", "1101 ARCH ST", []),
    ("gloria_dei", "Gloria Dei (Old Swedes') Church", "Q4352333", "916 S SWANSON ST", []),
    ("old_st_josephs", "Old St. Joseph's Church", "Q7085037", "321 WILLINGS ALY", []),
    ("lit_brothers", "Lit Brothers", "Q6647346", "701 MARKET ST", []),
]

GOOD_WORDS = ["general view", "perspective", "oblique", "exterior", "corner", "looking", "from", "view of"]
BAD_WORDS = ["interior", "detail", "plan", "drawing", "sheet", "room", "stair", "ceiling", "door", "window",
             "photocopy", "data page", "map", "night", "organ", "statue", "sculpture", "painting",
             "inside", "hallway", "lobby", "mural", "sign", "plaque", "lithograph", "engraving", "postcard",
             "construction", "panorama", "skyline", "gallery", "exhibit", "artwork",
             # off-subject files that pass the license filter in museum and stadium categories
             "aktie", "certificate", "stock", "logo", "newspaper", "times", "cover", "stamp", "woodcut",
             "page", "fossil", "butterfly", "relief", "soldier", "airmen", "sgt", "player", "game",
             "forward", "floor", "concert", "crowd", "event", "ceremony", "portrait", "cutaway"]
# Commons categories that mark a file as an artwork or object (the museums'
# categories are full of public-domain paintings), not a photo of the building
NOT_BUILDING_CATS = re.compile(r"painting|drawing|print|sculpture|collection|artwork|objects|textile|"
                               r"photographs by .* in the|interior|organ", re.I)


def get_json(url, kind, post=None):
    """GET (or POST form data, for long Commons title lists) with retries."""
    time.sleep(PAUSE[kind])
    data = urllib.parse.urlencode(post).encode() if post else None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # transient network or 429: back off and retry
            if attempt == 3:
                raise
            print(f"    retry {attempt + 1} ({e})")
            time.sleep(10 * (attempt + 1))


def haversine_m(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def mapped_areas():
    """Main mapped regions (not the small atlas windows) and their bboxes."""
    out = {}
    for p in sorted((REPO_ROOT / "config").glob("*_lidar.json")):
        if p.stem.startswith("atlas_"):
            continue
        out[p.stem] = json.loads(p.read_text())["bbox_wgs84"]
    return out


def wikidata(qid):
    d = get_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", "wiki")["entities"][qid]
    claims = d["claims"]

    def val(prop):
        return [c["mainsnak"].get("datavalue", {}).get("value") for c in claims.get(prop, [])]

    coords = [v for v in val("P625") if v]
    return {
        "label": d["labels"].get("en", {}).get("value"),
        "coord": (coords[0]["longitude"], coords[0]["latitude"]) if coords else None,
        "p18": [v for v in val("P18") if v],
        "commons_category": next(iter(val("P373")), None),
    }


def ais(address):
    url = "https://api.phila.gov/ais/v1/search/" + urllib.parse.quote(address)
    try:
        d = get_json(url, "ais")
    except Exception as e:
        return {"query": address, "error": str(e)}
    if not d.get("features"):
        return {"query": address, "error": "no match"}
    f = d["features"][0]
    lon, lat = f["geometry"]["coordinates"]
    return {"query": address, "matched": f["properties"]["street_address"], "lon": lon, "lat": lat,
            "match_type": f.get("match_type")}


def score_text(text):
    t = text.lower()
    s = sum(2 for w in GOOD_WORDS if w in t)
    s -= sum(5 for w in BAD_WORDS if re.search(r"\b" + re.escape(w), t))
    return s


def loc_candidates(item_id):
    d = get_json(f"https://www.loc.gov/item/{item_id}/?fo=json", "loc")
    item = d["item"]
    title = item.get("title", "")
    survey = next((n for n in item.get("other_number", []) or [] if "HABS" in n or "HAER" in n), None)
    cands = []
    for res in d.get("resources", []):
        for group in res.get("files", []):
            caption = next((f.get("title", "") for f in group if f.get("use") == "caption"), "")
            jpgs = [f for f in group if f.get("mimetype", "").startswith("image/jp") and f.get("width")]
            if not jpgs:
                continue
            kinds = {f.get("type") for f in group}
            if not any(k and "photo" in k for k in kinds):
                continue  # measured drawings and data pages
            best = max(jpgs, key=lambda f: f["width"] * f["height"])
            page = next((f.get("aka") for f in group if f.get("use") == "caption"), None)
            cands.append({
                "source": "loc_habs",
                "item": f"https://www.loc.gov/item/{item_id}/",
                "source_url": page or f"https://www.loc.gov/item/{item_id}/",
                "image_url": best["url"],
                "width": best["width"], "height": best["height"],
                "caption": caption,
                "license": "Public domain (work of the US government; Historic American Buildings Survey)",
                "author": "Historic American Buildings Survey / Historic American Engineering Record, "
                          "National Park Service",
                "credit": f"Historic American Buildings Survey{f' ({survey})' if survey else ''}, "
                          "Library of Congress Prints and Photographs Division; public domain",
                "score": score_text(caption) + 1,  # small preference: no license ambiguity at all
            })
    return title, cands


LICENSE_OK = re.compile(r"^(cc0|public domain|pd\b|pd-|cc by \d|cc-by-\d|cc by$)", re.I)


def license_ok(short):
    s = (short or "").strip()
    return bool(LICENSE_OK.match(s)) and "sa" not in s.lower().replace("usa", "")


def commons_files(titles):
    """imageinfo + extmetadata for File: titles (up to 50 per call)."""
    out = []
    for i in range(0, len(titles), 50):
        q = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
             "iiurlwidth": 1600, "titles": "|".join(titles[i:i + 50])}
        d = get_json("https://commons.wikimedia.org/w/api.php", "wiki", post=q)
        out += list(d.get("query", {}).get("pages", {}).values())
    return out


def commons_category_titles(cat, limit=150):
    q = {"action": "query", "format": "json", "list": "categorymembers", "cmtitle": f"Category:{cat}",
         "cmtype": "file", "cmlimit": limit}
    d = get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(q), "wiki")
    return [m["title"] for m in d.get("query", {}).get("categorymembers", [])]


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def name_words(name):
    """Distinctive words of a landmark's name, to require in a Commons file's
    title or description (category members drift to other subjects)."""
    stop = {"philadelphia", "building", "street", "center", "church", "hall", "university", "formerly",
            "pennsylvania", "the", "of", "and"}
    return [w for w in re.findall(r"[a-z0-9']+", name.lower()) if len(w) >= 4 and w not in stop]


def commons_candidates(p18, category, name):
    titles = [f"File:{t}" for t in p18]
    if category:
        titles += [t for t in commons_category_titles(category) if t not in titles]
    cands, rejected = [], {}
    for page in commons_files(titles):
        if "imageinfo" not in page:
            continue
        ii = page["imageinfo"][0]
        if ii.get("mime") not in ("image/jpeg", "image/png"):
            continue
        md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        if not license_ok(lic):
            rejected[lic] = rejected.get(lic, 0) + 1
            continue
        title = page["title"]
        desc = strip_html(md.get("ImageDescription", {}).get("value", ""))[:300]
        is_p18 = title.removeprefix("File:") in p18
        if not is_p18:
            if NOT_BUILDING_CATS.search(md.get("Categories", {}).get("value", "")):
                continue
            words = name_words(name)
            if words and not any(w in (title + " " + desc).lower() for w in words):
                continue
        author = strip_html(md.get("Artist", {}).get("value", "")) or "unknown"
        score = score_text(title + " " + desc) + (3 if is_p18 else 0)
        score += 1 if ii.get("width", 0) >= 1600 else 0
        cands.append({
            "source": "wikimedia_commons",
            "source_url": ii["descriptionurl"],
            "image_url": ii.get("thumburl") or ii["url"],
            "original_url": ii["url"],
            "width": ii.get("width"), "height": ii.get("height"),
            "caption": desc or title,
            "license": lic,
            "license_url": md.get("LicenseUrl", {}).get("value"),
            "author": author,
            "credit": f"{author} / Wikimedia Commons, {lic} ({ii['descriptionurl']})",
            "wikidata_p18": is_p18,
            "score": score,
        })
    return cands, rejected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--only", help="comma-separated slugs")
    args = ap.parse_args()

    areas = mapped_areas()
    manifest_path = OUT / "manifest.json"
    # Hand-set review fields survive a rebuild (keyed by image URL), and so do
    # references added by hand during review ("added_by"), which this script
    # would not find again. Landmark-level "status" is kept too.
    HAND = ("reviewed", "pick", "review_note")
    hand, added, status = {}, {}, {}
    if manifest_path.exists():
        for e in json.loads(manifest_path.read_text())["landmarks"]:
            kept = {k: e[k] for k in ("status", "status_note", "excluded_reason", "coord_override") if k in e}
            if kept:
                status[e["slug"]] = kept
            for ref in e["references"]:
                hand[ref["image_url"]] = {k: ref[k] for k in HAND if k in ref}
                if ref.get("author_checked"):  # author fixed by hand from the file page
                    hand[ref["image_url"]].update({k: ref[k] for k in ("author", "credit", "author_checked")})
                if ref.get("added_by"):
                    added.setdefault(e["slug"], []).append(ref)
    entries = []
    only = set(args.only.split(",")) if args.only else None
    for slug, name, qid, address, loc_ids in LANDMARKS:
        if only and slug not in only:
            continue
        print(slug)
        wd = wikidata(qid)
        lon, lat = wd["coord"] if wd["coord"] else (None, None)
        a = ais(address) if address else None
        if a and "lon" in a and lon is not None:
            a["distance_to_wikidata_m"] = round(haversine_m(lon, lat, a["lon"], a["lat"]), 1)
        inside = [k for k, (w, s, e, n) in areas.items() if lon is not None and w <= lon <= e and s <= lat <= n]

        cands, loc_titles = [], {}
        for item_id in loc_ids:
            title, c = loc_candidates(item_id)
            loc_titles[item_id] = title
            cands += c
        commons, rejected = commons_candidates(wd["p18"], wd["commons_category"], name)
        cands += commons
        cands.sort(key=lambda c: -c["score"])
        # Up to 3: best HABS photo, best Commons photo, then the next best of either
        chosen = []
        for src in ("loc_habs", "wikimedia_commons"):
            best = next((c for c in cands if c["source"] == src and c["score"] >= 0), None)
            if best:
                chosen.append(best)
        for c in cands:
            if len(chosen) >= 3:
                break
            if c not in chosen and c["score"] >= 0:
                chosen.append(c)

        refs = []
        for i, c in enumerate(chosen):
            entry = {k: v for k, v in c.items() if k != "score"}
            entry["heuristic_score"] = c["score"]
            # Set to true by hand after looking at the photo (license is
            # checked automatically; subject and viewpoint are not)
            entry["reviewed"] = False
            entry.update(hand.get(c["image_url"], {}))
            if not args.no_download:
                d = OUT / "refs" / slug
                d.mkdir(parents=True, exist_ok=True)
                ext = ".png" if c["image_url"].lower().endswith(".png") else ".jpg"
                path = d / f"{i}_{c['source']}{ext}"
                if not path.exists():
                    time.sleep(PAUSE["loc"] if c["source"] == "loc_habs" else PAUSE["wiki"])
                    req = urllib.request.Request(c["image_url"], headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=120) as r:
                        path.write_bytes(r.read())
                entry["local_path"] = str(path.relative_to(REPO_ROOT))
            refs.append(entry)

        refs += [r for r in added.get(slug, []) if r["image_url"] not in {x["image_url"] for x in refs}]
        entries.append({
            **status.get(slug, {}),
            "slug": slug,
            "name": name,
            "wikidata": qid,
            "wikidata_label": wd["label"],
            "lon": lon, "lat": lat,
            "coord_source": "Wikidata P625",
            "ais": a,
            "mapped_areas": inside,
            "loc_items": loc_titles,
            "commons_category": wd["commons_category"],
            "candidates_considered": len(cands),
            "commons_rejected_licenses": rejected,
            "references": refs,
        })
        print(f"  {wd['label']}  ({lon}, {lat})  areas {inside}  ais {a and a.get('distance_to_wikidata_m')} m"
              f"  candidates {len(cands)}  chosen {[r['source'] for r in refs]}")

    if only and manifest_path.exists():  # merge a partial run into the existing manifest
        old = {e["slug"]: e for e in json.loads(manifest_path.read_text())["landmarks"]}
        old.update({e["slug"]: e for e in entries})
        entries = [old[s] for s, *_ in LANDMARKS if s in old]
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "built_by": "scripts/19_landmark_refs.py",
        "license_policy": "LoC HABS/HAER (public domain) or Wikimedia Commons CC0 / public domain / CC BY "
                          "only. CC BY-SA and all other licenses rejected. CC BY requires the credit line.",
        "selection_note": "References are ranked by a caption/file-name keyword heuristic; review before use.",
        "landmarks": entries,
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {manifest_path} ({len(entries)} landmarks)")


if __name__ == "__main__":
    main()
