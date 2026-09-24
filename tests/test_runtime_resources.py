import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from analyzer import analyze_project
from builder.engine import BuildEngine, BuildRequest
from builder.experience import ExperienceEngine
from builder.models import BuildPlan


def resource_project(root):
    root.mkdir()
    (root / 'main.py').write_text('''import sys
from pathlib import Path
def resource_path(name):
    return Path(sys.executable).resolve().parent / name
VERSION = resource_path('VERSION')
INFO = resource_path('BUILD_INFO.json')
UNRELATED = 'main.py'
''')
    (root / 'VERSION').write_text('0.2.0-dev\n')
    analysis = analyze_project(root)
    return ExperienceEngine().plan(analysis, analysis.entry_point)


def test_source_and_generated_resources_have_separate_validation(tmp_path):
    source = tmp_path / 'source'
    plan = resource_project(source)
    assert plan.sidecar_files == [['VERSION', '.']]
    assert plan.generated_sidecars == [['BUILD_INFO.json', '.']]
    assert ['main.py', '.'] not in plan.data_files + plan.sidecar_files
    plan.validate(source)
    with pytest.raises(ValueError, match='Missing generated resource: BUILD_INFO.json'):
        plan.validate(source, require_generated=True)
    plan.data_files.append(['configs/missing.xlsx', 'configs'])
    with pytest.raises(ValueError, match='Missing source resource: configs/missing.xlsx'):
        plan.validate(source)


def test_explicit_missing_resource_is_not_silently_ignored(tmp_path):
    source = tmp_path / 'source'
    resource_project(source)
    (source / 'main.py').write_text("from helper import resource_path\nx = resource_path('missing.qss')\n")
    analysis = analyze_project(source)
    plan = ExperienceEngine().plan(analysis, analysis.entry_point)
    with pytest.raises(ValueError, match='missing.qss'):
        plan.validate(source)


@pytest.mark.parametrize('value', ['../BUILD_INFO.json', 'other.json'])
def test_generated_resources_are_restricted(tmp_path, value):
    source = tmp_path / 'source'
    plan = resource_project(source)
    plan.generated_sidecars = [[value, '.']]
    with pytest.raises(ValueError):
        plan.validate(source)


def test_materialization_uses_source_git_commit_and_version(tmp_path):
    source = tmp_path / 'source'
    plan = resource_project(source)
    subprocess.run(['git', 'init', str(source)], check=True, capture_output=True)
    subprocess.run(['git', 'add', '.'], cwd=source, check=True, capture_output=True)
    subprocess.run(['git', '-c', 'user.name=Acceptance', '-c', 'user.email=test@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture'], cwd=source, check=True, capture_output=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    project = tmp_path / 'copy'
    engine = BuildEngine(tmp_path / 'builds')
    engine._copy_source(source, source / 'main.py', project)
    engine._materialize_generated_sidecars(plan, project, source)
    plan.validate(project, require_generated=True)
    info = json.loads((project / 'BUILD_INFO.json').read_text())
    assert info['version'] == '0.2.0-dev'
    assert info['commit'] == commit
    assert info['built_at'].endswith('+00:00')
    assert info['dirty'] is False
    assert not (source / 'BUILD_INFO.json').exists()
    assert not (project / '.git').exists()


def test_generation_failure_is_build_failure(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    plan = resource_project(source)
    engine = BuildEngine(tmp_path / 'builds')
    monkeypatch.setattr(engine, '_materialize_generated_sidecars', lambda *args: None)
    result = engine.build(BuildRequest(source, entry_point=source / 'main.py', plan=plan))
    assert not result.success
    assert 'Missing generated resource: BUILD_INFO.json' in result.error


@pytest.mark.parametrize('mode', ['onefile', 'onedir'])
def test_final_package_stages_spreadsheets_and_no_source(tmp_path, mode):
    source = tmp_path / 'source'
    plan = resource_project(source)
    plan.mode = mode
    (source / 'configs').mkdir()
    (source / 'configs' / 'channel.xlsx').write_bytes(b'Excel fixture')
    plan.data_files.append(['configs/channel.xlsx', 'configs'])
    BuildEngine._materialize_generated_sidecars(plan, source, source)
    dist = tmp_path / 'dist'
    artifact = dist / ('main.exe' if mode == 'onefile' else 'main')
    exe = artifact if mode == 'onefile' else artifact / 'main.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'executable fixture')
    package = BuildEngine._stage_sidecars(artifact, exe, plan, source, 'main')
    assert (package / 'main.exe').is_file()
    assert (package / 'VERSION').is_file()
    assert (package / 'BUILD_INFO.json').is_file()
    assert (package / 'configs/channel.xlsx').is_file()
    assert not list(package.rglob('*.py'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows smoke test implementation')
@pytest.mark.parametrize('app_type,code,timeout,passes', [
    ('console', 0, False, True), ('console', 1, False, False),
    ('gui', 1, False, False), ('gui', None, True, True),
    ('console', None, True, True),
])
def test_smoke_rules_capture_output_and_stop_timed_out_process(tmp_path, monkeypatch, app_type, code, timeout, passes):
    stopped = []
    class Process:
        pid = 123
        def wait(self, timeout):
            if self.returncode is None:
                raise subprocess.TimeoutExpired('fixture', timeout)
            return self.returncode
        def poll(self):
            return self.returncode
    process = Process()
    process.returncode = None if timeout else code
    def popen(command, **kwargs):
        assert kwargs['cwd'] == tmp_path
        kwargs['stdout'].write('startup output\n')
        return process
    def stop(proc):
        if proc.poll() is None:
            stopped.append(proc.pid)
            proc.returncode = -1
    monkeypatch.setattr('builder.engine.subprocess.Popen', popen)
    monkeypatch.setattr(BuildEngine, '_stop_smoke_process', staticmethod(stop))
    log = tmp_path / 'build.log'
    if passes:
        BuildEngine._smoke_test_executable(tmp_path / 'app.exe', app_type, log)
        assert 'SMOKE TEST PASS' in log.read_text()
    else:
        with pytest.raises(RuntimeError):
            BuildEngine._smoke_test_executable(tmp_path / 'app.exe', app_type, log)
    assert 'startup output' in log.read_text()
    assert stopped == ([123] if timeout else [])
