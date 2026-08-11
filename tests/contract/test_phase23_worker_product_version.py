"""Mac Worker package and active runtime product-version contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "scripts" / "mac" / "phase23-worker"
DEPLOY = ROOT / "deploy" / "macos" / "phase23-worker"
VERSION_FILE = ROOT / "src" / "picotoopet_core" / "product-version.txt"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_worker_verify_checks_active_runtime_product_version() -> None:
    verifier = read(DEPLOY / "VERIFY_MAC_WORKER_SLICE_C.command")
    library = read(DEPLOY / "worker-lib.sh")
    assert "phase23_worker_product_version" in verifier
    assert "verify_worker_product_version" in verifier
    assert "from picotoopet_core import __version__" in library
    assert "expected_product_version" in library
    assert '"product_version"' in library


def test_worker_builder_packages_canonical_product_version() -> None:
    builder = read(BUILD / "Build-MacWorkerSliceC.sh")
    verifier = read(BUILD / "Test-MacWorkerSliceC.sh")
    for required in (
        "src/picotoopet_core/product-version.txt",
        "product-version.txt",
        '"product_version"',
        "PRODUCT_VERSION=",
    ):
        assert required in builder
    assert "phase23_worker_product_version" in verifier
    assert VERSION_FILE.read_text(encoding="utf-8").strip() == "2.3.19.1"
