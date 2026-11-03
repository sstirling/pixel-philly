"""Phase C: train the pixel-philly style LoRA on Qwen-Image-Edit-2511.

Subcommands:
  prepare  build the ai-toolkit dataset from output/trainset (target/,
           control/, one caption .txt per target), write the training config,
           and upload both to the pp-runs Volume
  start    launch training on a Modal H100 and return immediately (the run
           continues if this laptop sleeps); the call id is saved locally
  status   report whether the run is still going
  fetch    download checkpoints and sample images into output/lora/<run>/

Training targets are Gemini 3 Pro Image redraws (internal use only; see the
README for the terms question and the legal-review requirement).

Captions: one fixed instruction for every pair, with NO water sentence.
Phase A showed that naming water in the prompt ("WATER IN THIS VIEW: none")
made Qwen paint a river where there was none; the LoRA should learn water
from the images, and the same fixed caption is used at inference. Samples are drawn every 500 steps
on HELD-OUT frames (columns 4-5, never in the training set).

Usage:
  uv run modal deploy gpu/train_app.py
  uv run python scripts/14_train_lora.py prepare
  uv run python scripts/14_train_lora.py start
  uv run python scripts/14_train_lora.py status
  uv run python scripts/14_train_lora.py fetch
  ... add --profile clean for Candidate B (qe2511_clean_r16_v1, no Gemini targets)
"""

import argparse
import json
import shutil
from datetime import datetime, timezone

import yaml

from pixelphilly.projection import REPO_ROOT, area_dir

RUN = "qe2511_oldcity_r16_v1"
# The pinned Qwen-Image-Edit-2511 commit (BASE_REV in gpu/modal_app.py) as a
# local folder in the pp-weights Volume. A hub id like "Qwen/Qwen-Image-Edit-2511"
# fails offline because the pinned download stores only this snapshot, not
# the "main" ref; the explicit path also pins the version in the config.
BASE_SNAPSHOT = "/weights/hf/hub/models--Qwen--Qwen-Image-Edit-2511/snapshots/6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9"
DATASET = "oldcity_v1"
CAPTION = "Redraw this render as isometric pixel art in the pixel philly style."
HELDOUT_SAMPLES = ["frame_04_03", "frame_05_02", "frame_04_02"]

# The training set is Old City's (13_build_trainset.py); the LoRA itself is
# cross-area, so its local folder stays directly under output/lora/
TRAINSET = REPO_ROOT / "output" / "oldcity" / "trainset"
LOCAL_DS = TRAINSET / "aitk"
LOCAL_RUN = REPO_ROOT / "output" / "lora" / RUN
# Held-out sample inputs as (area, frame); the old profile's are Old City's
# held-out columns 4-5
HELDOUT = [("oldcity", n) for n in HELDOUT_SAMPLES]
SAMPLE_EVERY = 500
TARGETS_NOTE = "gemini-3-pro-image redraw_v3, water repainted; internal use only"

# --profile clean: Candidate B, the self-distilled LoRA (no Gemini anywhere).
# Targets: prompt-only Qwen-Image-Edit-2511 redraws of our renders, filtered
# (scripts/23_build_clean_trainset.py). Samples are drawn on three comparison
# atlas spots, which the training set excludes. Samples every 1,000 steps
# instead of 500 to save ~$0.30 of H100 time.
PROFILES = {
    "clean": {
        "RUN": "qe2511_clean_r16_v1",
        "DATASET": "clean_v1",
        "CAPTION": "Redraw this render as isometric pixel art in the pixel philly clean style.",
        "TRAINSET": REPO_ROOT / "output" / "trainset_clean",
        "HELDOUT": [("atlas_passyunk_fac", "frame_01_01"), ("atlas_cityhall_fac", "frame_01_01"),
                    ("atlas_porch_fac", "frame_01_01")],
        "SAMPLE_EVERY": 1000,
        "TARGETS_NOTE": "Qwen-Image-Edit-2511 + Lightning-8, no style LoRA, prompt 'Redraw this render as "
                        "isometric pixel art.', on City open-data renders; filtered; see manifest.jsonl",
    },
}


def use_profile(name):
    """Switch the module settings to a profile (default: the original run)."""
    global RUN, DATASET, CAPTION, TRAINSET, LOCAL_DS, LOCAL_RUN, HELDOUT, SAMPLE_EVERY, TARGETS_NOTE
    if name == "oldcity":
        return
    p = PROFILES[name]
    RUN, DATASET, CAPTION, TRAINSET = p["RUN"], p["DATASET"], p["CAPTION"], p["TRAINSET"]
    HELDOUT, SAMPLE_EVERY, TARGETS_NOTE = p["HELDOUT"], p["SAMPLE_EVERY"], p["TARGETS_NOTE"]
    LOCAL_DS = TRAINSET / "aitk"
    LOCAL_RUN = REPO_ROOT / "output" / "lora" / RUN


def config(n_pairs: int) -> dict:
    ds = f"/runs/datasets/{DATASET}"
    samples = []
    for area, name in HELDOUT:
        samples.append({"prompt": open(LOCAL_DS / "heldout" / f"{area}__{name}.txt").read().strip(),
                        "ctrl_img_1": f"{ds}/heldout/{area}__{name}.png"})
    return {
        "job": "extension",
        "config": {
            "name": RUN,
            "process": [
                {
                    "type": "diffusion_trainer",
                    "training_folder": "/runs/lora",
                    "device": "cuda:0",
                    "network": {"type": "lora", "linear": 16, "linear_alpha": 16},
                    "save": {"dtype": "float16", "save_every": 250, "max_step_saves_to_keep": 8},
                    "datasets": [
                        {
                            "folder_path": f"{ds}/target",
                            "control_path": [f"{ds}/control"],
                            "caption_ext": "txt",
                            "caption_dropout_rate": 0.05,
                            # All pairs are 1,024 px; 768 adds a cheaper scale
                            "resolution": [768, 1024],
                        }
                    ],
                    "train": {
                        "batch_size": 1,
                        "cache_text_embeddings": True,
                        "steps": 2000,
                        "gradient_accumulation": 1,
                        "timestep_type": "weighted",
                        "train_unet": True,
                        "train_text_encoder": False,
                        "gradient_checkpointing": True,
                        "noise_scheduler": "flowmatch",
                        "optimizer": "adamw8bit",
                        "lr": 1e-4,
                        "dtype": "bf16",
                    },
                    "model": {
                        # bf16 on an 80 GB H100, no quantization: the LoRA is
                        # trained against the same weights used at inference
                        "name_or_path": BASE_SNAPSHOT,
                        "arch": "qwen_image_edit_plus",
                        "quantize": False,
                        "quantize_te": True,
                        "qtype_te": "qfloat8",
                        "low_vram": False,
                    },
                    "sample": {
                        "sampler": "flowmatch",
                        "sample_every": SAMPLE_EVERY,
                        "sample_start_step": 0,
                        "width": 1024,
                        "height": 1024,
                        "samples": samples,
                        "neg": " ",
                        "seed": 42,
                        "walk_seed": False,
                        "guidance_scale": 4,
                        "sample_steps": 30,
                    },
                }
            ],
        },
        "meta": {"name": RUN, "version": "1.0", "pairs": n_pairs,
                 "targets": TARGETS_NOTE},
    }


def prepare():
    rows = [json.loads(line) for line in (TRAINSET / "manifest.jsonl").read_text().splitlines() if line]
    ok = {r["id"]: r for r in rows if r["status"] == "ok"}
    if LOCAL_DS.exists():
        shutil.rmtree(LOCAL_DS)
    for d in ("target", "control", "heldout"):
        (LOCAL_DS / d).mkdir(parents=True)
    for vid, r in ok.items():
        shutil.copy(TRAINSET / "target" / f"{vid}.png", LOCAL_DS / "target" / f"{vid}.png")
        shutil.copy(TRAINSET / "control" / f"{vid}.png", LOCAL_DS / "control" / f"{vid}.png")
        (LOCAL_DS / "target" / f"{vid}.txt").write_text(f"{CAPTION}\n")

    # Held-out sample inputs (never in the training set), same fixed caption
    from pixelphilly.projection import area_setup, load_config

    for area, name in HELDOUT:
        cfg = load_config(area)
        if area == "oldcity":
            f = {fr.name: fr for fr in area_setup(cfg)[2]}[name]
            assert f.col >= 4, f"{name} is not in the held-out columns"
        shutil.copy(area_dir(cfg, "renders", f"{name}.png"), LOCAL_DS / "heldout" / f"{area}__{name}.png")
        (LOCAL_DS / "heldout" / f"{area}__{name}.txt").write_text(f"{CAPTION}\n")

    cfg_yaml = LOCAL_DS / f"{RUN}.yaml"
    cfg_yaml.write_text(yaml.safe_dump(config(len(ok)), sort_keys=False))

    import modal

    vol = modal.Volume.from_name("pp-runs", create_if_missing=True)
    with vol.batch_upload(force=True) as batch:
        batch.put_directory(str(LOCAL_DS), f"/datasets/{DATASET}")
        batch.put_file(str(cfg_yaml), f"/configs/{RUN}.yaml")
    print(f"uploaded {len(ok)} pairs + {len(HELDOUT)} held-out samples and config {RUN}.yaml")


def start():
    import modal

    # Cheap CPU check first: the model path must resolve offline and the
    # dataset must be complete, before any GPU time is spent
    print("config check:", modal.Function.from_name("pixel-philly-train", "check_config").remote(
        f"/runs/configs/{RUN}.yaml"))
    train = modal.Function.from_name("pixel-philly-train", "train")
    call = train.spawn(f"/runs/configs/{RUN}.yaml")
    LOCAL_RUN.mkdir(parents=True, exist_ok=True)
    info = {"run": RUN, "call_id": call.object_id, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (LOCAL_RUN / "call.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"started {RUN}: call {call.object_id}")


def status():
    import modal

    info = json.loads((LOCAL_RUN / "call.json").read_text())
    call = modal.FunctionCall.from_id(info["call_id"])
    try:
        print("finished:", call.get(timeout=0))
    except TimeoutError:
        print(f"{RUN} still running (started {info['started_at']})")
    files = modal.Function.from_name("pixel-philly-train", "list_run").remote(f"/runs/lora/{RUN}")
    ckpts = [f for f in files if f.endswith(".safetensors")]
    samples = [f for f in files if "/samples/" in f]
    print(f"checkpoints: {len(ckpts)}  samples: {len(samples)}")
    for f in ckpts[-3:]:
        print("  ", f)


def fetch():
    import modal

    vol = modal.Volume.from_name("pp-runs")
    files = modal.Function.from_name("pixel-philly-train", "list_run").remote(f"/runs/lora/{RUN}")
    LOCAL_RUN.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files:
        if not (f.endswith(".safetensors") or "/samples/" in f or f.endswith((".yaml", ".json"))):
            continue
        if "optimizer" in f:
            continue
        rel = f.removeprefix(f"/runs/lora/{RUN}/")
        dest = LOCAL_RUN / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            for chunk in vol.read_file(f.removeprefix("/runs")):
                fh.write(chunk)
        n += 1
    print(f"fetched {n} files into {LOCAL_RUN}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["prepare", "start", "status", "fetch"])
    ap.add_argument("--profile", default="oldcity", choices=["oldcity", *PROFILES],
                    help="oldcity: the original (Gemini-target) run; clean: Candidate B")
    a = ap.parse_args()
    use_profile(a.profile)
    {"prepare": prepare, "start": start, "status": status, "fetch": fetch}[a.command]()
