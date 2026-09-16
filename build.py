from __future__ import annotations

import argparse
from pathlib import Path

from builder import EntryPointRequired, SmartBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze and build a Python file/project into a Windows EXE")
    parser.add_argument("source", type=Path, help="Python .py file or project folder")
    parser.add_argument("--entry", type=Path, help="Project entry file, relative to project root")
    parser.add_argument("--windowed", action="store_true", help="Build a GUI application without a console")
    parser.add_argument("--name", help="Output application name")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    args = parser.parse_args()

    try:
        result = SmartBuilder(args.workspace).build(
            args.source,
            entry_point=args.entry,
            windowed=args.windowed,
            app_name=args.name,
        )
    except EntryPointRequired as exc:
        print(f"ENTRY REQUIRED: {exc}")
        return 2

    analysis = result.analysis
    build = result.build
    print(f"Dependencies ({analysis.dependency_source}): {', '.join(analysis.packages) or '(none)'}")
    print(f"Entry     : {analysis.entry_point or args.entry}")
    for warning in analysis.warnings:
        print(f"Warning   : {warning}")
    print(f"Build ID  : {build.build_id}")
    print(f"Workspace : {build.workspace}")
    print(f"Log       : {build.log_file}")
    if build.success:
        print(f"SUCCESS   : {build.artifact}")
        return 0
    print(f"FAILED    : {build.error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
