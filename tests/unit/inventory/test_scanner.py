import os
from pathlib import Path

from picotoopet_core.inventory.scanner import InventoryScanner


def test_scanner_is_deterministic_and_does_not_mutate_sources(tmp_path: Path) -> None:
    """盘点只读取源文件，且相同输入生成相同文件清单。"""

    source = tmp_path / "source"
    source.mkdir()
    first = source / "a.txt"
    second = source / "nested" / "b.bin"
    second.parent.mkdir()
    first.write_text("alpha", encoding="utf-8")
    second.write_bytes(b"beta")
    before = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in (first, second)}

    scanner = InventoryScanner()
    one = scanner.scan_tree(source)
    two = scanner.scan_tree(source)

    assert one == two
    assert [item.relative_path for item in one.files] == ["a.txt", "nested/b.bin"]
    assert all(item.sha256 for item in one.files)
    after = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in (first, second)}
    assert after == before


def test_environment_inventory_redacts_secret_values(monkeypatch) -> None:
    """环境盘点只能记录敏感变量是否存在，不能记录其值。"""

    monkeypatch.setenv("PICOTOO_API_TOKEN", "super-secret-value")
    monkeypatch.setenv("PICOTOO_MODE", "test")

    environment = InventoryScanner().scan_environment(
        names=["PICOTOO_API_TOKEN", "PICOTOO_MODE", "MISSING_VALUE"]
    )

    assert environment["PICOTOO_API_TOKEN"] == "***PRESENT_REDACTED***"
    assert environment["PICOTOO_MODE"] == "test"
    assert environment["MISSING_VALUE"] is None
    assert "super-secret-value" not in str(environment)
