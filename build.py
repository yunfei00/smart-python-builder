from __future__ import annotations

import argparse
from pathlib import Path

from builder import BuildEngine, BuildRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Python file into a Windows EXE using uv + PyInstaller")
    parser.add_argument("source", type=Path, help="Python entry file")
    parser.add_argument("--package", action="append", default=[], help="PyPI package dependency; repeat as needed")
    parser.add_argument("--windowed", action="store_true", help="Build a GUI application without a console")
    parser.add_argument("--name", help="Output application name")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    args = parser.parse_args()

    result = BuildEngine(args.workspace).build(
        BuildRequest(
            source=args.source,
            packages=args.package,
            windowed=args.windowed,
            app_name=args.name,
        )
    )

    print(f"Build ID : {result.build_id}")
    print(f"Workspace: {result.workspace}")
    print(f"Log      : {result.log_file}")
    if result.success:
        print(f"SUCCESS  : {result.artifact}")
        return 0
    print(f"FAILED   : {result.error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
