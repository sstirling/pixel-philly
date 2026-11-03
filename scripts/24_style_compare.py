"""Phase 1 style comparison: render | old style | A | B on the 8 atlas spots.

Writes output/style/compare.html (self-contained: images embedded as JPEG
data URIs; readable in light and dark mode) and output/style/compare.jpg
(contact grid), plus output/style/metrics.json.

Variants (run names, drawings read from postprocessed/<run>/water/ after
10_repaint_water.py --invented-water fix, else redraws/<run>/):
  old  qwen_joint_light8           style LoRA trained on Gemini outputs: reference only
  A    qwen_joint_light8_nolora    no style LoRA, prompt only
  B    qwen_joint_light8_cleanlora self-distilled LoRA qe2511_clean_r16_v1

Per variant and spot:
  seam      frame-border seam ratio, only on borders between two drawn
            frames (clipped spots have empty lattice cells; a border with
            black would read as a seam). ~1.0 = invisible.
  flat      mean flat share (pixelphilly.qa.flat_share)
  water     invented-water blobs the fix found (non-exempt; before repair)
  color     mean invented saturated color share (cars, confetti;
            pixelphilly.trainset_clean.invented_color_share), in percent
  shift     worst registration shift against the render, px

Notes per spot come from output/style/notes.json (written by hand after
looking at the drawings).

Usage: uv run python scripts/24_style_compare.py
"""

import base64
import html
import io
import json

import numpy as np
from PIL import Image, ImageDraw

from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.qa import flat_share, registration_shift
from pixelphilly.trainset_clean import invented_color_share

SPOTS = [
    ("atlas_passyunk_fac", "East Passyunk rowhouses"),
    ("atlas_porch_fac", "Allegheny West porch fronts"),
    ("atlas_twin_fac", "West Philadelphia twins"),
    ("atlas_cityhall_fac", "City Hall"),
    ("atlas_indhall_fac", "Independence Hall"),
    ("atlas_wissahickon_fac", "Wissahickon woods and creek"),
    ("atlas_airport_fac", "PHL airport terminal and runway"),
    ("atlas_northeast_fac", "Northeast twins and singles"),
]
VARIANTS = [
    ("old", "qwen_joint_light8", "Old style (Gemini-derived LoRA, reference only)"),
    ("A", "qwen_joint_light8_nolora", "A: no style LoRA"),
    ("B", "qwen_joint_light8_cleanlora", "B: clean self-distilled LoRA"),
]
OUT = REPO_ROOT / "output" / "style"
DETAIL = 640  # px of the 1:1 detail crop
OVERVIEW = 560  # px width of the whole-spot overview


def drawn_dir(cfg, run):
    post = area_dir(cfg, "postprocessed", run, "water")
    return post if post.exists() else area_dir(cfg, "redraws", run)


def mosaic(cfg, folder):
    _, _, frames = area_setup(cfg)
    s = cfg["camera"]["frame_px"]
    cols, rows = max(f.col for f in frames) + 1, max(f.row for f in frames) + 1
    m = Image.new("RGB", (cols * s, rows * s), (0, 0, 0))
    have = set()
    for f in frames:
        p = folder / f"{f.name}.png"
        if p.exists():
            m.paste(Image.open(p).convert("RGB"), (f.col * s, f.row * s))
            have.add((f.col, f.row))
    return m, have


def border_seam(img, have, s):
    """Mean jump across frame borders shared by two drawn frames over the
    mean jump between other adjacent pixel pairs inside drawn frames."""
    a = np.asarray(img).astype(float)
    dx = np.abs(np.diff(a, axis=1)).mean(axis=2)
    dy = np.abs(np.diff(a, axis=0)).mean(axis=2)
    seam, inner = [], []
    for (c, r) in have:
        y0, x0 = r * s, c * s
        blk_dx = dx[y0:y0 + s, x0:x0 + s - 1]
        blk_dy = dy[y0:y0 + s - 1, x0:x0 + s]
        inner += [blk_dx.ravel(), blk_dy.ravel()]
        if (c + 1, r) in have:
            seam.append(dx[y0:y0 + s, x0 + s - 1])
        if (c, r + 1) in have:
            seam.append(dy[y0 + s - 1, x0:x0 + s])
    if not seam:
        return None
    return float(np.concatenate(seam).mean() / np.concatenate(inner).mean())


def b64(img, q=86):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def crop_box(have, s, render):
    """A DETAIL x DETAIL box centered on the middle of the drawn frames,
    nudged onto content."""
    cs = [c for c, _ in have]
    rs = [r for _, r in have]
    cx = int((min(cs) + max(cs) + 1) / 2 * s)
    cy = int((min(rs) + max(rs) + 1) / 2 * s)
    return (cx - DETAIL // 2, cy - DETAIL // 2, cx + DETAIL // 2, cy + DETAIL // 2)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    notes_path = OUT / "notes.json"
    notes = json.loads(notes_path.read_text()) if notes_path.exists() else {}
    metrics, rows_html, grid_rows = {}, [], []
    for area, label in SPOTS:
        cfg = load_config(area)
        s = cfg["camera"]["frame_px"]
        _, _, frames = area_setup(cfg)
        render, have = mosaic(cfg, area_dir(cfg, "renders"))
        box = crop_box(have, s, render)
        cells = [("render", "Render (City open data)", render, None)]
        m = {}
        for key, run, title in VARIANTS:
            folder = drawn_dir(cfg, run)
            if not folder.exists():
                cells.append((key, title, None, None))
                continue
            img, dhave = mosaic(cfg, folder)
            flats, colors, shifts = [], [], []
            for f in frames:
                p = folder / f"{f.name}.png"
                if not p.exists():
                    continue
                d = np.asarray(Image.open(p).convert("RGB"))
                r = np.asarray(Image.open(area_dir(cfg, "renders", f"{f.name}.png")).convert("RGB"))
                flats.append(flat_share(d))
                colors.append(invented_color_share(r, d))
                shifts.append(max(abs(v) for v in registration_shift(Image.fromarray(r), Image.fromarray(d))))
            rep = folder / "report.json"
            water = None
            if rep.exists():
                iwr = json.loads(rep.read_text()).get("invented_water")
                if iwr:
                    water = sum(1 for b in iwr["blobs"] if not b["exempt"])
            m[key] = {"run": run, "seam": round(border_seam(img, dhave, s) or float("nan"), 3),
                      "flat": round(float(np.mean(flats)), 3), "invented_water_blobs": water,
                      "invented_color_pct": round(100 * float(np.mean(colors)), 2),
                      "max_shift_px": int(max(shifts)), "frames": len(flats)}
            cells.append((key, title, img, m[key]))
        m["render"] = {"seam": round(border_seam(render, have, s) or float("nan"), 3),
                       "flat": round(float(np.mean([flat_share(np.asarray(Image.open(area_dir(cfg, "renders", f"{f.name}.png")).convert("RGB"))) for f in frames])), 3)}
        metrics[area] = m

        figs, grid = [], []
        for key, title, img, mm in cells:
            if img is None:
                figs.append(f'<figure class="cell missing"><div class="ph">not drawn yet</div><figcaption>{html.escape(title)}</figcaption></figure>')
                grid.append(None)
                continue
            over = img.copy()
            over.thumbnail((OVERVIEW, OVERVIEW * 2), Image.LANCZOS)
            det = img.crop(box)
            stats = ""
            if mm:
                w = "–" if mm.get("invented_water_blobs") is None else mm["invented_water_blobs"]
                stats = (f'<dl><dt>Seam</dt><dd>{mm["seam"]}</dd><dt>Flat</dt><dd>{mm["flat"]}</dd>'
                         f'<dt>Invented water</dt><dd>{w}</dd><dt>Invented color</dt><dd>{mm["invented_color_pct"]}%</dd>'
                         f'<dt>Max shift</dt><dd>{mm["max_shift_px"]} px</dd></dl>')
            else:
                stats = f'<dl><dt>Seam</dt><dd>{m["render"]["seam"]}</dd><dt>Flat</dt><dd>{m["render"]["flat"]}</dd></dl>'
            cls = "cell old" if key == "old" else "cell"
            alt = f"{label}: {title}, 1:1 detail"
            figs.append(f'<figure class="{cls}"><img loading="lazy" src="{b64(det)}" alt="{html.escape(alt)}">'
                        f'<details><summary>Whole spot</summary><img loading="lazy" src="{b64(over, 80)}" '
                        f'alt="{html.escape(label + ": " + title + ", whole spot")}"></details>'
                        f'<figcaption>{html.escape(title)}</figcaption>{stats}</figure>')
            grid.append(det.resize((384, 384), Image.LANCZOS))
        note = notes.get(area, "")
        rows_html.append(f'<section><h2>{html.escape(label)}</h2><p class="area">{area}</p>'
                         f'<p class="note">{html.escape(note)}</p><div class="row">{"".join(figs)}</div></section>')
        grid_rows.append((label, grid))

    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    # Contact grid
    t, lab = 384, 26
    sheet = Image.new("RGB", (4 * (t + 6) + 6, len(grid_rows) * (t + lab + 6) + 40), (250, 250, 247))
    d = ImageDraw.Draw(sheet)
    for i, h in enumerate(["Render", "Old (Gemini-derived, reference only)", "A: no LoRA", "B: clean LoRA"]):
        d.text((6 + i * (t + 6), 12), h, fill=(20, 20, 20))
    for j, (label, grid) in enumerate(grid_rows):
        y = 40 + j * (t + lab + 6)
        d.text((6, y + 6), label, fill=(20, 20, 20))
        for i, g in enumerate(grid):
            if g is not None:
                sheet.paste(g, (6 + i * (t + 6), y + lab))
    sheet.save(OUT / "compare.jpg", quality=85)

    summary = []
    for key, run, title in VARIANTS:
        vals = [metrics[a][key] for a, _ in SPOTS if key in metrics[a]]
        if not vals:
            continue
        summary.append(f'<tr><th scope="row">{html.escape(title)}</th>'
                       f'<td>{np.nanmedian([v["seam"] for v in vals]):.2f}</td>'
                       f'<td>{np.mean([v["flat"] for v in vals]):.3f}</td>'
                       f'<td>{sum(v["invented_water_blobs"] or 0 for v in vals)}</td>'
                       f'<td>{np.mean([v["invented_color_pct"] for v in vals]):.2f}%</td>'
                       f'<td>{max(v["max_shift_px"] for v in vals)} px</td><td>{len(vals)}</td></tr>')
    intro = notes.get("_intro", "")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Style Comparison</title>
<style>
:root {{ --bg:#fbfbf8; --fg:#1d1d1b; --muted:#5b5b55; --card:#ffffff; --line:#d9d8d0; --warn-bg:#fff4e0; --warn-fg:#6b3f00; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#161614; --fg:#ecebe6; --muted:#b1b0a8; --card:#22221f; --line:#3b3a35; --warn-bg:#3a2a10; --warn-fg:#ffd99a; }} }}
:root[data-theme="dark"] {{ --bg:#161614; --fg:#ecebe6; --muted:#b1b0a8; --card:#22221f; --line:#3b3a35; --warn-bg:#3a2a10; --warn-fg:#ffd99a; }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; margin:0; padding:16px; }}
main {{ max-width:1500px; margin:0 auto; }}
h1 {{ font-size:1.6rem; margin:.2rem 0 .6rem; }} h2 {{ font-size:1.2rem; margin:1.6rem 0 .1rem; }}
.area {{ color:var(--muted); font-size:.85rem; margin:0; font-family:ui-monospace,monospace; }}
.warn {{ background:var(--warn-bg); color:var(--warn-fg); border-radius:8px; padding:10px 14px; }}
.row {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }}
.cell {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin:0; padding:8px; }}
.cell.old {{ border-style:dashed; }}
.cell img {{ width:100%; height:auto; image-rendering:pixelated; display:block; }}
.ph {{ aspect-ratio:1; display:grid; place-items:center; color:var(--muted); }}
figcaption {{ font-weight:600; margin:.4rem 0 .2rem; font-size:.95rem; }}
dl {{ display:grid; grid-template-columns:auto auto; gap:0 10px; margin:0; font-size:.85rem; }}
dt {{ color:var(--muted); }} dd {{ margin:0; text-align:right; font-variant-numeric:tabular-nums; }}
details summary {{ cursor:pointer; color:var(--muted); font-size:.85rem; margin-top:4px; }}
table {{ border-collapse:collapse; width:100%; font-size:.9rem; }} th,td {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:right; }}
th[scope=row], thead th:first-child {{ text-align:left; }}
.tablewrap {{ overflow-x:auto; }}
.note {{ max-width:75ch; }}
footer {{ color:var(--muted); font-size:.85rem; margin-top:2rem; }}
</style></head><body><main>
<h1>Clean Style Candidates on Eight Atlas Spots</h1>
<p class="warn"><strong>The old style is Gemini-derived.</strong> Its LoRA (qe2511_oldcity_r16_v1) was trained on Gemini 3 Pro Image outputs. It is shown for reference only and is not a candidate for publication.</p>
<p class="note">{html.escape(intro)}</p>
<div class="tablewrap"><table><thead><tr><th>Variant</th><th>Seam (median)</th><th>Flat share</th><th>Invented water blobs (total)</th><th>Invented color</th><th>Worst shift</th><th>Spots</th></tr></thead>
<tbody>{''.join(summary)}</tbody></table></div>
<p class="note" style="color:var(--muted);font-size:.85rem">Seam: frame-border jump over interior jump, only on borders between two drawn frames (1.0 is invisible). Flat: share of pixels in a flat 3x3 neighborhood (renders score about 0.27). Invented water: blobs found and repaired by the invented-water fix. Invented color: share of saturated pixels where the render has no saturated color nearby (mostly cars and specks). Detail crops are 1:1 from the middle of each spot; open "Whole spot" for the full drawing.</p>
{''.join(rows_html)}
<footer>Source: City of Philadelphia open data (building footprints, 2024 aerial imagery, 2022 LiDAR via PASDA, property records), OpenStreetMap. Drawings: Qwen-Image-Edit-2511 with Lightning-8 (Apache 2.0). AI-generated illustrations, not photographs.</footer>
</main></body></html>"""
    (OUT / "compare.html").write_text(page)
    print(f"-> {OUT / 'compare.html'} ({(OUT / 'compare.html').stat().st_size / 1e6:.1f} MB), {OUT / 'compare.jpg'}")
    print(json.dumps(metrics, indent=1))


if __name__ == "__main__":
    main()
