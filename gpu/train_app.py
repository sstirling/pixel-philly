"""Modal app for Phase C: LoRA training with ostris/ai-toolkit.

Separate from gpu/modal_app.py because ai-toolkit pins its own versions of
torch, transformers and diffusers, which differ from the inference image.

- ai-toolkit is pinned to a commit checked on Oct. 20, 2026; its pinned
  diffusers commit (May 29, 2026) contains Qwen-Image-Edit-2511 support
  (zero_cond_t), and its qwen_image_edit_plus model passes control-image
  shapes to the transformer as 2511 requires.
- Base weights come from the pp-weights Volume filled by
  modal_app.download_weights (pinned commit). HF_HUB_OFFLINE=1 stops
  ai-toolkit from fetching a newer revision behind our backs.
- Runs, datasets, checkpoints and samples live in the pp-runs Volume, so a
  crashed or timed-out job restarts from its last checkpoint (ai-toolkit
  resumes from the newest save in the same training folder).

Driven by scripts/14_train_lora.py.
"""

import os
import subprocess

import modal

AITK_COMMIT = "04733873cf1da8060fce01316ec45daedbd4a918"
TORCH_INDEX = "https://download.pytorch.org/whl/cu130"

app = modal.App("pixel-philly-train")
weights = modal.Volume.from_name("pp-weights", create_if_missing=True)
runs = modal.Volume.from_name("pp-runs", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "libgl1", "libglib2.0-0", "ffmpeg")
    .run_commands(
        f"git clone https://github.com/ostris/ai-toolkit.git /root/ai-toolkit && cd /root/ai-toolkit && git checkout {AITK_COMMIT}",
        # Same torch build as ai-toolkit's README for this commit
        f"pip install --no-cache-dir torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0 --index-url {TORCH_INDEX}",
        "cd /root/ai-toolkit && pip install --no-cache-dir -r requirements.txt",
    )
    .env({"HF_HOME": "/weights/hf", "HF_HUB_OFFLINE": "1", "DISABLE_TELEMETRY": "YES"})
)


@app.function(image=image, gpu="H100", volumes={"/weights": weights, "/runs": runs},
              timeout=4 * 3600, retries=1)
def train(config_path: str) -> str:
    """Run one ai-toolkit job. config_path is inside the pp-runs Volume."""
    runs.reload()
    proc = subprocess.run(["python", "run.py", config_path], cwd="/root/ai-toolkit")
    runs.commit()
    if proc.returncode != 0:
        raise RuntimeError(f"ai-toolkit exited with {proc.returncode}")
    return "ok"


@app.function(image=image, volumes={"/weights": weights, "/runs": runs}, timeout=600, cpu=2, memory=8192)
def check_config(config_path: str) -> dict:
    """Cheap CPU check run before training: the model path in the config
    must resolve offline, and every dataset folder must exist and match.
    (It catches the failure where a hub id like "Qwen/..." can't resolve
    "main" because the pinned download only stored the commit snapshot.)"""
    import yaml
    from diffusers import QwenImageTransformer2DModel

    runs.reload()
    cfg = yaml.safe_load(open(config_path))
    proc = cfg["config"]["process"][0]
    path = proc["model"]["name_or_path"]
    QwenImageTransformer2DModel.load_config(path, subfolder="transformer")
    ds = proc["datasets"][0]
    targets = sorted(f for f in os.listdir(ds["folder_path"]) if f.endswith(".png"))
    controls = sorted(f for f in os.listdir(ds["control_path"][0]) if f.endswith(".png"))
    if targets != controls:
        raise ValueError("target and control file names differ")
    for s in proc["sample"]["samples"]:
        if not os.path.exists(s["ctrl_img_1"]):
            raise FileNotFoundError(s["ctrl_img_1"])
    return {"model": path, "pairs": len(targets)}


@app.function(image=image, volumes={"/runs": runs}, timeout=600)
def list_run(folder: str) -> list[str]:
    runs.reload()
    out = []
    for root, _, files in os.walk(folder):
        out += [os.path.join(root, f) for f in files]
    return sorted(out)
