from __future__ import annotations

import json
import shutil
import threading
import uuid
import zipfile
import time
import asyncio
import contextlib
import re
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Depends
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from analyzer import analyze_project
from builder import SmartBuilder
from builder.learning import ExperienceStore
from builder.maintenance import cleanup_workspaces
from builder.settings import SettingsStore, allowed_hosts, environment_settings
from .admin import register_admin
from .security import RequestLimitsMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .uploads import MAX_UPLOAD, save_upload
from .repositories import clone_public_github_repository


def _allowed_hosts() -> list[str]:
    return allowed_hosts(environment_settings()[0]['allowed_hosts'])


def create_app(root: Path | str = 'web-data', builder_factory=SmartBuilder, admin_token=None, *, ai_factory=None, notifier_factory=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = SettingsStore(root / 'settings.sqlite3')
    startup_settings = settings.effective()
    def make_builder():
        if builder_factory is SmartBuilder:
            return builder_factory(root / 'workspace', settings_store=settings)
        return builder_factory(root / 'workspace')
    jobs = {}
    lock = threading.RLock()
    pool = ThreadPoolExecutor(max_workers=1)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))

    def persist(job):
        with lock:
            target = root / (job['id'] + '.json')
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(target)

    for saved in root.glob('*.json'):
        try:
            job = json.loads(saved.read_text(encoding='utf-8'))
            if saved.stem != job['id'] or len(job['id']) != 32:
                continue
            if (job['status'] != 'READY' and not job.get('terminal', True)) or job['status'] not in {'READY','SUCCESS','FAILED','NEEDS_MANUAL_REVIEW','EXPIRED'}:
                job.update(status='NEEDS_MANUAL_REVIEW', error='Service restarted while task was active', terminal=True)
                build_id = job.get('build_id', '')
                if re.fullmatch('[a-f0-9]{32}', build_id):
                    marker = root / 'workspace' / build_id / 'task.json'
                    if marker.is_file() and marker.resolve().is_relative_to(root):
                        marker.write_text(json.dumps(dict(status='FAILED', build_id=build_id, finished_at=time.time(), error='Service restarted')), encoding='utf-8')
                persist(job)
            jobs[job['id']] = job
        except (OSError, ValueError, KeyError):
            continue

    @asynccontextmanager
    async def lifespan(app):
        retention = startup_settings['retention_days'] * 86400
        def cleanup():
            cleanup_workspaces(root / 'workspace', retention_seconds=retention)
            with lock:
                for job in jobs.values():
                    if not (job.get('terminal') or job['status']=='READY') or time.time()-job.get('created_at',time.time())<retention:
                        continue
                    target = root / 'uploads' / job['id']
                    if re.fullmatch('[a-f0-9]{32}', job['id']) and target.exists() and not target.is_symlink() and target.resolve().parent == (root/'uploads').resolve():
                        shutil.rmtree(target.resolve())
                    job.update(status='EXPIRED', terminal=True)
                    persist(job)
        await asyncio.to_thread(cleanup)
        async def scheduled_cleanup():
            while True:
                await asyncio.sleep(3600)
                await asyncio.to_thread(cleanup)
        maintenance = asyncio.create_task(scheduled_cleanup())
        try:
            yield
        finally:
            maintenance.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await maintenance
            pool.shutdown(wait=True)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(RequestLimitsMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(startup_settings['allowed_hosts']))
    app.mount('/static', StaticFiles(directory=str(Path(__file__).parent / 'static')), name='static')

    @app.middleware('http')
    async def same_origin(request, call_next):
        origin = request.headers.get('origin')
        if request.method not in {'GET','HEAD','OPTIONS'} and origin and (urlsplit(origin).netloc != request.headers.get('host') or urlsplit(origin).scheme != request.url.scheme):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Cross-origin writes are disabled'}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(('/admin', '/api/admin')):
            response.headers['Cache-Control'] = 'no-store'
        return response
    app.state.jobs = jobs
    app.state.root = root
    store = ExperienceStore(root / 'workspace' / 'experiences.sqlite3')
    app.state.experience_store = store
    app.state.settings = settings
    admin = register_admin(app, templates, settings, admin_token, ai_factory, notifier_factory)

    @app.get('/api/admin/experiences', dependencies=[Depends(admin)])
    def candidates():
        return store.list()

    @app.post('/api/admin/experiences/{identifier}', dependencies=[Depends(admin)])
    def review(identifier: str, payload: dict):
        try:
            return store.review(identifier, payload.get('decision'), payload.get('repair_plan'))
        except KeyError:
            raise HTTPException(404, '经验不存在')
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc))

    def get_job(job_id):
        with lock:
            if job_id not in jobs:
                raise HTTPException(404, '任务不存在')
            return jobs[job_id]

    def run_job(job_id, entry, mode):
        job = get_job(job_id)
        job['status'] = 'BUILDING'
        persist(job)
        try:
            builder = make_builder()
            def created(build_id, log_file):
                job.update(build_id=build_id, log=str(log_file))
                persist(job)
            def state_changed(state):
                job.update(status=state)
                persist(job)
            builder.engine.on_created = created
            builder.on_state = state_changed
            builder.web_job_id = job_id
            result = builder.build(Path(job['source']), entry_point=entry, mode=mode)
            job.update(build_id=result.build.build_id, plan=result.plan.to_dict(), log=str(result.build.log_file))
            if result.build.success:
                artifact = result.build.artifact
                if artifact.is_dir():
                    artifact = Path(shutil.make_archive(str(artifact), 'zip', artifact.parent, artifact.name))
                job.update(status='SUCCESS', artifact=str(artifact))
            else:
                job.update(status=result.status, error=result.build.error, attempts=result.attempts)
        except Exception as exc:
            job.update(status='FAILED', error=str(exc))
        finally:
            job['terminal'] = True
            persist(job)

    @app.get('/', response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request=request, name='index.html', context={})

    @app.post('/api/uploads')
    async def upload(file: UploadFile = File(...)):
        data = await file.read(MAX_UPLOAD + 1)
        job_id = uuid.uuid4().hex
        upload_dir = root / 'uploads' / job_id
        try:
            source = save_upload(file.filename, data, upload_dir)
            analysis = analyze_project(source)
            entries = analysis.entry_candidates or analysis.python_files
            builder = make_builder()
            plan = builder.experiences.plan(analysis, analysis.entry_point).to_dict() if analysis.entry_point else None
        except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
            if upload_dir.exists() and not upload_dir.is_symlink() and upload_dir.resolve().parent == (root / 'uploads').resolve():
                shutil.rmtree(upload_dir.resolve())
            raise HTTPException(400, str(exc)) from exc
        job = dict(id=job_id, status='READY', source=str(source), entries=[str(p.relative_to(analysis.project_root)) for p in entries],
                   entry=str(analysis.entry_point.relative_to(analysis.project_root)) if analysis.entry_point else None,
                   dependencies=analysis.packages, dependency_source=analysis.dependency_source, plan=plan, created_at=time.time(), terminal=False)
        jobs[job_id] = job
        persist(job)
        return job

    @app.post('/api/repositories')
    def import_repository(payload: dict):
        job_id = uuid.uuid4().hex
        upload_dir = root / 'uploads' / job_id
        try:
            source = clone_public_github_repository(payload.get('url', ''), upload_dir, payload.get('ref'))
            analysis = analyze_project(source)
            entries = analysis.entry_candidates or analysis.python_files
            builder = make_builder()
            plan = builder.experiences.plan(analysis, analysis.entry_point).to_dict() if analysis.entry_point else None
        except (ValueError, OSError, RuntimeError) as exc:
            if upload_dir.exists() and not upload_dir.is_symlink() and upload_dir.resolve().parent == (root / 'uploads').resolve():
                shutil.rmtree(upload_dir.resolve())
            raise HTTPException(400, str(exc)) from exc
        job = dict(id=job_id, status='READY', source=str(source), entries=[str(p.relative_to(analysis.project_root)) for p in entries],
                   entry=str(analysis.entry_point.relative_to(analysis.project_root)) if analysis.entry_point else None,
                   dependencies=analysis.packages, dependency_source=analysis.dependency_source, plan=plan, created_at=time.time(), terminal=False,
                   source_type='github', repository_url=payload.get('url', '').strip(), repository_ref=(payload.get('ref') or '').strip() or None)
        jobs[job_id] = job
        persist(job)
        return job

    @app.get('/api/jobs/{job_id}/plan')
    def preview(job_id: str, entry: str, mode: str = 'onefile'):
        job = get_job(job_id)
        if entry not in job['entries'] or mode not in {'onefile', 'onedir'}:
            raise HTTPException(400, '请选择有效入口和输出格式')
        analysis = analyze_project(job['source'])
        builder = make_builder()
        return builder.experiences.plan(analysis, analysis.project_root / entry, mode=mode).to_dict()

    @app.post('/api/jobs/{job_id}/build')
    def start(job_id: str, entry: str = Form(...), mode: str = Form('onefile')):
        job = get_job(job_id)
        with lock:
            if job['status'] != 'READY':
                raise HTTPException(409, '任务已开始')
            if entry not in job['entries'] or mode not in {'onefile', 'onedir'}:
                raise HTTPException(400, '请选择有效入口和输出格式')
            if sum(not item.get('terminal') and item['status'] != 'READY' for item in jobs.values()) >= 8:
                raise HTTPException(429, '构建队列已满，请稍后重试')
            job['status'] = 'QUEUED'
            persist(job)
            pool.submit(run_job, job_id, entry, mode)
        return {'id': job_id, 'status': 'QUEUED'}

    @app.get('/api/jobs/{job_id}')
    def status(job_id: str):
        job = dict(get_job(job_id))
        job['artifact_available'] = artifact_available(job)
        return job

    def artifact_available(job):
        if job['status'] != 'SUCCESS' or not job.get('terminal') or not job.get('artifact'):
            return False
        artifact = Path(job['artifact'])
        try:
            return artifact.resolve().is_relative_to(root) and artifact.is_file() and artifact.stat().st_size > 0
        except OSError:
            return False

    @app.get('/api/jobs/{job_id}/log')
    def log(job_id: str):
        job = get_job(job_id)
        path = Path(job['log']) if job.get('log') else None
        return {'text': path.read_text(encoding='utf-8', errors='replace')[-200000:] if path and path.exists() else ''}

    @app.get('/api/jobs/{job_id}/download')
    def download(job_id: str):
        job = get_job(job_id)
        if job['status'] != 'SUCCESS' or not job.get('terminal') or not job.get('artifact'):
            raise HTTPException(409, '文件尚未生成')
        artifact = Path(job['artifact'])
        if not artifact_available(job):
            raise HTTPException(410, '产物已过期或不可用')
        return FileResponse(artifact, filename=artifact.name)

    return app


app = create_app()
