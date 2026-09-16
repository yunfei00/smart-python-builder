from pathlib import Path

import pytest

from builder import SmartBuilder, BuildResult
from builder.ai import FakeAIProvider, RepairPlan
from builder.models import BuildPlan


def response(changes, retry=True):
    return dict(root_cause='test diagnosis',confidence=0.9,changes=changes,retry=retry)


@pytest.mark.parametrize('changes,field,value', [
    ({'add_dependencies':['requests']},'dependencies','requests'),
    ({'hidden_imports':['colorsys']},'hidden_imports','colorsys'),
    ({'data_files':[['config.json','.']]},'data_files',['config.json','.']),
    ({'remove_dependencies':['cv2'],'add_dependencies':['opencv-python']},'dependencies','opencv-python'),
    ({'remove_pyinstaller_args':['--broken'],'pyinstaller_args':['--noupx']},'pyinstaller_args','--noupx'),
])
def test_repair_scenarios(tmp_path,changes,field,value):
    (tmp_path/'main.py').write_text('print(1)')
    (tmp_path/'config.json').write_text('{}')
    plan=BuildPlan('main.py')
    if 'remove_dependencies' in changes:plan.dependencies=['cv2']
    if 'remove_pyinstaller_args' in changes:plan.pyinstaller_args=['--broken']
    repaired=RepairPlan.model_validate(response(changes)).apply(plan,tmp_path)
    assert value in getattr(repaired,field)
    assert '--broken' not in repaired.pyinstaller_args
    assert 'cv2' not in repaired.dependencies


def make_builder(tmp_path, monkeypatch, provider, succeeds):
    source=tmp_path/'main.py';source.write_text('print(1)')
    builder=SmartBuilder(tmp_path/'workspace',ai_provider=provider)
    calls=[]
    def build(request):
        calls.append(request)
        workspace=tmp_path/'workspace'/str(len(calls));workspace.mkdir()
        log=workspace/'build.log';log.write_text('missing module colorsys')
        return BuildResult(str(len(calls)),succeeds(request),workspace,None,log,'missing module')
    monkeypatch.setattr(builder.engine,'build',build)
    return builder,source,calls


def test_repair_success_and_context(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({'hidden_imports':['colorsys']})])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:'colorsys' in r.plan.hidden_imports)
    result=builder.build(source)
    assert result.status=='SUCCESS' and len(calls)==2
    assert result.states==['BUILDING','FAILED','AI_DIAGNOSING','AI_REPAIRING','REBUILDING','SUCCESS']
    assert provider.contexts[0]['previous_attempts']
    assert provider.contexts[0]['pyinstaller_log']


def test_repair_limit(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({})]*5)
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:False)
    result=builder.build(source)
    assert result.status=='NEEDS_MANUAL_REVIEW'
    assert len(calls)==3 and len(provider.contexts)==2


def test_rejects_ai_shell(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({'pyinstaller_args':['--runtime-hook=evil.py']})])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:False)
    result=builder.build(source)
    assert result.status=='NEEDS_MANUAL_REVIEW' and len(calls)==1


def test_unknown_fields_rejected():
    with pytest.raises(ValueError):RepairPlan.model_validate({**response({}),'shell':'echo hacked'})


def test_provider_http_contract(monkeypatch):
    import io,json
    from builder.ai import OpenAICompatibleProvider
    received={}
    def urlopen(request,timeout):
        received.update(json.loads(request.data))
        assert timeout==60
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(response({}))}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    result=OpenAICompatibleProvider('test-key','https://example.invalid/v1','test-model').diagnose({'error':'failed'})
    assert result['retry'] is True
    assert received['response_format']=={'type':'json_object'}
    assert received['model']=='test-model'
