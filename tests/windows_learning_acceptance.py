from pathlib import Path
import subprocess,json,sys,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from builder import SmartBuilder
from builder.ai import FakeAIProvider
from builder.learning import ExperienceStore
from fastapi.testclient import TestClient
from web.app import create_app

root=Path('.pytest-tmp-learning-'+uuid.uuid4().hex).resolve();root.mkdir()
code="import importlib\nm=importlib.import_module('color'+'sys')\nprint('learned-ok',m.rgb_to_hsv(1,0,0))\n"
def verify(path):
    p=subprocess.run([str(path)],capture_output=True,text=True,timeout=30)
    if p.returncode:raise RuntimeError(p.stderr)
    assert 'learned-ok' in p.stdout
provider=FakeAIProvider([dict(root_cause='dynamic import',confidence=1.0,changes={'hidden_imports':['colorsys']},retry=True)])
first_source=root/'first';first_source.mkdir();(first_source/'main.py').write_text(code)
second_source=root/'second';second_source.mkdir();(second_source/'main.py').write_text(code)
builder=SmartBuilder(root/'workspace',ai_provider=provider,artifact_validator=verify)
first=builder.build(first_source)
assert first.build.success and len(first.attempts)==2
with TestClient(create_app(root,admin_token='local-test-token')) as client:
    r=client.post('/api/admin/experiences/'+first.candidate_id,headers={'Authorization':'Bearer local-test-token'},json={'decision':'APPROVED'})
    assert r.status_code==200,r.text
second=builder.build(second_source)
assert second.build.success and len(second.attempts)==1
assert len(provider.contexts)==1
assert first.candidate_id in second.plan.matched_experiences
Path('docs/phase7-acceptance.json').write_text(json.dumps(dict(status='PASS',first_builds=first.attempts,candidate_id=first.candidate_id,second_builds=second.attempts,artifact=str(second.build.artifact),ai_calls=len(provider.contexts),notes='Real EXE failure, AI repair, authenticated HTTP approval, second project first-attempt EXE success without AI'),indent=2))
print('PASS',first.candidate_id,second.build.build_id)
