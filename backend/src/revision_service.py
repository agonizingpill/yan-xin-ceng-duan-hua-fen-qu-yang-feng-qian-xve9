from sqlalchemy import select
from fastapi import HTTPException
from .models import CoreRun,Reading,MissingInterval,Interpretation,Stratum,SampleInterval,Seal,Custody,ColumnRevision
from .common import hole,get,pack,audit

def create(s,p,u):
    h=hole(s,p.borehole_id)
    if s.scalar(select(ColumnRevision.id).where(ColumnRevision.borehole_id==h.id,ColumnRevision.state=='draft')):raise HTTPException(409,'已有待冻结版本，请继续原草稿')
    x=ColumnRevision(**p.model_dump());s.add(x);s.flush();audit(s,u,'编柱状图版本 '+x.version);return pack(x)
def freeze(s,id,u):
    ref=get(s,ColumnRevision,id);h=hole(s,ref.borehole_id);x=get(s,ColumnRevision,id,True)
    if x.state!='draft':raise HTTPException(409,'版本已冻结，不能重复')
    runs=s.scalars(select(CoreRun).where(CoreRun.borehole_id==h.id).order_by(CoreRun.start_m)).all();edge=0
    for r in runs:
        if abs(r.start_m-edge)>1e-6:raise HTTPException(409,'进尺回次不连续，须补齐孔深记录')
        edge=r.end_m
    if abs(edge-h.total_depth)>1e-6:raise HTTPException(409,'回次尚未覆盖全孔')
    points=s.scalars(select(Reading).where(Reading.borehole_id==h.id).order_by(Reading.depth_m)).all();missing=s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==h.id)).all()
    if any(m.state!='annotated'for m in missing):raise HTTPException(409,'缺失测段尚未补记原因，不得冻结')
    # Each one-metre logging cell needs an actual reading or an explicitly annotated gap.
    depth=.5
    while depth<h.total_depth:
        if not any(abs(r.depth_m-depth)<1e-6 for r in points)and not any(m.start_m<=depth<m.end_m for m in missing):raise HTTPException(409,'存在未标注的缺失测段 '+str(depth)+'m')
        depth+=1
    i=s.scalar(select(Interpretation).where(Interpretation.borehole_id==h.id,Interpretation.state=='confirmed'))
    if not i:raise HTTPException(409,'须主管确认人工层段')
    samples=s.scalars(select(SampleInterval).where(SampleInterval.borehole_id==h.id,SampleInterval.state!='cancelled')).all()
    if any(v.state!='transferred'for v in samples):raise HTTPException(409,'尚有未完整封签交接样袋，不能冻结')
    ids=[v.id for v in samples];seals=s.scalars(select(Seal).where(Seal.sample_id.in_(ids))).all()if ids else[];sealids=[v.id for v in seals];cust=s.scalars(select(Custody).where(Custody.seal_id.in_(sealids))).all()if sealids else[]
    x.snapshot={'borehole':pack(h),'runs':[pack(v)for v in runs],'readings':[pack(v)for v in points],'missing':[pack(v)for v in missing],'interpretation':pack(i),'strata':[pack(v)for v in s.scalars(select(Stratum).where(Stratum.interpretation_id==i.id))],'samples':[pack(v)for v in samples],'seals':[pack(v)for v in seals],'custodies':[pack(v)for v in cust]};x.state='frozen';x.frozen_by=u['email'];h.state='frozen';audit(s,u,'冻结柱状图 '+h.code+' '+x.version);return pack(x)
