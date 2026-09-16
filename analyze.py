from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyzer import analyze_project


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a Python file or project before building")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    result = analyze_project(args.source)
    payload = {
        "source": str(result.source),
        "project_root": str(result.project_root),
        "python_files": [str(p.relative_to(result.project_root)) for p in result.python_files],
        "entry_point": str(result.entry_point.relative_to(result.project_root)) if result.entry_point else None,
        "entry_candidates": [str(p.relative_to(result.project_root)) for p in result.entry_candidates],
        "stdlib_imports": sorted(result.stdlib_imports),
        "internal_imports": sorted(result.internal_imports),
        "third_party_imports": sorted(result.third_party_imports),
        "packages": result.packages,
        "dependency_source": result.dependency_source,
        "warnings": result.warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
