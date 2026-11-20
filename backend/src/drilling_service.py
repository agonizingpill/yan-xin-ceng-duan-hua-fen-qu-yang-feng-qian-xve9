from sqlalchemy import select
from fastapi import HTTPException
from .models import CoreRun,Reading,MissingInterval,Interpretation
from .common import hole,get,pack,audit,interval,overlaps

def mutable_readings(s,h):
    if s.scalar(select(Interpretation.id).where(Interpretation.borehole_id==h.id,Interpretation.state.in_(['queued','ready','confirmed']))):raise HTTPException(409,'已有排队或已确认层段，不能改测点；请先撤销未取样的解释')
def run(s,p,u):
    h=hole(s,p.borehole_id);interval(p.start_m,p.end_m,h.total_depth)
    if p.recovered_m>p.end_m-p.start_m:raise HTTPException(409,'回收长度不得超本回次进尺')
    for x in s.scalars(select(CoreRun).where(CoreRun.borehole_id==h.id)):
        if overlaps(p.start_m,p.end_m,x.start_m,x.end_m):raise HTTPException(409,'回次进尺区间重叠')
    x=CoreRun(**p.model_dump());s.add(x);s.flush();audit(s,u,'登记回次 '+p.code);return pack(x)
def reading(s,p,u):
    h=hole(s,p.borehole_id);mutable_readings(s,h);r=get(s,CoreRun,p.run_id)
    if r.borehole_id!=h.id or not r.start_m<=p.depth_m<r.end_m:raise HTTPException(409,'测点须位于本孔关联回次内')
    for m in s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==h.id)):
        if m.start_m<=p.depth_m<m.end_m:raise HTTPException(409,'已标记缺失区间不可录入假测点')
    x=Reading(**p.model_dump());s.add(x);s.flush();audit(s,u,'录物性 '+str(p.depth_m));return pack(x)
def missing(s,p,u):
    h=hole(s,p.borehole_id);mutable_readings(s,h);interval(p.start_m,p.end_m,h.total_depth)
    for m in s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==h.id)):
        if overlaps(m.start_m,m.end_m,p.start_m,p.end_m):raise HTTPException(409,'缺失区间不可重叠')
    if s.scalar(select(Reading.id).where(Reading.borehole_id==h.id,Reading.depth_m>=p.start_m,Reading.depth_m<p.end_m)):raise HTTPException(409,'缺失区间包含已测物性，不能覆盖')
    x=MissingInterval(**p.model_dump(),state='annotated'if len(p.reason)>=8 else'observed');s.add(x);s.flush();audit(s,u,'标缺段');return pack(x)
def annotate(s,id,p,u):
    ref=get(s,MissingInterval,id);hole(s,ref.borehole_id);x=get(s,MissingInterval,id,True)
    if x.state=='annotated':raise HTTPException(409,'缺段说明已签记，不可重复覆盖')
    x.reason=p.reason;x.state='annotated';audit(s,u,'补记缺芯原因');return pack(x)
