import hashlib
import itertools
import json
import math
from sqlalchemy import select
from fastapi import HTTPException
from .models import Borehole,Reading,SampleInterval,Seal,Custody,ReceiptBatch,ReceiptSample,ReceiptBag,LabReceipt
from .common import get,pack,audit,now

# 实验室复测与原切样段物性分布的比对规则。距离按“原区间内离散 + 实验室复现误差”
# 合成尺度归一，全部袋—段组合用 RMS z 值衡量；χ²=RMS²。阈值随每次配对写入 evidence，
# 便于交接页复核，也便于主管按同一规则解释暂扣。
FEATURES=('density','susceptibility','velocity')
LAB_SIGMA={'density':0.02,'susceptibility':1.0,'velocity':50.0}
ACCEPT_RMS=3.0
# 两种完整一段一袋配法的 χ² 差小于该值即“都说得通”（似然比不足约 7:1），整组暂扣。
AMBIGUITY_CHI2=4.0
MAX_BAGS=8
SYSTEM={'email':'system / 封签事件'}

def lock_hole(s,id):return get(s,Borehole,id,True)
def context(s,id):
    ref=get(s,ReceiptBatch,id);h=lock_hole(s,ref.borehole_id);return h,get(s,ReceiptBatch,id,True)
def readings_in(s,sample):
    return s.scalars(select(Reading).where(Reading.borehole_id==sample.borehole_id,Reading.depth_m>=sample.start_m,Reading.depth_m<sample.end_m).order_by(Reading.depth_m)).all()
def profile(s,sample):
    rows=readings_in(s,sample)
    if not rows:return None
    out={'n':len(rows)}
    for f in FEATURES:
        vals=[getattr(r,f)for r in rows];mean=sum(vals)/len(vals);var=sum((v-mean)**2 for v in vals)/len(vals)
        out[f]={'mean':mean,'var':var,'scale':math.sqrt(var+LAB_SIGMA[f]**2)}
    return out
def bag_distance(bag,prof):
    chi=sum(((getattr(bag,f)-prof[f]['mean'])/prof[f]['scale'])**2 for f in FEATURES)
    return math.sqrt(chi/len(FEATURES)),chi
def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def latest_seal(s,sample_id):
    return s.scalar(select(Seal).where(Seal.sample_id==sample_id).order_by(Seal.id.desc()))
def seal_problem(s,rs):
    sample=get(s,SampleInterval,rs.sample_id)
    if sample.state!='transferred':return f'{sample.code} 尚未完成封签交接（当前 {sample.state}），不能按收样组签收'
    latest=latest_seal(s,sample.id)
    if not latest or latest.state!='intact':return f'{sample.code} 当前封签不完整，旧配对作废，须重封并重新签收'
    if rs.seal_id and rs.seal_id!=latest.id:return f'{sample.code} 封签已更换，须按新封签重新签收后配对'
    return None
def clear_pairing(s,b):
    for bag in s.scalars(select(ReceiptBag).where(ReceiptBag.batch_id==b.id)).all():
        bag.matched_sample_id=None;bag.distance=None;bag.score=None
def invalidate_for_sample(s,sample_id,reason):
    """封签破签/重封后调用：作废旧配对与已开回执，等待重封重签。"""
    for rs in s.scalars(select(ReceiptSample).where(ReceiptSample.sample_id==sample_id)).all():
        b=get(s,ReceiptBatch,rs.batch_id,True)
        if b.state not in ('collecting','matched','held','released','receipted'):continue
        active=s.scalar(select(LabReceipt).where(LabReceipt.batch_id==b.id,LabReceipt.state=='complete').order_by(LabReceipt.version.desc()))
        if active:
            active.state='void';active.void_reason=reason
        clear_pairing(s,b)
        rs.checked_in=False;rs.checked_in_at='';rs.checked_in_by='';rs.seal_id=None
        b.state='held';b.holds=[f'{reason}；旧配对已失效，重封后重新签收再配对'];b.hold_summary=b.holds[0]
        b.evidence={**(b.evidence or {}),'invalidated_at':now(),'invalidated_reason':reason,
                    **({'voided_receipt':active.code}if active else{})}
        audit(s,SYSTEM,f'收样组 {b.code} 因破签作废配对'+(f'与回执 {active.code}'if active else''))

def reseal_resets(s,sample_id,old_seal):
    """重封后旧封签链保留，但收样组须重新交接、重新签收后才能重算。"""
    for rs in s.scalars(select(ReceiptSample).where(ReceiptSample.sample_id==sample_id)).all():
        b=get(s,ReceiptBatch,rs.batch_id,True)
        if b.state not in ('collecting','matched','held','released'):continue
        clear_pairing(s,b);rs.checked_in=False;rs.checked_in_at='';rs.checked_in_by='';rs.seal_id=None
        msg=f'已重封 {old_seal.code} → 新封签，旧配对失效；重新交接并重新签收后才能重算'
        b.holds=[msg];b.hold_summary=msg;b.state='held'
        b.evidence={**(b.evidence or {}),'resealed_at':now(),'resealed_from':old_seal.code}
        audit(s,SYSTEM,f'收样组 {b.code}：{msg}')

def validate_group(s,b):
    rows=s.scalars(select(ReceiptSample).where(ReceiptSample.batch_id==b.id).order_by(ReceiptSample.id)).all()
    bags=s.scalars(select(ReceiptBag).where(ReceiptBag.batch_id==b.id).order_by(ReceiptBag.id)).all()
    if not rows:raise HTTPException(409,'收样组为空')
    # 封签问题优先报出：破签/重封未重新交接时，先说清“旧配对作废、须重封重签”。
    for rs in rows:
        reason=seal_problem(s,rs)
        if reason:raise HTTPException(409,reason)
    if len(bags)!=len(rows):raise HTTPException(409,f'样段 {len(rows)} 个、复测样袋 {len(bags)} 个，袋数不一致，不能一段一袋配对')
    if not all(rs.checked_in for rs in rows):raise HTTPException(409,'整组尚未签收完成，不能配对或开回执；请继续签收剩余样袋')
    if {bag.nominal_sample_id for bag in bags}!={rs.sample_id for rs in rows}:raise HTTPException(409,'复测样袋标签未覆盖本组全部样段')
    return rows,bags

def create(s,p,u):
    h=lock_hole(s,p.borehole_id)
    ids=list(dict.fromkeys(p.sample_ids))
    if len(ids)!=len(p.sample_ids):raise HTTPException(409,'收样组内样段不能重复')
    if not 2<=len(ids)<=MAX_BAGS:raise HTTPException(409,f'一组须含 2–{MAX_BAGS} 个样段')
    samples=[get(s,SampleInterval,i)for i in ids]
    for x in samples:
        if x.borehole_id!=h.id:raise HTTPException(409,'收样组只能包含同一钻孔的样袋')
        if x.state!='transferred':raise HTTPException(409,f'{x.code} 尚未完成封签交接，不能登记实验室收样')
        seal=latest_seal(s,x.id)
        if not seal or seal.state!='intact':raise HTTPException(409,f'{x.code} 当前封签不完整，须重封交接后再收样')
        if s.scalar(select(ReceiptSample.id).where(ReceiptSample.sample_id==x.id)):raise HTTPException(409,f'{x.code} 已在其他收样组，不能重复收样')
        if not readings_in(s,x):raise HTTPException(409,f'{x.code} 区间内没有原切样段物性测点，无法配对')
    if s.scalar(select(ReceiptBatch.id).where(ReceiptBatch.borehole_id==h.id,ReceiptBatch.code==p.code)):raise HTTPException(409,'本孔已有同号收样组')
    b=ReceiptBatch(borehole_id=h.id,code=p.code,note=p.note,state='collecting',evidence={},holds=[],hold_summary='',created_by=u['email'],created_at=now())
    s.add(b);s.flush()
    for x in samples:s.add(ReceiptSample(batch_id=b.id,sample_id=x.id))
    s.flush();audit(s,u,f'登记实验室收样组 {b.code}（{len(samples)} 袋）');return pack(b)

def add_bag(s,batch_id,p,u):
    h,b=context(s,batch_id)
    if b.state not in ('collecting','matched','held'):raise HTTPException(409,'已放行或已开回执的收样组不能加袋')
    if not s.scalar(select(ReceiptSample.id).where(ReceiptSample.batch_id==b.id,ReceiptSample.sample_id==p.nominal_sample_id)):raise HTTPException(409,'样袋标签样段不属于本收样组')
    if s.scalar(select(ReceiptBag.id).where(ReceiptBag.batch_id==b.id,ReceiptBag.nominal_sample_id==p.nominal_sample_id)):raise HTTPException(409,'该样段已登记复测样袋')
    if s.scalar(select(ReceiptBag.id).where(ReceiptBag.batch_id==b.id,ReceiptBag.code==p.code)):raise HTTPException(409,'本组已有同样袋号')
    bag=ReceiptBag(batch_id=b.id,code=p.code,nominal_sample_id=p.nominal_sample_id,density=p.density,susceptibility=p.susceptibility,velocity=p.velocity,measured_by=u['email'],measured_at=now())
    s.add(bag);s.flush();clear_pairing(s,b)
    if b.state=='held':
        note='样袋已变更，须重新配对'
        if note not in b.holds:b.holds=[v for v in b.holds if '袋数不一致' not in v]+[note]
    else:
        b.state='collecting';b.holds=[]
    b.hold_summary='；'.join(b.holds)
    audit(s,u,f'登记复测样袋 {bag.code}');return pack(bag)

def check_in(s,batch_id,p,u):
    h,b=context(s,batch_id)
    if b.state not in ('collecting','matched','held'):raise HTTPException(409,'已放行或已开回执的收样组不能再签收')
    rows={rs.sample_id:rs for rs in s.scalars(select(ReceiptSample).where(ReceiptSample.batch_id==b.id)).all()}
    if any(i not in rows for i in p.sample_ids):raise HTTPException(409,'所列样段不属于本收样组')
    changed=0
    for sid in dict.fromkeys(p.sample_ids):
        rs=rows[sid]
        if rs.checked_in:continue
        sample=get(s,SampleInterval,sid)
        if not s.scalar(select(ReceiptBag.id).where(ReceiptBag.batch_id==b.id,ReceiptBag.nominal_sample_id==sid)):raise HTTPException(409,f'{sample.code} 尚未登记复测样袋，不能签收')
        reason=seal_problem(s,rs)
        if reason:raise HTTPException(409,reason)
        rs.checked_in=True;rs.checked_in_at=now();rs.checked_in_by=u['email'];rs.seal_id=latest_seal(s,sid).id;changed+=1
    if changed:
        clear_pairing(s,b)
        if b.state in ('matched','released'):b.state='collecting'
        if b.state=='collecting':b.holds=[];b.hold_summary=''
        audit(s,u,f'签收收样组 {b.code} 本次 {changed} 袋')
    allrows=s.scalars(select(ReceiptSample).where(ReceiptSample.batch_id==b.id)).all()
    done=[rs for rs in allrows if rs.checked_in]
    return {'batch':pack(b),'checked':len(done),'total':len(allrows),
            'remaining_sample_ids':[rs.sample_id for rs in allrows if not rs.checked_in]}

def _acceptable_assignments(bags,samples,chi):
    ids=[x.id for x in samples];out=[]
    for perm in itertools.permutations(ids,len(bags)):
        cost=0.0
        for bag,sid in zip(bags,perm):
            c=chi.get((bag.id,sid))
            if c is None or c>ACCEPT_RMS**2:break
            cost+=c
        else:out.append((cost,perm))
    return out

def match(s,batch_id,u):
    h,b=context(s,batch_id)
    if b.state not in ('collecting','matched','held'):raise HTTPException(409,'已放行或已开回执的收样组不能重算配对')
    rows,bags=validate_group(s,b)
    samples=[get(s,SampleInterval,rs.sample_id)for rs in rows]
    code_of={x.id:x.code for x in samples}
    profiles={x.id:profile(s,x)for x in samples}
    chi={};matrix=[]
    for bag in bags:
        for sample in samples:
            prof=profiles[sample.id]
            d,c=(bag_distance(bag,prof)if prof else(None,None))
            if c is not None:chi[(bag.id,sample.id)]=c
            matrix.append({'bag_id':bag.id,'bag_code':bag.code,'sample_id':sample.id,'sample_code':sample.code,
                           'rms':None if d is None else round(d,6),'chi2':None if c is None else round(c,6),
                           'acceptable':c is not None and c<=ACCEPT_RMS**2})
    options=sorted(_acceptable_assignments(bags,samples,chi))
    holds=[];chosen=None
    if not options:
        for bag in bags:
            near=min(((sample.code,chi[(bag.id,sample.id)])for sample in samples if(bag.id,sample.id)in chi),key=lambda z:z[1],default=None)
            holds.append(f'样袋 {bag.code} 配不上任何原切样段'+ (f'（最接近 {near[0]}，χ²={near[1]:.2f}）'if near else'（缺原切样物性）'))
        holds.append('没有完整的一段一袋配法，整组暂扣待主管验明实物')
        clear_pairing(s,b)
        b.state='held'
    else:
        cost,best=options[0];neargroup=[x for x in options if x[0]<=cost+AMBIGUITY_CHI2]
        chosen=list(zip(bags,best))
        for bag,sid in chosen:
            bag.matched_sample_id=sid;bag.distance=round(math.sqrt(chi[(bag.id,sid)]),6);bag.score=round(math.exp(-0.5*chi[(bag.id,sid)]),6)
        if len(neargroup)>1:
            holds.append(f'有两种及以上配法都说得通（{len(neargroup)} 种落在 χ² 容差 {AMBIGUITY_CHI2} 内），整组暂扣')
            holds.append('备选配法：'+' / '.join('→'.join(code_of[sid]for sid in perm)for _,perm in neargroup[:8]))
        swapped=[bag for bag,sid in chosen if bag.nominal_sample_id!=sid]
        if swapped:
            holds.append('疑似封签贴反：'+'；'.join(f'{bag.code} 标签 {code_of[bag.nominal_sample_id]}，物性最接近 {code_of[bag.matched_sample_id]}'for bag in swapped))
        b.state='held' if holds else 'matched'
    b.holds=holds;b.hold_summary='；'.join(holds)
    b.evidence={'computed_at':now(),'computed_by':u['email'],'features':list(FEATURES),'lab_sigma':LAB_SIGMA,
        'accept_rms':ACCEPT_RMS,'ambiguity_chi2':AMBIGUITY_CHI2,
        'profiles':{str(x.id):{'code':x.code,'start_m':x.start_m,'end_m':x.end_m,
            'reading_count':profiles[x.id]['n']if profiles[x.id]else 0,
            'mean':{f:round(profiles[x.id][f]['mean'],6)for f in FEATURES}if profiles[x.id]else{},
            'scale':{f:round(profiles[x.id][f]['scale'],6)for f in FEATURES}if profiles[x.id]else{}}for x in samples},
        'matrix':matrix,
        'chosen':[{'bag_id':bag.id,'bag_code':bag.code,'nominal_sample_id':bag.nominal_sample_id,
                   'nominal_sample_code':code_of[bag.nominal_sample_id],'sample_id':sid,'sample_code':code_of[sid],
                   'rms':round(math.sqrt(chi[(bag.id,sid)]),6)}for bag,sid in(chosen or[])],
        'chosen_cost':None if not options else round(options[0][0],6),
        'alternative_count':0 if not options else len([x for x in options if x[0]<=options[0][0]+AMBIGUITY_CHI2]),
        'alternatives':[] if not options else[[code_of[sid]for sid in perm]for _,perm in[x for x in options if x[0]<=options[0][0]+AMBIGUITY_CHI2][:8]],
        'holds':holds,'previous':(b.evidence or{}).get('computed_at')}
    audit(s,u,f'实验室收样组 {b.code} 配对：{b.state}（{len(holds)} 条暂扣提示）');return pack(b)

def verify(s,batch_id,p,u):
    h,b=context(s,batch_id)
    if b.state!='held':raise HTTPException(409,'只有暂扣组需要主管验明实物后放行')
    rows,bags=validate_group(s,b)
    samples=[get(s,SampleInterval,rs.sample_id)for rs in rows]
    bag_ids=[x.bag_id for x in p.assignment];sample_ids=[x.sample_id for x in p.assignment]
    if len(set(bag_ids))!=len(bag_ids)or len(set(sample_ids))!=len(sample_ids):raise HTTPException(409,'放行配法必须一袋对一段，不能重复')
    if set(bag_ids)!={x.id for x in bags}or set(sample_ids)!={x.id for x in samples}:raise HTTPException(409,'放行配法必须完整覆盖本组全部样袋与样段')
    by_bag={x.id:x for x in bags};code_of={x.id:x.code for x in samples};profiles={x.id:profile(s,x)for x in samples}
    chosen=[];over=[]
    for pair in p.assignment:
        prof=profiles[pair.sample_id]
        if not prof:raise HTTPException(409,f'{code_of[pair.sample_id]} 没有原切样段物性分布')
        d,c=bag_distance(by_bag[pair.bag_id],prof)
        if c>ACCEPT_RMS**2:over.append(by_bag[pair.bag_id].code)
        chosen.append((by_bag[pair.bag_id],pair.sample_id,d,c))
    clear_pairing(s,b)
    for bag,sid,d,c in chosen:
        bag.matched_sample_id=sid;bag.distance=round(d,6);bag.score=round(math.exp(-0.5*c),6)
    b.state='released';b.verified_by=u['email'];b.verified_reason=p.reason
    b.evidence={**(b.evidence or{}),'release':{'at':now(),'by':u['email'],'reason':p.reason,'manual':True,
        'assignment':[{'bag_id':bag.id,'bag_code':bag.code,'sample_id':sid,'sample_code':code_of[sid],'rms':round(d,6)}for bag,sid,d,_ in chosen],
        'over_threshold_bags':over,'note':'主管验明实物后人工指定配法；超阈值袋按实物放行并留档'}}
    audit(s,u,f'主管验明实物放行收样组 {b.code}'+(f'（超阈值 {",".join(over)}）'if over else''));return pack(b)

def issue_receipt(s,batch_id,key,u):
    h,b=context(s,batch_id)
    if key:
        used=s.scalar(select(LabReceipt).where(LabReceipt.idempotency_key==key))
        if used:
            if used.batch_id!=b.id:raise HTTPException(409,'幂等键已用于其他收样组')
            if used.state!='complete':raise HTTPException(409,'该幂等键对应的回执已作废，请用新键重开整组回执')
            return {'receipt':pack(used),'replayed':True}
    active=s.scalar(select(LabReceipt).where(LabReceipt.batch_id==b.id,LabReceipt.state=='complete').order_by(LabReceipt.version.desc()))
    if active:return {'receipt':pack(active),'replayed':True}
    last=s.scalar(select(LabReceipt).where(LabReceipt.batch_id==b.id).order_by(LabReceipt.version.desc()))
    default_key=key or f'batch:{b.id}:v{(last.version+1)if last else 1}'
    if b.state not in ('matched','released'):raise HTTPException(409,'整组须配对完成或主管放行后才能开回执；暂扣/签收中一律不出回执')
    rows,bags=validate_group(s,b)
    if not all(bag.matched_sample_id for bag in bags):raise HTTPException(409,'尚有样袋未配对，不能开回执')
    if len({bag.matched_sample_id for bag in bags})!=len(bags):raise HTTPException(409,'配对不是一段一袋，不能开回执')
    if {bag.matched_sample_id for bag in bags}!={rs.sample_id for rs in rows}:raise HTTPException(409,'配对未覆盖全部样段，不能开半组回执')
    version=(last.version+1)if last else 1
    snap={'batch':pack(b),'receipt_version':version,
            'samples':[pack(x)for x in s.scalars(select(SampleInterval).where(SampleInterval.id.in_([rs.sample_id for rs in rows]))).all()],
            'bags':[pack(x)for x in bags],
            'checked_in':[{'sample_id':rs.sample_id,'at':rs.checked_in_at,'by':rs.checked_in_by,'seal_id':rs.seal_id}for rs in rows],
            'seals':[pack(x)for x in s.scalars(select(Seal).where(Seal.id.in_([rs.seal_id for rs in rows if rs.seal_id]))).all()],
            'custodies':[pack(x)for x in s.scalars(select(Custody).where(Custody.seal_id.in_([rs.seal_id for rs in rows if rs.seal_id]))).all()],
            'evidence':b.evidence or{}}
    snap['sha256']=digest(snap)
    receipt=LabReceipt(batch_id=b.id,code=f'{b.code}-R{version:02d}',version=version,
        idempotency_key=default_key,received_by=u['email'],at=now(),
        bag_count=len(bags),state='complete',snapshot=snap)
    s.add(receipt);s.flush()
    for bag in bags:bag.receipt_id=receipt.id
    b.state='receipted'
    audit(s,u,f'实验室收样组 {b.code} 开回执 {receipt.code}（{len(bags)} 袋一次全组）')
    return {'receipt':pack(receipt),'replayed':False}
