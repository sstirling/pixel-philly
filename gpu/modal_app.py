"""Modal GPU app for phase 2: Qwen-Image-Edit-2511 on rented H100s.

Everything that needs a GPU runs here; local scripts (scripts/12-15) call
these functions and write results into output/. Nothing in this file runs
on the laptop except Modal's client.

Why these choices:
- Qwen-Image-Edit-2511 (Apache 2.0) and lightx2v's Lightning LoRAs (Apache
  2.0) are the commercially usable models; tiny.london's Qwen-Image-2.1-Turbo
  is under a non-commercial research license. Both repos are pinned to exact
  commits so every run uses identical weights.
- diffusers 0.41.0 is the first release checked to contain 2511's
  zero_cond_t handling and VAE tiling.
- Weights (~58 GB) live in a Modal Volume so each container loads them from
  disk instead of downloading.

Usage (from the repo root, after `modal token new`):
  uv run modal run gpu/modal_app.py::download_weights
"""

from __future__ import annotations

import io
import math
import time

import modal

BASE_REPO = "Qwen/Qwen-Image-Edit-2511"
BASE_REV = "6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9"
LIGHT_REPO = "lightx2v/Qwen-Image-Edit-2511-Lightning"
LIGHT_REV = "107d238d68b8387e32843d0b4a2e24ceb0d3ad86"
LIGHT_FILES = {
    "4": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
    "8": "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors",
}

# Scheduler used to distill the Lightning LoRAs: a constant shift of 3 and no
# terminal shift. From ModelTC/Qwen-Image-Lightning generate_with_diffusers.py.
LIGHTNING_SCHEDULER = {
    "base_image_seq_len": 256,
    "base_shift": math.log(3),
    "invert_sigmas": False,
    "max_image_seq_len": 8192,
    "max_shift": math.log(3),
    "num_train_timesteps": 1000,
    "shift": 1.0,
    "shift_terminal": None,
    "stochastic_sampling": False,
    "time_shift_type": "exponential",
    "use_beta_sigmas": False,
    "use_dynamic_shifting": True,
    "use_exponential_sigmas": False,
    "use_karras_sigmas": False,
}

WEIGHTS_DIR = "/weights"
GPU = "H100"

app = modal.App("pixel-philly")
weights = modal.Volume.from_name("pp-weights", create_if_missing=True)
# Trained style LoRAs (written by gpu/train_app.py)
runs = modal.Volume.from_name("pp-runs", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.14.1",
        # Qwen2.5-VL's video processor (part of the edit pipeline) imports torchvision
        "torchvision==0.29.1",
        "diffusers==0.41.0",
        "transformers==5.20.2",
        "accelerate",
        "peft",
        "safetensors",
        "huggingface_hub[hf_xet]",
        "pillow",
        "numpy",
    )
    .env({"HF_HOME": f"{WEIGHTS_DIR}/hf"})
    .add_local_python_source("pixelphilly")
)


@app.function(image=image, volumes={WEIGHTS_DIR: weights}, timeout=3 * 3600, cpu=4, memory=16384)
def download_weights():
    """One-time download of the pinned base model and Lightning LoRAs."""
    from huggingface_hub import hf_hub_download, snapshot_download

    base = snapshot_download(BASE_REPO, revision=BASE_REV)
    light = {k: hf_hub_download(LIGHT_REPO, f, revision=LIGHT_REV) for k, f in LIGHT_FILES.items()}
    weights.commit()
    return {"base": base, "lightning": light}


@app.function(image=image, volumes={WEIGHTS_DIR: weights}, timeout=600, cpu=2, memory=8192)
def check_env() -> dict:
    """Cheap CPU smoke test run before any GPU job: load every lightweight
    pipeline component (processor, tokenizer, scheduler) from the pinned
    weights. A missing dependency then fails here for a fraction of a cent
    instead of crash-looping an H100 container. (It caught a missing
    torchvision, which Qwen2.5-VL's video processor needs.)"""
    import importlib.metadata as md

    from diffusers import FlowMatchEulerDiscreteScheduler
    from huggingface_hub import snapshot_download
    from transformers import AutoProcessor, AutoTokenizer

    path = snapshot_download(BASE_REPO, revision=BASE_REV, local_files_only=True)
    AutoProcessor.from_pretrained(f"{path}/processor")
    AutoTokenizer.from_pretrained(f"{path}/tokenizer")
    FlowMatchEulerDiscreteScheduler.from_pretrained(f"{path}/scheduler")
    return {p: md.version(p) for p in ("torch", "torchvision", "diffusers", "transformers", "peft")}


@app.cls(image=image, gpu=GPU, volumes={WEIGHTS_DIR: weights, "/runs": runs}, timeout=2 * 3600, scaledown_window=120)
class Editor:
    """Qwen-Image-Edit-2511 on one H100: plain per-image edits (Phase A) and
    joint whole-canvas denoising (Phase D)."""

    @modal.enter()
    def load(self):
        import torch
        from diffusers import FlowMatchEulerDiscreteScheduler, QwenImageEditPlusPipeline
        from huggingface_hub import hf_hub_download

        t0 = time.time()
        self.torch = torch
        self.pipe = QwenImageEditPlusPipeline.from_pretrained(
            BASE_REPO, revision=BASE_REV, torch_dtype=torch.bfloat16
        ).to("cuda")
        self.base_scheduler = self.pipe.scheduler
        self.light_scheduler = FlowMatchEulerDiscreteScheduler.from_config(LIGHTNING_SCHEDULER)
        for k, f in LIGHT_FILES.items():
            path = hf_hub_download(LIGHT_REPO, f, revision=LIGHT_REV)
            self.pipe.load_lora_weights(path, adapter_name=f"light{k}")
        self.pipe.disable_lora()
        self.load_seconds = time.time() - t0

    def _configure(self, lightning: str | None, style: dict | None = None):
        """Choose adapters and scheduler. style = {"path": LoRA file in the
        pp-runs Volume, "scale": weight}."""
        names, scales = [], []
        if style:
            runs.reload()
            key = "style_" + "".join(c if c.isalnum() else "_" for c in style["path"])[-60:]
            if key not in self.pipe.get_list_adapters().get("transformer", []):
                self.pipe.load_lora_weights(style["path"], adapter_name=key)
            names.append(key)
            scales.append(style.get("scale", 1.0))
        if lightning:
            names.append(f"light{lightning}")
            scales.append(1.0)
        if names:
            self.pipe.enable_lora()
            self.pipe.set_adapters(names, adapter_weights=scales)
        else:
            self.pipe.disable_lora()
        self.pipe.scheduler = self.light_scheduler if lightning else self.base_scheduler

    @modal.method()
    def run(self, jobs: list[dict]) -> list[dict]:
        """Each job: image (PNG bytes), prompt, steps, cfg, seed, lightning
        (None, "4" or "8"). Returns PNG bytes plus timing and peak memory."""
        from PIL import Image

        torch = self.torch
        out = []
        for job in sorted(jobs, key=lambda j: str(j.get("lightning"))):
            self._configure(job.get("lightning"))
            src = Image.open(io.BytesIO(job["image"])).convert("RGB")
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            t0 = time.time()
            kwargs = {}
            if job["cfg"] > 1:
                # diffusers only runs true CFG when a negative prompt is given
                kwargs["negative_prompt"] = job.get("negative_prompt", " ")
            result = self.pipe(
                image=[src],
                prompt=job["prompt"],
                num_inference_steps=job["steps"],
                true_cfg_scale=job["cfg"],
                height=src.height,
                width=src.width,
                generator=torch.Generator("cuda").manual_seed(job["seed"]),
                **kwargs,
            ).images[0]
            torch.cuda.synchronize()
            buf = io.BytesIO()
            result.save(buf, "PNG")
            out.append(
                {
                    **{k: v for k, v in job.items() if k != "image"},
                    "png": buf.getvalue(),
                    "seconds": round(time.time() - t0, 2),
                    "peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
                    "load_seconds": round(self.load_seconds, 1),
                }
            )
        return out

    @modal.method()
    def joint(
        self,
        render_png: bytes,
        prompt: str,
        steps: int,
        cfg: float,
        seed: int,
        lightning: str | None = None,
        style: dict | None = None,
        mode: str = "joint",
        tile: int = 128,
        check_tiling: bool = False,
    ) -> dict:
        """Denoise a whole render (any size, multiple of 16 px) as ONE latent.

        mode "joint": overlapping 1,024 px windows on two alternating grids,
        blended with tent weights (pixelphilly.joint_sampler, tested on CPU).
        mode "independent": non-overlapping `tile`-latent tiles denoised
        separately, the stitched baseline used to prove the seam metric works.

        Each window is conditioned exactly like a normal 2511 edit of that
        crop: VAE latents of the crop appended as reference tokens, and a
        Qwen2.5-VL prompt embedding computed from the crop at ~384x384.
        """
        import numpy as np
        from diffusers.pipelines.qwenimage.pipeline_qwenimage_edit_plus import (
            CONDITION_IMAGE_SIZE,
            calculate_dimensions,
            calculate_shift,
        )
        from PIL import Image

        from pixelphilly.joint_sampler import independent_tiles, joint_denoise
        from pixelphilly.windows import WIN, two_grids

        torch = self.torch
        pipe = self.pipe
        self._configure(lightning, style)
        dev, dtype = "cuda", torch.bfloat16
        t_start = time.time()
        torch.cuda.reset_peak_memory_stats()

        render = Image.open(io.BytesIO(render_png)).convert("RGB")
        W, H = render.size
        if W % 16 or H % 16:
            raise ValueError("render size must be a multiple of 16 px")
        lh, lw = H // 8, W // 8
        C = pipe.transformer.config.in_channels // 4

        if mode == "joint":
            grids = two_grids(lh, lw)
            keys = sorted({k for g in grids for k in g})
            win = WIN
        else:
            keys = [(y, x) for y in range(0, lh, tile) for x in range(0, lw, tile)]
            win = tile

        # Per-window conditioning, computed once and reused at every step
        cache = {}
        with torch.no_grad():
            for y, x in keys:
                h, w = min(win, lh - y), min(win, lw - x)
                crop = render.crop((x * 8, y * 8, (x + w) * 8, (y + h) * 8))
                cw, ch = calculate_dimensions(CONDITION_IMAGE_SIZE, crop.width / crop.height)
                cond_img = pipe.image_processor.resize(crop, ch, cw)
                emb, mask = pipe.encode_prompt(prompt=prompt, image=[cond_img], device=dev)
                neg = pipe.encode_prompt(prompt=" ", image=[cond_img], device=dev) if cfg > 1 else None
                vae_in = pipe.image_processor.preprocess(crop, crop.height, crop.width).unsqueeze(2)
                lat = pipe._encode_vae_image(vae_in.to(dev, pipe.vae.dtype), generator=None)
                cond = pipe._pack_latents(lat, 1, C, h, w).to(dtype)
                cache[(y, x)] = (emb, mask, neg, cond, h, w)
        t_encode = time.time() - t_start

        # The scheduler's own sigmas for a normal 1,024 px edit (window size),
        # so each window sees exactly the schedule the model was trained on
        sched = pipe.scheduler
        mu = calculate_shift(
            (win // 2) * (win // 2),
            sched.config.get("base_image_seq_len", 256),
            sched.config.get("max_image_seq_len", 4096),
            sched.config.get("base_shift", 0.5),
            sched.config.get("max_shift", 1.15),
        )
        sched.set_timesteps(sigmas=np.linspace(1.0, 1 / steps, steps), mu=mu, device=dev)
        sigmas = [float(s) for s in sched.sigmas]

        forwards = {"n": 0}

        def predict(x_win, y, x, sigma):
            emb, mask, neg, cond, h, w = cache[(y, x)]
            xin = pipe._pack_latents(x_win.unsqueeze(0).to(dtype), 1, C, h, w)
            hidden = torch.cat([xin, cond], dim=1)
            t = torch.full((1,), sigma, device=dev, dtype=dtype)
            shapes = [[(1, h // 2, w // 2), (1, h // 2, w // 2)]]
            with torch.no_grad():
                v = pipe.transformer(hidden_states=hidden, timestep=t, guidance=None,
                                     encoder_hidden_states_mask=mask, encoder_hidden_states=emb,
                                     img_shapes=shapes, return_dict=False)[0][:, : xin.shape[1]]
                forwards["n"] += 1
                if neg is not None:
                    nv = pipe.transformer(hidden_states=hidden, timestep=t, guidance=None,
                                          encoder_hidden_states_mask=neg[1], encoder_hidden_states=neg[0],
                                          img_shapes=shapes, return_dict=False)[0][:, : xin.shape[1]]
                    forwards["n"] += 1
                    comb = nv + cfg * (v - nv)
                    # Same norm rescaling as the diffusers pipeline
                    v = comb * (torch.norm(v, dim=-1, keepdim=True) / torch.norm(comb, dim=-1, keepdim=True))
            return pipe._unpack_latents(v, h * 8, w * 8, 8)[0, :, 0].float()

        noise = torch.randn((C, lh, lw), generator=torch.Generator(dev).manual_seed(seed), device=dev,
                            dtype=torch.float32)
        if mode == "joint":
            latents = joint_denoise(noise, sigmas, grids, predict, win)
        else:
            latents = independent_tiles(noise, sigmas, tile, predict)
        t_denoise = time.time() - t_start - t_encode

        # Decode the whole canvas with the VAE's built-in overlapping tiles
        def denorm(lat):
            lat = lat.unsqueeze(0).unsqueeze(2).to(pipe.vae.dtype)
            mean = torch.tensor(pipe.vae.config.latents_mean).view(1, C, 1, 1, 1).to(lat)
            std = 1.0 / torch.tensor(pipe.vae.config.latents_std).view(1, C, 1, 1, 1).to(lat)
            return lat / std + mean

        tiling_diff = None
        untiled_png = None
        with torch.no_grad():
            pipe.vae.enable_tiling()
            img = pipe.vae.decode(denorm(latents), return_dict=False)[0][:, :, 0]
            if check_tiling and max(lh, lw) <= 256:
                # Small canvases also get an untiled decode, so any seams the
                # VAE's own tiling adds can be measured separately
                pipe.vae.disable_tiling()
                plain = pipe.vae.decode(denorm(latents), return_dict=False)[0][:, :, 0]
                pipe.vae.enable_tiling()
                ubuf = io.BytesIO()
                pipe.image_processor.postprocess(plain, output_type="pil")[0].save(ubuf, "PNG")
                untiled_png = ubuf.getvalue()
            if check_tiling:
                # Tiled vs. untiled decode of a 2,048 px patch: should agree
                patch = latents[:, : min(256, lh), : min(256, lw)]
                pipe.vae.disable_tiling()
                full = pipe.vae.decode(denorm(patch), return_dict=False)[0][:, :, 0]
                pipe.vae.enable_tiling()
                tiled = pipe.vae.decode(denorm(patch), return_dict=False)[0][:, :, 0]
                to8 = lambda t: ((t.float().clamp(-1, 1) + 1) * 127.5).round()  # noqa: E731
                tiling_diff = float((to8(full) - to8(tiled)).abs().max())
        pil = pipe.image_processor.postprocess(img, output_type="pil")[0]
        buf = io.BytesIO()
        pil.save(buf, "PNG")
        return {
            "png": buf.getvalue(),
            "png_untiled": untiled_png,
            "mode": mode,
            "windows": len(keys),
            "forwards": forwards["n"],
            "sigmas": [round(s, 4) for s in sigmas],
            "encode_seconds": round(t_encode, 1),
            "denoise_seconds": round(t_denoise, 1),
            "total_seconds": round(time.time() - t_start, 1),
            "peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
            "tiling_max_diff_levels": tiling_diff,
        }
