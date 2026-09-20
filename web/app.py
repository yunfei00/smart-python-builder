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
import secrets
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Depends
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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
from .repositories import RepositoryImportError, clone_public_github_repository, safe_git_diagnostic
from .accounts import AccountStore, USER_COOKIE, SESSION_SECONDS


def _allowed_hosts() -> list[str]:
    return allowed_hosts(environment_settings()[0]['allowed_hosts'])


def create_app(root: Path | str = 'web-data', builder_factory=SmartBuilder, admin_token=None, *, ai_factory=None, notifier_factory=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = SettingsStore(root / 'settings.sqlite3')
    accounts = AccountStore(root / 'accounts.sqlite3')
    startup_settings = settings.effective()
    def make_builder():
        if builder_factory is SmartBuilder:
            return builder_factory(root / 'workspace', settings_store=settings)
        return builder_factory(root / 'workspace')
    jobs = {}
    futures = {}
    active_builders = {}
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
            if job.get('status') == 'CANCELING':
                job.update(status='CANCELED', error='Build cancelled before service restart completed', terminal=True)
                persist(job)
            elif (job['status'] != 'READY' and not job.get('terminal', True)) or job['status'] not in {'READY','SUCCESS','FAILED','NEEDS_MANUAL_REVIEW','EXPIRED','CANCELED'}:
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
    app.state.accounts = accounts
    admin = register_admin(app, templates, settings, admin_token, ai_factory, notifier_factory, accounts=accounts)

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

    def account_session(request: Request):
        return accounts.session(request.cookies.get(USER_COOKIE, ''))

    def safe_next_url(value, default='/dashboard'):
        value = (value or '').strip()
        if not value or len(value) > 2048 or '\\' in value or '\r' in value or '\n' in value:
            return default
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or value.startswith('//'):
            return default
        return value

    def get_job(job_id):
        with lock:
            if job_id not in jobs:
                raise HTTPException(404, '任务不存在')
            return jobs[job_id]

    def get_job_for_request(job_id, request: Request):
        job = get_job(job_id)
        owner_id = job.get('owner_id')
        if owner_id:
            user = account_session(request)
            if not user or user['id'] != owner_id:
                raise HTTPException(404, '任务不存在')
        return job

    def get_owned_job(job_id, request: Request):
        user = account_session(request)
        if not user:
            raise HTTPException(401, '请先登录')
        job = get_job(job_id)
        if job.get('owner_id') != user['id']:
            raise HTTPException(404, '任务不存在')
        return job, user

    def remove_job_files(job):
        job_id = job['id']
        upload_dir = root / 'uploads' / job_id
        if (
            re.fullmatch('[a-f0-9]{32}', job_id)
            and upload_dir.exists()
            and not upload_dir.is_symlink()
            and upload_dir.resolve().parent == (root / 'uploads').resolve()
        ):
            shutil.rmtree(upload_dir.resolve(), ignore_errors=True)

        build_ids = {job.get('build_id')}
        for attempt in job.get('attempts', []):
            if isinstance(attempt, dict):
                build_ids.add(attempt.get('build_id'))
        workspace_root = (root / 'workspace').resolve()
        for build_id in build_ids:
            if not isinstance(build_id, str) or not re.fullmatch('[a-f0-9]{32}', build_id):
                continue
            target = workspace_root / build_id
            if target.exists() and not target.is_symlink() and target.resolve().parent == workspace_root:
                shutil.rmtree(target.resolve(), ignore_errors=True)

        metadata = root / (job_id + '.json')
        if metadata.exists() and metadata.resolve().parent == root:
            metadata.unlink(missing_ok=True)

    def import_slots(user):
        """How many additional READY jobs this account may create.

        FREE quota is consumed when a build starts. READY jobs therefore reserve
        one future build slot so users cannot upload projects they will be unable
        to start later. TEST accounts and guests are currently unlimited here.
        """
        if not user or user.get('quota_unlimited'):
            return None
        ready_jobs = sum(
            item.get('owner_id') == user['id'] and item.get('status') == 'READY'
            for item in jobs.values()
        )
        return max(0, user['quota_remaining'] - ready_jobs)

    def ensure_import_slot(user):
        slots = import_slots(user)
        if slots is None or slots > 0:
            return
        if user and user['quota_remaining'] <= 0:
            raise HTTPException(402, '免费构建额度已用完，当前不能再导入新项目')
        raise HTTPException(402, '当前剩余额度已被待构建项目占用，请先完成已有 READY 项目后再导入')

    def run_job(job_id, entry, mode):
        job = get_job(job_id)
        with lock:
            if job.get('cancel_requested'):
                job.update(status='CANCELED', error='Build cancelled by user', terminal=True)
                owner_id = job.get('owner_id')
                if owner_id:
                    accounts.refund_build(owner_id)
                futures.pop(job_id, None)
                persist(job)
                return
            job['status'] = 'BUILDING'
            persist(job)
        try:
            builder = make_builder()
            with lock:
                active_builders[job_id] = builder
                if job.get('cancel_requested'):
                    builder.cancel()
            def created(build_id, log_file):
                job.update(build_id=build_id, log=str(log_file))
                persist(job)
            def state_changed(state):
                if job.get('cancel_requested') and state != 'CANCELED':
                    job.update(status='CANCELING')
                else:
                    job.update(status=state)
                persist(job)
            builder.engine.on_created = created
            builder.on_state = state_changed
            builder.web_job_id = job_id
            result = builder.build(Path(job['source']), entry_point=entry, mode=mode)
            job.update(build_id=result.build.build_id, plan=result.plan.to_dict(), log=str(result.build.log_file), attempts=result.attempts)
            if result.status == 'CANCELED' or job.get('cancel_requested'):
                job.update(status='CANCELED', error='Build cancelled by user')
            elif result.build.success:
                artifact = result.build.artifact
                if artifact.is_dir():
                    artifact = Path(shutil.make_archive(str(artifact), 'zip', artifact.parent, artifact.name))
                job.update(status='SUCCESS', artifact=str(artifact))
            else:
                job.update(status=result.status, error=result.build.error, attempts=result.attempts)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            if job.get('cancel_requested'):
                job.update(status='CANCELED', error='Build cancelled by user')
            else:
                job.update(status='FAILED', error=error)
            # Failures before BuildEngine creates a workspace/log (for example
            # plan validation) still need a visible diagnostic in the Web UI.
            if not job.get('log'):
                diagnostic = root / 'uploads' / job_id / 'build-error.log'
                diagnostic.parent.mkdir(parents=True, exist_ok=True)
                diagnostic.write_text('BUILD FAILED BEFORE ENGINE START\n' + error + '\n', encoding='utf-8')
                job['log'] = str(diagnostic)
        finally:
            with lock:
                active_builders.pop(job_id, None)
                futures.pop(job_id, None)
                job['terminal'] = True
                persist(job)

    @app.get('/', response_class=HTMLResponse)
    def home(request: Request):
        user = account_session(request)
        slots = import_slots(user)
        return templates.TemplateResponse(
            request=request,
            name='index.html',
            context={
                'user': user,
                'import_slots': slots,
                'import_blocked': user is not None and slots == 0,
            },
        )

    def account_page(request, mode, error='', email='', next_url='/dashboard'):
        next_url = safe_next_url(next_url)
        user = account_session(request)
        if user:
            return RedirectResponse(next_url, status_code=303)
        return templates.TemplateResponse(
            request=request, name='account_auth.html',
            context={'mode': mode, 'error': error, 'email': email, 'next_url': next_url},
            headers={'Cache-Control': 'no-store'},
        )

    @app.get('/account/register', response_class=HTMLResponse)
    def register_page(request: Request):
        return account_page(request, 'register', next_url=request.query_params.get('next', '/dashboard'))

    @app.post('/account/register')
    def register_account(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        next_url: str = Form('/dashboard', alias='next'),
    ):
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Cross-origin writes are disabled')
        next_url = safe_next_url(next_url)
        try:
            user = accounts.create_user(email, password)
        except ValueError as exc:
            return account_page(request, 'register', str(exc), email.strip(), next_url)
        token, _ = accounts.new_session(user['id'])
        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(
            USER_COOKIE, token, httponly=True, samesite='lax',
            secure=settings.effective()['cookie_secure'], max_age=SESSION_SECONDS, path='/'
        )
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/account/login', response_class=HTMLResponse)
    def account_login_page(request: Request):
        return account_page(request, 'login', next_url=request.query_params.get('next', '/dashboard'))

    @app.post('/account/login')
    def account_login(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        next_url: str = Form('/dashboard', alias='next'),
    ):
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Cross-origin writes are disabled')
        next_url = safe_next_url(next_url)
        user = accounts.authenticate(email, password)
        if not user:
            return account_page(request, 'login', '邮箱或密码不正确', email.strip(), next_url)
        accounts.logout(request.cookies.get(USER_COOKIE, ''))
        token, _ = accounts.new_session(user['id'])
        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(
            USER_COOKIE, token, httponly=True, samesite='lax',
            secure=settings.effective()['cookie_secure'], max_age=SESSION_SECONDS, path='/'
        )
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/account/logout')
    def account_logout(request: Request, csrf: str = Form(...)):
        user = account_session(request)
        if not user or not secrets.compare_digest(csrf, user['csrf']):
            raise HTTPException(403, '会话校验失败，请刷新页面')
        accounts.logout(request.cookies.get(USER_COOKIE, ''))
        response = RedirectResponse('/', status_code=303)
        response.delete_cookie(USER_COOKIE, path='/')
        return response

    @app.get('/account/settings', response_class=HTMLResponse)
    def account_settings(request: Request):
        user = account_session(request)
        if not user:
            return RedirectResponse('/account/login?next=%2Faccount%2Fsettings', status_code=303)
        return templates.TemplateResponse(
            request=request,
            name='account_settings.html',
            context={'user': user, 'changed': request.query_params.get('changed') == '1', 'error': ''},
            headers={'Cache-Control': 'no-store'},
        )

    @app.post('/account/password')
    def change_account_password(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...),
        csrf: str = Form(...),
    ):
        user = account_session(request)
        if not user:
            return RedirectResponse('/account/login?next=%2Faccount%2Fsettings', status_code=303)
        if not secrets.compare_digest(csrf, user['csrf']):
            raise HTTPException(403, '会话校验失败，请刷新页面')
        if new_password != confirm_password:
            return templates.TemplateResponse(
                request=request,
                name='account_settings.html',
                context={'user': user, 'changed': False, 'error': '两次输入的新密码不一致'},
                status_code=400,
                headers={'Cache-Control': 'no-store'},
            )
        try:
            accounts.change_password(user['id'], current_password, new_password)
        except ValueError as exc:
            return templates.TemplateResponse(
                request=request,
                name='account_settings.html',
                context={'user': user, 'changed': False, 'error': str(exc)},
                status_code=400,
                headers={'Cache-Control': 'no-store'},
            )
        token, _ = accounts.new_session(user['id'])
        response = RedirectResponse('/account/settings?changed=1', status_code=303)
        response.set_cookie(
            USER_COOKIE, token, httponly=True, samesite='lax',
            secure=settings.effective()['cookie_secure'], max_age=SESSION_SECONDS, path='/'
        )
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/dashboard', response_class=HTMLResponse)
    def dashboard(request: Request):
        user = account_session(request)
        if not user:
            return RedirectResponse('/account/login', status_code=303)
        owned = []
        for item in sorted(jobs.values(), key=lambda value: value.get('created_at', 0), reverse=True):
            if item.get('owner_id') != user['id']:
                continue
            entry = dict(item)
            source_type = entry.get('source_type', 'upload')
            entry['source_type'] = source_type
            entry['project_name'] = entry.get('project_name') or ('GitHub project' if source_type == 'github' else 'Python project')
            entry['source_label'] = entry.get('repository_url') or ('本地上传 · ' + (entry.get('dependency_source') or 'Python'))
            entry['created_label'] = time.strftime('%m-%d %H:%M', time.localtime(entry.get('created_at', time.time())))
            owned.append(entry)
        slots = import_slots(user)
        return templates.TemplateResponse(
            request=request, name='dashboard.html',
            context={
                'user': user,
                'jobs': owned[:30],
                'import_slots': slots,
                'import_blocked': slots == 0,
            },
            headers={'Cache-Control': 'no-store'},
        )

    @app.get('/api/account/me')
    def account_me(request: Request):
        user = account_session(request)
        if not user:
            raise HTTPException(401, '请先登录')
        return {key: value for key, value in user.items() if key != 'csrf'}

    @app.post('/api/uploads')
    async def upload(request: Request, file: UploadFile = File(...)):
        user = account_session(request)
        with lock:
            ensure_import_slot(user)
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
                   dependencies=analysis.packages, dependency_source=analysis.dependency_source, plan=plan, created_at=time.time(), terminal=False,
                   source_type='upload', owner_id=user['id'] if user else None,
                   project_name=Path(file.filename or 'Python project').stem[:120] or 'Python project')
        try:
            with lock:
                ensure_import_slot(user)
                jobs[job_id] = job
                persist(job)
        except HTTPException:
            if upload_dir.exists() and not upload_dir.is_symlink() and upload_dir.resolve().parent == (root / 'uploads').resolve():
                shutil.rmtree(upload_dir.resolve())
            raise
        return job

    @app.post('/api/repositories')
    def import_repository(request: Request, payload: dict):
        user = account_session(request)
        with lock:
            ensure_import_slot(user)
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
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=400, content={
                'detail': safe_git_diagnostic(str(exc)),
                'code': exc.code if isinstance(exc, RepositoryImportError) else 'repository_import_error',
            })
        job = dict(id=job_id, status='READY', source=str(source), entries=[str(p.relative_to(analysis.project_root)) for p in entries],
                   entry=str(analysis.entry_point.relative_to(analysis.project_root)) if analysis.entry_point else None,
                   dependencies=analysis.packages, dependency_source=analysis.dependency_source, plan=plan, created_at=time.time(), terminal=False,
                   source_type='github', repository_url=payload.get('url', '').strip(), repository_ref=(payload.get('ref') or '').strip() or None,
                   owner_id=user['id'] if user else None,
                   project_name=(payload.get('url', '').rstrip('/').rsplit('/', 1)[-1].removesuffix('.git') or 'GitHub project')[:120])
        try:
            with lock:
                ensure_import_slot(user)
                jobs[job_id] = job
                persist(job)
        except HTTPException:
            if upload_dir.exists() and not upload_dir.is_symlink() and upload_dir.resolve().parent == (root / 'uploads').resolve():
                shutil.rmtree(upload_dir.resolve())
            raise
        return job

    @app.get('/api/jobs/{job_id}/plan')
    def preview(request: Request, job_id: str, entry: str, mode: str = 'onefile'):
        job = get_job_for_request(job_id, request)
        if entry not in job['entries'] or mode not in {'onefile', 'onedir'}:
            raise HTTPException(400, '请选择有效入口和输出格式')
        analysis = analyze_project(job['source'])
        builder = make_builder()
        return builder.experiences.plan(analysis, analysis.project_root / entry, mode=mode).to_dict()

    @app.post('/api/jobs/{job_id}/build')
    def start(request: Request, job_id: str, entry: str = Form(...), mode: str = Form('onefile')):
        user = account_session(request)
        if not user:
            raise HTTPException(401, '请先登录或注册，再开始 Windows 构建')
        job = get_job_for_request(job_id, request)
        with lock:
            if job['status'] != 'READY':
                raise HTTPException(409, '任务已开始')
            if entry not in job['entries'] or mode not in {'onefile', 'onedir'}:
                raise HTTPException(400, '请选择有效入口和输出格式')
            if sum(not item.get('terminal') and item['status'] != 'READY' for item in jobs.values()) >= 8:
                raise HTTPException(429, '构建队列已满，请稍后重试')
            if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
                raise HTTPException(403, '会话校验失败，请刷新页面')
            if job.get('owner_id') not in (None, user['id']):
                raise HTTPException(404, '任务不存在')
            if not job.get('owner_id'):
                ensure_import_slot(user)
                job['owner_id'] = user['id']
            try:
                accounts.consume_build(user['id'])
            except ValueError as exc:
                raise HTTPException(402, str(exc)) from exc
            job.update(status='QUEUED', terminal=False, cancel_requested=False)
            persist(job)
            future = pool.submit(run_job, job_id, entry, mode)
            futures[job_id] = future
        return {'id': job_id, 'status': 'QUEUED'}


    @app.post('/api/jobs/{job_id}/claim')
    def claim_job(request: Request, job_id: str):
        user = account_session(request)
        if not user:
            raise HTTPException(401, '请先登录')
        if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
            raise HTTPException(403, '会话校验失败，请刷新页面')
        with lock:
            job = get_job(job_id)
            if job.get('owner_id') and job.get('owner_id') != user['id']:
                raise HTTPException(404, '任务不存在')
            if job.get('status') != 'READY':
                if job.get('owner_id') == user['id']:
                    return job
                raise HTTPException(409, '只有待构建项目可以关联到账号')
            if not job.get('owner_id'):
                ensure_import_slot(user)
                job['owner_id'] = user['id']
                persist(job)
            return job

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel_job(request: Request, job_id: str):
        job, user = get_owned_job(job_id, request)
        if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
            raise HTTPException(403, '会话校验失败，请刷新页面')
        with lock:
            status = job.get('status')
            if status == 'READY':
                raise HTTPException(409, '项目尚未开始构建，可直接删除项目')
            if job.get('terminal') or status in {'SUCCESS','FAILED','NEEDS_MANUAL_REVIEW','EXPIRED','CANCELED'}:
                raise HTTPException(409, '当前任务已经结束，无法取消')
            job['cancel_requested'] = True
            future = futures.get(job_id)
            if status == 'QUEUED' and future is not None and future.cancel():
                futures.pop(job_id, None)
                job.update(status='CANCELED', error='Build cancelled before execution', terminal=True)
                accounts.refund_build(user['id'])
                persist(job)
                return {'id': job_id, 'status': 'CANCELED', 'quota_refunded': True}
            job['status'] = 'CANCELING'
            persist(job)
            builder = active_builders.get(job_id)
            if builder is not None:
                builder.cancel()
        return {'id': job_id, 'status': 'CANCELING', 'quota_refunded': False}

    @app.delete('/api/jobs/{job_id}')
    def delete_job(request: Request, job_id: str):
        job, user = get_owned_job(job_id, request)
        if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
            raise HTTPException(403, '会话校验失败，请刷新页面')
        with lock:
            if not job.get('terminal') and job.get('status') != 'READY':
                raise HTTPException(409, '任务正在构建，请先取消并等待任务结束')
            futures.pop(job_id, None)
            active_builders.pop(job_id, None)
            jobs.pop(job_id, None)
            remove_job_files(job)
        return {'id': job_id, 'deleted': True}

    @app.get('/api/jobs/{job_id}')
    def status(request: Request, job_id: str):
        job = dict(get_job_for_request(job_id, request))
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
    def log(request: Request, job_id: str):
        job = get_job_for_request(job_id, request)
        path = Path(job['log']) if job.get('log') else None
        return {'text': path.read_text(encoding='utf-8', errors='replace')[-200000:] if path and path.exists() else ''}

    @app.get('/api/jobs/{job_id}/download')
    def download(request: Request, job_id: str):
        job = get_job_for_request(job_id, request)
        if job['status'] != 'SUCCESS' or not job.get('terminal') or not job.get('artifact'):
            raise HTTPException(409, '文件尚未生成')
        artifact = Path(job['artifact'])
        if not artifact_available(job):
            raise HTTPException(410, '产物已过期或不可用')
        return FileResponse(artifact, filename=artifact.name)

    return app


app = create_app()
