"""About 15-second promo of the map's features, cut together from the other
promo scripts' segments:

1. Live transit (3.6 s): scripts/39_transit_promo.py, 2 cuts (a moving
   Regional Rail train, then a trolley or bus).
2. Live weather (3 s) and neighborhood prints (3 s):
   scripts/42_weather_prints_promo.py --parts storm=3,prints=3. The storm is
   simulated and labeled so on screen.
3. The whole city (5 s): scripts/29_flyover.py feature_city (or
   feature_city_vertical), a pull-back from Center City.

Each segment is rendered by its own script (so it's filmed or drawn exactly as
that script documents), then the clips are joined with hard cuts and
re-encoded once.

Needs what the segments need: the repo served on 127.0.0.1:8000 and
scripts/38_live_feed.py running (transit needs a moving train in view, so run
it when Regional Rail is in service).

Output: output/flyover/promo_features.mp4 (1920 x 1080) or
promo_features_vertical.mp4 (1080 x 1920), not tracked. Segments are kept
next to it as feature_*.mp4; --join-only re-joins them without rendering.
Usage: uv run python scripts/43_feature_promo.py [--vertical] [--join-only]
"""

import argparse
import subprocess
import sys

import imageio_ffmpeg

from pixelphilly.projection import REPO_ROOT

OUT = REPO_ROOT / "output" / "flyover"
TRANSIT_CAPTION = "Live SEPTA buses, trolleys and trains"


def run(*cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run([sys.executable, *cmd], cwd=REPO_ROOT, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vertical", action="store_true", help="TikTok/Reels cut, 1080 x 1920")
    ap.add_argument("--join-only", action="store_true", help="re-join existing segments without rendering them")
    args = ap.parse_args()
    v = "_vertical" if args.vertical else ""
    vflag = ["--vertical"] if args.vertical else []
    segments = [OUT / f"feature_transit{v}.mp4", OUT / f"feature_weather_prints{v}.mp4", OUT / f"feature_city{v}.mp4"]
    if not args.join_only:
        run("scripts/39_transit_promo.py", *vflag, "--cuts", "2", "--seconds", "3.6",
            "--caption", TRANSIT_CAPTION, "--name", f"feature_transit{v}")
        run("scripts/42_weather_prints_promo.py", *vflag, "--parts", "storm=3,prints=3", "--name", f"feature_weather_prints{v}")
        run("scripts/29_flyover.py", f"feature_city{v}")
    out = OUT / f"promo_features{v}.mp4"
    inputs = sum((["-i", str(s)] for s in segments), [])
    chain = "".join(f"[{i}:v]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[v]"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", *inputs, "-filter_complex", chain,
                    "-map", "[v]", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-movflags", "+faststart", str(out)], check=True)
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
