"""CLI interface for editing tool: python -m edit assemble ..."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from edit.assembler import assemble_video_pipeline
from edit.plan import EditPlan

logger = logging.getLogger("edit.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edit",
        description="Auto Assemble and Editing Tool for Alaskan Malamute Maotai Animation Production.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    assemble_parser = subparsers.add_parser("assemble", help="Assemble multi-shot edit plan into finished video")
    assemble_parser.add_argument("--plan", required=True, type=str, help="Path to edit_plan.json")
    assemble_parser.add_argument("--out", required=False, type=str, default="final.mp4", help="Path to output final.mp4")
    assemble_parser.add_argument("--edl", required=False, type=str, default=None, help="Path to output edl.txt")
    assemble_parser.add_argument("--strip", required=False, type=str, default=None, help="Path to output strip.jpg")
    assemble_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    return parser


def main(args: list[str] | None = None) -> int:
    """CLI entrypoint returning exit code 0 on success, non-zero on failure."""
    parser = build_parser()
    parsed = parser.parse_args(args)

    log_level = logging.DEBUG if getattr(parsed, "verbose", False) else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not parsed.subcommand:
        parser.print_help()
        return 2

    if parsed.subcommand == "assemble":
        try:
            plan_path = Path(parsed.plan)
            if not plan_path.is_file():
                sys.stderr.write(f"Error: Plan file not found: {parsed.plan}\n")
                return 2

            plan = EditPlan.from_file(plan_path)
            print(f"[Edit Assemble] Assembling {len(plan.shots)} shots at {plan.fps} fps ({plan.size[0]}x{plan.size[1]})...")

            result = assemble_video_pipeline(
                plan=plan,
                out_video_path=parsed.out,
                out_edl_path=parsed.edl,
                out_strip_path=parsed.strip,
            )

            print(f"Assembly completed successfully!")
            print(f"  Final Video : {result['final_video']} ({result['total_duration_sec']}s, {result['total_frames']} frames)")
            print(f"  EDL List    : {result['edl_file']}")
            print(f"  Filmstrip   : {result['strip_image']}")
            return 0

        except Exception as exc:
            sys.stderr.write(f"Assembly Error: {exc}\n")
            import traceback
            traceback.print_exc()
            return 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
