from sqlalchemy import select,delete
from fastapi import HTTPException
from .models import Reading,Interpretation,Stratum,SampleInterval
from .common import hole,get,pack,audit

def queue(s,p,u):
    h=hole(s,p.borehole_id)
    if s.scalar(select(Interpretation.id).where(Interpretation.borehole_id==h.id,Interpretation.state.in_(['queued','confirmed']))):raise HTTPException(409,'本孔已有排队或已确认解释')
    n=len(s.scalars(select(Reading).where(Reading.borehole_id==h.id)).all())
    if n<12:raise HTTPException(409,'至少12个真实物性测点才可选层数')
    x=Interpretation(borehole_id=h.id,state='queued');s.add(x);s.flush();audit(s,u,'申请GMM层段解释');return pack(x)
def layers(s,id,p,u):
    ref=get(s,Interpretation,id);h=hole(s,ref.borehole_id);x=get(s,Interpretation,id,True)
    if x.state!='ready':raise HTTPException(409,'须算法已就绪且未主管确认才能修订接触面')
    rows=sorted(p.layers,key=lambda z:z.start_m);edge=0
    for z in rows:
        if abs(z.start_m-edge)>1e-6 or z.end_m<=z.start_m:raise HTTPException(409,'人工层段须从0连续衔接，不得缺段或重叠')
        edge=z.end_m
    if abs(edge-h.total_depth)>1e-6:raise HTTPException(409,'人工层段必须完整覆盖孔深')
    s.execute(delete(Stratum).where(Stratum.interpretation_id==id))
    for z in rows:s.add(Stratum(interpretation_id=id,**z.model_dump()))
    s.flush();audit(s,u,'人工接触面已编录');return pack(x)
def confirm(s,id,u):
    ref=get(s,Interpretation,id);hole(s,ref.borehole_id);x=get(s,Interpretation,id,True)
    if s.scalar(select(Interpretation.id).where(Interpretation.borehole_id==x.borehole_id,Interpretation.state=='confirmed',Interpretation.id!=id)):raise HTTPException(409,'本孔已有主管确认的解释，须先撤销未被取样引用的旧解释')
    if x.state!='ready' or not s.scalar(select(Stratum.id).where(Stratum.interpretation_id==id)):raise HTTPException(409,'须算法就绪且人工完整编录层段，不能重复确认')
    x.state='confirmed';audit(s,u,'主管确认地层接触面');return pack(x)
def withdraw(s,id,u):
    ref=get(s,Interpretation,id);hole(s,ref.borehole_id);x=get(s,Interpretation,id,True)
    if x.state not in ['ready','failed','confirmed']:raise HTTPException(409,'仅已完成/失败解释可撤销重编')
    ids=s.scalars(select(Stratum.id).where(Stratum.interpretation_id==id)).all()
    if ids and s.scalar(select(SampleInterval.id).where(SampleInterval.stratum_id.in_(ids))):raise HTTPException(409,'已有取样引用层面，禁止撤销解释')
    x.state='withdrawn';audit(s,u,'撤销解释，允许重测重编');return pack(x)
