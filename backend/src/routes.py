from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import Session
from .security import current,allow
from .common import pack,audit,hole
from .models import Borehole,CoreRun,Reading,MissingInterval,Interpretation,Stratum,SampleInterval,Seal,Custody,ColumnRevision,Audit,ReceiptBatch,ReceiptSample,LabReceipt,ReceiptBag
from .schemas import HoleInput,RunInput,ReadingInput,MissingInput,Reason,BoreholeRef,Layers,SampleInput,SealInput,CustodyInput,RevisionInput,ReceiptBatchInput,ReceiptBagInput,ReceiptCheckin,ReceiptVerify,ReceiptIssue
from . import drilling_service as drilling,strata_service as strata,sample_service as sampling,custody_service as custody,revision_service as revision,receipt_service as receipt
router=APIRouter()
def permissions(u,controlled=False):allow(u,*(['supervisor']if controlled else['operator','supervisor']))
@router.get('/register')
def register(u=Depends(current)):
    with Session()as s:return {name:[pack(x)for x in s.scalars(select(cls).order_by(cls.id))]for name,cls in [('boreholes',Borehole),('runs',CoreRun),('readings',Reading),('missing',MissingInterval),('interpretations',Interpretation),('strata',Stratum),('samples',SampleInterval),('seals',Seal),('custodies',Custody),('revisions',ColumnRevision),('receipt_batches',ReceiptBatch),('receipt_samples',ReceiptSample),('receipt_bags',ReceiptBag),('lab_receipts',LabReceipt)]}
@router.get('/audit')
def history(u=Depends(current)):
    with Session()as s:return [pack(x)for x in s.scalars(select(Audit).order_by(Audit.id.desc()).limit(35))]
@router.post('/boreholes')
def new_hole(p:HoleInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:
        if p.cut_quota>p.total_depth:from fastapi import HTTPException;raise HTTPException(409,'切样配额不得超过孔深')
        x=Borehole(**p.model_dump());s.add(x);s.flush();audit(s,u,'登记钻孔 '+x.code);return pack(x)
@router.patch('/boreholes/{id}/site')
def site(id:int,p:Reason,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:
        x=hole(s,id);x.site=p.reason;audit(s,u,'补记孔位描述');return pack(x)
@router.post('/runs')
def new_run(p:RunInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return drilling.run(s,p,u)
@router.post('/readings')
def new_reading(p:ReadingInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return drilling.reading(s,p,u)
@router.post('/missing-intervals')
def new_missing(p:MissingInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return drilling.missing(s,p,u)
@router.post('/missing-intervals/{id}/annotate')
def annotate(id:int,p:Reason,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return drilling.annotate(s,id,p,u)
@router.post('/interpretations')
def interpret(p:BoreholeRef,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:x=strata.queue(s,p,u)
    from .main import redis
    try:redis.rpush('core-interpret',x['id'])
    except Exception:
        from .common import get
        with Session.begin()as s:y=get(s,Interpretation,x['id'],True);y.state='failed';y.error='队列不可用，请撤销后重试'
        from fastapi import HTTPException
        raise HTTPException(503,'队列不可用，失败已留档，可撤销后重试')
    return x
@router.put('/interpretations/{id}/contacts')
def contacts(id:int,p:Layers,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return strata.layers(s,id,p,u)
@router.post('/interpretations/{id}/confirm')
def confirm(id:int,u=Depends(current)):
    permissions(u,True)
    with Session.begin()as s:return strata.confirm(s,id,u)
@router.post('/interpretations/{id}/withdraw')
def withdraw(id:int,u=Depends(current)):
    permissions(u,True)
    with Session.begin()as s:return strata.withdraw(s,id,u)
@router.post('/samples')
def sample(p:SampleInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return sampling.create(s,p,u)
@router.put('/samples/{id}')
def revise(id:int,p:SampleInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return sampling.revise(s,id,p,u)
@router.post('/samples/{id}/cancel')
def cancel(id:int,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return sampling.cancel(s,id,u)
@router.post('/seals')
def seal(p:SealInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return custody.seal(s,p,u)
@router.post('/seals/{id}/break')
def broken(id:int,p:Reason,u=Depends(current)):
    permissions(u,True)
    with Session.begin()as s:return custody.break_seal(s,id,p,u)
@router.post('/custodies')
def handover(p:CustodyInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return custody.handover(s,p,u)
@router.post('/revisions')
def new_revision(p:RevisionInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return revision.create(s,p,u)
@router.post('/revisions/{id}/freeze')
def freeze(id:int,u=Depends(current)):
    permissions(u,True)
    with Session.begin()as s:return revision.freeze(s,id,u)
# 实验室收样组：整组一次签收、一次配对、一次回执；暂扣或破签时不放行。
@router.post('/receipt-batches')
def new_batch(p:ReceiptBatchInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return receipt.create(s,p,u)
@router.post('/receipt-batches/{id}/bags')
def new_bag(id:int,p:ReceiptBagInput,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return receipt.add_bag(s,id,p,u)
@router.post('/receipt-batches/{id}/check-in')
def check_in(id:int,p:ReceiptCheckin,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return receipt.check_in(s,id,p,u)
@router.post('/receipt-batches/{id}/match')
def match(id:int,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return receipt.match(s,id,u)
@router.post('/receipt-batches/{id}/verify')
def verify(id:int,p:ReceiptVerify,u=Depends(current)):
    permissions(u,True)
    with Session.begin()as s:return receipt.verify(s,id,p,u)
@router.post('/receipt-batches/{id}/receipt')
def issue_receipt(id:int,p:ReceiptIssue,u=Depends(current)):
    permissions(u)
    with Session.begin()as s:return receipt.issue_receipt(s,id,p.idempotency_key,u)
