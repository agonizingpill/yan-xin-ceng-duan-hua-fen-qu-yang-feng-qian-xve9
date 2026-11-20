from datetime import datetime,timezone
from sqlalchemy import select
from fastapi import HTTPException
from .models import Borehole,Audit

def now():return datetime.now(timezone.utc).isoformat()
def pack(x):return {c.name:getattr(x,c.name)for c in x.__table__.columns}
def get(s,cls,id,lock=False):
    q=select(cls).where(cls.id==id)
    if lock:q=q.with_for_update().execution_options(populate_existing=True)
    x=s.scalar(q)
    if not x:raise HTTPException(404,'关联记录不存在')
    return x
def hole(s,id):
    h=get(s,Borehole,id,True)
    if h.state!='open':raise HTTPException(409,'柱状图已冻结，钻孔业务记录不能改写')
    return h
def audit(s,u,msg):s.add(Audit(actor=u['email'],action=msg,at=now()))
def interval(start,end,total):
    if end<=start or end>total:raise HTTPException(409,'区间终点须大于起点且不超孔深')
def overlaps(a,b,c,d):return a<d-1e-8 and b>c+1e-8
