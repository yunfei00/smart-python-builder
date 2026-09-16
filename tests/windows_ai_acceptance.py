from pathlib import Path
import sys,subprocess,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from builder import SmartBuilder
from builder.ai import FakeAIProvider
from builder.notifications import FakeNotifier, NotificationService

source=Path('.pytest-tmp-ai-real').resolve();source.mkdir(exist_ok=True)
(source/'main.py').write_text("import importlib\nm=importlib.import_module('color'+'sys')\nprint('repair-ok',m.rgb_to_hsv(1,0,0))\n")
def verify(path):
    p=subprocess.run([str(path)],capture_output=True,text=True,timeout=30)
    if p.returncode:raise RuntimeError(p.stderr)
    assert 'repair-ok' in p.stdout
provider=FakeAIProvider([dict(root_cause='Dynamic colorsys import missing',confidence=0.99,changes={'hidden_imports':['colorsys']},retry=True)])
notifier=FakeNotifier()
result=SmartBuilder(ai_provider=provider,artifact_validator=verify,notifications=NotificationService(notifier)).build(source)
assert result.status=='SUCCESS' and len(result.attempts)==2,result
assert len(provider.contexts)==1
assert [e['event'] for e in notifier.events]==['Build Failed','AI Repair Success']
Path('docs',sys.argv[1] if len(sys.argv)>1 else 'phase5-acceptance.json').write_text(json.dumps(dict(status=result.status,states=result.states,attempts=result.attempts,notifications=notifier.events,artifact=str(result.build.artifact),notes='Real EXE failed with missing colorsys, FakeAIProvider supplied validated hidden import, rebuilt EXE exited 0'),indent=2))
print(result.status,result.build.build_id)
