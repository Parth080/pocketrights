"""Modal application — the CUDA side of PocketRights.

Everything that needs an NVIDIA GPU runs here: every training run, AWQ and GPTQ
quantization, and vLLM evaluation of the INT4 variants. Everything else runs on
the Mac (PROJECT.md §1A).

Task 5 provides only the plumbing and a hello-GPU check. Real training entry
points land in task 43.

    modal setup                                          # once, authenticates
    modal run packages/pr_train/src/pr_train/modal_app.py::hello
    modal run packages/pr_train/src/pr_train/modal_app.py::check_volume

`hello` runs on the cheapest GPU Modal offers and exits in seconds. It exists to
prove auth, image build, volume mount, and GPU visibility all work — so that
none of those fail for the first time in month four with a real run queued
behind them.
"""

from __future__ import annotations

import os

import modal

APP_NAME = "pocketrights"

# --------------------------------------------------------------------------
# Volumes — persistent state between ephemeral runs
# --------------------------------------------------------------------------
# Separated by lifecycle rather than lumped together: datasets are written once
# and read many times; checkpoints are large and churn; the HF cache is pure
# derived data that can be nuked without losing anything.

datasets_vol = modal.Volume.from_name(f"{APP_NAME}-datasets", create_if_missing=True)
models_vol = modal.Volume.from_name(f"{APP_NAME}-models", create_if_missing=True)
runs_vol = modal.Volume.from_name(f"{APP_NAME}-runs", create_if_missing=True)
hf_cache_vol = modal.Volume.from_name(f"{APP_NAME}-hf-cache", create_if_missing=True)

VOLUMES = {
    "/data": datasets_vol,
    "/models": models_vol,
    "/runs": runs_vol,
    "/hf-cache": hf_cache_vol,
}

# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
# Pinned versions on purpose. An unpinned training image means two runs of the
# "same" configuration can differ, which would quietly break the controlled
# comparison the whole study rests on (PROJECT.md §9).

base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .env({"HF_HOME": "/hf-cache", "HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

train_image = base_image.pip_install(
    "torch==2.9.1",
    "transformers==4.57.1",
    "peft==0.18.0",
    "trl==0.26.0",
    "accelerate==1.11.0",
    "bitsandbytes==0.49.0",
    "datasets==4.4.1",
    "sentencepiece==0.2.1",
    "hf-transfer==0.1.9",
)

app = modal.App(APP_NAME)

# Set once with:  modal secret create huggingface HF_TOKEN=hf_...
# Gated base models need it; ungated ones do not. Declared optional so the
# hello check works before the secret exists.
try:
    hf_secret = [modal.Secret.from_name("huggingface")]
except Exception:  # pragma: no cover - depends on remote state
    hf_secret = []


# --------------------------------------------------------------------------
# Health checks (task 5)
# --------------------------------------------------------------------------

@app.function(image=train_image, gpu="A10G", volumes=VOLUMES, timeout=600)
def hello() -> dict:
    """Prove the whole chain works: auth, image, GPU, volumes, torch."""
    import subprocess

    import torch

    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
         "--format=csv,noheader"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    info = {
        "gpu": smi,
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "device_count": torch.cuda.device_count(),
        "bf16_supported": torch.cuda.is_bf16_supported(),
        "mounts": {p: os.path.isdir(p) for p in VOLUMES},
    }

    # Prove the volume is writable and actually persists.
    marker = "/runs/.modal_hello"
    with open(marker, "a") as fh:
        fh.write("ok\n")
    runs_vol.commit()
    info["volume_writable"] = os.path.exists(marker)

    for k, v in info.items():
        print(f"  {k:18} {v}")
    return info


@app.function(image=base_image, volumes=VOLUMES, timeout=300)
def check_volume() -> dict:
    """List what is on each volume. Cheap — no GPU."""
    listing = {}
    for mount in VOLUMES:
        try:
            listing[mount] = sorted(os.listdir(mount))[:20]
        except OSError as exc:
            listing[mount] = f"ERROR: {exc}"
    for mount, entries in listing.items():
        print(f"  {mount:10} {entries}")
    return listing


@app.function(image=train_image, gpu="A10G", volumes=VOLUMES, timeout=1800)
def bench_gpu(matrix: int = 8192, iters: int = 50) -> dict:
    """Rough bf16 matmul throughput. Establishes a baseline for the per-run cost
    estimates in PROJECT.md §12 before committing to the training grid."""
    import time

    import torch

    dev = torch.device("cuda")
    a = torch.randn(matrix, matrix, device=dev, dtype=torch.bfloat16)
    b = torch.randn(matrix, matrix, device=dev, dtype=torch.bfloat16)

    for _ in range(5):  # warm up
        a @ b
    torch.cuda.synchronize()

    start = time.perf_counter()
    for _ in range(iters):
        a @ b
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    tflops = (2 * matrix**3 * iters) / elapsed / 1e12
    result = {
        "gpu": torch.cuda.get_device_name(0),
        "matrix": matrix,
        "iters": iters,
        "seconds": round(elapsed, 3),
        "bf16_tflops": round(tflops, 1),
    }
    print(f"  {result['gpu']}: {result['bf16_tflops']} bf16 TFLOP/s")
    return result


@app.local_entrypoint()
def main() -> None:
    """`modal run modal_app.py` — the full task-5 acceptance check."""
    print("\n=== hello ===")
    hello.remote()
    print("\n=== volumes ===")
    check_volume.remote()
    print("\nTask 5 acceptance: auth, image, GPU, and volumes all OK.")
