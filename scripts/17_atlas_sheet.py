"""Before/after sheet for the problem atlas: footprint boxes vs. LiDAR shapes.

For each atlas spot, the same view (centered on the landmark, lifted to show
tall structures) is cropped from four mosaics:
  baseline render | baseline drawing | LiDAR render | LiDAR drawing
Writes output/atlas/compare.html (self-contained, JPEGs embedded) and
output/atlas/contact.jpg. Spots whose LiDAR version isn't drawn yet are shown
with what exists.

Usage: uv run python scripts/17_atlas_sheet.py
"""

import base64
import html
import io
import json
from datetime import date

from PIL import Image, ImageDraw

from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config

SPOTS = ["cityhall", "artmuseum", "30thst", "cathedral", "indhall", "franklinfield", "linc", "cbp", "pennslanding"]
CROP = 1280
OUT = REPO_ROOT / "output" / "atlas"
DRAWING = "qwen_joint_light8"
# What we saw comparing the four panels (Oct. 22, 2026), written by hand after
# reviewing the crops; rerunning the GPU step would change details
NOTES = {
    "cityhall": "Better. The clock tower rises in steps and William Penn sits on top (166.8 m vs. 167 m published). "
                "Two stray 145 m clusters on the wings, which drew as needle spires, are now flattened.",
    "artmuseum": "Better. The wings get pitched-roof forms instead of flat slabs. Small change in the drawing.",
    "30thst": "Small change. The station (flat roof, lower middle) looks much the same; the Cira Centre gets its angled top.",
    "cathedral": "Better. The dome renders as a stepped dome; the baseline had a flat box. "
                 "Eight stray clusters were flattened: six at 143-161 m on low roofs to the south, and two at 160-180 m "
                 "on the 74 m building next door (no City height on record), which had drawn as two spires.",
    "indhall": "Small change. Independence Hall's steeple appears, but it's thin at this zoom. "
               "The LiDAR drawing turned a shaded tree area into brown dirt (sampling variation, not LiDAR).",
    "franklinfield": "Better. The base now comes from the field, not the nearby rail cut (heights were 4.7 m too high), the upper deck "
                     "keeps its rows, and seat risers take the seats' color. The lower deck under the overhang isn't visible to LiDAR.",
    "linc": "Much better. The baseline drew the inside of the bowl as an apartment-style facade. "
            "With LiDAR the bowl is open, with tiered seating and the canopy ring. The outer walls still get windows.",
    "cbp": "Much better. Open bowl with tiered seating around the field; the baseline drew window walls inside the park. "
           "The sunken field used to set the base; it now comes from street level, so the tallest element (likely the scoreboard) "
           "is capped at 50.5 m instead of 71 m.",
    "pennslanding": "Not targeted. The baseline drawing invented a swimming pool on the construction site; "
                    "the LiDAR drawing shows dirt. That difference is sampling luck, not a fix.",
}


def mosaic(cfg, folder):
    _, _, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    if not all((folder / f"{f.name}.png").exists() for f in frames):
        return None
    cols = max(f.col for f in frames) + 1
    rows = max(f.row for f in frames) + 1
    m = Image.new("RGB", (cols * size, rows * size), (204, 214, 227))
    for f in frames:
        m.paste(Image.open(folder / f"{f.name}.png").convert("RGB"), (f.col * size, f.row * size))
    return m


def center_px(cfg):
    """Mosaic pixel of the spot's center, lifted a little so towers fit."""
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    w, s, e, n = cfg["bbox_wgs84"]
    le, ln = frame.to_local([(w + e) / 2], [(s + n) / 2])
    sx, sy = cam.world_to_screen(le, ln, cfg["max_height_m"] * 0.35)
    x0 = min(f.x0 - f.col * size for f in frames)
    y0 = min(f.y0 - f.row * size for f in frames)
    return int(sx[0] - x0), int(sy[0] - y0)


def crop(img, cx, cy):
    if img is None:
        im = Image.new("RGB", (CROP, CROP), (240, 240, 240))
        ImageDraw.Draw(im).text((20, 20), "not drawn yet", fill=(90, 90, 90))
        return im
    return img.crop((cx - CROP // 2, cy - CROP // 2, cx + CROP // 2, cy + CROP // 2))


def uri(im, q=82):
    buf = io.BytesIO()
    im.resize((640, 640), Image.LANCZOS).save(buf, "JPEG", quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows_html, contact_rows = [], []
    for spot in SPOTS:
        base_cfg = load_config(f"atlas_{spot}")
        lid_cfg = load_config(f"atlas_{spot}_lidar")
        cx, cy = center_px(base_cfg)
        cells = [
            ("Baseline render (one height per footprint)", mosaic(base_cfg, area_dir(base_cfg, "renders"))),
            ("Baseline drawing", mosaic(base_cfg, area_dir(base_cfg, "redraws", DRAWING))),
            ("LiDAR render (stepped parts)", mosaic(lid_cfg, area_dir(lid_cfg, "renders"))),
            ("LiDAR drawing", mosaic(lid_cfg, area_dir(lid_cfg, "redraws", DRAWING))),
        ]
        crops = [crop(m, cx, cy) for _, m in cells]
        qa_path = REPO_ROOT / "data" / "processed" / f"atlas_{spot}_lidar_qa.json"
        qa = json.loads(qa_path.read_text()) if qa_path.exists() else {}
        note = (NOTES.get(spot, "") + f" LiDAR shaped {qa.get('lidar_buildings_shaped', '?')} buildings into "
                f"{qa.get('lidar_parts', '?')} parts; {qa.get('lidar_fallback_single_height', '?')} kept a single height.")
        figs = "".join(
            f'<figure><img src="{uri(c)}" alt="{html.escape(label)}, {html.escape(base_cfg["label"])}">'
            f"<figcaption>{html.escape(label)}</figcaption></figure>"
            for (label, _), c in zip(cells, crops)
        )
        rows_html.append(f'<section><h2>{html.escape(base_cfg["label"].removeprefix("Problem atlas: "))}</h2>'
                         f'<p class="note">{html.escape(note)}</p><div class="row">{figs}</div></section>')
        strip = Image.new("RGB", (4 * 400, 400))
        for i, c in enumerate(crops):
            strip.paste(c.resize((400, 400), Image.LANCZOS), (i * 400, 0))
        contact_rows.append(strip)

    sheet = Image.new("RGB", (1600, 400 * len(contact_rows)))
    for i, r in enumerate(contact_rows):
        sheet.paste(r, (0, i * 400))
    sheet.save(OUT / "contact.jpg", quality=85)

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Problem Atlas</title>
<style>
:root {{ --bg:#f6f5f2; --fg:#1d1d1b; --muted:#5c5a55; --line:#d9d6cf; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#161615; --fg:#ecebe7; --muted:#a9a69f; --line:#3a3936; }} }}
:root[data-theme="dark"] {{ --bg:#161615; --fg:#ecebe7; --muted:#a9a69f; --line:#3a3936; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,-apple-system,sans-serif; }}
main {{ max-width:1400px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:1.6rem; margin:0 0 6px; }} h2 {{ font-size:1.1rem; margin:28px 0 4px; }}
.dek, .note {{ color:var(--muted); }} .note {{ margin:0 0 8px; font-size:.85rem; }}
.row {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr)); gap:10px; }}
figure {{ margin:0; border:1px solid var(--line); border-radius:6px; overflow:hidden; }}
img {{ display:block; width:100%; height:auto; image-rendering:pixelated; }}
figcaption {{ padding:6px 8px; font-size:.8rem; color:var(--muted); }}
.source {{ font-size:.8rem; color:var(--muted); margin-top:32px; border-top:1px solid var(--line); padding-top:12px; }}
</style></head><body><main>
<h1>LiDAR Shapes Give Landmarks and Stadiums Their Form</h1>
<p class="dek">Internal test, AI-generated illustrations. Each row is one problem spot: the City footprint layer's single height per building (baseline) vs. stepped parts cut from the City's 2022 LiDAR, before and after the AI redraw. Construction sites are a separate problem this step doesn't target.</p>
{''.join(rows_html)}
<p class="source">Sources: City of Philadelphia L&amp;I building footprints, 2024 aerial imagery and 2022 LiDAR (via PASDA). Drawings by Qwen-Image-Edit-2511 with a style LoRA trained on Gemini 3 Pro Image outputs (internal use only). Built {date.today().isoformat()}.</p>
</main></body></html>"""
    (OUT / "compare.html").write_text(page)
    print(f"-> {OUT / 'compare.html'}  ({(OUT / 'compare.html').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
