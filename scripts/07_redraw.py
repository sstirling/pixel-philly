"""Redraw render frames as pixel art with Gemini 3 Pro Image.

Each frame in output/renders/ is sent with a versioned prompt from prompts/
(plus a per-frame water sentence) and the result saved to
output/redraws/<prompt version>/. Every call is appended to log.jsonl in that
folder. Frames that already have a redraw are skipped, so the script can be
stopped and rerun. Keeping each prompt version in its own folder lets
versions be compared side by side.

These outputs are AI-generated illustrations, not photographs or survey data.

Cost: see pixelphilly/gemini.py. --max-calls caps spending per run.

Usage:
  uv run python scripts/07_redraw.py --prompt redraw_v3 --frames frame_02_02 frame_03_02
  uv run python scripts/07_redraw.py --prompt redraw_v3 --max-calls 30
"""

import argparse
import json
import time
from datetime import datetime, timezone

from pixelphilly import gemini
from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.water import water_screen_geometry, water_sentence, water_share


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", nargs="*", help="frame names to redraw (default: all)")
    ap.add_argument("--max-calls", type=int, default=30)
    ap.add_argument("--prompt", default="redraw_v3", help="prompt file name in prompts/, without .txt")
    ap.add_argument("--redo", nargs="*", default=[],
                    help="frames to redraw again; the old output is kept in rejected/, not overwritten")
    ap.add_argument("--reason", default="", help="why --redo frames were rejected (logged)")
    args = ap.parse_args()

    client = gemini.make_client()

    cfg = load_config()
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    water = water_screen_geometry(cfg, frame, cam)
    template = (REPO_ROOT / "prompts" / f"{args.prompt}.txt").read_text()

    render_dir = REPO_ROOT / "output" / "renders"
    out_dir = REPO_ROOT / "output" / "redraws" / args.prompt
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "log.jsonl"

    # Move rejected outputs aside (never delete them) and record why, so the
    # log shows every image that was made and which ones were thrown out.
    rejected_dir = out_dir / "rejected"
    for name in args.redo:
        old = out_dir / f"{name}.png"
        if not old.exists():
            continue
        rejected_dir.mkdir(exist_ok=True)
        n = len(list(rejected_dir.glob(f"{name}_try*.png"))) + 1
        old.rename(rejected_dir / f"{name}_try{n}.png")
        with log_path.open("a") as fh:
            fh.write(json.dumps({"frame": name, "status": "rejected", "rejected_file": f"rejected/{name}_try{n}.png",
                                 "reason": args.reason,
                                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
    if args.redo:
        args.frames = (args.frames or []) + args.redo

    wanted = set(args.frames) if args.frames else None
    calls = succeeded = 0
    quota_hit = False
    for f in frames:
        if wanted and f.name not in wanted:
            continue
        out = out_dir / f"{f.name}.png"
        if out.exists():
            continue
        if calls >= args.max_calls:
            print(f"stopping at --max-calls {args.max_calls}")
            break

        share = water_share(water, f.x0, f.y0, size)
        prompt = template.replace("{water_sentence}", water_sentence(share))
        src = render_dir / f"{f.name}.png"
        entry = {
            "frame": f.name,
            "model": gemini.MODEL,
            "prompt_version": args.prompt,
            "water_share": round(share, 3),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        t0 = time.time()
        calls += 1
        try:
            img, returned = gemini.redraw(client, src.read_bytes(), prompt, size)
            if returned:
                entry["returned_size"] = returned
            img.save(out)
            entry["status"] = "ok"
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)[:500]
            # (On a free-tier key this model's quota is 0: billing must be
            # enabled on the key's project.)
            quota_hit = gemini.is_quota_error(exc)
        entry["seconds"] = round(time.time() - t0, 1)
        with log_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        if entry["status"] == "ok":
            succeeded += 1
        print(f"{f.name}: {entry['status']} ({entry['seconds']} s){' ' + entry.get('error', '') if entry['status'] != 'ok' else ''}")
        if quota_hit:
            print("quota exhausted: stopping. Check billing at https://aistudio.google.com/ and retry.")
            break

    # Failed calls return no image and are not billed for output.
    print(f"{calls} calls this run, {succeeded} images (~${succeeded * gemini.PRICE_PER_IMAGE:.2f} at standard pricing)")


if __name__ == "__main__":
    main()
