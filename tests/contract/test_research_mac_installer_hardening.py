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


def test_worker_installer_preserves_real_mac_startup_diagnostics() -> None:
    source = _read(WORKER_INSTALLER)

    # 实机候选进程失败必须可诊断：提前退出立即暴露 stderr，慢启动给足窗口，
    # cleanup 前把临时 stdout/stderr 固化到 reports。
    assert "wait_for_candidate_health()" in source
    assert 'wait_for_candidate_health "$candidate_url" 240' in source
    assert "候选 Worker 进程在 health ready 前已退出" in source
    assert "candidate.stderr.log" in source
    assert "candidate_stdout_report" in source
    assert "candidate_stderr_report" in source


def test_worker_installer_quiesces_previous_worker_before_candidate_health() -> None:
    source = _read(WORKER_INSTALLER)

    # 实机旧 Worker 可能已经制造大量 loopback TIME_WAIT。候选验证前必须先卸载旧 Worker，
    # 但要在 wheel 安装完成后再暂停以缩短停机窗口；任何失败仍由 rollback 恢复旧定义。
    pip_install = source.index('"$new_version/.venv/bin/python" -m pip install')
    quiesce = source.index(
        "stop_worker_agent",
        source.index('if [[ "$installed_product_version" != "$product_version" ]]'),
    )
    candidate = source.index('candidate_root="$(mktemp -d ')
    health = source.index('wait_for_candidate_health "$candidate_url" 240')
    activation = source.index('atomic_switch_current "$runtime_root" "$new_version"')

    assert pip_install < quiesce < candidate < health < activation
    assert "restore_previous_worker_definition || true" in source
    assert 'launchctl bootstrap "gui/$UID" "$plist"' in source
    assert 'launchctl kickstart -k "gui/$UID/$(worker_label)"' in source


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


def test_worker_loopback_checks_ignore_user_proxy_environment() -> None:
    installer = _read(WORKER_INSTALLER)
    worker_lib = _read(REPO_ROOT / "deploy/macos/phase23-worker/worker-lib.sh")
    core_lib = _read(REPO_ROOT / "deploy/macos/phase23/lib.sh")

    # 所有安装/验证期 loopback HTTP 必须绕过用户 HTTP(S)/ALL_PROXY。
    assert "ProxyHandler({})" in installer
    assert worker_lib.count("ProxyHandler({})") >= 2
    assert core_lib.count("ProxyHandler({})") >= 3
