from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol


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
        self.webhook=webhook or os.environ.get('BUILDER_FEISHU_WEBHOOK')
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
    def configured(cls):
        return cls(FeishuNotifier()) if os.environ.get('BUILDER_FEISHU_WEBHOOK') else cls()
