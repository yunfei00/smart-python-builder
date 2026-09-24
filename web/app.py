from __future__ import annotations

import json
import shutil
import threading
import uuid
import zipfile
import time
import asyncio
from datetime import datetime, timezone
import contextlib
import re
import secrets
import os
import stat
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Depends
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from analyzer import analyze_project
from builder import SmartBuilder
from builder.learning import ExperienceStore
from builder.maintenance import cleanup_workspaces
from builder.notifications import NotificationService
from builder.settings import SettingsStore, allowed_hosts, environment_settings, notification_secrets
from .admin import register_admin
from .security import RequestLimitsMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .uploads import MAX_UPLOAD, save_upload
from .repositories import RepositoryImportError, clone_public_github_repository, safe_git_diagnostic
from .accounts import AccountStore, USER_COOKIE, SESSION_SECONDS
from .analytics import AnalyticsStore, repair_count_from_attempts
from .feedback import FeedbackStore
from .maintenance import cleanup_jobs, delete_job_files


def _allowed_hosts() -> list[str]:
    return allowed_hosts(environment_settings()[0]['allowed_hosts'])


def _normalize_entry_path(value: str) -> str:
    """Canonical project-relative entry path used by API, persisted jobs, and UI."""
    raw = (value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raise ValueError("empty entry path")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {".", ".."} for part in path.parts)
        or ":" in path.parts[0]
    ):
        raise ValueError(f"invalid entry path: {value}")
    return path.as_posix()


def _normalized_job_entries(job: dict) -> list[str]:
    normalized: list[str] = []
    for value in job.get("entries", []):
        try:
            entry = _normalize_entry_path(value)
        except ValueError:
            continue
        if entry not in normalized:
            normalized.append(entry)
    return normalized


def _safe_rmtree(path: Path) -> None:
    """Best-effort cleanup that does not hide the original import/build error."""
    def retry_readonly(function, filename, _exc_info):
        try:
            os.chmod(filename, stat.S_IWRITE)
            function(filename)
        except OSError:
            pass

    try:
        shutil.rmtree(path, onerror=retry_readonly)
    except OSError:
        pass


def create_app(root: Path | str = 'web-data', builder_factory=SmartBuilder, admin_token=None, *, ai_factory=None, notifier_factory=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = SettingsStore(root / 'settings.sqlite3')
    accounts = AccountStore(root / 'accounts.sqlite3')
    analytics = AnalyticsStore(root / 'analytics.sqlite3')
    feedback_store = FeedbackStore(root / 'feedback.sqlite3')
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
    analytics.backfill(jobs.values())

    @asynccontextmanager
    async def lifespan(app):
        def cleanup():
            retention = settings.effective()['retention_days'] * 86400
            cleanup_workspaces(root / 'workspace', retention_seconds=retention)
            with lock:
                cleanup_jobs(root, jobs, retention, dry_run=False)
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
    app.state.analytics = analytics
    app.state.feedback_store = feedback_store
    admin = register_admin(
        app,
        templates,
        settings,
        admin_token,
        ai_factory,
        notifier_factory,
        accounts=accounts,
        runtime={
            'jobs': jobs,
            'root': root,
            'futures': futures,
            'active_builders': active_builders,
            'lock': lock,
            'analytics': analytics,
        },
        feedback_store=feedback_store,
    )

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

    def default_free_quota():
        values = settings.effective()
        return values['family_free_quota'] if values['service_mode'] == 'family_free' else 3

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
        return delete_job_files(root, job)

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

    def run_job(job_id, entries, mode):
        job = get_job(job_id)
        with lock:
            if job.get('cancel_requested'):
                job.update(status='CANCELED', error='Build cancelled by user', terminal=True, finished_at=time.time())
                analytics.finish(
                    job_id,
                    'CANCELED',
                    finished_at=job['finished_at'],
                    user_id=job.get('owner_id'),
                    started_at=job.get('started_at') or job.get('created_at'),
                )
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
            if len(entries) == 1:
                result = builder.build(Path(job['source']), entry_point=entries[0], mode=mode)
                plans = [result.plan]
            else:
                analysis = analyze_project(job['source'])
                selected = [analysis.project_root / entry for entry in entries]
                plans = [builder.experiences.plan(analysis, entry, mode=mode) for entry in selected]
                for plan in plans:
                    plan.validate(analysis.project_root)
                build = builder.engine.build_many(analysis.source, selected, plans)
                from builder.smart import SmartBuildResult
                result = SmartBuildResult(analysis, build, plans[0], 'SUCCESS' if build.success else 'FAILED', [], ['BUILDING', 'SUCCESS' if build.success else 'FAILED'])
            job.update(build_id=result.build.build_id, plan=[plan.to_dict() for plan in plans] if len(plans) > 1 else plans[0].to_dict(), selected_entries=entries, log=str(result.build.log_file), attempts=result.attempts)
            if result.status == 'CANCELED' or job.get('cancel_requested'):
                job.update(status='CANCELED', error='Build cancelled by user')
            elif result.build.success:
                if len(entries) > 1:
                    bundle = result.build.workspace / 'artifacts'
                    bundle.mkdir(exist_ok=True)
                    for artifact in result.build.artifacts:
                        if artifact.is_dir():
                            target = Path(shutil.make_archive(str(bundle / artifact.name), 'zip', artifact.parent, artifact.name))
                        else:
                            target = bundle / artifact.name
                            shutil.copy2(artifact, target)
                    artifact = Path(shutil.make_archive(str(result.build.workspace / 'multi-apps'), 'zip', bundle))
                else:
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
                job.setdefault('finished_at', time.time())
                analytics.finish(
                    job_id,
                    job.get('status', 'UNKNOWN'),
                    finished_at=job['finished_at'],
                    ai_repairs=repair_count_from_attempts(job.get('attempts')),
                    user_id=job.get('owner_id'),
                    started_at=job.get('started_at') or job.get('created_at'),
                )
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

    def account_page(request, mode, error='', email='', next_url='/dashboard', *, username='', login=''):
        next_url = safe_next_url(next_url)
        user = account_session(request)
        if user:
            return RedirectResponse(next_url, status_code=303)
        return templates.TemplateResponse(
            request=request, name='account_auth.html',
            context={'mode': mode, 'error': error, 'email': email, 'next_url': next_url,
                     'username': username, 'login': login},
            headers={'Cache-Control': 'no-store'},
        )

    @app.get('/account/register', response_class=HTMLResponse)
    def register_page(request: Request):
        return account_page(request, 'register', next_url=request.query_params.get('next', '/dashboard'))

    @app.post('/account/register')
    def register_account(
        request: Request,
        username: str = Form(''),
        email: str = Form(''),
        password: str = Form(...),
        next_url: str = Form('/dashboard', alias='next'),
    ):
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Cross-origin writes are disabled')
        next_url = safe_next_url(next_url)
        try:
            user = accounts.create_user(
                username,
                password,
                email=email,
                remaining=default_free_quota(),
            )
        except ValueError as exc:
            return account_page(request, 'register', str(exc), email[:254], next_url, username=username[:32])
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
        login: str | None = Form(None),
        email: str = Form(''),
        password: str = Form(...),
        next_url: str = Form('/dashboard', alias='next'),
    ):
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Cross-origin writes are disabled')
        next_url = safe_next_url(next_url)
        identifier = login if login is not None else email
        user = accounts.authenticate(identifier, password)
        if not user:
            return account_page(request, 'login', '用户名、邮箱或密码不正确', next_url=next_url, login=identifier[:254])
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

    def feedback_items_for_user(user_id: str):
        category_labels = {
            'SUGGESTION': '功能建议',
            'BUG': '问题反馈',
            'EXPERIENCE': '使用体验',
            'OTHER': '其他',
        }
        status_labels = {'NEW': '待处理', 'READ': '已查看', 'RESOLVED': '已解决'}
        result = []
        for item in feedback_store.list_for_user(user_id):
            row = dict(item)
            row['category_label'] = category_labels.get(row.get('category'), row.get('category', ''))
            row['status_label'] = status_labels.get(row.get('status'), row.get('status', ''))
            row['created_label'] = time.strftime(
                '%Y-%m-%d %H:%M',
                time.localtime(row.get('created_at', time.time())),
            )
            result.append(row)
        return result

    @app.get('/feedback', response_class=HTMLResponse)
    def feedback_page(request: Request):
        user = account_session(request)
        if not user:
            return RedirectResponse('/account/login?next=%2Ffeedback', status_code=303)
        return templates.TemplateResponse(
            request=request,
            name='feedback.html',
            context={
                'user': user,
                'items': feedback_items_for_user(user['id']),
                'submitted': request.query_params.get('submitted') == '1',
                'error': '',
            },
            headers={'Cache-Control': 'no-store'},
        )

    @app.post('/feedback')
    def submit_feedback(
        request: Request,
        category: str = Form('OTHER'),
        message: str = Form(...),
        csrf: str = Form(...),
    ):
        user = account_session(request)
        if not user:
            return RedirectResponse('/account/login?next=%2Ffeedback', status_code=303)
        if not secrets.compare_digest(csrf, user['csrf']):
            raise HTTPException(403, '会话校验失败，请刷新页面')
        try:
            item = feedback_store.create(user, category, message)
        except ValueError as exc:
            return templates.TemplateResponse(
                request=request,
                name='feedback.html',
                context={
                    'user': user,
                    'items': feedback_items_for_user(user['id']),
                    'submitted': False,
                    'error': str(exc),
                },
                status_code=400,
                headers={'Cache-Control': 'no-store'},
            )

        values = settings.effective()
        if values.get('feedback_notifications'):
            notifications = (
                NotificationService(notifier_factory(values), notification_secrets(values))
                if notifier_factory is not None and values.get('feishu_enabled')
                else NotificationService.configured(values)
            )
            if notifications.notifier is not None:
                notifications.emit({
                    'event': 'User Feedback',
                    'username': user['username'],
                    'category': item['category'],
                    'message': item['message'][:800],
                    'time': datetime.now(timezone.utc).isoformat(),
                    'details_url': values['base_url'].rstrip('/') + '/admin/feedback',
                })
                feedback_store.set_notification_result(
                    item['id'],
                    notified=not notifications.failures,
                    error=notifications.failures[0] if notifications.failures else None,
                )
        return RedirectResponse('/feedback?submitted=1', status_code=303)

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
                _safe_rmtree(upload_dir.resolve())
            raise HTTPException(400, str(exc)) from exc
        job = dict(id=job_id, status='READY', source=str(source), entries=[p.relative_to(analysis.project_root).as_posix() for p in entries], entry_details=analysis.entry_details,
                   entry=analysis.entry_point.relative_to(analysis.project_root).as_posix() if analysis.entry_point else None,
                   dependencies=analysis.packages, dependency_source=analysis.dependency_source, plan=plan, created_at=time.time(), terminal=False,
                   source_type='upload', owner_id=user['id'] if user else None,
                   project_name=Path(file.filename or 'Python project').stem[:120] or 'Python project',
                   upload_filename=(file.filename or 'Python project')[:255])
        try:
            with lock:
                ensure_import_slot(user)
                jobs[job_id] = job
                persist(job)
        except HTTPException:
            if upload_dir.exists() and not upload_dir.is_symlink() and upload_dir.resolve().parent == (root / 'uploads').resolve():
                _safe_rmtree(upload_dir.resolve())
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
                _safe_rmtree(upload_dir.resolve())
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=400, content={
                'detail': safe_git_diagnostic(str(exc)),
                'code': exc.code if isinstance(exc, RepositoryImportError) else 'repository_import_error',
            })
        job = dict(id=job_id, status='READY', source=str(source), entries=[p.relative_to(analysis.project_root).as_posix() for p in entries], entry_details=analysis.entry_details,
                   entry=analysis.entry_point.relative_to(analysis.project_root).as_posix() if analysis.entry_point else None,
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
                _safe_rmtree(upload_dir.resolve())
            raise
        return job

    @app.get('/api/jobs/{job_id}/plan')
    def preview(request: Request, job_id: str, entry: str, mode: str = 'onefile'):
        job = get_job_for_request(job_id, request)
        try:
            normalized_entry = _normalize_entry_path(entry)
        except ValueError:
            raise HTTPException(400, '请选择有效入口和输出格式')
        allowed_entries = _normalized_job_entries(job)
        if normalized_entry not in allowed_entries or mode not in {'onefile', 'onedir'}:
            raise HTTPException(400, '请选择有效入口和输出格式')
        analysis = analyze_project(job['source'])
        builder = make_builder()
        return builder.experiences.plan(
            analysis, analysis.project_root / normalized_entry, mode=mode
        ).to_dict()

    @app.post('/api/jobs/{job_id}/build')
    def start(request: Request, job_id: str, entry: str = Form(''), entries: str = Form(''), mode: str = Form('onefile')):
        user = account_session(request)
        if not user:
            raise HTTPException(401, '请先登录或注册，再开始 Windows 构建')
        job = get_job_for_request(job_id, request)
        with lock:
            if job['status'] != 'READY':
                raise HTTPException(409, '任务已开始')
            raw_entries = [value for value in entries.split('|') if value] if entries else ([entry] if entry else [])
            try:
                selected_entries = [_normalize_entry_path(value) for value in raw_entries]
            except ValueError:
                raise HTTPException(400, '请选择有效入口和输出格式')
            allowed_entries = _normalized_job_entries(job)
            if (
                not selected_entries
                or any(value not in allowed_entries for value in selected_entries)
                or len(set(selected_entries)) != len(selected_entries)
                or mode not in {'onefile', 'onedir'}
            ):
                raise HTTPException(400, '请选择有效入口和输出格式')
            # Migrate persisted READY jobs created on Windows before entry paths
            # were canonicalized. This keeps old browser sessions buildable.
            if job.get('entries') != allowed_entries:
                job['entries'] = allowed_entries
                if job.get('entry'):
                    try:
                        job['entry'] = _normalize_entry_path(job['entry'])
                    except ValueError:
                        job['entry'] = None
                persist(job)
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
            job.update(status='QUEUED', terminal=False, cancel_requested=False, started_at=time.time())
            analytics.start(job_id, user['id'], job['started_at'])
            persist(job)
            future = pool.submit(run_job, job_id, selected_entries, mode)
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
                job.update(status='CANCELED', error='Build cancelled before execution', terminal=True, finished_at=time.time())
                analytics.finish(
                    job_id,
                    'CANCELED',
                    finished_at=job['finished_at'],
                    user_id=user['id'],
                    started_at=job.get('started_at') or job.get('created_at'),
                )
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
