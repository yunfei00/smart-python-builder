"""Password sessions and the existing automation Bearer credential."""
import secrets
import threading
import time
from datetime import datetime, timezone

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from builder.ai import configured_provider
from builder.notifications import FeishuNotifier
from .maintenance import cleanup_jobs, disk_usage

COOKIE = 'builder_admin'


def register_admin(
    app,
    templates,
    settings,
    admin_token=None,
    ai_factory=None,
    notifier_factory=None,
    accounts=None,
    *,
    runtime=None,
    feedback_store=None,
):
    admin_token = admin_token or settings.effective()['admin_token']
    failures = {}
    login_lock = threading.Lock()
    runtime = runtime or {}

    def session(request):
        return settings.session(request.cookies.get(COOKIE, ''))

    def admin(request: Request):
        authorization = request.headers.get('authorization', '')
        if admin_token and secrets.compare_digest(authorization, 'Bearer ' + admin_token):
            return
        csrf = session(request)
        if csrf:
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), csrf):
                raise HTTPException(403, '会话校验失败，请刷新页面')
            return
        if not admin_token and not settings.initialized():
            raise HTTPException(503, '管理员尚未初始化，请设置 BUILDER_ADMIN_PASSWORD')
        raise HTTPException(401, '请先登录管理员')

    @app.get('/admin/login')
    def login_page(request: Request):
        return templates.TemplateResponse(request=request, name='login.html', context={'initialized': settings.initialized(), 'error': ''}, headers={'Cache-Control': 'no-store'})

    @app.post('/admin/login')
    def login(request: Request, password: str = Form(...)):
        # Browser forms without Origin are still protected against cross-site login.
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Cross-origin writes are disabled')
        address = request.client.host if request.client else 'unknown'
        with login_lock:
            now = time.monotonic()
            for key in list(failures):
                if failures[key][1] < now - 300:
                    failures.pop(key)
            count, last = failures.get(address, (0, now))
            if count >= 10:
                raise HTTPException(429, '登录尝试过多，请五分钟后重试')
            if not settings.authenticate(password):
                failures[address] = (count + 1, last)
                return templates.TemplateResponse(request=request, name='login.html', context={'initialized': settings.initialized(), 'error': '密码错误或管理员尚未初始化'}, status_code=401, headers={'Cache-Control': 'no-store'})
            failures.pop(address, None)
        settings.logout(request.cookies.get(COOKIE, ''))
        response = RedirectResponse('/admin', status_code=303)
        response.set_cookie(COOKIE, settings.new_session(), httponly=True, samesite='lax', secure=settings.effective()['cookie_secure'], max_age=28800, path='/')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/admin/logout', dependencies=[Depends(admin)])
    def logout(request: Request):
        settings.logout(request.cookies.get(COOKIE, ''))
        response = RedirectResponse('/admin/login', status_code=303)
        response.delete_cookie(COOKIE, path='/')
        return response

    def page(request, name):
        csrf = session(request)
        if not csrf:
            return RedirectResponse('/admin/login', status_code=303)
        return templates.TemplateResponse(request=request, name=name, context={'csrf': csrf}, headers={'Cache-Control': 'no-store'})

    @app.get('/admin')
    def experience_page(request: Request):
        return page(request, 'admin.html')

    @app.get('/admin/overview')
    def overview_page(request: Request):
        return page(request, 'overview.html')

    @app.get('/admin/feedback')
    def feedback_page(request: Request):
        return page(request, 'feedback_admin.html')

    @app.get('/admin/settings')
    def settings_page(request: Request):
        return page(request, 'settings.html')

    @app.get('/admin/users')
    def users_page(request: Request):
        return page(request, 'users.html')


    def default_free_quota():
        values = settings.effective()
        return values['family_free_quota'] if values['service_mode'] == 'family_free' else 3

    def build_jobs():
        jobs = runtime.get('jobs') or {}
        return [
            job for job in jobs.values()
            if job.get('started_at') or job.get('status') not in {None, 'READY'}
        ]

    def build_counts_by_owner():
        counts = {}
        for job in build_jobs():
            owner_id = job.get('owner_id')
            if owner_id:
                counts[owner_id] = counts.get(owner_id, 0) + 1
        return counts

    @app.get('/api/admin/users', dependencies=[Depends(admin)])
    def list_users(search: str = '', plan: str = '', disabled: str = ''):
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        values = settings.effective()
        try:
            users = accounts.list_users(search=search, plan=plan, disabled=disabled)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        counts = build_counts_by_owner()
        for user in users:
            user['build_count'] = counts.get(user['id'], 0)
        return {
            'users': users,
            'summary': accounts.user_summary(),
            'service_mode': values['service_mode'],
            'default_free_quota': default_free_quota(),
            'family_free_quota': values['family_free_quota'],
        }

    @app.post('/api/admin/users', dependencies=[Depends(admin)])
    def create_user(payload: dict):
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        try:
            return accounts.create_managed_user(
                payload.get('username', ''),
                payload.get('password', ''),
                email=payload.get('email'),
                plan=payload.get('plan', 'FREE'),
                remaining=payload.get('remaining', default_free_quota()),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/admin/users/{user_id}/password', dependencies=[Depends(admin)])
    def reset_user_password(user_id: str, payload: dict):
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        try:
            return accounts.reset_password(user_id, payload.get('password', ''))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/admin/users/{user_id}/plan', dependencies=[Depends(admin)])
    def set_user_plan(user_id: str, payload: dict):
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        try:
            return accounts.set_plan_by_id(
                user_id,
                payload.get('plan', ''),
                default_free_quota=default_free_quota(),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/admin/users/{user_id}/quota', dependencies=[Depends(admin)])
    def set_user_quota(user_id: str, payload: dict):
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        try:
            return accounts.set_remaining_quota(user_id, payload.get('remaining'))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/admin/users/{user_id}/quota/reset', dependencies=[Depends(admin)])
    def reset_user_quota(user_id: str):
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        try:
            return accounts.reset_quota(user_id, default_free_quota=default_free_quota())
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post('/api/admin/users/{user_id}/disabled', dependencies=[Depends(admin)])
    def set_user_disabled(user_id: str, payload: dict):
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        disabled = payload.get('disabled')
        if type(disabled) is not bool:
            raise HTTPException(400, 'disabled 必须为布尔值')
        try:
            return accounts.set_disabled(user_id, disabled)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post('/api/admin/users/free-quota/top-up', dependencies=[Depends(admin)])
    def top_up_free_users():
        if accounts is None:
            raise HTTPException(503, '用户管理尚未启用')
        values = settings.effective()
        if values['service_mode'] != 'family_free':
            raise HTTPException(400, '请先切换到家庭免费模式')
        result = accounts.top_up_free_users(values['family_free_quota'])
        return {
            **result,
            'message': f"已将 {result['updated']} 个 FREE 用户的剩余额度补到 {result['remaining']} 次",
        }

    @app.get('/api/admin/overview', dependencies=[Depends(admin)])
    def overview():
        jobs = list((runtime.get('jobs') or {}).values())
        built = [
            job for job in jobs
            if job.get('started_at') or job.get('status') not in {None, 'READY'}
        ]
        today = time.localtime()
        day_start = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
        today_builds = sum(
            (job.get('started_at') or job.get('created_at') or 0) >= day_start
            for job in built
        )
        successes = sum(job.get('status') == 'SUCCESS' for job in built)
        failures = sum(job.get('status') in {'FAILED', 'NEEDS_MANUAL_REVIEW'} for job in built)
        completed = successes + failures
        ai_repairs = 0
        for job in built:
            for attempt in job.get('attempts', []):
                if not isinstance(attempt, dict):
                    continue
                repair = attempt.get('repair')
                if isinstance(repair, dict) and repair.get('retry'):
                    ai_repairs += 1

        statuses = [job.get('status') for job in jobs]
        queued = statuses.count('QUEUED')
        running = sum(status in {'BUILDING', 'AI_DIAGNOSING', 'AI_REPAIRING', 'REBUILDING'} for status in statuses)
        canceling = statuses.count('CANCELING')
        root = runtime.get('root')
        storage = disk_usage(root) if root is not None else {
            'total_bytes': 0, 'uploads_bytes': 0, 'workspace_bytes': 0,
            'database_bytes': 0, 'metadata_bytes': 0,
        }
        feedback = feedback_store.summary() if feedback_store is not None else {'total': 0, 'new': 0, 'resolved': 0}
        return {
            'users': accounts.user_summary() if accounts is not None else {'total': 0, 'enabled': 0, 'free': 0, 'test': 0},
            'builds': {
                'total': len(built),
                'today': int(today_builds),
                'success': int(successes),
                'failed': int(failures),
                'success_rate': round(successes * 100 / completed, 1) if completed else None,
                'ai_repairs': int(ai_repairs),
            },
            'queue': {
                'queued': int(queued),
                'running': int(running),
                'canceling': int(canceling),
                'active_slots': int(queued + running + canceling),
                'limit': 8,
                'workers': 1,
                'futures': len(runtime.get('futures') or {}),
                'active_builders': len(runtime.get('active_builders') or {}),
            },
            'disk': storage,
            'feedback': feedback,
            'retention_days': settings.effective()['retention_days'],
        }

    @app.get('/api/admin/maintenance/cleanup-preview', dependencies=[Depends(admin)])
    def cleanup_preview():
        root = runtime.get('root')
        jobs = runtime.get('jobs')
        if root is None or jobs is None:
            raise HTTPException(503, '运行时清理服务尚未启用')
        retention = settings.effective()['retention_days'] * 86400
        lock = runtime.get('lock')
        if lock is None:
            return cleanup_jobs(root, jobs, retention, dry_run=True)
        with lock:
            return cleanup_jobs(root, jobs, retention, dry_run=True)

    @app.post('/api/admin/maintenance/cleanup', dependencies=[Depends(admin)])
    def cleanup_now():
        root = runtime.get('root')
        jobs = runtime.get('jobs')
        if root is None or jobs is None:
            raise HTTPException(503, '运行时清理服务尚未启用')
        retention = settings.effective()['retention_days'] * 86400
        lock = runtime.get('lock')
        if lock is None:
            result = cleanup_jobs(root, jobs, retention, dry_run=False)
        else:
            with lock:
                result = cleanup_jobs(root, jobs, retention, dry_run=False)
        return {
            **result,
            'message': f"已清理 {result['count']} 条过期构建记录",
        }

    @app.get('/api/admin/feedback', dependencies=[Depends(admin)])
    def list_feedback(search: str = '', status: str = '', category: str = ''):
        if feedback_store is None:
            raise HTTPException(503, '用户反馈尚未启用')
        try:
            return {
                'items': feedback_store.list_admin(search=search, status=status, category=category),
                'summary': feedback_store.summary(),
            }
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/admin/feedback/{identifier}/status', dependencies=[Depends(admin)])
    def update_feedback(identifier: str, payload: dict):
        if feedback_store is None:
            raise HTTPException(503, '用户反馈尚未启用')
        try:
            return feedback_store.set_status(identifier, payload.get('status', ''))
        except ValueError as exc:
            raise HTTPException(404 if '不存在' in str(exc) else 400, str(exc)) from exc

    @app.get('/api/admin/settings', dependencies=[Depends(admin)])
    def read_settings():
        return settings.public()

    @app.post('/api/admin/settings', dependencies=[Depends(admin)])
    def save_settings(payload: dict):
        try:
            previous = settings.public()
            result = settings.save(payload)
        except (ValueError, TypeError):
            raise HTTPException(400, '配置无效：请检查 Hosts、天数及服务地址；Builder 地址须为 HTTP(S)，不能含查询、片段、凭证或 0.0.0.0。') from None
        restart = any(key in payload and previous[key] != result[key] for key in ('allowed_hosts',))
        return {'settings': result, 'message': '保存成功，重启 Smart Python Builder 后生效。Builder 访问地址立即用于后续通知（环境变量覆盖优先）。' if restart else '保存成功，后续请求将使用当前设置；Builder 访问地址立即用于后续通知。'}

    @app.post('/api/admin/settings/test-ai', dependencies=[Depends(admin)])
    def test_ai(payload: dict):
        try:
            values = settings.preview(payload)
            # Testing is explicit and is allowed while automatic AI repair is off.
            values['ai_enabled'] = True
            provider = (ai_factory or configured_provider)(values)
            if provider is None:
                raise ValueError('Missing AI configuration')
            provider.test_connection()
        except Exception:
            raise HTTPException(400, 'AI 连接失败，请检查 API 地址、模型、凭证和网络。') from None
        return {'message': 'AI 连接成功'}

    @app.post('/api/admin/settings/test-feishu', dependencies=[Depends(admin)])
    def test_feishu(payload: dict):
        try:
            values = settings.preview(payload)
            notifier = notifier_factory(values) if notifier_factory else FeishuNotifier(values['feishu_webhook'])
            notifier.send({'builder': 'Smart Python Builder', 'message': '飞书通知测试成功', 'time': datetime.now(timezone.utc).isoformat()})
        except Exception:
            raise HTTPException(400, '飞书测试失败，请检查 Webhook、机器人设置和网络。') from None
        return {'message': '飞书通知测试成功'}

    return admin
