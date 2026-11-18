"""GPU VRAM management and cooperative device resolution.

Checks nvidia-smi on startup; if VRAM usage exceeds 5000 MiB, automatically
routes workload to CPU to avoid competing with ComfyUI.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger("qc.gpu")

VRAM_THRESHOLD_MIB = 5000


def get_gpu_memory_used_mb() -> Optional[int]:
    """Query currently used GPU VRAM in MiB using nvidia-smi.

    Returns:
        int: Used VRAM in MiB, or None if nvidia-smi is not available/failed.
    """
    if not shutil.which("nvidia-smi"):
        logger.debug("nvidia-smi binary not found in PATH.")
        return None

    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        lines = result.stdout.strip().splitlines()
        if lines:
            # If multiple GPUs, take the maximum used memory across them
            used_list = [int(line.strip()) for line in lines if line.strip().isdigit()]
            if used_list:
                return max(used_list)
    except Exception as exc:
        logger.warning(f"Failed to query nvidia-smi: {exc}")
    return None


def resolve_device(threshold_mb: int = VRAM_THRESHOLD_MIB, prefer_device: Optional[str] = None) -> str:
    """Resolve compute device ('cuda' or 'cpu').

    If prefer_device is explicitly specified (e.g. 'cpu'), respect it.
    Otherwise checks torch CUDA availability and VRAM usage.
    If VRAM used > threshold_mb, falls back to 'cpu'.
    """
    if prefer_device == "cpu":
        return "cpu"

    try:
        import torch
        if not torch.cuda.is_available():
            logger.info("CUDA not available in PyTorch, using CPU.")
            return "cpu"
    except ImportError:
        return "cpu"

    used_mb = get_gpu_memory_used_mb()
    if used_mb is not None:
        if used_mb > threshold_mb:
            logger.warning(
                f"[GPU Safeguard] GPU VRAM currently used is {used_mb} MiB "
                f"(exceeds threshold of {threshold_mb} MiB). "
                "Cooperatively routing to CPU to avoid conflicting with ComfyUI."
            )
            return "cpu"
        logger.info(f"[GPU Safeguard] GPU VRAM used is {used_mb} MiB <= {threshold_mb} MiB. Using CUDA.")
        return "cuda"

    # If nvidia-smi couldn't be queried, default to safe CPU mode unless torch has free memory
    return "cpu"
