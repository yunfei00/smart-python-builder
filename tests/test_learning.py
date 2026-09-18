from pathlib import Path

from fastapi.testclient import TestClient

from builder.ai import FakeAIProvider
from builder.learning import ExperienceStore
from test_ai import make_builder,response
from web.app import create_app


def test_approved_experience_closes_loop(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({'hidden_imports':['colorsys']})])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:'colorsys' in r.plan.hidden_imports)
    first=builder.build(source)
    assert first.candidate_id
    store=builder.experience_store
    assert store.get(first.candidate_id)['status']=='CANDIDATE'
    from analyzer import analyze_project
    analysis=analyze_project(source)
    initial=builder.experiences.plan(analysis,source)
    assert store.apply(analysis,initial).hidden_imports==[]
    store.review(first.candidate_id,'APPROVED')
    second=builder.build(source)
    assert second.status=='SUCCESS' and len(second.attempts)==1
    assert len(provider.contexts)==1
    assert first.candidate_id in second.plan.matched_experiences
    # Persistence survives a new store instance.
    assert ExperienceStore(store.path).get(first.candidate_id)['status']=='APPROVED'


def test_admin_auth_and_rejection(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({'hidden_imports':['colorsys']})])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:'colorsys' in r.plan.hidden_imports)
    first=builder.build(source)
    with TestClient(create_app(tmp_path,admin_token='test-token')) as client:
        assert client.get('/api/admin/experiences').status_code==401
        headers={'Authorization':'Bearer test-token'}
        assert client.get('/api/admin/experiences',headers=headers).json()[0]['id']==first.candidate_id
        url='/api/admin/experiences/'+first.candidate_id
        invalid=response({'pyinstaller_args':['--runtime-hook=evil.py']})
        assert client.post(url,headers=headers,json={'decision':'APPROVED','repair_plan':invalid}).status_code==400
        assert client.post(url,headers=headers,json={'decision':'REJECTED'}).status_code==200
        assert client.post(url,headers=headers,json={'decision':'APPROVED'}).status_code==400
    assert builder.experience_store.list('APPROVED')==[]


def test_changed_source_does_not_match(tmp_path,monkeypatch):
    provider=FakeAIProvider([response({'hidden_imports':['colorsys']})])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r:'colorsys' in r.plan.hidden_imports)
    first=builder.build(source)
    builder.experience_store.review(first.candidate_id,'APPROVED')
    source.write_text('print(2)')
    from analyzer import analyze_project
    plan=builder.experiences.plan(analyze_project(source),source)
    assert plan.hidden_imports==[]


def test_admin_disabled_without_token(tmp_path,monkeypatch):
    # This legacy test verifies the truly uninitialized admin state. Do not
    # inherit the developer machine's password bootstrap environment.
    monkeypatch.delenv('BUILDER_ADMIN_TOKEN',raising=False)
    monkeypatch.delenv('BUILDER_ADMIN_PASSWORD',raising=False)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/admin/experiences').status_code==503
