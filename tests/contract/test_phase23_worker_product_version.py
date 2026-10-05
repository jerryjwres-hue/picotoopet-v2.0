"""Mac Worker package and active runtime product-version / capability verifier contract."""

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
    # Version gate              Worker package reads the same current 27.1 product resource as Core.
    assert VERSION_FILE.read_text(encoding="utf-8").strip() == "2.3.27.1"


def test_worker_verifier_accepts_only_the_cumulative_closed_task_allowlist() -> None:
    """正式 VERIFY 必须接受已实现累计能力，同时继续拒绝任意未知任务类型。"""

    verifier = read(DEPLOY / "VERIFY_MAC_WORKER_SLICE_C.command")
    library = read(DEPLOY / "worker-lib.sh")
    combined = "\n".join((verifier, library))

    for required in (
        '"system.diagnostic_snapshot"',
        '"system.noop"',
        '"business.local_intelligence.v1"',
        '"creative.content_plan.v1"',
        '"provider.codex.handoff-v1"',
        '"provider.adoption.apply-v1"',
        '"provider.commit.create-v1"',
        '"provider.publish.pr-create-v1"',
    ):
        assert required in combined

    # Allowlist gate             系统任务是必需项；累计已实现类型只是允许出现，不能要求严格等于两个 system 类型。
    assert "required <= set(supported)" in combined or "required.issubset(supported_set)" in combined
    assert "unexpected Worker task type" in combined
    assert 'payload.get("supported_task_types") != [' not in verifier
