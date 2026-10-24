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
    out = {p: md.version(p) for p in ("torch", "torchvision", "diffusers", "transformers", "peft")}
    out["known_band"] = _known_band_smoke()
    return out


def _known_band_smoke() -> dict:
    """The known-band code path of AreaSampler.joint_volume on a tiny canvas
    with a toy predictor (no model): the mask, the windows and
    joint_denoise(known=...), so an import or shape error shows up here on a
    CPU instead of on an H100."""
    import numpy as np
    import torch

    from pixelphilly.joint_sampler import joint_denoise
    from pixelphilly.regions import known_mask, repair_mask
    from pixelphilly.windows import active_grids, two_grids

    cell, win, C = 64, 128, 4
    frames = [{"name": f"f{c}{r}", "col": c, "row": r} for r in range(2) for c in range(3)]
    known = [f["name"] for f in frames if f["row"] == 1]
    mask = known_mask(frames, known, cell, 8)
    lh, lw = mask.shape
    active = np.ones((lh, lw), bool)
    grids = active_grids(two_grids(lh, lw, win=win, stride=96, shift=48), active, win)
    x0_known = torch.full((C, lh, lw), 0.5)
    noise = torch.randn((C, lh, lw), generator=torch.Generator().manual_seed(0))

    def predict(x_win, y, x, sigma):  # velocity toward 0.5 everywhere
        return (x_win - 0.5) / max(sigma, 1e-6)

    lat = joint_denoise(noise, [1.0, 0.5, 0.0], grids, predict, win, active=torch.from_numpy(active),
                        known=(x0_known, torch.from_numpy(mask)))
    exact = bool(torch.allclose(lat[:, mask == 1.0], x0_known[:, mask == 1.0]))
    if not exact:
        raise RuntimeError("known cells are not reproduced exactly")
    # The repair pass on the result: only the strip may change
    fixed, strip = repair_mask(frames, known, cell, 10)
    noise2 = torch.randn((C, lh, lw), generator=torch.Generator().manual_seed(1))
    rgrids = active_grids(two_grids(lh, lw, win=win, stride=96, shift=48), strip, win)
    rep = joint_denoise(noise2, [0.5, 0.0], rgrids, predict, win, active=torch.from_numpy(strip),
                        known=(lat, torch.from_numpy(fixed)), start=0.5 * lat + 0.5 * noise2)
    if not torch.equal(rep[:, ~torch.from_numpy(strip)], lat[:, ~torch.from_numpy(strip)]):
        raise RuntimeError("the repair pass changed cells outside its strip")
    return {"canvas_cells": [lh, lw], "windows": sum(len(g) for g in grids), "known_exact": exact,
            "repair_strip_cells": int(strip.sum()), "repair_windows": sum(len(g) for g in rgrids),
            "repair_fixed_exact": True,
            "ramp_levels": int(len(np.unique(mask[(mask > 0) & (mask < 1)])))}


class _QwenBase:
    """Model loading and adapter switching shared by the GPU classes. A plain
    base class: Modal can't subclass a class it has already decorated."""

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



@app.cls(image=image, gpu=GPU, volumes={WEIGHTS_DIR: weights, "/runs": runs}, timeout=2 * 3600, scaledown_window=120)
class Editor(_QwenBase):
    """Qwen-Image-Edit-2511 on one H100: plain per-image edits (Phase A) and
    joint whole-canvas denoising (Phase D)."""

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


@app.cls(image=image, gpu=GPU, volumes={WEIGHTS_DIR: weights, "/runs": runs}, timeout=4 * 3600,
         memory=65536, scaledown_window=60)
class AreaSampler(_QwenBase):
    """Joint denoising for areas too big to pass around as one PNG.

    Inputs and outputs live in the pp-runs Volume:
      /runs/areas/<area>/renders/<frame>.png            (uploaded by 15_joint_sample.py)
      /runs/areas/<area>/joint/<name>/latent.pt         (saved BEFORE decoding)
      /runs/areas/<area>/joint/<name>/frames/<frame>.png
    Only windows touching kept frames run (clipped areas leave about half the
    rectangular canvas empty). Each frame is decoded on its own with a
    128 px halo, so decode memory doesn't grow with the area.
    """

    @modal.method()
    def joint_volume(self, area: str, name: str, frames: list[dict], frame_px: int, prompt: str,
                     steps: int, cfg: float, seed: int, lightning: str | None = None,
                     style: dict | None = None, known_frames: list[str] | None = None,
                     known_ramp_cells: int = 0, repair_width_px: int = 200,
                     repair_sigma: float = 0.6) -> dict:
        """known_frames: names (in `frames`) whose drawn pixels are already
        final, from a neighboring area drawn earlier (uploaded by
        15_joint_sample.py --known-area to <out>/known/<frame>.png). They are
        VAE-encoded to the latent the decoder turns back into that drawing
        and held there by joint_denoise(known=...), with a mask of 1 on
        their cells ramping to 0 over known_ramp_cells into the new frames
        (pixelphilly.regions.known_mask). Their render is still the edit
        model's conditioning, like every other frame. Only the other frames
        are decoded and returned, so the old area's pixels stay
        authoritative.

        Repair pass (with known frames and repair_width_px > 0): after the
        main denoise, the new frames' cells within repair_width_px of a known
        cell (pixelphilly.regions.repair_mask) are re-noised to the schedule
        step nearest repair_sigma with fresh noise (seed + 1) and redrawn with
        the rest of the schedule, everything else held exactly as drawn, so
        the strip is redrawn seeing both finished sides (tiny.london's repair
        step, SDEdit-style). The boundary test without it drew a building
        straddling the join gray on one side and beige on the other."""
        import os

        import numpy as np
        from diffusers.pipelines.qwenimage.pipeline_qwenimage_edit_plus import (
            CONDITION_IMAGE_SIZE,
            calculate_dimensions,
            calculate_shift,
        )
        from PIL import Image

        from pixelphilly.joint_sampler import joint_denoise
        from pixelphilly.regions import known_mask, repair_mask, repair_step
        from pixelphilly.windows import WIN, active_grids, two_grids

        Image.MAX_IMAGE_PIXELS = None
        known_frames = list(known_frames or [])
        torch = self.torch
        pipe = self.pipe
        self._configure(lightning, style)
        runs.reload()
        dev, dtype = "cuda", torch.bfloat16
        t_start = time.time()
        torch.cuda.reset_peak_memory_stats()

        src = f"/runs/areas/{area}/renders"
        out = f"/runs/areas/{area}/joint/{name}"
        os.makedirs(f"{out}/frames", exist_ok=True)
        cols = max(f["col"] for f in frames) + 1
        rows = max(f["row"] for f in frames) + 1
        W, H = cols * frame_px, rows * frame_px
        lw, lh = W // 8, H // 8
        cell = frame_px // 8
        canvas = np.zeros((H, W, 3), np.uint8)
        active = np.zeros((lh, lw), bool)
        for f in frames:
            canvas[f["row"] * frame_px:(f["row"] + 1) * frame_px, f["col"] * frame_px:(f["col"] + 1) * frame_px] = \
                np.asarray(Image.open(f"{src}/{f['name']}.png").convert("RGB"))
            active[f["row"] * cell:(f["row"] + 1) * cell, f["col"] * cell:(f["col"] + 1) * cell] = True
        grids = active_grids(two_grids(lh, lw), active)
        keys = sorted({k for g in grids for k in g})
        C = pipe.transformer.config.in_channels // 4

        # Per-window conditioning, exactly as in Editor.joint, kept on the CPU
        cache = {}
        with torch.no_grad():
            for y, x in keys:
                crop = Image.fromarray(canvas[y * 8:(y + WIN) * 8, x * 8:(x + WIN) * 8])
                cw, ch = calculate_dimensions(CONDITION_IMAGE_SIZE, crop.width / crop.height)
                cond_img = pipe.image_processor.resize(crop, ch, cw)
                emb, mask = pipe.encode_prompt(prompt=prompt, image=[cond_img], device=dev)
                neg = pipe.encode_prompt(prompt=" ", image=[cond_img], device=dev) if cfg > 1 else None
                vae_in = pipe.image_processor.preprocess(crop, crop.height, crop.width).unsqueeze(2)
                lat = pipe._encode_vae_image(vae_in.to(dev, pipe.vae.dtype), generator=None)
                cond = pipe._pack_latents(lat, 1, C, WIN, WIN).to(dtype)
                to_cpu = lambda t: None if t is None else t.to("cpu")  # noqa: E731
                cache[(y, x)] = (to_cpu(emb), to_cpu(mask), None if neg is None else (to_cpu(neg[0]), to_cpu(neg[1])),
                                 to_cpu(cond))

        sched = pipe.scheduler
        mu = calculate_shift((WIN // 2) ** 2, sched.config.get("base_image_seq_len", 256),
                             sched.config.get("max_image_seq_len", 4096), sched.config.get("base_shift", 0.5),
                             sched.config.get("max_shift", 1.15))
        sched.set_timesteps(sigmas=np.linspace(1.0, 1 / steps, steps), mu=mu, device=dev)
        sigmas = [float(s) for s in sched.sigmas]
        shapes = [[(1, WIN // 2, WIN // 2), (1, WIN // 2, WIN // 2)]]
        forwards = {"n": 0}

        def g(t):
            return None if t is None else t.to(dev, non_blocking=True)

        def predict(x_win, y, x, sigma):
            emb, mask, neg, cond = cache[(y, x)]
            xin = pipe._pack_latents(x_win.unsqueeze(0).to(dtype), 1, C, WIN, WIN)
            hidden = torch.cat([xin, g(cond)], dim=1)
            t = torch.full((1,), sigma, device=dev, dtype=dtype)
            with torch.no_grad():
                v = pipe.transformer(hidden_states=hidden, timestep=t, guidance=None, encoder_hidden_states_mask=g(mask),
                                     encoder_hidden_states=g(emb), img_shapes=shapes, return_dict=False)[0][:, : xin.shape[1]]
                forwards["n"] += 1
                if neg is not None:
                    nv = pipe.transformer(hidden_states=hidden, timestep=t, guidance=None,
                                          encoder_hidden_states_mask=g(neg[1]), encoder_hidden_states=g(neg[0]),
                                          img_shapes=shapes, return_dict=False)[0][:, : xin.shape[1]]
                    forwards["n"] += 1
                    comb = nv + cfg * (v - nv)
                    v = comb * (torch.norm(v, dim=-1, keepdim=True) / torch.norm(comb, dim=-1, keepdim=True))
            return pipe._unpack_latents(v, WIN * 8, WIN * 8, 8)[0, :, 0].float()

        known = None
        if known_frames:
            # Target latents of the drawn neighbor: _encode_vae_image returns
            # (raw - latents_mean) / latents_std, which the decode below inverts
            x0_known = torch.zeros((C, lh, lw), device=dev, dtype=torch.float32)
            by_name = {f["name"]: f for f in frames}
            with torch.no_grad():
                for k in known_frames:
                    f = by_name[k]
                    img = Image.open(f"{out}/known/{k}.png").convert("RGB")
                    vae_in = pipe.image_processor.preprocess(img, frame_px, frame_px).unsqueeze(2)
                    lat = pipe._encode_vae_image(vae_in.to(dev, pipe.vae.dtype), generator=None)
                    x0_known[:, f["row"] * cell:(f["row"] + 1) * cell, f["col"] * cell:(f["col"] + 1) * cell] = \
                        lat[0, :, 0].float()
            kmask = torch.from_numpy(known_mask(frames, known_frames, cell, known_ramp_cells)).to(dev)
            known = (x0_known, kmask)
        t_encode = time.time() - t_start

        noise = torch.randn((C, lh, lw), generator=torch.Generator(dev).manual_seed(seed), device=dev,
                            dtype=torch.float32)
        latents = joint_denoise(noise, sigmas, grids, predict, WIN, active=torch.from_numpy(active).to(dev),
                                known=known)
        t_denoise = time.time() - t_start - t_encode
        main_forwards = forwards["n"]

        repair = None
        if known_frames and repair_width_px > 0:
            torch.save(latents.cpu(), f"{out}/latent_main.pt")  # before the repair, for comparison
            t_rep = time.time()
            fixed, strip = repair_mask(frames, known_frames, cell, repair_width_px // 8)
            k = repair_step(sigmas, repair_sigma)
            s0 = sigmas[k]
            noise2 = torch.randn((C, lh, lw), generator=torch.Generator(dev).manual_seed(seed + 1), device=dev,
                                 dtype=torch.float32)
            # Windows touching the strip: a subset of the main pass's, so the
            # conditioning cache already has them
            rgrids = active_grids(two_grids(lh, lw), strip)
            latents = joint_denoise(noise2, sigmas[k:], rgrids, predict, WIN, active=torch.from_numpy(strip).to(dev),
                                    known=(latents, torch.from_numpy(fixed).to(dev)),
                                    start=(1 - s0) * latents + s0 * noise2)
            repair = {"width_px": repair_width_px, "sigma_target": repair_sigma, "start_step": k,
                      "start_sigma": round(s0, 4), "steps": len(sigmas) - 1 - k, "strip_cells": int(strip.sum()),
                      "windows_per_grid": [len(g_) for g_ in rgrids], "forwards": forwards["n"] - main_forwards,
                      "seconds": round(time.time() - t_rep, 1)}
        # Save before decoding: a decode failure must not lose the run
        torch.save(latents.cpu(), f"{out}/latent.pt")
        runs.commit()

        mean = torch.tensor(pipe.vae.config.latents_mean).view(1, C, 1, 1, 1)
        std = 1.0 / torch.tensor(pipe.vae.config.latents_std).view(1, C, 1, 1, 1)
        halo = 16  # latent cells = 128 px of overlap so frame edges decode with context
        pipe.vae.disable_tiling()
        decoded = [f for f in frames if f["name"] not in set(known_frames)]
        with torch.no_grad():
            for f in decoded:
                y0, x0 = f["row"] * cell, f["col"] * cell
                ya, xa = max(0, y0 - halo), max(0, x0 - halo)
                yb, xb = min(lh, y0 + cell + halo), min(lw, x0 + cell + halo)
                lat = latents[:, ya:yb, xa:xb].unsqueeze(0).unsqueeze(2).to(pipe.vae.dtype)
                lat = lat / std.to(lat) + mean.to(lat)
                img = pipe.vae.decode(lat, return_dict=False)[0][:, :, 0]
                pil = pipe.image_processor.postprocess(img, output_type="pil")[0]
                oy, ox = (y0 - ya) * 8, (x0 - xa) * 8
                pil.crop((ox, oy, ox + frame_px, oy + frame_px)).save(f"{out}/frames/{f['name']}.png")
        runs.commit()
        return {
            "area": area, "name": name, "frames": len(frames), "canvas_px": [W, H],
            "decoded_frames": [f["name"] for f in decoded], "known_frames": len(known_frames),
            "known_ramp_cells": known_ramp_cells if known_frames else None,
            "main_forwards": main_forwards, "repair": repair,
            "windows": len(keys), "windows_per_grid": [len(g_) for g_ in grids], "forwards": forwards["n"],
            "sigmas": [round(s, 4) for s in sigmas], "encode_seconds": round(t_encode, 1),
            "denoise_seconds": round(t_denoise, 1), "total_seconds": round(time.time() - t_start, 1),
            "peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
        }
