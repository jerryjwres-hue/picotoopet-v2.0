"""CLI interface for editing tool: python -m edit assemble ..."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from edit.production import assemble_cut

logger = logging.getLogger("edit.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edit",
        description="Assemble multi-shot edit plans.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    assemble_parser = subparsers.add_parser(
        "assemble", help="Assemble multi-shot edit plan into finished video"
    )
    assemble_parser.add_argument("--plan", required=True, type=str, help="Path to edit_plan.json")
    assemble_parser.add_argument(
        "--out", required=False, type=str, default="final.mp4", help="Path to output final.mp4"
    )
    assemble_parser.add_argument(
        "--edl", required=False, type=str, default=None, help="Path to output edl.txt"
    )
    assemble_parser.add_argument(
        "--strip", required=False, type=str, default=None, help="Path to output strip.jpg"
    )
    assemble_parser.add_argument(
        "--root", help="Override the asset root of a cut_v2 production plan"
    )
    assemble_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

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

            data = json.loads(plan_path.read_text(encoding="utf-8"))
            if parsed.root or "root" in data:
                root = Path(parsed.root or data["root"])
                if not root.is_absolute():
                    root = plan_path.resolve().parent / root
                if not root.is_dir():
                    raise ValueError(
                        "Asset root is missing. Use --root to point to the local media."
                    )
                root = root.resolve()

                def resolve_asset(ref):
                    path = (root / ref).resolve()
                    if not path.is_relative_to(root):
                        raise ValueError("Media is outside the selected project root")
                    return path

                out = Path(parsed.out)
                rows = assemble_cut(
                    data,
                    out,
                    resolve=resolve_asset,
                    edl=parsed.edl or out.with_name("edl.txt"),
                    strip=parsed.strip,
                )
                print(f"Rendered {len(rows)} shots to {out}")
                return 0

            from edit.assembler import assemble_video_pipeline
            from edit.plan import EditPlan

            plan = EditPlan.model_validate(data)
            print(
                f"[Edit Assemble] Assembling {len(plan.shots)} shots at {plan.fps} fps "
                f"({plan.size[0]}x{plan.size[1]})..."
            )

            result = assemble_video_pipeline(
                plan=plan,
                out_video_path=parsed.out,
                out_edl_path=parsed.edl,
                out_strip_path=parsed.strip,
            )

            print("Assembly completed successfully!")
            print(
                f"  Final Video : {result['final_video']} ({result['total_duration_sec']}s, "
                f"{result['total_frames']} frames)"
            )
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
