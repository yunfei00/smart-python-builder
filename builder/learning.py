from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from .ai import RepairPlan
from .models import BuildPlan


def conditions(analysis):
    digest=hashlib.sha256()
    for path in sorted(analysis.python_files):
        digest.update(str(path.relative_to(analysis.project_root)).replace('\\','/').encode())
        digest.update(path.read_bytes())
    return dict(imports=sorted(analysis.imports), source_sha256=digest.hexdigest(), dependencies=analysis.packages)


class ExperienceStore:
    def __init__(self,path):
        self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS experiences (id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.path,timeout=15)

    def list(self,status=None):
        with self.connect() as db:
            rows=db.execute('SELECT data FROM experiences'+(' WHERE status=?' if status else ''),(status,) if status else ()).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self,identifier):
        with self.connect() as db:
            row=db.execute('SELECT data FROM experiences WHERE id=?',(identifier,)).fetchone()
        if row is None:raise KeyError(identifier)
        return json.loads(row[0])

    def candidate(self,analysis,attempts,success_plan):
        failed=attempts[0]['plan']
        changes={}
        for target,field in [('add_dependencies','dependencies'),('hidden_imports','hidden_imports'),('collect_all','collect_all'),('data_files','data_files'),('pyinstaller_args','pyinstaller_args')]:
            changes[target]=[v for v in getattr(success_plan,field) if v not in failed[field]]
        changes['remove_dependencies']=[v for v in failed['dependencies'] if v not in success_plan.dependencies]
        changes['remove_pyinstaller_args']=[v for v in failed['pyinstaller_args'] if v not in success_plan.pyinstaller_args]
        repair=dict(root_cause='Approved aggregate of successful repairs',confidence=1.0,changes=changes,retry=True)
        identifier=uuid.uuid4().hex
        item=dict(id=identifier,status='CANDIDATE',conditions=conditions(analysis),project_root=str(analysis.project_root),failed_build_plan=failed,
                  error=attempts[0]['error'],ai_diagnosis=[a['repair'] for a in attempts if 'repair' in a],repair_plan=repair,
                  success_build_plan=success_plan.to_dict(),build_ids=[a['build_id'] for a in attempts])
        with self.connect() as db:db.execute('INSERT INTO experiences VALUES (?,?,?)',(identifier,item['status'],json.dumps(item)))
        return identifier

    def review(self,identifier,decision,repair=None):
        if decision not in {'APPROVED','REJECTED'}:raise ValueError('Invalid decision')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM experiences WHERE id=?',(identifier,)).fetchone()
            if row is None:raise KeyError(identifier)
            item=json.loads(row[0])
            if item['status']!='CANDIDATE':raise ValueError('Candidate already reviewed')
            if decision=='APPROVED':
                selected=RepairPlan.model_validate(repair or item['repair_plan'])
                selected.apply(BuildPlan(**item['failed_build_plan']),Path(item['project_root']))
                item['repair_plan']=selected.model_dump()
            item['status']=decision
            db.execute('UPDATE experiences SET status=?,data=? WHERE id=?',(decision,json.dumps(item),identifier))
        return item

    def apply(self,analysis,plan):
        match=conditions(analysis)
        for item in self.list('APPROVED'):
            if item['conditions'] != match:continue
            plan=RepairPlan.model_validate(item['repair_plan']).apply(plan,analysis.project_root)
            plan.matched_experiences.append(item['id'])
            plan.decision_sources['approved_experience']=item['id']
        return plan
