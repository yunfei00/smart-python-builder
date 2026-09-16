from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from analyzer.models import ProjectAnalysis
from .models import BuildPlan


@dataclass(frozen=True)
class RepairRule:
    action: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class KnownError:
    pattern: str
    repair: RepairRule


@dataclass(frozen=True)
class BuildProfile:
    name: str
    imports: tuple[str, ...]
    package: str | None
    app_type: str = 'console'
    hidden_imports: tuple[str, ...] = ()
    collect_all: tuple[str, ...] = ()
    data_files: tuple[tuple[str, str], ...] = ()
    pyinstaller_args: tuple[str, ...] = ()
    known_errors: tuple[KnownError, ...] = ()


PROFILES = (
    BuildProfile('requests', ('requests',), 'requests'),
    BuildProfile('numpy', ('numpy',), 'numpy'),
    BuildProfile('pandas', ('pandas',), 'pandas'),
    BuildProfile('openpyxl', ('openpyxl',), 'openpyxl'),
    BuildProfile('PySide6', ('PySide6',), 'PySide6', 'gui', hidden_imports=('PySide6.QtCore',)),
    BuildProfile('PyQt6', ('PyQt6',), 'PyQt6', 'gui', hidden_imports=('PyQt6.QtCore',)),
    BuildProfile('tkinter', ('tkinter',), None, 'gui'),
    BuildProfile('opencv-python', ('cv2',), 'opencv-python'),
    BuildProfile('Pillow', ('PIL',), 'Pillow', hidden_imports=('PIL.Image',)),
    BuildProfile('pyserial', ('serial',), 'pyserial'),
    BuildProfile('PyYAML', ('yaml',), 'PyYAML'),
)

PROFILES = tuple(replace(profile, known_errors=(KnownError(
    f"No module named '{profile.imports[0]}'",
    RepairRule('add_dependencies' if profile.package else 'hidden_imports',
               (profile.package or profile.imports[0],)),
),)) for profile in PROFILES)


class ExperienceEngine:
    def __init__(self, profiles=PROFILES, store=None):
        self.profiles = profiles
        self.store = store

    def diagnose(self, error: str) -> list[RepairRule]:
        return [known.repair for profile in self.profiles for known in profile.known_errors if known.pattern in error]

    def plan(self, analysis: ProjectAnalysis, entry: Path, *, windowed=None, mode='onefile') -> BuildPlan:
        plan = BuildPlan(str(entry.relative_to(analysis.project_root)), list(analysis.packages), analysis.dependency_source, mode=mode)
        plan.decision_sources = {'entry_point': 'analysis/user selection', 'dependencies': analysis.dependency_source, 'mode': 'user/default'}
        for profile in self.profiles:
            if not set(profile.imports) & analysis.imports:
                continue
            plan.matched_experiences.append(profile.name)
            if profile.app_type == 'gui':
                plan.app_type = 'gui'
                plan.decision_sources['app_type'] = profile.name
            plan.hidden_imports.extend(profile.hidden_imports)
            plan.collect_all.extend(profile.collect_all)
            plan.data_files.extend([list(item) for item in profile.data_files])
            plan.pyinstaller_args.extend(profile.pyinstaller_args)
        if windowed is not None:
            plan.app_type = 'gui' if windowed else 'console'
            plan.decision_sources['app_type'] = 'user'
        return self.store.apply(analysis, plan) if self.store else plan
