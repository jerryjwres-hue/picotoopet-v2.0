"""Mac install + Keychain Worker HMAC pairing is optional and non-authorizing."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from picotoopet_core.config import loader

_ROOT = Path(__file__).resolve().parents[2]
_INSTALL = _ROOT / "scripts" / "mac" / "INSTALL_MAC.command"
_SHOW = _ROOT / "scripts" / "mac" / "SHOW_WORKER_PAIRING.command"
_SECRET = "u" * 43


@pytest.fixture
def pairing_env(monkeypatch, tmp_path):
    # 合成测试用随机目录和明确设备令牌，不接触真实系统 Keychain。
    monkeypatch.setenv("PICOTOO_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("PICOTOO_API_TOKEN", "api-test-" + "a" * 43)
    monkeypatch.delenv("PICOTOO_WORKER_ATTEST_ID", raising=False)
    monkeypatch.delenv("PICOTOO_WORKER_ATTEST_KEY", raising=False)


def test_keychain_pairing_defaults_to_disabled_and_never_enables_gpu(
    pairing_env, monkeypatch,
):
    monkeypatch.setattr(loader, "read_worker_attestation_key_from_keychain", lambda: None)
    settings = loader.load_settings()
    assert settings.worker_attestation_id is None
    assert settings.worker_attestation_key is None
    assert settings.scoped_gpu_admission_enabled is False


def test_mac_keychain_secret_is_bound_to_same_windows_worker_id(pairing_env, monkeypatch):
    monkeypatch.setattr(loader, "read_worker_attestation_key_from_keychain", lambda: _SECRET)
    settings = loader.load_settings()
    assert settings.worker_attestation_id == "edit-workstation"
    assert settings.worker_attestation_key == _SECRET
    assert settings.scoped_gpu_admission_enabled is False
    assert _SECRET not in str(settings.redacted_dict())
    assert settings.redacted_dict()["worker_attestation_key"] == "***REDACTED***"


def test_complete_environment_pair_has_priority_over_keychain(pairing_env, monkeypatch):
    def inaccessible_keychain():
        raise AssertionError("显式提供 Worker ID/Key 时不得触碰 Keychain")

    monkeypatch.setattr(loader, "read_worker_attestation_key_from_keychain", inaccessible_keychain)
    monkeypatch.setenv("PICOTOO_WORKER_ATTEST_ID", "dedicated-worker")
    monkeypatch.setenv("PICOTOO_WORKER_ATTEST_KEY", "v" * 43)
    settings = loader.load_settings()
    assert settings.worker_attestation_id == "dedicated-worker"
    assert settings.worker_attestation_key == "v" * 43
    assert settings.scoped_gpu_admission_enabled is False


@pytest.mark.parametrize("missing", ["id", "key"])
def test_partial_environment_pair_does_not_fall_back_to_keychain(
    pairing_env, monkeypatch, missing,
):
    monkeypatch.setattr(loader, "read_worker_attestation_key_from_keychain", lambda: _SECRET)
    if missing == "id":
        monkeypatch.setenv("PICOTOO_WORKER_ATTEST_KEY", _SECRET)
    else:
        monkeypatch.setenv("PICOTOO_WORKER_ATTEST_ID", "edit-workstation")
    with pytest.raises(ValidationError, match="WORKER_ATTESTATION_ID_AND_KEY_REQUIRED_TOGETHER"):
        loader.load_settings()


def test_mac_installer_provisions_keychain_once_without_creating_gpu_approval():
    text = _INSTALL.read_text(encoding="utf-8")
    assert 'WORKER_SERVICE="PicotooPetV3.WorkerAttestation"' in text
    assert 'security find-generic-password -a "$USER" -s "$WORKER_SERVICE"' in text
    assert 'security add-generic-password -a "$USER" -s "$WORKER_SERVICE"' in text
    assert 'openssl rand -base64 32' in text
    assert 'unset WORKER_KEY' in text
    assert "PICOTOO_SCOPED_GPU_ADMISSION=1" not in text
    assert 'export PICOTOO_WORKER_ATTEST_KEY' not in text


def test_installer_hmac_base64url_does_not_remove_letter_n(tmp_path):
    """原样执行安装器的密钥生成行，确保只去掉 '=' 而不会破坏随机 n 字符。"""
    shell = shutil.which("bash")
    if shell is None:
        pytest.skip("Bash not available")
    line = next(
        line for line in _INSTALL.read_text(encoding="utf-8").splitlines()
        if 'WORKER_KEY="$(' in line
    )
    # 用固定的测试假数据取代 openssl，而不调用用户 Mac Keychain。
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_openssl = fake_bin / "openssl"
    fake_openssl.write_text(
        "#!/bin/bash\\n"
        "printf '%s\\\\n' 'n" + "A" * 42 + "='\\n",
        encoding="utf-8",
    )
    fake_openssl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    run = subprocess.run(
        [shell, "-c", line + "\\nprintf '%s' \\"$WORKER_KEY\\""],
        capture_output=True, text=True, check=False, env=env, timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "n" + "A" * 42
    assert len(run.stdout) == 43


def test_pairing_viewer_is_executable_and_only_reads_existing_keychain_secret():
    content = _SHOW.read_text(encoding="utf-8")
    assert content.startswith("#!/bin/bash")
    assert os.access(_SHOW, os.X_OK) if os.name == "posix" else True
    assert 'WORKER_ID=edit-workstation' not in content  # 显示项不是 Shell 环境配置。
    assert "Worker ID: edit-workstation" in content
    assert "find-generic-password" in content
    assert "add-generic-password" not in content
    assert "curl " not in content
    assert "PICOTOO_SCOPED_GPU_ADMISSION" not in content

    shell = shutil.which("bash")
    if shell is None:
        pytest.skip("Bash not available")
    for script in (_SHOW, _INSTALL):
        checked = subprocess.run(
            [shell, "-n", str(script)],
            check=False, capture_output=True, text=True, timeout=10,
        )
        assert checked.returncode == 0, checked.stderr


def test_pairing_viewer_shows_secret_only_when_explicitly_launched(tmp_path, monkeypatch):
    # 只替换 security 命令，完全不修改/读取 macOS 真实 Keychain。
    shell = shutil.which("bash")
    if shell is None:
        pytest.skip("Bash not available")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_security = fake_bin / "security"
    fake_security.write_text(
        "#!/bin/bash\n"
        "if [ \"$1\" = \"find-generic-password\" ]; then printf '%s\\n' " + repr(_SECRET) + "; exit 0; fi\n"
        "exit 3\n",
        encoding="utf-8",
    )
    fake_security.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    completed = subprocess.run(
        [shell, str(_SHOW)],
        input="\n", text=True, capture_output=True, env=env,
        check=False, timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Worker ID: edit-workstation" in completed.stdout
    assert _SECRET in completed.stdout
    assert "GPU" in completed.stdout
    assert not list(tmp_path.rglob("*.log"))
