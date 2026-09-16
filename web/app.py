from __future__ import annotations

import json
import shutil
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from analyzer import analyze_project
from builder import SmartBuilder
from .uploads import MAX_UPLOAD, save_upload


def create_app(root: Path | str = 'web-data', builder_factory=SmartBuilder):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    jobs = {}
    lock = threading.RLock()
    pool = ThreadPoolExecutor(max_workers=1)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))

    @asynccontextmanager
    async def lifespan(app):
        yield
        pool.shutdown(wait=True)

    app = FastAPI(lifespan=lifespan)
    app.state.jobs = jobs
    app.state.root = root

    def get_job(job_id):
        with lock:
            if job_id not in jobs:
                raise HTTPException(404, '任务不存在')
            return jobs[job_id]

    def run_job(job_id, entry, mode):
        job = get_job(job_id)
        job['status'] = 'BUILDING'
        try:
            builder = builder_factory(root / 'workspace')
            builder.engine.on_created = lambda build_id, log_file: job.update(build_id=build_id, log=str(log_file))
            builder.on_state = lambda state: job.update(status=state)
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
            (root / f'{job_id}.json').write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')

    @app.get('/', response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request=request, name='index.html', context={})

    @app.post('/api/uploads')
    async def upload(file: UploadFile = File(...)):
        data = await file.read(MAX_UPLOAD + 1)
        job_id = uuid.uuid4().hex
        try:
            source = save_upload(file.filename, data, root / 'uploads' / job_id)
            analysis = analyze_project(source)
            entries = analysis.entry_candidates or analysis.python_files
            builder = builder_factory(root / 'workspace')
            plan = builder.experiences.plan(analysis, analysis.entry_point).to_dict() if analysis.entry_point else None
        except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
        job = dict(id=job_id, status='READY', source=str(source), entries=[str(p.relative_to(analysis.project_root)) for p in entries],
                   entry=str(analysis.entry_point.relative_to(analysis.project_root)) if analysis.entry_point else None,
                   dependencies=analysis.packages, dependency_source=analysis.dependency_source, plan=plan)
        jobs[job_id] = job
        return job

    @app.get('/api/jobs/{job_id}/plan')
    def preview(job_id: str, entry: str, mode: str = 'onefile'):
        job = get_job(job_id)
        if entry not in job['entries'] or mode not in {'onefile', 'onedir'}:
            raise HTTPException(400, '请选择有效入口和输出格式')
        analysis = analyze_project(job['source'])
        builder = builder_factory(root / 'workspace')
        return builder.experiences.plan(analysis, analysis.project_root / entry, mode=mode).to_dict()

    @app.post('/api/jobs/{job_id}/build')
    def start(job_id: str, entry: str = Form(...), mode: str = Form('onefile')):
        job = get_job(job_id)
        with lock:
            if job['status'] != 'READY':
                raise HTTPException(409, '任务已开始')
            if entry not in job['entries'] or mode not in {'onefile', 'onedir'}:
                raise HTTPException(400, '请选择有效入口和输出格式')
            job['status'] = 'QUEUED'
            pool.submit(run_job, job_id, entry, mode)
        return {'id': job_id, 'status': 'QUEUED'}

    @app.get('/api/jobs/{job_id}')
    def status(job_id: str):
        return dict(get_job(job_id))

    @app.get('/api/jobs/{job_id}/log')
    def log(job_id: str):
        job = get_job(job_id)
        path = Path(job['log']) if job.get('log') else None
        return {'text': path.read_text(encoding='utf-8', errors='replace')[-200000:] if path and path.exists() else ''}

    @app.get('/api/jobs/{job_id}/download')
    def download(job_id: str):
        job = get_job(job_id)
        if job['status'] != 'SUCCESS' or not job.get('artifact'):
            raise HTTPException(409, '文件尚未生成')
        artifact = Path(job['artifact'])
        return FileResponse(artifact, filename=artifact.name)

    return app


app = create_app()
