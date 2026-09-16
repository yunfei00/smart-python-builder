from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyzer import ProjectAnalysis, analyze_project

from .engine import BuildEngine, BuildRequest, BuildResult


@dataclass(slots=True)
class SmartBuildResult:
    analysis: ProjectAnalysis
    build: BuildResult


class EntryPointRequired(ValueError):
    def __init__(self, analysis: ProjectAnalysis):
        self.analysis = analysis
        candidates = ", ".join(str(p.relative_to(analysis.project_root)) for p in analysis.entry_candidates)
        detail = candidates or "no conventional entry candidates"
        super().__init__(f"Entry point must be selected: {detail}")


class SmartBuilder:
    """Analyze an uploaded source and feed deterministic results into BuildEngine."""

    def __init__(self, workspace_root: Path | str = "workspace", timeout: int = 900):
        self.engine = BuildEngine(workspace_root, timeout)

    def build(
        self,
        source: Path | str,
        *,
        entry_point: Path | str | None = None,
        windowed: bool = False,
        app_name: str | None = None,
    ) -> SmartBuildResult:
        analysis = analyze_project(source)
        selected_entry = self._select_entry(analysis, entry_point)
        result = self.engine.build(
            BuildRequest(
                source=analysis.source,
                packages=analysis.packages,
                windowed=windowed,
                app_name=app_name,
                entry_point=selected_entry,
            )
        )
        return SmartBuildResult(analysis, result)

    @staticmethod
    def _select_entry(analysis: ProjectAnalysis, entry_point: Path | str | None) -> Path:
        if entry_point is None:
            if analysis.entry_point is None:
                raise EntryPointRequired(analysis)
            return analysis.entry_point

        candidate = Path(entry_point)
        if not candidate.is_absolute():
            candidate = analysis.project_root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(analysis.project_root)
        except ValueError as exc:
            raise ValueError("Selected entry point must be inside the project") from exc
        if candidate not in analysis.python_files:
            raise ValueError("Selected entry point is not an analyzed Python file")
        return candidate
