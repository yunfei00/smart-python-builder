from __future__ import annotations

import json
import urllib.request
from typing import Protocol
from .settings import environment_settings, notification_secrets


class Notifier(Protocol):
    def send(self, event: dict) -> None: ...


class FakeNotifier:
    def __init__(self, fail=False):
        self.events=[]
        self.fail=fail

    def send(self,event):
        if self.fail:raise RuntimeError('Simulated notification outage')
        self.events.append(event)


class FeishuNotifier:
    def __init__(self, webhook=None):
        self.webhook=webhook if webhook is not None else environment_settings()[0]['feishu_webhook']
        if not self.webhook:raise ValueError('Configure BUILDER_FEISHU_WEBHOOK')

    def send(self,event):
        payload={'msg_type':'text','content':{'text':format_message(event)}}
        request=urllib.request.Request(self.webhook,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:
            data=json.loads(response.read(65536))
        if data.get('code',data.get('StatusCode',0)) != 0:
            raise RuntimeError('Feishu rejected notification')


def format_message(event):
    """Only display notification metadata, never raw diagnostics/configuration."""
    titles = {'Build Success': '✅ 构建成功', 'Build Failed': '❌ 构建失败',
              'AI Repair Success': '✅ AI 修复成功', 'AI Repair Failed': '⚠️ AI 修复失败'}
    kind = event.get('event')
    lines = ['Smart Python Builder', titles.get(kind, '飞书通知测试成功')]
    if kind in titles:
        lines.append(kind)
    for key, label in [('project', '项目'), ('build_id', 'Build ID'), ('entry', '入口'),
                       ('attempt_count', '尝试次数'), ('status', '状态'), ('mode', '输出格式'),
                       ('experience_candidate', '经验候选'), ('time', '时间')]:
        if event.get(key) is not None:
            lines.append(f'{label}：{event[key]}')
    if event.get('dependencies'):
        lines.append('依赖：' + ', '.join(event['dependencies']))
    for key, label in [('details_url', '查看任务'), ('approval_url', '管理员审批')]:
        if event.get(key):
            lines.extend(['', label + '：', event[key]])
    return '\n'.join(lines)


class NotificationService:
    def __init__(self, notifier=None, secret_values=()):
        self.notifier=notifier
        self.failures=[]
        self.secret_values = tuple(value for value in secret_values if value)

    def redact(self, value):
        if isinstance(value, str):
            for secret in sorted(self.secret_values, key=len, reverse=True):
                value = value.replace(secret, '[REDACTED]')
            return value
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()
                    if not any(word in key.lower() for word in ('password', 'secret', 'token', 'api_key', 'webhook'))}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def emit(self,event):
        if self.notifier is None:return
        try:self.notifier.send(self.redact(event))
        except Exception as exc:
            # Never propagate delivery failures into the build state machine.
            self.failures.append(type(exc).__name__)

    @classmethod
    def configured(cls, settings=None):
        settings = settings if settings is not None else environment_settings()[0]
        return cls(FeishuNotifier(settings['feishu_webhook']), notification_secrets(settings)) if settings['feishu_enabled'] and settings['feishu_webhook'] else cls()
