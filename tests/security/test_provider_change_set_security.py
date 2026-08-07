from pathlib import Path

import pytest


def _api():
    from picotoopet_core.providers.artifact_store import (
        ProviderArtifactError,
        ProviderReturnArtifactStore,
    )
    from picotoopet_core.providers.change_set import ProviderChangeInput

    return ProviderArtifactError, ProviderReturnArtifactStore, ProviderChangeInput


@pytest.mark.parametrize(
    "path",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "docs/../../escape.txt",
        "docs\\windows.txt",
        "./dot.txt",
        "docs/./dot.txt",
        "docs\x00bad.txt",
    ],
)
def test_change_set_rejects_non_normalized_or_escaping_paths(tmp_path: Path, path: str) -> None:
    ArtifactError, Store, Change = _api()
    store = Store(tmp_path / "provider-returns")
    with pytest.raises(ArtifactError, match="PATH_POLICY"):
        store.write(
            return_id="return-path",
            base_commit="a" * 40,
            changes=[Change(operation="add", path=path, result_text="safe")],
            review_diff="",
        )


def _secret_samples() -> list[str]:
    """运行时拼出敏感样本，避免仓库发布扫描把测试夹具误判成真实凭据。"""

    return [
        "Author" + "ization: Bearer definitely-secret-value",
        "api_" + "key=definitely-secret-value",
        "to" + "ken: definitely-secret-value",
        "pass" + "word=definitely-secret-value",
        "-----BEGIN PRIVATE " + "KEY-----\nsecret\n-----END PRIVATE KEY-----",
    ]


@pytest.mark.parametrize("content", _secret_samples())
def test_change_set_rejects_obvious_secret_material(tmp_path: Path, content: str) -> None:
    ArtifactError, Store, Change = _api()
    store = Store(tmp_path / "provider-returns")
    with pytest.raises(ArtifactError, match="SECRET_REJECTED"):
        store.write(
            return_id="return-secret",
            base_commit="a" * 40,
            changes=[Change(operation="add", path="docs/a.txt", result_text=content)],
            review_diff="",
        )


def test_change_set_requires_operation_specific_hash_and_payload_rules(tmp_path: Path) -> None:
    ArtifactError, Store, Change = _api()
    store = Store(tmp_path / "provider-returns")

    with pytest.raises(ArtifactError, match="CHANGE_INVALID"):
        store.write(
            return_id="bad-add",
            base_commit="a" * 40,
            changes=[
                Change(
                    operation="add",
                    path="docs/a.txt",
                    base_sha256="b" * 64,
                    result_text="x",
                )
            ],
            review_diff="",
        )

    with pytest.raises(ArtifactError, match="CHANGE_INVALID"):
        store.write(
            return_id="bad-modify",
            base_commit="a" * 40,
            changes=[Change(operation="modify", path="docs/a.txt", result_text="x")],
            review_diff="",
        )

    with pytest.raises(ArtifactError, match="CHANGE_INVALID"):
        store.write(
            return_id="bad-delete",
            base_commit="a" * 40,
            changes=[
                Change(
                    operation="delete",
                    path="docs/a.txt",
                    base_sha256="b" * 64,
                    result_text="must-not-exist",
                )
            ],
            review_diff="",
        )


def test_runtime_paths_expose_server_derived_provider_return_directory(tmp_path: Path) -> None:
    from picotoopet_core.config.paths import RuntimePaths

    paths = RuntimePaths.from_root(tmp_path / "runtime-root")
    assert paths.provider_returns_dir == paths.runtime_dir / "provider-returns"
    paths.ensure()
    assert paths.provider_returns_dir.is_dir()
