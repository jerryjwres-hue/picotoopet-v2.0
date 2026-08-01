from picotoopet_core import __version__


def test_package_exposes_phase_one_version() -> None:
    """包必须暴露明确的 Phase 1 版本号。"""

    assert __version__ == "2.2.0-phase2-slice1"
