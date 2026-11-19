"""Tests for GPU VRAM check and cooperative fallback."""

from unittest.mock import Mock, patch
from qc.gpu import get_gpu_memory_used_mb, resolve_device


def test_get_gpu_memory_used_mb_real_or_mock():
    # Should either return an integer MiB or None without raising an exception
    mem = get_gpu_memory_used_mb()
    if mem is not None:
        assert isinstance(mem, int)
        assert mem >= 0


@patch("qc.gpu.get_gpu_memory_used_mb")
def test_resolve_device_switches_to_cpu_when_vram_exceeds_threshold(mock_get_mem):
    mock_get_mem.return_value = 8500  # > 5000 MiB (e.g. ComfyUI running)
    device = resolve_device(threshold_mb=5000)
    assert device == "cpu"


@patch("qc.gpu.get_gpu_memory_used_mb")
def test_resolve_device_uses_cuda_when_vram_low(mock_get_mem):
    mock_get_mem.return_value = 2100  # < 5000 MiB
    torch = Mock()
    torch.cuda.is_available.return_value = True
    with patch.dict("sys.modules", {"torch": torch}):
        device = resolve_device(threshold_mb=5000)
        assert device == "cuda"


def test_resolve_device_explicit_cpu():
    device = resolve_device(prefer_device="cpu")
    assert device == "cpu"
