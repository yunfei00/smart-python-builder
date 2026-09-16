import json
from pathlib import Path

import pytest

from analyzer import analyze_project
from builder.experience import BuildProfile, ExperienceEngine, PROFILES
from builder.models import BuildPlan


@pytest.mark.parametrize('profile', PROFILES, ids=lambda p: p.name)
def test_builtin_profiles(tmp_path, profile):
    entry = tmp_path / 'main.py'
    entry.write_text('import ' + profile.imports[0], encoding='utf-8')
    analysis = analyze_project(entry)
    plan = ExperienceEngine().plan(analysis, entry)
    assert profile.name in plan.matched_experiences
    assert plan.app_type == profile.app_type
    assert profile.package is None or profile.package in plan.dependencies
    assert json.loads(plan.to_json()) == plan.to_dict()


def test_profile_options_and_override(tmp_path):
    entry = tmp_path / 'main.py'
    entry.write_text('import tkinter', encoding='utf-8')
    profile = BuildProfile('custom', ('tkinter',), None, 'gui', ('json',), ('email',), (('config.json', '.'),), ('--noupx',))
    plan = ExperienceEngine((profile,)).plan(analyze_project(entry), entry, windowed=False, mode='onedir')
    assert plan.app_type == 'console'
    assert plan.mode == 'onedir'
    assert plan.hidden_imports == ['json']
    assert plan.collect_all == ['email']
    assert plan.data_files == [['config.json', '.']]
    assert plan.pyinstaller_args == ['--noupx']
    assert plan.decision_sources['app_type'] == 'user'


def test_known_error_rules():
    rules = ExperienceEngine().diagnose("ModuleNotFoundError: No module named 'cv2'")
    assert rules[0].action == 'add_dependencies'
    assert rules[0].values == ('opencv-python',)


@pytest.mark.parametrize('field,value', [('entry_point','../escape.py'), ('mode','shell'), ('hidden_imports',['--evil']), ('pyinstaller_args',['--runtime-hook=evil.py']), ('dependencies',['--index-url=https://evil'])])
def test_plan_rejects_unsafe_options(tmp_path, field, value):
    (tmp_path/'main.py').write_text('print(1)')
    plan = BuildPlan('main.py')
    setattr(plan, field, value)
    with pytest.raises(ValueError):
        plan.validate(tmp_path)
