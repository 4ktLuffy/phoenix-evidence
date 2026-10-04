import ast, asyncio, types
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import Session
from phoenix.db import models
from phoenix.db.insertion.helpers import insert_on_conflict, OnConflict, SupportedSQLDialect
from phoenix.db.models import ExperimentRunOutput
from strawberry.relay import GlobalID
P=Path('<scratch>/px-main')
source=P/'src/phoenix/server/api/routers/v1/experiment_runs.py'
fn=next(x for x in ast.parse(source.read_text()).body if isinstance(x,ast.AsyncFunctionDef) and x.name=='create_experiment_run')
fn.decorator_list=[]
fn.returns=None
for arg in fn.args.args:arg.annotation=None
engine=create_engine('sqlite:///:memory:')
models.ExperimentRun.__table__.create(engine)
models.ExperimentRunAnnotation.__table__.create(engine)
s=Session(engine);now=datetime.now(timezone.utc)
r=models.ExperimentRun(id=1,experiment_id=1,dataset_example_id=1,repetition_number=1,output={'task_output':None},start_time=now,end_time=now,error='boom')
s.add(r)
s.add_all([models.ExperimentRunAnnotation(experiment_run_id=1,name=name,annotator_kind=kind,label='pass',score=1,metadata_={},start_time=now,end_time=now) for name,kind in [('human_label','HUMAN'),('exact','CODE')]])
s.commit()
class AsyncSession:
 async def scalar(self,stmt):return s.scalar(stmt)
 async def execute(self,stmt):return s.execute(stmt)
 async def __aenter__(self):return self
 async def __aexit__(self,*a):s.commit()
class DB:
 dialect=SupportedSQLDialect.SQLITE
 def __call__(self):return AsyncSession()
ns=globals()|dict(from_global_id_with_expected_type=lambda g,t:int(g.node_id),ExperimentRunInsertEvent=lambda x:x,CreateExperimentRunResponseBody=lambda **kw:kw,CreateExperimentRunResponseBodyData=lambda **kw:kw)
exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),ns)
request=types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(db=DB())),state=types.SimpleNamespace(event_queue=types.SimpleNamespace(put=lambda x:None)))
body=types.SimpleNamespace(dataset_example_id=str(GlobalID('DatasetExample','1')),trace_id=None,output='B',repetition_number=1,start_time=now,end_time=now,error=None)
print('BEFORE',[(a.name,a.annotator_kind) for a in s.scalars(select(models.ExperimentRunAnnotation))])
print('RESPONSE',asyncio.run(ns['create_experiment_run'](request,str(GlobalID('Experiment','1')),body)))
print('AFTER',list(s.scalars(select(models.ExperimentRunAnnotation))))
print('OUTPUT',s.scalar(select(models.ExperimentRun)).output)
