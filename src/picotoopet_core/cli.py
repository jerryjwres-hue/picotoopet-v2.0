"""Mac Core 命令行入口；由 launchd 和双击脚本调用。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from picotoopet_core.api.app import create_app
from picotoopet_core.config.loader import load_settings
from picotoopet_core.config.models import AppSettings
from picotoopet_core.domain.directing import (
    DirectorError,
    direct_episode,
    load_directions,
    write_directed_episode,
)
from picotoopet_core.domain.episode import EpisodeValidationError, load_episode
from picotoopet_core.health.supervisor import HealthSupervisor
from picotoopet_core.ollama.client import OllamaClient
from picotoopet_core.ollama.resident_manager import (
    ResidentManager,
    ResidentResult,
    ResidentStatus,
)
from picotoopet_core.services import build_services


class _HealthyResident:
    """仅供数据库/磁盘验证跳过 Ollama 时使用。"""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def ensure_resident(self) -> ResidentResult:
        """返回明确的跳过状态。"""

        return ResidentResult(
            status=ResidentStatus.RESIDENT,
            model_name=self.model_name,
            detail="本次健康检查按参数跳过 Ollama。",
        )


def _build_resident_manager(settings: AppSettings) -> ResidentManager:
    """构建独立 Ollama 常驻管理器，便于测试替换。"""

    client = OllamaClient(settings.ollama_base_url, timeout_seconds=10.0)
    return ResidentManager(client, settings.ollama_model)


def _parser() -> argparse.ArgumentParser:
    """创建稳定 CLI 契约。"""

    parser = argparse.ArgumentParser(prog="picotoopet-core")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("serve", help="启动 REST、WebSocket 和 OpenAPI 服务")

    health = commands.add_parser("health", help="执行一次本地健康检查")
    health.add_argument("--skip-ollama", action="store_true")

    resident = commands.add_parser("resident-check", help="检查并恢复 gpt-oss:20b 常驻")
    resident.add_argument("--json", action="store_true", default=True)

    supervise = commands.add_parser("supervise", help="持续执行健康监督")
    supervise.add_argument("--loop", action="store_true")
    episode = commands.add_parser("episode", help="检查或编译剧集文件")
    episode_commands = episode.add_subparsers(dest="episode_command", required=True)
    validate = episode_commands.add_parser("validate")
    validate.add_argument("file", type=Path)
    direct = episode_commands.add_parser("direct", help="离线编译明确填写的导演方向")
    direct.add_argument("file", type=Path)
    direct.add_argument("--directions", type=Path, required=True)
    direct_mode = direct.add_mutually_exclusive_group(required=True)
    direct_mode.add_argument("--output", type=Path, help="生成完整剧集 YAML 至新文件")
    direct_mode.add_argument("--preview", action="store_true", help="仅向 stdout 输出剧集 YAML")

    return parser


def _run_health(settings: AppSettings, *, skip_ollama: bool) -> int:
    """执行一次健康检查并输出 JSON。"""

    services = build_services(settings)
    try:
        resident = _HealthyResident(settings.ollama_model) if skip_ollama else services.resident
        report = HealthSupervisor(
            database=services.database,
            paths=settings.paths,
            resident=resident,
        ).run_once()
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        services.close()


def _run_resident_check(settings: AppSettings) -> int:
    """检查唯一核心模型；缺失时不自动下载。"""

    manager = _build_resident_manager(settings)
    try:
        result = manager.ensure_resident()
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        return 0 if result.status is ResidentStatus.RESIDENT else 3
    finally:
        client = getattr(manager, "client", None)
        if client is not None and hasattr(client, "close"):
            client.close()


def _run_supervisor(settings: AppSettings, *, loop: bool) -> int:
    """运行一次或按冻结间隔持续监督。"""

    while True:
        _run_health(settings, skip_ollama=False)
        if not loop:
            return 0
        time.sleep(settings.resident_check_seconds)


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数并返回进程退出码。"""

    arguments = _parser().parse_args(argv)
    if arguments.command == "episode":
        if arguments.episode_command == "direct":
            return _run_direct(arguments)
        try:
            episode = load_episode(arguments.file.read_bytes(), as_yaml=True)
        except (EpisodeValidationError, OSError) as exc:
            message = str(exc) if isinstance(exc, EpisodeValidationError) else "无法读取文件。"
            print(f"剧集校验失败：{message}", file=sys.stderr)
            return 2
        print(f"剧集 {episode.episode_id} 校验通过（{len(episode.shots)} 个分镜）。")
        return 0
    settings  = load_settings()
    if arguments.command == "serve":
        import uvicorn

        uvicorn.run(
            create_app(settings),
            host=settings.api_host,
            port=settings.api_port,
            log_level="info",
        )
        return 0
    if arguments.command == "health":
        return _run_health(settings, skip_ollama=arguments.skip_ollama)
    if arguments.command == "resident-check":
        return _run_resident_check(settings)
    if arguments.command == "supervise":
        return _run_supervisor(settings, loop=arguments.loop)
    raise AssertionError(f"未处理命令：{arguments.command}")


def _run_direct(arguments: argparse.Namespace) -> int:
    try:
        episode = load_episode(arguments.file.read_bytes(), as_yaml=True)
        directions = load_directions(arguments.directions.read_bytes())
        result = direct_episode(episode, directions)
        if arguments.preview:
            print(result, end="")
        else:
            write_directed_episode(
                arguments.output, result, (arguments.file, arguments.directions),
            )
            print(f"已离线编译 {len(directions.shots)} 个镜头。")
    except (DirectorError, EpisodeValidationError, OSError) as exc:
        print(f"导演编译失败：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - 控制台脚本入口
    raise SystemExit(main())
