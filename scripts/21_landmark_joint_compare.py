"""Track 3: compare joint-sampler drawings with and without landmark references.

For each area drawn with 15_joint_sample.py --landmarks, and each landmark in
its plan (output/<area>/joint/<run>/result.json):
  - a row of the comparison sheet: render | current drawing (the baseline
    run, no references) | drawing with the reference | the reference photo,
    with the safety verdict and the photo's credit line underneath
  - seam check: seam_ratio_local on the borders of the landmark's frame,
    in a crop of the assembled frames that reaches 128 px into each
    neighbor, for the baseline and the reference run (after any fallback).
    References must not add tone seams at frame borders.

Writes:
  output/landmarks/joint_compare.jpg
  output/landmarks/joint_compare.json

Usage:
  uv run python scripts/21_landmark_joint_compare.py --areas atlas_cityhall_lidar,atlas_artmuseum_lidar
"""

import argparse
import json
import textwrap

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pixelphilly.landmarks import center_box
from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.qa import seam_ratio_local

OUT = REPO_ROOT / "output" / "landmarks"
MARGIN = 128  # px into each neighboring frame for the seam crop


def font(n):
    for f in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(f, n)
        except OSError:
            pass
    return ImageFont.load_default()


def neighborhood(cfg, run, f):
    """The landmark frame plus MARGIN px of each neighbor, from a run's frames
    (missing neighbors stay black and their borders are skipped)."""
    size = f.size
    _, _, frames = area_setup(cfg)
    by_pos = {(g.col, g.row): g for g in frames}
    canvas = np.zeros((size + 2 * MARGIN, size + 2 * MARGIN, 3), np.uint8)
    cols, rows = [], []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            g = by_pos.get((f.col + dc, f.row + dr))
            p = area_dir(cfg, "redraws", run, f"{g.name}.png") if g else None
            if not p or not p.exists():
                continue
            img = np.asarray(Image.open(p).convert("RGB"))
            # Canvas window of this frame: frame origin at MARGIN + dc * size
            x0, y0 = MARGIN + dc * size, MARGIN + dr * size
            xa, ya = max(0, x0), max(0, y0)
            xb, yb = min(canvas.shape[1], x0 + size), min(canvas.shape[0], y0 + size)
            canvas[ya:yb, xa:xb] = img[ya - y0:yb - y0, xa - x0:xb - x0]
            if dr == 0 and dc != 0:
                cols.append(MARGIN if dc < 0 else MARGIN + size)
            if dc == 0 and dr != 0:
                rows.append(MARGIN if dr < 0 else MARGIN + size)
    return canvas, cols, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--areas", required=True)
    ap.add_argument("--run", default="qwen_joint_light8_landmarks")
    args = ap.parse_args()

    rows, report = [], {}
    for area in args.areas.split(","):
        cfg = load_config(area)
        res = json.loads(area_dir(cfg, "joint", args.run, "result.json").read_text())
        plan, safety = res["landmark_plan"], res["landmark_safety"]
        base = plan["baseline"]
        _, _, frames = area_setup(cfg)
        by_name = {f.name: f for f in frames}
        report[area] = {"timing": res.get("landmarks"), "total_seconds": res["total_seconds"],
                        "peak_gb": res["peak_gb"], "fallback_frames": safety["fallback_frames"], "landmarks": {}}
        seams_done = {}
        for slug, lm in sorted(plan["landmarks"].items()):
            f = by_name[lm["frame"]]
            box = center_box(*lm["canvas_px"], f, size=768)
            render = Image.open(area_dir(cfg, "renders", f"{f.name}.png")).convert("RGB").crop(box)
            cur = Image.open(area_dir(cfg, "redraws", base, f"{f.name}.png")).convert("RGB").crop(box)
            final = Image.open(area_dir(cfg, "redraws", args.run, f"{f.name}.png")).convert("RGB")
            rej = area_dir(cfg, "joint", args.run, "rejected", f"{f.name}.png")
            withref = (Image.open(rej).convert("RGB") if rej.exists() else final).crop(box)
            photo = Image.open(REPO_ROOT / lm["local_path"]).convert("RGB")
            s = safety["landmarks"][slug]
            if f.name not in seams_done:
                out = {}
                for label, run in (("baseline", base), ("landmarks", args.run)):
                    img, c, r = neighborhood(cfg, run, f)
                    out[label] = round(seam_ratio_local(img, c, r), 3) if (c or r) else None
                seams_done[f.name] = out
            report[area]["landmarks"][slug] = {"frame": f.name, "accepted": s["accepted"], "reason": s["reason"],
                                               "shift_center": s["shift_center"], "edge_center": s["edge_center"],
                                               "edge_center_baseline": s["edge_center_baseline"],
                                               "seam_ratio": seams_done[f.name], "credit": lm["credit"]}
            verdict = "ACCEPTED" if s["accepted"] else f"REJECTED ({s['reason']}); frame fell back to the current drawing"
            rows.append({"title": f"{lm['name']} ({area}, {f.name})", "verdict": verdict,
                         "metrics": f"center shift {s['shift_center']}, edge {s['edge_center']} vs "
                                    f"{s['edge_center_baseline']} without reference; frame-border seam ratio "
                                    f"{seams_done[f.name]['baseline']} -> {seams_done[f.name]['landmarks']}",
                         "credit": f"Reference: {lm['credit']}",
                         "tiles": [("Render", render), ("Current drawing", cur),
                                   ("With reference" + ("" if s["accepted"] else " (rejected)"), withref),
                                   ("Reference photo", photo)]})

    T, pad, head, foot = 360, 10, 52, 70
    F, Fb, Fs = font(15), font(17), font(13)
    W = 4 * (T + pad) + pad
    H = 60 + len(rows) * (head + T + foot + pad)
    sheet = Image.new("RGB", (W, H), (250, 250, 247))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 16), "Landmark References in the Joint Sampler: Current Drawing vs. With Reference Photo",
           fill=(20, 20, 20), font=font(24))
    y = 60
    for r in rows:
        d.text((pad, y), r["title"], fill=(20, 20, 20), font=Fb)
        d.text((pad, y + 24), r["verdict"], fill=(0, 110, 60) if r["verdict"].startswith("ACC") else (170, 40, 0),
               font=F)
        for j, (label, im) in enumerate(r["tiles"]):
            x = pad + j * (T + pad)
            t = im.copy()
            t.thumbnail((T, T), Image.LANCZOS)
            d.rectangle((x, y + head, x + T, y + head + T), fill=(232, 232, 228))
            sheet.paste(t, (x + (T - t.width) // 2, y + head + (T - t.height) // 2))
            d.text((x + 4, y + head + 4), label, fill=(255, 255, 255), font=Fs, stroke_width=2, stroke_fill=(0, 0, 0))
        ty = y + head + T + 6
        d.text((pad, ty), r["metrics"], fill=(60, 60, 60), font=Fs)
        for k, line in enumerate(textwrap.wrap(r["credit"], 190)[:3]):
            d.text((pad, ty + 18 + 16 * k), line, fill=(60, 60, 60), font=Fs)
        y += head + T + foot + pad
    OUT.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT / "joint_compare.jpg", quality=86)
    (OUT / "joint_compare.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {OUT / 'joint_compare.jpg'} ({len(rows)} landmarks)")
    for area, a in report.items():
        print(area, a["timing"], "total", a["total_seconds"], "peak", a["peak_gb"], "fallback", a["fallback_frames"])
        for slug, v in a["landmarks"].items():
            print(f"  {slug:26s} {'ok ' if v['accepted'] else 'REJ'} center {v['shift_center']} edge "
                  f"{v['edge_center']}/{v['edge_center_baseline']} seams {v['seam_ratio']}")


if __name__ == "__main__":
    main()
