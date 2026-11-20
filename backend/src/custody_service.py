from sqlalchemy import select
from fastapi import HTTPException
from .models import SampleInterval,Seal,Custody
from .common import hole,get,pack,audit,now

def context(s,id):
    ref=get(s,SampleInterval,id);hole(s,ref.borehole_id);return get(s,SampleInterval,id,True)
def seal(s,p,u):
    sample=context(s,p.sample_id)
    if sample.state not in ['planned','broken']:raise HTTPException(409,'仅待封样或破签待重封样可封签')
    old=s.scalar(select(Seal).where(Seal.sample_id==sample.id).order_by(Seal.id.desc()))
    if old and (old.state!='broken' or len(p.reason)<8):raise HTTPException(409,'重封须保留破签旧链并写至少8字重封依据')
    x=Seal(sample_id=sample.id,code=p.code,previous_id=old.id if old else None,reason=p.reason,sealed_by=u['email'],snapshot=pack(sample));s.add(x);sample.state='sealed';s.flush();audit(s,u,'样袋封签 '+p.code);return pack(x)
def break_seal(s,id,p,u):
    ref=get(s,Seal,id);sample=context(s,ref.sample_id);x=get(s,Seal,id,True)
    latest=s.scalar(select(Seal.id).where(Seal.sample_id==sample.id).order_by(Seal.id.desc()))
    if x.state!='intact' or latest!=x.id:raise HTTPException(409,'仅当前完整封签可报告破签')
    x.state='broken';x.reason=p.reason;sample.state='broken';audit(s,u,'报告破签 '+x.code);return pack(x)
def handover(s,p,u):
    ref=get(s,Seal,p.seal_id);sample=context(s,ref.sample_id);x=get(s,Seal,p.seal_id,True)
    if x.state!='intact' or sample.state!='sealed':raise HTTPException(409,'当前样袋须封签完整且未移交，破签须重封')
    latest=s.scalar(select(Seal.id).where(Seal.sample_id==sample.id).order_by(Seal.id.desc()))
    if latest!=x.id:raise HTTPException(409,'旧封签不能代替当前封签移交')
    y=Custody(**p.model_dump(),at=now());s.add(y);sample.state='transferred';s.flush();audit(s,u,'交接样袋 '+x.code+' → '+p.receiver);return pack(y)
