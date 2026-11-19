"""CLI interface for QC tool: python -m qc check ..."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from qc.checker import ShotChecker
from qc.spec import ShotSpec

logger = logging.getLogger("qc.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qc",
        description="Auto Quality Control (QC) for Alaskan Malamute Maotai Animation Production.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    check_parser = subparsers.add_parser("check", help="Run QC check on a shot image or video")
    check_parser.add_argument("--spec", required=True, type=str, help="Path to shot_spec.json")
    check_parser.add_argument("--media", required=True, type=str, help="Path to target image or video to inspect")
    check_parser.add_argument("--prev", required=False, type=str, default=None, help="Path to previous shot video (for cross-shot jump check)")
    check_parser.add_argument("--out", required=False, type=str, default="report.json", help="Path to output report.json")
    check_parser.add_argument("--out-jpg", required=False, type=str, default=None, help="Path to output visual collage report.jpg")
    check_parser.add_argument("--use-florence", action="store_true", help="Force using Florence-2 if weights available")
    check_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")

    return parser


def main(args: list[str] | None = None) -> int:
    """CLI entry point returning exit code (0=pass, 1=fail, 2=program error)."""
    parser = build_parser()
    parsed = parser.parse_args(args)

    log_level = logging.DEBUG if getattr(parsed, "verbose", False) else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not parsed.subcommand:
        parser.print_help()
        return 2

    if parsed.subcommand == "check":
        try:
            spec_path = Path(parsed.spec)
            if not spec_path.is_file():
                sys.stderr.write(f"Error: Spec file not found: {parsed.spec}\n")
                return 2

            media_path = Path(parsed.media)
            if not media_path.is_file():
                sys.stderr.write(f"Error: Media file not found: {parsed.media}\n")
                return 2

            spec = ShotSpec.from_file(spec_path)
            checker = ShotChecker(spec=spec, use_florence=parsed.use_florence)
            report_data, exit_code = checker.run_check(
                media_path=media_path,
                prev_media_path=parsed.prev,
                out_json_path=parsed.out,
                out_jpg_path=parsed.out_jpg,
            )

            status_str = "PASS" if exit_code == 0 else "FAIL"
            print(f"[QC {spec.shot_id}] Result: {status_str} | Score: {report_data.get('score', 0)}/100")
            if report_data.get("fails"):
                print("Failed checks:")
                for f in report_data["fails"]:
                    frame_info = f" (frame {f['frame']})" if f.get("frame") is not None else ""
                    print(f"  - [{f['check']}]{frame_info}: {f['detail']}")
            if report_data.get("warnings"):
                print("Warnings:")
                for w in report_data["warnings"]:
                    frame_info = f" (frame {w['frame']})" if w.get("frame") is not None else ""
                    print(f"  - [{w['check']}]{frame_info}: {w['detail']}")

            print(f"Report written to: {parsed.out}")
            if "report_jpg" in report_data:
                print(f"Collage saved to: {report_data['report_jpg']}")

            return exit_code

        except Exception as exc:
            sys.stderr.write(f"Program Error: {exc}\n")
            import traceback
            traceback.print_exc()
            return 2

    return 2


if __name__ == "__main__":
    sys.exit(main())
