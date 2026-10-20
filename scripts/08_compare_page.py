"""Build a self-contained comparison page: render vs. AI redraw, per frame.

Writes output/compare/index.html with every image embedded as a JPEG data
URI, so the single file can be opened locally, emailed or published as-is.

Sections:
  1. Mosaics: the full render and the naive stitch of all redraws, with an
     optional outline of where the PWD layer says the river is.
  2. Per-frame sliders: drag to wipe between render and redraw.

Frames without a redraw yet are shown as render only.
"""

import argparse
import base64
import html
import io
import json
from datetime import date

import numpy as np
from PIL import Image

from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.qa import seam_ratio
from pixelphilly.water import water_screen_geometry

OUT = REPO_ROOT / "output" / "compare"
FRAME_DISPLAY_PX = 768  # embedded frame size; 1024 originals stay in output/
MOSAIC_DISPLAY_W = 2048


AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


def ap_date(d: date) -> str:
    return f"{AP_MONTHS[d.month - 1]} {d.day}, {d.year}"


def data_uri(img: Image.Image, quality=84) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def water_svg_path(water, x_origin, y_origin, scale):
    geoms = [water] if water.geom_type == "Polygon" else list(getattr(water, "geoms", []))
    d = []
    for g in geoms:
        for ring in [g.exterior, *g.interiors]:
            pts = [f"{(x - x_origin) * scale:.1f},{(y - y_origin) * scale:.1f}" for x, y in ring.coords]
            d.append("M" + "L".join(pts) + "Z")
    return " ".join(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="redraw_v3", help="which prompt version's redraws to show")
    ap.add_argument("--stage", default="water", choices=["raw", "water", "pixelized"],
                    help="raw redraws, after 10_repaint_water.py, or after 11_pixelize.py")
    args = ap.parse_args()
    cfg = load_config()
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    render_dir = REPO_ROOT / "output" / "renders"
    if args.stage == "raw":
        redraw_dir = REPO_ROOT / "output" / "redraws" / args.prompt
    else:
        redraw_dir = REPO_ROOT / "output" / "postprocessed" / args.prompt / args.stage
    log_dir = REPO_ROOT / "output" / "redraws" / args.prompt
    OUT.mkdir(parents=True, exist_ok=True)

    cols = max(f.col for f in frames) + 1
    rows = max(f.row for f in frames) + 1
    x_origin = min(f.x0 for f in frames)
    y_origin = min(f.y0 for f in frames)

    render_mosaic = Image.open(render_dir / "mosaic.png")
    redraw_mosaic = Image.new("RGB", render_mosaic.size, (204, 214, 227))
    n_redrawn = 0
    cards = []
    for f in frames:
        rd = redraw_dir / f"{f.name}.png"
        render = Image.open(render_dir / f"{f.name}.png")
        small = (FRAME_DISPLAY_PX, FRAME_DISPLAY_PX)
        r_uri = data_uri(render.resize(small, Image.LANCZOS))
        if rd.exists():
            n_redrawn += 1
            redraw = Image.open(rd).convert("RGB")
            redraw_mosaic.paste(redraw, (f.col * size, f.row * size))
            d_uri = data_uri(redraw.resize(small, Image.LANCZOS))
            cards.append(
                f"""<figure class="card">
  <div class="wipe" style="--pos:50%">
    <img src="{r_uri}" alt="3D render of frame {f.name}: aerial photo on extruded city buildings">
    <img class="top" src="{d_uri}" alt="AI pixel-art redraw of frame {f.name}">
    <input type="range" min="0" max="100" value="50" aria-label="Wipe between render and redraw for {f.name}">
  </div>
  <figcaption><span>Render</span><code>{f.name}</code><span>AI redraw</span></figcaption>
</figure>"""
            )
        else:
            cards.append(
                f"""<figure class="card pending">
  <div class="wipe"><img src="{r_uri}" alt="3D render of frame {f.name}; not yet redrawn"></div>
  <figcaption><span>Render only</span><code>{f.name}</code><span>no redraw yet</span></figcaption>
</figure>"""
            )

    scale = MOSAIC_DISPLAY_W / render_mosaic.width
    mh = round(render_mosaic.height * scale)
    disp = (MOSAIC_DISPLAY_W, mh)
    render_m_uri = data_uri(render_mosaic.resize(disp, Image.LANCZOS), quality=82)
    redraw_m_uri = data_uri(redraw_mosaic.resize(disp, Image.LANCZOS), quality=82)
    water_d = water_svg_path(water_screen_geometry(cfg, frame, cam), x_origin, y_origin, scale)
    grid_lines = "".join(
        f'<line x1="{c * size * scale:.1f}" y1="0" x2="{c * size * scale:.1f}" y2="{mh}"/>' for c in range(1, cols)
    ) + "".join(
        f'<line x1="0" y1="{r * size * scale:.1f}" x2="{MOSAIC_DISPLAY_W}" y2="{r * size * scale:.1f}"/>'
        for r in range(1, rows)
    )

    log = []
    if (log_dir / "log.jsonl").exists():
        log = [json.loads(line) for line in (log_dir / "log.jsonl").read_text().splitlines() if line]
    ok_calls = sum(1 for e in log if e.get("status") == "ok")
    err_calls = sum(1 for e in log if e.get("status") == "error")
    qa = json.loads((REPO_ROOT / "data" / "processed" / f"{cfg['name']}_qa.json").read_text())

    page = TEMPLATE.format(
        label=html.escape(cfg["label"]),
        n_frames=len(frames),
        prompt=html.escape(args.prompt),
        seam=f"{seam_ratio(np.asarray(redraw_mosaic), size):.2f}",
        **METHODS["joint" if args.prompt.startswith("qwen_joint") else "gemini"],
        stage_note=STAGE_NOTES[args.stage],
        n_redrawn=n_redrawn,
        ok_calls=ok_calls,
        err_calls=err_calls,
        buildings=f"{qa['buildings_in_scene']:,}",
        trees=f"{qa['trees_in_scene']:,}",
        outliers=len(qa["height_outliers_max_gt_ratio_x_approx"]),
        fallbacks=qa["height_source_counts"].get("max_hgt", 0) + qa["height_source_counts"].get("default", 0),
        render_m=render_m_uri,
        redraw_m=redraw_m_uri,
        mw=MOSAIC_DISPLAY_W,
        mh=mh,
        water_d=water_d,
        grid_lines=grid_lines,
        cards="\n".join(cards),
        built=ap_date(date.today()),
    )
    (OUT / "index.html").write_text(page)
    print(f"{OUT / 'index.html'}: {n_redrawn}/{len(frames)} frames redrawn, "
          f"{(OUT / 'index.html').stat().st_size / 1e6:.1f} MB")


# Wording that depends on how the pixel art was made
METHODS = {
    "gemini": {
        "method_dek": "redrawn frame by frame by Gemini 3 Pro Image",
        "method_mosaic_note": "Each square is one 1,024-pixel frame. Frames were redrawn one at a time and stitched, so tone shifts between frames remain on land; tiny.london avoids them by denoising the whole city as one image with a fine-tuned model.",
        "method_source": "Pixel art generated by Google Gemini 3 Pro Image.",
    },
    "joint": {
        "method_dek": "drawn as ONE image by Qwen-Image-Edit-2511 (Apache 2.0) with a style LoRA trained on 141 Gemini 3 Pro Image redraws (internal use only), using joint denoising over overlapping windows so frames share no seams",
        "method_mosaic_note": "Each square is one 1,024-pixel frame, cut from a single 6,144 x 5,120 image. The whole canvas was denoised at once, so there are no frame seams to hide; the frame grid is shown only for comparison with the per-frame Gemini version.",
        "method_source": "Pixel art generated by Qwen-Image-Edit-2511 with the Lightning 8-step LoRA (both Apache 2.0) and a pixel-philly style LoRA trained on Gemini 3 Pro Image outputs; internal use only pending legal review of Gemini's terms.",
    },
}

STAGE_NOTES = {
    "raw": "Shown as the model returned them.",
    "water": "Open water is then repainted in one style using USGS river outlines, because the model chose a different river color in every frame.",
    "pixelized": "Open water is repainted in one style, then every frame is snapped to one shared 40-color palette on a 2x pixel grid.",
}

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pixel Philly Pilot</title>
<style>
:root {{
  --bg: #f6f5f2; --fg: #1d1d1b; --muted: #5c5a55; --card: #ffffff; --line: #d9d6cf;
  --accent: #0b5cad; --water: #0b5cad; --grid: rgba(0,0,0,.35);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #161615; --fg: #ecebe7; --muted: #a9a69f; --card: #222220; --line: #3a3936;
    --accent: #7db7f0; --water: #7db7f0; --grid: rgba(255,255,255,.4);
  }}
}}
:root[data-theme="dark"] {{
  --bg: #161615; --fg: #ecebe7; --muted: #a9a69f; --card: #222220; --line: #3a3936;
  --accent: #7db7f0; --water: #7db7f0; --grid: rgba(255,255,255,.4);
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1200px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: clamp(1.6rem, 4vw, 2.3rem); line-height: 1.15; margin: 0 0 8px; }}
h2 {{ font-size: 1.25rem; margin: 40px 0 8px; }}
p {{ max-width: 70ch; }}
.dek {{ color: var(--muted); font-size: 1.05rem; margin-top: 0; }}
.label {{ display: inline-block; font-size: .78rem; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; border: 1px solid var(--line); border-radius: 4px; padding: 2px 8px; color: var(--muted); }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
.stat {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
.stat b {{ display: block; font-size: 1.35rem; }}
.stat span {{ color: var(--muted); font-size: .85rem; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; margin: 8px 0 12px; }}
.controls button {{ font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--line);
  background: var(--card); color: var(--fg); cursor: pointer; }}
.controls button[aria-pressed="true"] {{ background: var(--accent); color: var(--bg); border-color: var(--accent); }}
.mosaic {{ position: relative; width: 100%; border-radius: 8px; overflow: hidden; border: 1px solid var(--line); }}
.mosaic img {{ display: block; width: 100%; height: auto; }}
.mosaic svg {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }}
.mosaic .water {{ fill: none; stroke: var(--water); stroke-width: 4; stroke-dasharray: 10 6; }}
.mosaic .grid line {{ stroke: var(--grid); stroke-width: 1.5; stroke-dasharray: 4 6; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); gap: 16px; }}
.card {{ margin: 0; background: var(--card); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
.card.pending {{ opacity: .7; }}
.wipe {{ position: relative; aspect-ratio: 1; }}
.wipe img {{ position: absolute; inset: 0; width: 100%; height: 100%; display: block; }}
.wipe img.top {{ clip-path: inset(0 0 0 var(--pos)); }}
.wipe::after {{ content: ""; position: absolute; top: 0; bottom: 0; left: var(--pos); width: 2px;
  background: #fff; box-shadow: 0 0 0 1px rgba(0,0,0,.4); pointer-events: none; }}
.card.pending .wipe::after {{ display: none; }}
.wipe input {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: ew-resize; margin: 0; }}
figcaption {{ display: flex; justify-content: space-between; gap: 8px; padding: 8px 12px; font-size: .85rem; color: var(--muted); }}
figcaption code {{ color: var(--fg); }}
ul {{ max-width: 70ch; padding-left: 20px; }}
li {{ margin: 4px 0; }}
.source {{ font-size: .85rem; color: var(--muted); border-top: 1px solid var(--line); margin-top: 40px; padding-top: 16px; }}
</style>
</head>
<body>
<main>
<span class="label">Internal pilot · AI-generated illustration</span>
<h1>Old City, Drawn as Pixel Art From Open City Data</h1>
<p class="dek">A test of whether City of Philadelphia open data can stand in for Google’s 3D tiles as the input to a tiny.london-style pixel-art map. {label}, rendered from city building footprints, 2024 aerial photos and the street-tree inventory, then {method_dek}. {stage_note}</p>

<div class="stats">
  <div class="stat"><b>{n_redrawn}/{n_frames}</b><span>frames redrawn</span></div>
  <div class="stat"><b>{buildings}</b><span>building footprints</span></div>
  <div class="stat"><b>{trees}</b><span>inventory trees</span></div>
  <div class="stat"><b>{seam}</b><span>seam score at frame borders (1.0 = invisible)</span></div>
</div>

<h2>The whole area</h2>
<p>{method_mosaic_note}</p>
<div class="controls" role="group" aria-label="Mosaic view">
  <button type="button" data-view="redraw" aria-pressed="true">AI redraw</button>
  <button type="button" data-view="render" aria-pressed="false">Render</button>
  <label><input type="checkbox" id="water"> River outline (PWD, Pennsylvania half)</label>
  <label><input type="checkbox" id="grid" checked> Frame edges</label>
</div>
<div class="mosaic">
  <img id="mosaic-img" src="{redraw_m}" data-redraw="{redraw_m}" data-render="{render_m}"
       alt="Mosaic of Old City Philadelphia as AI pixel art, the Delaware River and Ben Franklin Bridge at top right" width="{mw}" height="{mh}">
  <svg viewBox="0 0 {mw} {mh}" preserveAspectRatio="none" aria-hidden="true">
    <path class="water" d="{water_d}" hidden></path>
    <g class="grid">{grid_lines}</g>
  </svg>
</div>

<h2>Frame by frame</h2>
<p>Drag across a frame to wipe between the render (left) and the AI redraw (right).</p>
<div class="cards">
{cards}
</div>

<h2>Known limits of this input</h2>
<ul>
  <li>The Ben Franklin Bridge deck, I-95 and I-676 are not in the building layer, so they lie flat on the ground as photo texture.</li>
  <li>The aerials are not true orthophotos: tall buildings lean in the photo, so some roof textures sit slightly off their footprints.</li>
  <li>Walls have no façade imagery. Buildings 20 m or shorter are tinted toward brick as a stylistic assumption (the city publishes no façade-material data); taller ones take their roof color. The model invents windows.</li>
  <li>The Ben Franklin Bridge deck is flat photo texture; the towers and cables the model drew follow the bridge's shadow in the photo, not its real structure.</li>
  <li>The aerial is median-filtered before rendering to remove cars and rooftop clutter, which the model otherwise copies instead of redrawing.</li>
  <li>Trees are stylized balls at city inventory points, sized from trunk diameter. Private trees are missing, and the aerials were flown leaf-off.</li>
  <li>Heights use the city’s approx_hgt field; {fallbacks} buildings fell back to max_hgt or a 10 m default, and {outliers} have max_hgt over three times approx_hgt (listed in the QA file).</li>
</ul>

<p class="source">Sources: City of Philadelphia (L&amp;I building footprints; 2024 3-inch aerial imagery; Parks &amp; Recreation tree inventory, 2025), Philadelphia Water Department hydrography, via OpenDataPhilly and the city’s ArcGIS services. {method_source} Labeled as AI-generated illustration; it is not a photograph or survey. Method after isometric-nyc (Andy Coenen) and tiny.london (Boris Starkov). Built {built}.</p>
</main>
<script>
const img = document.getElementById("mosaic-img");
document.querySelectorAll("[data-view]").forEach(btn => btn.addEventListener("click", () => {{
  document.querySelectorAll("[data-view]").forEach(b => b.setAttribute("aria-pressed", String(b === btn)));
  img.src = img.dataset[btn.dataset.view];
  img.alt = btn.dataset.view === "render"
    ? "Mosaic of the 3D render of Old City Philadelphia built from city open data"
    : "Mosaic of Old City Philadelphia as AI pixel art, the Delaware River and Ben Franklin Bridge at top right";
}}));
document.getElementById("water").addEventListener("change", e => {{
  document.querySelector(".mosaic .water").toggleAttribute("hidden", !e.target.checked);
}});
document.getElementById("grid").addEventListener("change", e => {{
  document.querySelector(".mosaic .grid").style.display = e.target.checked ? "" : "none";
}});
document.querySelectorAll(".wipe input").forEach(r => r.addEventListener("input", () => {{
  r.parentElement.style.setProperty("--pos", r.value + "%");
}}));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
