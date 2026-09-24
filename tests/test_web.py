import io
import time
import zipfile
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from web.app import create_app


def zipped(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name, data in files.items(): z.writestr(name,data)
    return stream.getvalue()


def test_upload_and_entry_selection(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        registered = client.post(
            '/account/register',
            data={'username': 'entry', 'email':'entry@example.com','password':'password123'},
            follow_redirects=False,
        )
        assert registered.status_code == 303
        session = app.state.accounts.session(client.cookies.get('builder_user'))
        headers = {'X-CSRF-Token': session['csrf']}
        response=client.post('/api/uploads',files={'file':('demo.zip',zipped({'main.py':'print(1)','app.py':'print(2)'}))})
        assert response.status_code == 200
        job=response.json()
        assert job['entry'] is None and len(job['entries'])==2
        assert client.post(f"/api/jobs/{job['id']}/build",data={'entry':'../main.py'},headers=headers).status_code==400
        assert client.get(f"/api/jobs/{job['id']}/download").status_code==409


def test_upload_rejects_unsafe_files(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        for name, content in [('evil.txt',b'bad'),('bad.zip',zipped({'../evil.py':'bad'})),('bad.zip',zipped({'C:/evil.py':'bad'}))]:
            assert client.post('/api/uploads',files={'file':(name,content)}).status_code==400
        assert not (tmp_path/'evil.py').exists()


def test_upload_plan(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        job=client.post('/api/uploads',files={'file':('demo.py',b'import tkinter')}).json()
        assert job['plan']['app_type']=='gui'
        assert job['dependencies']==[]
        assert client.get('/api/jobs/unknown').status_code==404


def test_plan_preview_for_multiple_entries(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        job=client.post('/api/uploads',files={'file':('demo.zip',zipped({'main.py':'print(1)','app.py':'print(2)'}))}).json()
        r=client.get(f"/api/jobs/{job['id']}/plan",params={'entry':'app.py','mode':'onedir'})
        assert r.status_code==200
        assert r.json()['entry_point']=='app.py' and r.json()['mode']=='onedir'
        assert client.post('/api/uploads',files={'file':('broken.zip',b'not zip')}).status_code==400


def test_github_repository_import_uses_normal_analysis_flow(tmp_path, monkeypatch):
    project = tmp_path / "fake-repository"
    project.mkdir()
    (project / "main.py").write_text("import requests\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="0.1.0"\ndependencies=["requests", "agent @ git+https://github.com/example/agent.git@v1"]\n',
        encoding="utf-8",
    )

    def fake_clone(url, target, ref=None):
        assert url == "https://github.com/example/demo"
        assert ref == "v2"
        return project

    monkeypatch.setattr("web.app.clone_public_github_repository", fake_clone)
    with TestClient(create_app(tmp_path / "web")) as client:
        response = client.post(
            "/api/repositories",
            json={"url": "https://github.com/example/demo", "ref": "v2"},
        )
        assert response.status_code == 200
        job = response.json()
        assert job["source_type"] == "github"
        assert job["entry"] == "main.py"
        assert job["dependency_source"] == "pyproject.toml"
        assert job["dependencies"][1].startswith("agent @ git+https://")


@pytest.mark.parametrize('entries', ['main.py', 'main.py|app.py'])
def test_web_build_validates_generated_resources_before_materialization(tmp_path, monkeypatch, entries):
    from builder.engine import BuildEngine
    checked = []
    def run(self, command, cwd, log_file):
        if str(command[0]).endswith('pyinstaller.exe'):
            name = command[command.index('--name') + 1]
            (cwd / 'dist').mkdir(exist_ok=True)
            (cwd / 'dist' / (name + '.exe')).write_bytes(b'exe fixture')
    def smoke(self, executable, app_type, log_file):
        assert executable.parent.name.endswith('-package')
        assert (executable.parent / 'BUILD_INFO.json').is_file()
        assert (executable.parent / 'VERSION').is_file()
        assert not list(executable.parent.rglob('*.py'))
        checked.append(executable.name)
    monkeypatch.setattr(BuildEngine, '_run', run)
    monkeypatch.setattr(BuildEngine, '_smoke_test_executable', smoke)
    app = create_app(tmp_path)
    app.state.settings.save({'ai_enabled': False, 'feishu_enabled': False})
    with TestClient(app) as client:
        client.post('/account/register', data={'username':'resource-user', 'password':'password123'})
        session = app.state.accounts.session(client.cookies.get('builder_user'))
        source = "from paths import resource_path\nprint(resource_path('VERSION'))\nprint(resource_path('BUILD_INFO.json'))"
        archive = zipped({'main.py': source, 'app.py':source, 'VERSION':'0.2.0-dev',
                          'paths.py':'import sys\nfrom pathlib import Path\ndef resource_path(name):\n    return Path(sys.executable).parent/name'})
        job = client.post('/api/uploads', files={'file':('project.zip', archive)}).json()
        started = client.post(f"/api/jobs/{job['id']}/build", data={'entries':entries}, headers={'X-CSRF-Token':session['csrf']})
        assert started.status_code == 200
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = client.get(f"/api/jobs/{job['id']}").json()
            if result.get('terminal'):
                break
            time.sleep(.02)
        assert result['status'] == 'SUCCESS', result
        assert sorted(checked) == sorted(Path(entry).stem + '.exe' for entry in entries.split('|'))
        downloaded = client.get(f"/api/jobs/{job['id']}/download")
        assert downloaded.status_code == 200
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            assert not any(name.endswith('.py') for name in archive.namelist())


def test_nested_windows_entry_paths_are_normalized_for_build(tmp_path, monkeypatch):
    from builder.engine import BuildEngine

    def fake_run(self, command, cwd, log_file):
        if str(command[0]).endswith("pyinstaller.exe"):
            name = command[command.index("--name") + 1]
            (cwd / "dist").mkdir(exist_ok=True)
            (cwd / "dist" / (name + ".exe")).write_bytes(b"exe fixture")

    monkeypatch.setattr(BuildEngine, "_run", fake_run)
    monkeypatch.setattr(BuildEngine, "_smoke_test_executable", lambda *args, **kwargs: None)

    app = create_app(tmp_path)
    app.state.settings.save({"ai_enabled": False, "feishu_enabled": False})

    with TestClient(app) as client:
        client.post(
            "/account/register",
            data={"username": "nested-entry-user", "password": "password123"},
        )
        session = app.state.accounts.session(client.cookies.get("builder_user"))
        headers = {"X-CSRF-Token": session["csrf"]}

        archive = zipped({
            "src/Instruments Capture Studio UI APP.py":
                "def main():\n    print('app')\n\nif __name__ == '__main__':\n    main()\n",
            "scripts/Run GUI.py":
                "def main():\n    print('gui')\n\nif __name__ == '__main__':\n    main()\n",
        })
        job = client.post(
            "/api/uploads",
            files={"file": ("instrument-capture-studio.zip", archive)},
        ).json()

        assert "src/Instruments Capture Studio UI APP.py" in job["entries"]
        assert "scripts/Run GUI.py" in job["entries"]
        assert all("\\" not in entry for entry in job["entries"])

        preview = client.get(
            f"/api/jobs/{job['id']}/plan",
            params={"entry": "src/Instruments Capture Studio UI APP.py", "mode": "onefile"},
        )
        assert preview.status_code == 200, preview.text

        # Simulate a READY job created by an older Windows build where entries
        # were persisted with backslashes. The current API must still accept
        # the POSIX path emitted by entry_details/the browser.
        app.state.jobs[job["id"]]["entries"] = [
            "src\\Instruments Capture Studio UI APP.py",
            "scripts\\Run GUI.py",
        ]
        started = client.post(
            f"/api/jobs/{job['id']}/build",
            data={"entries": "src/Instruments Capture Studio UI APP.py", "mode": "onefile"},
            headers=headers,
        )
        assert started.status_code == 200, started.text
