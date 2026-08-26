from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_INSTALLER = REPO_ROOT / "deploy/macos/phase23-worker/INSTALL_MAC_WORKER_SLICE_C.command"
GATEWAY_INSTALLER = REPO_ROOT / "deploy/macos/research_gateway/INSTALL_RESEARCH_GATEWAY.command"
GATEWAY_VERIFY = REPO_ROOT / "deploy/macos/research_gateway/VERIFY_RESEARCH_GATEWAY.command"
INTEGRATED_INSTALLER = (
    REPO_ROOT / "deploy/macos/research_integration/INSTALL_PICOTOOPET_RESEARCH_2_3_27_1.command"
)
INTEGRATED_VERIFY = (
    REPO_ROOT / "deploy/macos/research_integration/VERIFY_PICOTOOPET_RESEARCH_2_3_27_1.command"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_worker_installer_marks_and_cleans_incomplete_versions() -> None:
    source = _read(WORKER_INSTALLER)

    # 失败恢复合同：只有带明确未完成标记的候选目录可以被安装器自动清理。
    assert 'install_marker_name=".picotoopet-install-incomplete"' in source
    assert "cleanup_new_version()" in source
    assert 'touch "$new_version/$install_marker_name"' in source
    assert 'rm -f "$new_version/$install_marker_name"' in source
    assert "目标版本已存在，拒绝覆盖" in source


def test_gateway_installer_restores_snapshot_when_health_fails() -> None:
    source = _read(GATEWAY_INSTALLER)

    # 原子安装合同：覆盖 Gateway 前保存快照，health 成功前不得提交安装成功状态。
    assert 'backup_root="$(mktemp -d ' in source
    assert 'cp -a "$install_root" "$backup_root/install-root"' in source
    assert 'if [[ "$install_success" != "1" && "$gateway_touched" == "1" ]]' in source
    assert 'cp -a "$backup_root/install-root" "$install_root"' in source
    assert source.index('"$bin_dir/picotoopet-research-gateway" --health') < source.index(
        "install_success=1"
    )


def test_install_contract_is_separate_from_full_shared_health() -> None:
    gateway_source = _read(GATEWAY_VERIFY)
    installer_source = _read(INTEGRATED_INSTALLER)
    integrated_source = _read(INTEGRATED_VERIFY)

    # 安装只验证 PicotooPet 自身；人工 full 验证仍保持共享 CLI、认证和在线 smoke 的严格语义。
    assert "full|install-contract" in gateway_source
    assert 'verify_mode="full"' in gateway_source
    assert 'if [[ "$verify_mode" == "install-contract" ]]' in gateway_source
    assert "RESEARCH_SHARED_HEALTH=NOT_REQUIRED" in gateway_source
    assert "RESEARCH_GATEWAY_VERIFY=FAIL" in gateway_source
    assert 'VERIFY_PICOTOOPET_RESEARCH_2_3_27_1.command" --mode install-contract' in installer_source
    assert 'verify_mode="full"' in integrated_source
    assert 'VERIFY_RESEARCH_GATEWAY.command" --mode "$verify_mode"' in integrated_source
