import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from builder.ai import configured_provider, OpenAICompatibleProvider, FakeAIProvider
from builder.notifications import NotificationService, FeishuNotifier, FakeNotifier
from web.app import create_app


@pytest.mark.parametrize('configured', [False, True])
def test_production_provider_selection(monkeypatch, configured):
    for name in ('BUILDER_AI_API_KEY', 'BUILDER_AI_MODEL', 'BUILDER_AI_BASE_URL', 'BUILDER_FEISHU_WEBHOOK'):
        monkeypatch.delenv(name, raising=False)
    if configured:
        monkeypatch.setenv('BUILDER_AI_API_KEY', 'audit-placeholder')
        monkeypatch.setenv('BUILDER_AI_MODEL', 'audit-model')
        monkeypatch.setenv('BUILDER_AI_BASE_URL', 'https://example.invalid/v1')
        monkeypatch.setenv('BUILDER_FEISHU_WEBHOOK', 'https://example.invalid/webhook')
    ai = configured_provider()
    notifier = NotificationService.configured().notifier
    assert not isinstance(ai, FakeAIProvider)
    assert not isinstance(notifier, FakeNotifier)
    if configured:
        assert isinstance(ai, OpenAICompatibleProvider)
        assert ai.base_url == 'https://example.invalid/v1'
        assert isinstance(notifier, FeishuNotifier)
    else:
        assert ai is None and notifier is None


def test_rejected_upload_removes_partial_files(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('main.py', 'print(1)')
        archive.writestr('../escape.py', 'print(2)')
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/api/uploads', files={'file': ('bad.zip', data.getvalue())}).status_code == 400
        assert list((tmp_path / 'uploads').iterdir()) == []


def test_web_queue_is_bounded(tmp_path, monkeypatch):
    pending = []
    class DeferredExecutor:
        def __init__(self, max_workers):
            assert max_workers == 1
        def submit(self, *args):
            pending.append(args)
        def shutdown(self, wait):
            pass
    monkeypatch.setattr('web.app.ThreadPoolExecutor', DeferredExecutor)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        registered = client.post(
            '/account/register',
            data={'username': 'queue', 'email': 'queue@example.com', 'password': 'password123'},
            follow_redirects=False,
        )
        assert registered.status_code == 303
        app.state.accounts.set_plan('queue@example.com', 'TEST')
        session = app.state.accounts.session(client.cookies.get('builder_user'))
        headers = {'X-CSRF-Token': session['csrf']}
        ids = [client.post('/api/uploads', files={'file': ('main.py', b'print(1)')}).json()['id'] for _ in range(9)]
        for identifier in ids[:8]:
            assert client.post('/api/jobs/' + identifier + '/build', data={'entry': 'main.py'}, headers=headers).status_code == 200
        assert client.post('/api/jobs/' + ids[8] + '/build', data={'entry': 'main.py'}, headers=headers).status_code == 429
        assert len(pending) == 8


def test_invalid_python_upload_is_cleaned(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post('/api/uploads', files={'file': ('bad.py', b'def invalid(')})
        assert response.status_code == 400
        assert list((tmp_path / 'uploads').iterdir()) == []


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows process tree verification')
def test_timeout_terminates_child_process(tmp_path):
    import ctypes
    import sys
    from builder.execution import LocalWindowsBackend
    child_file = tmp_path / 'child.pid'
    program = (
        'import subprocess,sys,time\n'
        'from pathlib import Path\n'
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
        f'Path({str(child_file)!r}).write_text(str(child.pid))\n'
        'time.sleep(30)\n'
    )
    with (tmp_path / 'process.log').open('w') as log:
        with pytest.raises(TimeoutError):
            LocalWindowsBackend().run([sys.executable, '-c', program], tmp_path, log, 2)
    assert child_file.exists(), 'Child process did not start before timeout'
    pid = int(child_file.read_text())
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 0) == 0, 'Child process survived timeout'
        finally:
            kernel.CloseHandle(handle)


def test_actual_oversize_upload_rejected(tmp_path):
    from web.uploads import MAX_UPLOAD
    with TestClient(create_app(tmp_path)) as client:
        response = client.post('/api/uploads', files={'file': ('large.py', b'#' * (MAX_UPLOAD + 1))})
        assert response.status_code == 400
        assert '20 MB' in response.json()['detail']
        assert not (tmp_path / 'uploads').exists()


def test_zip_expansion_and_symlink_rejected(tmp_path, monkeypatch):
    import stat
    monkeypatch.setattr('web.uploads.MAX_EXPANDED', 16)
    expanded = io.BytesIO()
    with zipfile.ZipFile(expanded, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('main.py', b'#' * 32)
    linked = io.BytesIO()
    with zipfile.ZipFile(linked, 'w') as archive:
        item = zipfile.ZipInfo('main.py')
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(item, 'outside.py')
    with TestClient(create_app(tmp_path)) as client:
        for content in (expanded.getvalue(), linked.getvalue()):
            assert client.post('/api/uploads', files={'file': ('bad.zip', content)}).status_code == 400
        assert list((tmp_path / 'uploads').iterdir()) == []
