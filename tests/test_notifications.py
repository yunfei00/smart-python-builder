from builder.ai import FakeAIProvider
from builder.notifications import FakeNotifier, NotificationService, FeishuNotifier
from test_ai import make_builder, response


def test_failure_then_repair_success_notifications(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({'hidden_imports':['colorsys']})])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:'colorsys' in r.plan.hidden_imports)
    fake=FakeNotifier();builder.notifications=NotificationService(fake)
    result=builder.build(source)
    assert result.status=='SUCCESS'
    assert [e['event'] for e in fake.events]==['Build Failed','AI Repair Success']
    assert fake.events[0]['ai_diagnosis_started']
    assert fake.events[1]['attempts']==[{'number':1,'success':False},{'number':2,'success':True}]
    assert fake.events[1]['diagnoses'][0]['changes']['hidden_imports']==['colorsys']


def test_failure_notifications(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({})]*2)
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:False)
    fake=FakeNotifier();builder.notifications=NotificationService(fake)
    assert builder.build(source).status=='NEEDS_MANUAL_REVIEW'
    assert [e['event'] for e in fake.events]==['Build Failed','AI Repair Failed']
    assert len(fake.events[-1]['attempts'])==3


def test_notification_outage_does_not_break_repair(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({'hidden_imports':['colorsys']})])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:'colorsys' in r.plan.hidden_imports)
    builder.notifications=NotificationService(FakeNotifier(fail=True))
    assert builder.build(source).status=='SUCCESS'
    assert len(builder.notifications.failures)==2


def test_feishu_contract(monkeypatch):
    import io,json
    def urlopen(request,timeout):
        assert timeout==5
        assert json.loads(request.data)['msg_type']=='text'
        return io.BytesIO(b'{"code":0}')
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    FeishuNotifier('https://example.invalid/hook').send({'event':'Build Failed'})
