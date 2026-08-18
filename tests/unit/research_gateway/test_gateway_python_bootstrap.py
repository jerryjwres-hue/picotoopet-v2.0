"""Research Gateway 在旧 macOS 系统 Python 下的 adapter 私有解释器 bootstrap。"""

from __future__ import annotations

import os
from pathlib import Path

from research_gateway import gateway

ROOT = Path(__file__).resolve().parents[3]
GATEWAY_SOURCE = ROOT / "research_gateway" / "gateway.py"


def test_old_python_resolves_only_adapter_private_compatible_runtime(tmp_path: Path) -> None:
    adapter_root = tmp_path / "crawl4ai"
    private_python = adapter_root / "venv" / "bin" / "python"
    private_python.parent.mkdir(parents=True)
    private_python.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    private_python.chmod(0o755)
    candidate = gateway._adapter_bootstrap_python(version_info=(3, 9), environ={"PICOTOOPET_CRAWL4AI_ROOT": str(adapter_root)}, home=tmp_path / "home")
    assert candidate == private_python


def test_supported_python_does_not_reexec_even_when_private_runtime_exists(tmp_path: Path) -> None:
    adapter_root = tmp_path / "crawl4ai"
    private_python = adapter_root / "venv" / "bin" / "python"
    private_python.parent.mkdir(parents=True)
    private_python.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    private_python.chmod(0o755)
    candidate = gateway._adapter_bootstrap_python(version_info=(3, 13), environ={"PICOTOOPET_CRAWL4AI_ROOT": str(adapter_root)}, home=tmp_path / "home")
    assert candidate is None


def test_bootstrap_runs_before_python312_only_runtime_imports() -> None:
    source = GATEWAY_SOURCE.read_text(encoding="utf-8")
    bootstrap_call = source.index("_bootstrap_adapter_python()")
    dataclass_import = source.index("from dataclasses import")
    crawler_import = source.index("from research_gateway.crawler_adapter import")
    assert bootstrap_call < dataclass_import
    assert bootstrap_call < crawler_import
    assert "os.execv" in source[:dataclass_import]
    assert "PICOTOOPET_CRAWL4AI_ROOT" in source[:dataclass_import]


def test_bootstrap_default_path_is_fixed_under_user_home(tmp_path: Path) -> None:
    private_python = tmp_path / ".local" / "share" / "picotoopet" / "research" / "crawl4ai" / "venv" / "bin" / "python"
    private_python.parent.mkdir(parents=True)
    private_python.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    private_python.chmod(0o755)
    candidate = gateway._adapter_bootstrap_python(version_info=(3, 9), environ={}, home=tmp_path)
    assert candidate == private_python
    assert os.access(candidate, os.X_OK)
