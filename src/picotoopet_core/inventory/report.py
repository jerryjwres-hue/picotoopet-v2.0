"""Phase 0 JSON 与 Markdown 报告生成。"""

from __future__ import annotations

import json
from pathlib import Path

from .scanner import FileInventory


def write_inventory_reports(
    inventory: FileInventory,
    *,
    json_path: Path | str,
    markdown_path: Path | str,
) -> None:
    """把确定性清单写入 V2 Workspace。"""

    json_output = Path(json_path)
    md_output   = Path(markdown_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    md_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(inventory.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    lines = [
        f"# {inventory.root_name} 只读盘点",
        "",
        f"- 文件数：{inventory.file_count}",
        f"- 总字节数：{inventory.total_bytes}",
        "",
        "| 相对路径 | 字节 | SHA-256 |",
        "|---|---:|---|",
    ]
    lines.extend(
        f"| `{item.relative_path}` | {item.size_bytes} | `{item.sha256}` |"
        for item in inventory.files
    )
    md_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
