from pathlib import Path
import json,sys,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from builder import BuildEngine,BuildRequest
root=Path('workspace')/('release-failure-'+uuid.uuid4().hex)
root.mkdir(parents=True)
source=root/'invalid.py';source.write_text('def broken(:\n')
result=BuildEngine().build(BuildRequest(source=source,app_name='expected-release-failure'))
assert not result.success and result.artifact is None
log=result.log_file.read_text(encoding='utf-8',errors='replace')
assert 'SyntaxError' in log and '[exit_code=1]' in log
record=dict(case='normal packaging failure',status='PASS',build_id=result.build_id,artifact=None,runtime_verification='Not applicable: packaging rejected invalid Python, no EXE generated',notes='Actual PyInstaller exit 1 and SyntaxError captured; build failed as expected',log=str(result.log_file))
root.joinpath('acceptance-result.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print('EXPECTED PACKAGING FAILURE PASS',result.build_id)
