import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "windows" / "bootstrap"


def test_visual_model_manifest_is_frozen_and_hash_pinned() -> None:
    """主视频生成与编辑模型必须精确固定文件、来源、目录和 SHA-256。"""

    manifest = json.loads((BOOTSTRAP / "model_manifest.json").read_text(encoding="utf-8"))
    by_name = {item["filename"]: item for item in manifest["models"]}

    assert manifest["hf_cli_version"] == "1.24.0"

    assert set(by_name) == {
        "wan2.2_ti2v_5B_fp16.safetensors",
        "wan2.1_vace_1.3B_fp16.safetensors",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "wan2.2_vae.safetensors",
        "wan_2.1_vae.safetensors",
    }
    assert by_name["wan2.2_ti2v_5B_fp16.safetensors"]["destination"] == "diffusion_models"
    assert by_name["wan2.1_vace_1.3B_fp16.safetensors"]["destination"] == "diffusion_models"
    assert by_name["umt5_xxl_fp8_e4m3fn_scaled.safetensors"]["destination"] == "text_encoders"
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in by_name.values())
    assert not any("gpt-oss" in str(item).lower() for item in manifest["models"])
    assert not any("8b" in item["filename"].lower() for item in manifest["models"])


def test_detection_and_configuration_protect_desktop_resources() -> None:
    """脚本必须识别用户路径，但禁止把 Desktop resources 目录当作可修改仓库。"""

    detection = (BOOTSTRAP / "Detect-ComfyEnvironment.ps1").read_text(encoding="utf-8")
    configure = (BOOTSTRAP / "Configure-ComfyPaths.ps1").read_text(encoding="utf-8")

    assert r"C:\zhaoyang lin\opc\Comfy Desktop" in detection
    assert "resources\\ComfyUI" in detection
    assert "ReadOnlyDesktopResource" in detection
    assert "config.json" in detection
    assert "basePath" in detection
    assert "extra_models_config.yaml" in configure
    assert "$env:APPDATA" in configure
    assert "Copy-Item" in configure
    assert "E:\\PicotooPet\\Models" in configure
    assert "resources\\ComfyUI" in configure
    assert "throw" in configure.lower()
    assert "[switch]$VerifyOnly" in configure
    assert configure.index("if ($VerifyOnly)") < configure.index("New-Item -ItemType Directory")


def test_model_installer_uses_staging_hash_quarantine_and_atomic_move() -> None:
    """模型必须先暂存、校验、隔离错误文件，再原子放入 E 盘。"""

    installer = (BOOTSTRAP / "Install-VisualModels.ps1").read_text(encoding="utf-8")

    assert "uvx" in installer
    assert "--from" in installer
    assert "hf==" in installer
    assert "huggingface_hub==" not in installer
    assert "huggingface_hub_version" in installer
    assert "hf" in installer
    assert "download" in installer
    assert "RedirectStandardOutput" in installer
    assert "RedirectStandardError" in installer
    assert "download-logs" in installer
    assert "HF_HUB_DOWNLOAD_TIMEOUT" in installer
    assert "Get-FileHash" in installer
    assert "Quarantine" in installer
    assert "Move-Item" in installer
    assert "HF_XET_HIGH_PERFORMANCE" in installer
    assert "--revision" in installer
    assert "$downloadComplete" in installer
    assert "hash_mismatch" in installer
    assert installer.index("if (-not $VerifyOnly)") < installer.index("New-Item -ItemType Directory -Path $modelRoot")
    assert "NewGuid" not in installer
    assert "main" not in json.loads((BOOTSTRAP / "model_manifest.json").read_text())["models"][0]["revision"]


def test_double_click_launcher_runs_hidden_and_generates_reports() -> None:
    """用户入口必须无终端，并由总控脚本生成 JSON/HTML 验证报告。"""

    launcher = (BOOTSTRAP / "RUN_WINDOWS_SETUP.vbs").read_text(encoding="utf-8")
    orchestrator = (BOOTSTRAP / "WindowsBootstrap.ps1").read_text(encoding="utf-8")

    assert ", 0, True" in launcher
    assert "Detect-ComfyEnvironment.ps1" in orchestrator
    assert "Configure-ComfyPaths.ps1" in orchestrator
    assert "-VerifyOnly:$VerifyOnly" in orchestrator
    assert "hash_mismatch" in orchestrator
    assert "Install-VisualModels.ps1" in orchestrator
    assert "windows_setup_report.json" in orchestrator
    assert "windows_setup_report.html" in orchestrator


def test_windows_powershell_scripts_have_utf8_bom() -> None:
    """Windows PowerShell 5.1 必须借助 UTF-8 BOM 正确解析中文源码。"""

    scripts = sorted(BOOTSTRAP.glob("*.ps1"))

    assert scripts
    for script in scripts:
        assert script.read_bytes().startswith(b"\xef\xbb\xbf"), script.name


def test_model_installer_does_not_treat_native_stderr_as_powershell_failure() -> None:
    """uvx 的正常 stderr 提示不得在 Windows PowerShell 5.1 下触发终止错误。"""

    installer = (BOOTSTRAP / "Install-VisualModels.ps1").read_text(encoding="utf-8")

    assert "Start-Process" in installer
    assert "-RedirectStandardOutput" in installer
    assert "-RedirectStandardError" in installer
    assert "2>&1" not in installer
    assert "NativeCommandError" in installer
