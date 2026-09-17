from __future__ import annotations

import json
import urllib.request
from typing import Protocol
from .settings import environment_settings


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
        payload={'msg_type':'text','content':{'text':json.dumps(event,ensure_ascii=False,indent=2)}}
        request=urllib.request.Request(self.webhook,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:
            data=json.loads(response.read(65536))
        if data.get('code',data.get('StatusCode',0)) != 0:
            raise RuntimeError('Feishu rejected notification')


class NotificationService:
    def __init__(self, notifier=None):
        self.notifier=notifier
        self.failures=[]

    def emit(self,event):
        if self.notifier is None:return
        try:self.notifier.send(event)
        except Exception as exc:
            # Never propagate delivery failures into the build state machine.
            self.failures.append(type(exc).__name__)

    @classmethod
    def configured(cls, settings=None):
        settings = settings if settings is not None else environment_settings()[0]
        return cls(FeishuNotifier(settings['feishu_webhook'])) if settings['feishu_enabled'] and settings['feishu_webhook'] else cls()
