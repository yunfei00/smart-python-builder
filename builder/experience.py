from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import ast

from analyzer.models import ProjectAnalysis
from .models import BuildPlan
from analyzer.project import IGNORED_DIRS


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
    BuildProfile('pyserial', ('serial',), 'pyserial', hidden_imports=('serial.urlhandler.protocol_loop', 'serial.urlhandler.protocol_socket', 'serial.urlhandler.protocol_rfc2217')),
    BuildProfile('PyYAML', ('yaml',), 'PyYAML'),
)

PROFILES = tuple(replace(profile, known_errors=(KnownError(
    f"No module named '{profile.imports[0]}'",
    RepairRule('add_dependencies' if profile.package else 'hidden_imports',
               (profile.package or profile.imports[0],)),
),)) for profile in PROFILES)


def _runtime_python_files(analysis: ProjectAnalysis) -> list[Path]:
    return [
        path for path in analysis.python_files
        if not {"tests", "test"} & set(path.relative_to(analysis.project_root).parts[:-1])
        and not path.name.startswith("test_")
        and not path.name.endswith("_test.py")
        and path.name != "conftest.py"
    ]


def _contains_sys_executable(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Attribute)
        and child.attr == "executable"
        and isinstance(child.value, ast.Name)
        and child.value.id == "sys"
        for child in ast.walk(node)
    )


def _discover_sidecar_files(analysis: ProjectAnalysis) -> list[list[str]]:
    """Find files that application code explicitly resolves beside sys.executable."""
    if not analysis.source.is_dir():
        return []

    names: set[str] = set()
    helper_parameters: dict[str, set[str]] = {}

    trees: list[ast.AST] = []
    for path in _runtime_python_files(analysis):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            continue
        trees.append(tree)

        for node in ast.walk(tree):
            # A conventional resource helper may be imported from another module
            # or resolve through an application_root helper. Only its actual
            # literal argument is a resource, never unrelated string constants.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'resource_path':
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    names.add(node.args[0].value)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                if _contains_sys_executable(node.left):
                    if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
                        names.add(node.right.value.strip())
                    elif isinstance(node.right, ast.Name):
                        parent = next(
                            (
                                fn for fn in ast.walk(tree)
                                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                                and node in list(ast.walk(fn))
                            ),
                            None,
                        )
                        if parent and node.right.id in {arg.arg for arg in parent.args.args}:
                            helper_parameters.setdefault(parent.name, set()).add(node.right.id)

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "joinpath" and _contains_sys_executable(node.func.value):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            names.add(arg.value.strip())

    if helper_parameters:
        for tree in trees:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                parameters = helper_parameters.get(node.func.id)
                if not parameters:
                    continue
                definition = next(
                    (
                        fn for fn in ast.walk(tree)
                        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and fn.name == node.func.id
                    ),
                    None,
                )
                if definition is None:
                    continue
                argument_names = [arg.arg for arg in definition.args.args]
                for index, arg in enumerate(node.args):
                    if index < len(argument_names) and argument_names[index] in parameters:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            names.add(arg.value.strip())

    result: list[list[str]] = []
    for value in sorted(name for name in names if name):
        candidate = Path(value.replace("\\", "/"))
        if not candidate.parts or candidate.is_absolute() or ":" in value or ".." in candidate.parts:
            continue
        source = analysis.project_root / candidate
        # BUILD_INFO.json is a supported generated sidecar. It is commonly
        # created by project-specific release scripts and may not exist in source.
        if source.is_symlink():
            continue
        relative = candidate
        if any(part in IGNORED_DIRS or part.startswith(".pytest-tmp") for part in relative.parts[:-1]):
            continue
        item = [relative.as_posix(), relative.parent.as_posix()]
        if item not in result:
            result.append(item)
    return result


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
        if analysis.source.is_dir():
            for path in analysis.project_root.rglob('*'):
                relative = path.relative_to(analysis.project_root)
                if any(part in IGNORED_DIRS | {'.github', 'tests', 'test'} or part.startswith('.pytest-tmp') for part in relative.parts[:-1]):
                    continue
                if path.is_file() and not path.is_symlink() and path.suffix.lower() in {'.json','.png','.jpg','.jpeg','.gif','.ico','.csv','.yaml','.yml','.ui','.qss','.xlsx','.xls'}:
                    item = [str(relative), str(relative.parent)]
                    if item not in plan.data_files:
                        plan.data_files.append(item)
            sidecars = _discover_sidecar_files(analysis)
            for item in sidecars:
                if item[0] == 'BUILD_INFO.json' and not (analysis.project_root / item[0]).exists():
                    plan.generated_sidecars.append(item)
                    continue
                if item not in plan.sidecar_files:
                    plan.sidecar_files.append(item)
                if item not in plan.data_files:
                    plan.data_files.append(item)
            if plan.data_files:
                plan.decision_sources['data_files'] = 'project resource files'
            if plan.sidecar_files:
                plan.decision_sources['sidecar_files'] = 'sys.executable-relative project resources'
            if plan.generated_sidecars:
                plan.decision_sources['generated_sidecars'] = 'Builder-generated runtime metadata'
        return self.store.apply(analysis, plan) if self.store else plan
