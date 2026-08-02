from picotoopet_core import __version__


def test_package_exposes_slice_b_runtime_version() -> None:
    """包必须暴露明确的 Phase 2.3 Slice B 运行时版本。"""

    assert __version__ == "2.3.0-slice-b"
