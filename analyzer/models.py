from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ProjectAnalysis:
    source: Path
    project_root: Path
    python_files: list[Path]
    entry_point: Path | None
    entry_candidates: list[Path] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)
    stdlib_imports: set[str] = field(default_factory=set)
    internal_imports: set[str] = field(default_factory=set)
    third_party_imports: set[str] = field(default_factory=set)
    packages: list[str] = field(default_factory=list)
    dependency_source: str = "ast"
    warnings: list[str] = field(default_factory=list)

    @property
    def entry_is_ambiguous(self) -> bool:
        return self.entry_point is None and len(self.entry_candidates) > 1
