"""Real Web API -> GitHub clone -> build -> download -> extracted EXE acceptance.

Run on Windows with: uv run python tests/windows_github_import_acceptance.py
No clone, analyzer, build, packaging, or smoke components are mocked.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from builder.engine import BuildEngine
from builder.settings import SettingsStore
from web.app import create_app

REPOSITORY = 'https://github.com/yunfei00/cmw500_auto_test'


def build_and_download(client, job, entries, csrf, root):
    response = client.post(f"/api/jobs/{job['id']}/build",
                           data={'entries': '|'.join(entries), 'mode': 'onefile'},
                           headers={'X-CSRF-Token': csrf})
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 1800
    last_status = None
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{job['id']}").json()
        if result['status'] != last_status:
            print(result['status'], result.get('log'), flush=True)
            last_status = result['status']
        if result.get('terminal'):
            break
        time.sleep(2)
    (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    assert result['status'] == 'SUCCESS', (result.get('error'), result.get('log'))
    response = client.get(f"/api/jobs/{job['id']}/download")
    assert response.status_code == 200, response.text[:1000]
    archive = root / 'download.zip'
    archive.write_bytes(response.content)
    with zipfile.ZipFile(archive) as bundle:
        assert not [name for name in bundle.namelist() if name.lower().endswith('.py')]
        bundle.extractall(root / 'extracted')
    return result


def check_multi_app(client, csrf, root):
    root.mkdir()
    content = '''import json,sys
from pathlib import Path
def resource_path(name):
    return Path(sys.executable).resolve().parent/name
version = resource_path('VERSION').read_text().strip()
info = json.loads(resource_path('BUILD_INFO.json').read_text())
assert info['version'] == version
print(version)
UNRELATED = 'main.py'
'''
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('main.py', content)
        archive.writestr('app.py', content)
        archive.writestr('VERSION', '1.2.3\n')
    response = client.post('/api/uploads', files={'file': ('multi.zip', stream.getvalue())})
    assert response.status_code == 200, response.text
    result = build_and_download(client, response.json(), ['main.py', 'app.py'], csrf, root)
    archives = list((root / 'extracted').glob('*.zip'))
    assert len(archives) == 2
    for archive in archives:
        with zipfile.ZipFile(archive) as bundle:
            assert not any(name.endswith('.py') for name in bundle.namelist())
            bundle.extractall(root / 'applications')
    executables = list((root / 'applications').rglob('*.exe'))
    assert len(executables) == 2
    for exe in executables:
        BuildEngine._smoke_test_executable(exe, 'console', root / 'download-smoke.log')
    print('MULTI-APP WEB ACCEPTANCE PASS', result['id'], flush=True)


def main():
    root = Path(__file__).resolve().parents[1] / 'workspace' / ('github-acceptance-' + uuid.uuid4().hex)
    root.mkdir()
    # Test runs never send real notifications or call a configured repair service.
    SettingsStore(root / 'settings.sqlite3').save({'ai_enabled': False, 'feishu_enabled': False})
    app = create_app(root)
    with TestClient(app) as client:
        response = client.post('/account/register',
                               data={'username': 'acceptance', 'password': secrets.token_urlsafe(24)},
                               follow_redirects=False)
        assert response.status_code == 303, response.text
        session = app.state.accounts.session(client.cookies.get('builder_user'))
        app.state.accounts.set_plan_by_id(session['id'], 'TEST')
        response = client.post('/api/repositories', json={'url': REPOSITORY})
        assert response.status_code == 200, response.text
        job = response.json()
        print('ACCEPTANCE ROOT', root, flush=True)
        print('ENTRY DETAILS', json.dumps(job['entry_details']), flush=True)
        assert any(item['path'] == 'main.py' and item['recommended'] and item['kind'] == 'application'
                   for item in job['entry_details'])
        preview = client.get(f"/api/jobs/{job['id']}/plan", params={'entry': 'main.py'}).json()
        (root / 'preview.json').write_text(json.dumps(preview, indent=2), encoding='utf-8')
        result = build_and_download(client, job, ['main.py'], session['csrf'], root)
        exe = next((root / 'extracted').rglob('main.exe'))
        version = (exe.parent / 'VERSION').read_text().strip()
        info = json.loads((exe.parent / 'BUILD_INFO.json').read_text())
        source = Path(job['source'])
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
        assert info['version'] == version and info['commit'] == commit, info
        assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip()
        for resource, destination in preview['data_files']:
            assert (exe.parent / destination / Path(resource).name).is_file(), resource
        assert list(exe.parent.rglob('*.xlsx'))
        BuildEngine._smoke_test_executable(exe, 'gui', root / 'download-smoke.log', startup_seconds=10)
        # This application's own opt-in smoke mode exercises optional VISA paths
        # and creates/closes its main window. It supplements the normal launch.
        with (root / 'application-smoke.log').open('w', encoding='utf-8') as log:
            completed = subprocess.run([str(exe), '--smoke-test'], cwd=exe.parent,
                                       stdout=log, stderr=subprocess.STDOUT, timeout=90)
        assert completed.returncode == 0, root / 'application-smoke.log'
        evidence = {'repository': REPOSITORY, 'commit': commit, 'job_id': job['id'],
                    'build_id': result['build_id'], 'exe': str(exe), 'build_info': info,
                    'files': [str(path.relative_to(root / 'extracted')) for path in (root / 'extracted').rglob('*') if path.is_file()],
                    'smoke': 'PASS', 'application_smoke_exit_code': completed.returncode}
        (root / 'inspection.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print('REAL GITHUB IMPORT / EXTRACTED EXE SMOKE PASS', exe, flush=True)
        check_multi_app(client, session['csrf'], root / 'multi-app')
    print('GITHUB IMPORT ACCEPTANCE PASS', root, flush=True)


if __name__ == '__main__':
    main()
