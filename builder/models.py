from __future__ import annotations

import json
import re
from pathlib import Path
from dataclasses import asdict, dataclass, field


@dataclass
class BuildPlan:
    entry_point: str
    dependencies: list[str] = field(default_factory=list)
    dependency_source: str = 'ast'
    app_type: str = 'console'
    mode: str = 'onefile'
    hidden_imports: list[str] = field(default_factory=list)
    collect_all: list[str] = field(default_factory=list)
    data_files: list[list[str]] = field(default_factory=list)
    sidecar_files: list[list[str]] = field(default_factory=list)
    pyinstaller_args: list[str] = field(default_factory=list)
    matched_experiences: list[str] = field(default_factory=list)
    decision_sources: dict[str, str] = field(default_factory=dict)

    def validate(self, root: Path):
        if self.mode not in {'onefile', 'onedir'} or self.app_type not in {'gui', 'console'}:
            raise ValueError('Invalid build mode/application type')
        root = root.resolve()
        def inside(value):
            path = Path(value)
            if path.is_absolute() or ':' in value or not (root / path).resolve().is_relative_to(root):
                raise ValueError('Build Plan path must stay inside project')
            return root / path
        entry = inside(self.entry_point)
        if entry.suffix != '.py' or not entry.is_file():
            raise ValueError('Invalid entry point')
        for dependency in self.dependencies:
            registry = re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.\-\[\],<>=!~;\s\'"()*+]*', dependency)
            vcs = re.fullmatch(
                r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?\s*@\s*'
                r'git\+https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?'
                r'(?:@[A-Za-z0-9][A-Za-z0-9._/-]{0,199})?',
                dependency,
            )
            if not registry and not vcs:
                raise ValueError('Only package requirements or public GitHub git+https dependencies are allowed')
        for module in self.hidden_imports + self.collect_all:
            if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module):
                raise ValueError('Invalid module name')
        for source, destination in self.data_files + self.sidecar_files:
            if not inside(source).exists():
                raise ValueError('Resource does not exist')
            inside(destination)
        allowed = {'--noupx', '--debug=imports', '--debug=all', '--log-level=DEBUG', '--log-level=INFO', '--optimize=0', '--optimize=1', '--optimize=2'}
        if any(arg not in allowed for arg in self.pyinstaller_args):
            raise ValueError('Unsupported PyInstaller argument')

    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
