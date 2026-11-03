"""Clean style v2: full-quality Qwen targets, our own palette, human curation.

No Gemini output and nothing from the old LoRA is used anywhere: inputs are
our renders of City open data; targets come from Qwen-Image-Edit-2511
(Apache 2.0) WITHOUT Lightning (full 40-step schedule, true CFG with a
negative prompt); colors are snapped to a palette built from our renders
(pixelphilly.palette).

Subcommands so far (each writes under output/trainset_clean_v2/):
  sweep    6 stress frames x 4 prompt/CFG/step settings on Modal (Editor.run,
           the deployed app; no code change). sweep/sheet.jpg (whole frames)
           and sweep/detail.jpg (1:1 centers), sweep/scores.json
  palette  k-means palette (k=56) over our renders across terrain ->
           palette.json + palette.png; then snap + speck removal on the sweep
           outputs -> palette/before_after.jpg

Usage:
  uv run python scripts/25_clean_v2.py sweep [--dry-run]
  uv run python scripts/25_clean_v2.py palette
"""

import argparse
import io
import json
import time
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw

from pixelphilly import palette as pal
from pixelphilly import trainset_clean as tc
from pixelphilly.projection import REPO_ROOT
from pixelphilly.qa import flat_share, registration_shift

OUT = REPO_ROOT / "output" / "trainset_clean_v2"
V1 = REPO_ROOT / "output" / "trainset_clean"
H100_PER_HOUR = 3.95
SEC_PER_FORWARD = 0.55  # measured on 1,024 px windows (joint runs, Oct. 26-28)

NEGATIVE = ("cars, vehicles, trucks, buses, parked cars, traffic, people, pedestrians, text, letters, signs, "
            "logos, labels, clutter, noise, grain, dithering, speckles, photo, photorealistic, aerial photo, "
            "blurry, soft focus, 3d render, gradient, watermark")
PROMPTS = {
    "P1": ("Redraw this render as clean isometric pixel art. Use flat areas of solid color, crisp one-pixel dark "
           "outlines on building edges, simple two- or three-tone shading and a small, consistent palette; no "
           "photographic texture. Keep every building, roof, street, tree, field and shoreline exactly where it "
           "is, with the same shape, height and color family."),
    "P2": ("Isometric pixel art of this exact scene, in the style of a retro city-building game: tidy flat "
           "colors, sharp pixel edges, clear roof and wall shading. Preserve the geometry precisely: the same "
           "buildings, footprints and heights, the same streets, trees and water, nothing added or removed."),
}
# (name, prompt, cfg, steps). S4 asks whether 24 steps are enough: at 40
# steps with CFG a target costs ~45 s of H100, which limits how many
# candidates fit the $25 budget
SETTINGS = [("S1_P1_cfg4_40", "P1", 4.0, 40), ("S2_P2_cfg4_40", "P2", 4.0, 40),
            ("S3_P2_cfg6_40", "P2", 6.0, 40), ("S4_P1_cfg4_24", "P1", 4.0, 24)]
SWEEP_TERRAIN = ["rowhouse", "tower", "woods", "port", "stadium", "industrial"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_run(entry):
    with (REPO_ROOT / "output" / "gpu_runs.jsonl").open("a") as fh:
        fh.write(json.dumps({**entry, "at": now()}) + "\n")


def sweep_views():
    """One full frame per terrain class from the v1 plan (comparison spots
    already excluded): the one where prompt-only Qwen (v1 seed 0) invented
    the most color, i.e. a stress test for cars and clutter."""
    rows = [json.loads(x) for f in ("manifest.jsonl", "rejected.jsonl")
            for x in (V1 / f).read_text().splitlines()]
    out = []
    for t in SWEEP_TERRAIN:
        cand = [r for r in rows if r["terrain"] == t and r["kind"] == "full" and r["seed"] == 0]
        cand.sort(key=lambda r: -r["scores"].get("invented_color_share_before_cleanup",
                                                  r["scores"]["invented_color_share"]))
        out.append({"terrain": t, "view_id": cand[0]["id"], "control": cand[0]["control"]})
    return out


def scores(render, img):
    r, d = np.asarray(render), np.asarray(img)
    return {"shift": list(registration_shift(render, img)), "flat_share": round(flat_share(d), 3),
            "invented_color_pct": round(100 * tc.invented_color_share(r, d), 2),
            "mean_abs_diff": round(float(np.abs(d.astype(int) - r.astype(int)).mean()), 1)}


def sweep(dry_run):
    views = sweep_views()
    jobs = []
    for v in views:
        png = (REPO_ROOT / v["control"]).read_bytes()
        for name, p, cfg, steps in SETTINGS:
            jobs.append({"image": png, "prompt": PROMPTS[p], "negative_prompt": NEGATIVE, "steps": steps,
                         "cfg": cfg, "seed": 0, "lightning": None, "view_id": v["view_id"], "setting": name})
    fw = sum(j["steps"] * 2 for j in jobs)
    est = fw * SEC_PER_FORWARD + 90
    print(f"{len(jobs)} edits ({', '.join(v['terrain'] for v in views)}); ~{fw} forwards, "
          f"~{est / 60:.0f} H100-min (~${est / 3600 * H100_PER_HOUR:.2f})")
    for v in views:
        print("  ", v["terrain"], v["view_id"])
    if dry_run:
        return
    import modal

    print("environment:", modal.Function.from_name("pixel-philly", "check_env").remote())
    editor = modal.Cls.from_name("pixel-philly", "Editor")()
    d = OUT / "sweep"
    d.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # Two spawned calls (two containers, ~9 min each): a local call held open
    # past ~10 min was cancelled once; spawn + get survives that
    calls = [editor.run.spawn(jobs[i::2]) for i in range(2)]
    res = [r for c in calls for r in c.get(timeout=3600)]
    wall = time.time() - t0
    rows = []
    for r in res:
        img = Image.open(io.BytesIO(r.pop("png"))).convert("RGB")
        (d / r["setting"]).mkdir(exist_ok=True)
        img.save(d / r["setting"] / f"{r['view_id']}.png")
        render = Image.open(V1 / "control" / f"{r['view_id']}.png").convert("RGB")
        rows.append({k: r[k] for k in ("view_id", "setting", "steps", "cfg", "seed", "seconds", "peak_gb")}
                    | {"prompt_key": next(p for n, p, _, _ in SETTINGS if n == r["setting"])}
                    | scores(render, img))
    (d / "scores.json").write_text(json.dumps({"prompts": PROMPTS, "negative_prompt": NEGATIVE, "views": views,
                                               "rows": rows, "wall_seconds": round(wall, 1)}, indent=1) + "\n")
    gpu = sum(r["seconds"] for r in rows)
    log_run({"run": "25_clean_v2 sweep", "gpu": "H100", "wall_seconds": round(wall, 1), "images": len(rows),
             "gpu_seconds_images": round(gpu, 1), "load_seconds": res[0].get("load_seconds"),
             "containers": 2,
             "estimated_cost_usd": round(max(2 * wall, gpu + 2 * 90) / 3600 * H100_PER_HOUR, 2)})
    print(f"done in {wall / 60:.1f} min; {gpu / len(rows):.1f} s/image")
    sweep_sheets(views, rows)


def _label(img, text):
    ImageDraw.Draw(img).rectangle([0, 0, img.width, 18], fill=(255, 255, 255))
    ImageDraw.Draw(img).text((4, 3), text, fill=(0, 0, 0))
    return img


def sweep_sheets(views=None, rows=None):
    d = OUT / "sweep"
    if rows is None:
        j = json.loads((d / "scores.json").read_text())
        views, rows = j["views"], j["rows"]
    by = {(r["view_id"], r["setting"]): r for r in rows}
    cols = ["render"] + [s[0] for s in SETTINGS]
    for name, size, crop in (("sheet.jpg", 420, None), ("detail.jpg", 420, (302, 302, 722, 722))):
        sheet = Image.new("RGB", (len(cols) * (size + 6), len(views) * (size + 6) + 24), (250, 250, 247))
        dr = ImageDraw.Draw(sheet)
        for i, c in enumerate(cols):
            dr.text((i * (size + 6) + 4, 6), c if c == "render" else
                    f"{c}: prompt {c.split('_')[1]}, CFG {c.split('_')[2][3:]}, {c.split('_')[3]} steps", fill=0)
        for j, v in enumerate(views):
            for i, c in enumerate(cols):
                p = (V1 / "control" / f"{v['view_id']}.png") if c == "render" else d / c / f"{v['view_id']}.png"
                im = Image.open(p).convert("RGB")
                im = im.crop(crop) if crop else im.resize((size, size), Image.LANCZOS)
                if c == "render":
                    txt = f"{v['terrain']}  {v['view_id'].split('__', 1)[1]}"
                else:
                    r = by[(v["view_id"], c)]
                    txt = (f"shift {r['shift']} flat {r['flat_share']} cars/specks {r['invented_color_pct']}% "
                           f"diff {r['mean_abs_diff']}")
                sheet.paste(_label(im, txt), (i * (size + 6), 24 + j * (size + 6)))
        sheet.save(d / name, quality=88)
    print(f"-> {d / 'sheet.jpg'}, {d / 'detail.jpg'}")


def palette_cmd(k):
    """Palette from our renders: every v1 control view (renders and 2x
    re-renders, comparison spots excluded, all terrain classes), a fixed
    sample of pixels each."""
    from pixelphilly.trainset_clean import featureless_share

    plan = json.loads((V1 / "plan.json").read_text())["views"]
    rng = np.random.default_rng(0)
    samples = []
    for v in plan:
        a = np.asarray(Image.open(V1 / "control" / f"{v['view_id']}.png").convert("RGB"))
        if featureless_share(a) > 0.05:
            continue  # the no-data gray is not a city color
        samples.append(a.reshape(-1, 3)[rng.choice(a.shape[0] * a.shape[1], 4000, replace=False)])
    p = pal.build_palette(samples, k=k, seed=0)
    (OUT / "palette").mkdir(parents=True, exist_ok=True)
    (OUT / "palette.json").write_text(json.dumps({
        "k": k, "source": f"k-means over 4,000 px from each of {len(samples)} renders/2x re-renders in "
                          "output/trainset_clean/control (our City open-data renders; no model drawings)",
        "colors": p.tolist()}, indent=1) + "\n")
    sw = Image.new("RGB", (8 * 40, -(-k // 8) * 40), "white")
    for i, c in enumerate(p):
        ImageDraw.Draw(sw).rectangle([(i % 8) * 40, (i // 8) * 40, (i % 8) * 40 + 39, (i // 8) * 40 + 39],
                                     fill=tuple(int(x) for x in c))
    sw.save(OUT / "palette.png")
    print(f"palette: {k} colors from {len(samples)} renders -> {OUT / 'palette.json'}")

    # Before/after on the sweep outputs
    j = json.loads((OUT / "sweep" / "scores.json").read_text())
    rows_out, tiles = [], []
    for v in j["views"]:
        render = np.asarray(Image.open(V1 / "control" / f"{v['view_id']}.png").convert("RGB"))
        for setting in [s[0] for s in SETTINGS]:
            src = np.asarray(Image.open(OUT / "sweep" / setting / f"{v['view_id']}.png").convert("RGB"))
            snapped, idx = pal.snap(src, p)
            clean_idx = pal.remove_specks(idx, p, render, max_px=40)
            clean = p[clean_idx]
            rows_out.append({"view_id": v["view_id"], "setting": setting,
                             "before": scores(Image.fromarray(render), Image.fromarray(src)),
                             "snapped": scores(Image.fromarray(render), Image.fromarray(snapped)),
                             "after": scores(Image.fromarray(render), Image.fromarray(clean)),
                             "speck_px_removed": int((clean_idx != idx).sum())})
            Image.fromarray(clean).save(OUT / "palette" / f"{setting}__{v['view_id']}.png")
            if setting == SETTINGS[0][0]:
                tiles.append((v, render, src, snapped, clean, rows_out[-1]))
    (OUT / "palette" / "scores.json").write_text(json.dumps(rows_out, indent=1) + "\n")
    size, crop = 420, (302, 302, 722, 722)
    sheet = Image.new("RGB", (4 * (size + 6), len(tiles) * (size + 6) + 24), (250, 250, 247))
    for i, h in enumerate(["render", f"{SETTINGS[0][0]} as drawn", f"snapped to {k} colors",
                           "snapped + speck removal"]):
        ImageDraw.Draw(sheet).text((i * (size + 6) + 4, 6), h + " (1:1 center crop)", fill=0)
    for jn, (v, render, src, snapped, clean, r) in enumerate(tiles):
        for i, (im, txt) in enumerate([(render, v["terrain"]),
                                       (src, f"specks {r['before']['invented_color_pct']}%"),
                                       (snapped, f"specks {r['snapped']['invented_color_pct']}%"),
                                       (clean, f"specks {r['after']['invented_color_pct']}%  "
                                               f"removed {r['speck_px_removed']} px")]):
            sheet.paste(_label(Image.fromarray(im).crop(crop), txt), (i * (size + 6), 24 + jn * (size + 6)))
    sheet.save(OUT / "palette" / "before_after.jpg", quality=88)
    print(f"-> {OUT / 'palette' / 'before_after.jpg'}")


def palette_compare(k):
    """Option B palette: k-means over our own Qwen v2 targets (the P1 sweep
    outputs: Apache-2.0 model run on our renders), next to the renders-only
    palette (palette.json). Sheet: render | as drawn | renders palette +
    clean-up | targets palette + clean-up."""
    j = json.loads((OUT / "sweep" / "scores.json").read_text())
    p1 = [s[0] for s in SETTINGS if s[1] == "P1"]
    samples = [np.asarray(Image.open(OUT / "sweep" / st / f"{v['view_id']}.png").convert("RGB"))
               for v in j["views"] for st in p1]
    pq = pal.build_palette(samples, k=k, seed=0)
    (OUT / "palette_targets.json").write_text(json.dumps({
        "k": k, "source": f"k-means over the {len(samples)} prompt-P1 sweep targets (Qwen-Image-Edit-2511, "
                          "no LoRA, on our renders); no Gemini or old-LoRA drawings", "colors": pq.tolist()},
        indent=1) + "\n")
    pr = np.array(json.loads((OUT / "palette.json").read_text())["colors"], np.uint8)
    size, crop = 420, (302, 302, 722, 722)
    heads = ["render", "S1 as drawn", f"renders palette ({len(pr)}) + clean-up",
             f"targets palette ({k}) + clean-up"]
    sheet = Image.new("RGB", (4 * (size + 6), len(j["views"]) * (size + 6) + 24), (250, 250, 247))
    for i, h in enumerate(heads):
        ImageDraw.Draw(sheet).text((i * (size + 6) + 4, 6), h + " (1:1 center crop)", fill=0)
    rows = []
    for n, v in enumerate(j["views"]):
        render = np.asarray(Image.open(V1 / "control" / f"{v['view_id']}.png").convert("RGB"))
        src = np.asarray(Image.open(OUT / "sweep" / SETTINGS[0][0] / f"{v['view_id']}.png").convert("RGB"))
        ims = [(render, v["terrain"]), (src, f"specks {scores(Image.fromarray(render), Image.fromarray(src))['invented_color_pct']}%")]
        for name, p in (("renders", pr), ("targets", pq)):
            _, idx = pal.snap(src, p)
            ci = pal.remove_specks(idx, p, render, max_px=40)
            out = p[ci]
            sc = scores(Image.fromarray(render), Image.fromarray(out))
            rows.append({"view_id": v["view_id"], "palette": name, **sc, "speck_px_removed": int((ci != idx).sum())})
            Image.fromarray(out).save(OUT / "palette" / f"{name}__{v['view_id']}.png")
            ims.append((out, f"specks {sc['invented_color_pct']}% removed {int((ci != idx).sum())} px"))
        for i, (im, txt) in enumerate(ims):
            sheet.paste(_label(Image.fromarray(im).crop(crop), txt), (i * (size + 6), 24 + n * (size + 6)))
    sheet.save(OUT / "palette" / "palette_options.jpg", quality=88)
    sw = Image.new("RGB", (8 * 40, -(-k // 8) * 40), "white")
    for i, c in enumerate(pq):
        ImageDraw.Draw(sw).rectangle([(i % 8) * 40, (i // 8) * 40, (i % 8) * 40 + 39, (i // 8) * 40 + 39],
                                     fill=tuple(int(x) for x in c))
    sw.save(OUT / "palette_targets.png")
    (OUT / "palette" / "options_scores.json").write_text(json.dumps(rows, indent=1) + "\n")
    print(f"-> {OUT / 'palette' / 'palette_options.jpg'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["sweep", "sheets", "palette", "palette-compare"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-k", type=int, default=56)
    a = ap.parse_args()
    if a.command == "sweep":
        sweep(a.dry_run)
    elif a.command == "sheets":
        sweep_sheets()
    elif a.command == "palette":
        palette_cmd(a.k)
    else:
        palette_compare(a.k)
