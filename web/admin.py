"""Password sessions and the existing automation Bearer credential."""
import secrets
import threading
import time
from datetime import datetime, timezone

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from builder.ai import configured_provider
from builder.notifications import FeishuNotifier

COOKIE = 'builder_admin'


def register_admin(app, templates, settings, admin_token=None, ai_factory=None, notifier_factory=None):
    admin_token = admin_token or settings.effective()['admin_token']
    failures = {}
    login_lock = threading.Lock()

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

    @app.get('/admin/settings')
    def settings_page(request: Request):
        return page(request, 'settings.html')

    @app.get('/api/admin/settings', dependencies=[Depends(admin)])
    def read_settings():
        return settings.public()

    @app.post('/api/admin/settings', dependencies=[Depends(admin)])
    def save_settings(payload: dict):
        try:
            result = settings.save(payload)
        except (ValueError, TypeError):
            raise HTTPException(400, '配置无效，请检查 Hosts、天数、服务地址和字段格式') from None
        restart = bool({'allowed_hosts', 'retention_days'} & payload.keys())
        return {'settings': result, 'message': '保存成功，重启 Smart Python Builder 后生效。' if restart else '保存成功，新构建将使用当前设置。'}

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
