"""为 Slice D CI 生成确定性的 Mac Core OpenAPI 文档。"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="picotoopet-openapi-") as temporary:
        settings = AppSettings(
            paths=RuntimePaths.from_root(Path(temporary) / "runtime"),
            api_token="00000000000000000000000000000000",
        )
        document = create_app(settings).openapi()

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
