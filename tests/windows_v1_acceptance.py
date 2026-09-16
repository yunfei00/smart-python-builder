"""Run the V1 Windows acceptance matrix against real generated executables."""
from pathlib import Path
import io,json,subprocess,sys,time,uuid,struct,zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from builder import SmartBuilder
from builder.ai import FakeAIProvider
from builder.models import BuildPlan
from builder.notifications import FakeNotifier,NotificationService
from windows_acceptance import verify_executable
from analyzer import analyze_project

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'workspace'/('v1-'+uuid.uuid4().hex)
BASE.mkdir(parents=True)
records=[]
def record(case,result,notes):
    records.append(dict(case=case,status='PASS',build_id=result.build.build_id,artifact=str(result.build.artifact) if result.build.artifact else None,notes=notes))
    (ROOT/'docs'/'v1-acceptance.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
    print(case,'PASS',result.build.build_id,flush=True)
def project(name,code):
    path=BASE/name;path.mkdir();(path/'main.py').write_text(code,encoding='utf-8');return path
def build(source,**kwargs):
    result=SmartBuilder(BASE/'builds').build(source,**kwargs)
    assert result.build.success,(result.build.error,result.build.log_file)
    return result

def verify(path):
    completed=subprocess.run([str(path)],capture_output=True,text=True,timeout=90)
    if completed.returncode:raise RuntimeError(completed.stderr or 'EXE exit '+str(completed.returncode))
    return completed.stdout

simple=project('stdlib',"import json\nprint(json.dumps({'stdlib':True}))")
r=build(simple);assert json.loads(verify(r.build.artifact))['stdlib'];record('stdlib CLI',r,'EXE exit 0, JSON output verified')

code='''import io,json
from pathlib import Path
import requests,pandas as pd,openpyxl,numpy as np,cv2,serial,yaml
from PIL import Image
from helpers import message
root=Path(__file__).parent
out={}
out['requests']=requests.Request('GET','https://example.invalid').prepare().method=='GET'
out['pandas']=int(pd.DataFrame({'x':[1,2]}).x.sum())==3
book=openpyxl.Workbook();book.active['A1']='ok';buffer=io.BytesIO();book.save(buffer);buffer.seek(0)
out['openpyxl']=openpyxl.load_workbook(buffer).active['A1'].value=='ok'
out['numpy']=int(np.arange(4).sum())==6
out['OpenCV']=cv2.cvtColor(np.zeros((2,2,3),dtype=np.uint8),cv2.COLOR_BGR2GRAY).shape==(2,2)
out['Pillow']=Image.open(root/'pixel.png').size==(1,1)
with serial.serial_for_url('loop://',timeout=1) as port:
    port.write(b'ok');out['pyserial']=port.read(2)==b'ok'
out['PyYAML']=yaml.safe_load('value: 1')['value']==1
out['multi-file project']=message()=='helper-ok'
out['JSON config']=json.loads((root/'config.json').read_text())['value']=='config-ok'
out['image assets']=out['Pillow']
print(json.dumps(out))
assert all(out.values()),out
'''
source=project('libraries',code)
(source/'helpers.py').write_text("def message(): return 'helper-ok'\n")
(source/'requirements.txt').write_text('requests\npandas\nopenpyxl\nnumpy\nopencv-python\nPillow\npyserial\nPyYAML\n')
(source/'config.json').write_text('{"value":"config-ok"}')
def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
(source/'pixel.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00'))+chunk(b'IEND',b''))
a=analyze_project(source)
b=SmartBuilder(BASE/'builds');plan=b.experiences.plan(a,a.entry_point);plan.data_files=[['pixel.png','.'],['config.json','.']]
r=b.build(source,plan=plan);assert r.build.success,(r.build.error,r.build.log_file)
output=json.loads(verify(r.build.artifact));assert all(output.values())
for case in output:record(case,r,'EXE exit 0; functional check '+case+' = true')
assert r.plan.dependency_source=='requirements.txt';record('requirements project',r,'Declared dependencies used; combined EXE functional checks passed')

for name,code in [
    ('Tkinter',"import tkinter as tk\nr=tk.Tk();tk.Label(r,text='V1 Tkinter').pack();r.mainloop()"),
    ('PySide6',"from PySide6.QtWidgets import QApplication,QLabel\na=QApplication([]);w=QLabel('V1 PySide6');w.show();a.exec()"),
    ('PyQt6',"from PyQt6.QtWidgets import QApplication,QLabel\na=QApplication([]);w=QLabel('V1 PyQt6');w.show();a.exec()"),
]:
    r=build(project(name,code));record(name,r,verify_executable(r.build.artifact,gui=True))

source=project('metadata',"print('pyproject-ok')")
(source/'pyproject.toml').write_text('[project]\nname="demo"\nversion="1.0"\ndependencies=[]\n')
(source/'requirements.txt').write_text('this-must-not-be-installed\n')
r=build(source);assert r.plan.dependency_source=='pyproject.toml';assert 'pyproject-ok' in verify(r.build.artifact);record('pyproject project',r,'pyproject overrides requirements; EXE exit 0')

source=project('failure',"raise RuntimeError('intentional-v1-failure')")
fake=FakeNotifier()
r=SmartBuilder(BASE/'builds',artifact_validator=verify,notifications=NotificationService(fake)).build(source)
assert not r.build.success and r.status=='FAILED';assert fake.events[0]['event']=='Build Failed';record('normal build failure',r,'Intentional EXE runtime failure correctly reported and notified')
provider=FakeAIProvider([dict(root_cause='Unrepairable application error',confidence=0.5,changes={},retry=True)]*2)
r=SmartBuilder(BASE/'builds',artifact_validator=verify,ai_provider=provider,notifications=NotificationService(fake)).build(source)
assert not r.build.success and r.status=='NEEDS_MANUAL_REVIEW' and len(provider.contexts)==2 and len(r.attempts)==3
assert fake.events[-1]['event']=='AI Repair Failed';record('AI repair failure',r,'3 real failing EXEs; 2 AI calls; manual review; notification delivered')

source=project('learn-first',"import importlib\nm=importlib.import_module('color'+'sys')\nprint(m.rgb_to_hsv(1,0,0))")
provider=FakeAIProvider([dict(root_cause='Dynamic import missing',confidence=1.0,changes={'hidden_imports':['colorsys']},retry=True)])
b=SmartBuilder(BASE/'builds',artifact_validator=verify,ai_provider=provider)
r=b.build(source);assert r.build.success and len(r.attempts)==2;record('AI repair success',r,'Real EXE missing module repaired; rebuilt EXE exit 0')
b.experience_store.review(r.candidate_id,'APPROVED')
second=project('learn-second',(source/'main.py').read_text())
r=b.build(second);assert r.build.success and len(r.attempts)==1 and len(provider.contexts)==1
record('approved experience hit',r,'Second independent project first attempt succeeds; no additional AI call')
assert len(records)>=20
print('V1 MATRIX PASS:',len(records),'checks',flush=True)
