import json
import numpy as np
from sqlalchemy import select
from src.database import Session,Base,engine
from src.models import (User,Borehole,CoreRun,Reading,MissingInterval,Interpretation,Stratum,SampleInterval,
                        Seal,Custody,ColumnRevision,ReceiptBatch,ReceiptSample,ReceiptBag,LabReceipt)
from src.security import password_hash

def seed():
    Base.metadata.create_all(engine)
    with Session.begin()as s:
        for role in ['operator','supervisor','viewer']:
            if not s.scalar(select(User).where(User.email==role+'@liheng.local')):s.add(User(email=role+'@liheng.local',password=password_hash('Core2026!'),role=role))
        h=s.scalar(select(Borehole).where(Borehole.code=='BH-31'))
        if not h:
            h=Borehole(code='BH-31',site='砾衡青石沟东线 / ZK-31',total_depth=36,cut_quota=6);s.add(h);s.flush()
            rng=np.random.default_rng(42)
            for code,start,end,recovered in [('R01',0,18,17),('R02',18,36,18)]:
                run=CoreRun(borehole_id=h.id,code=code,start_m=start,end_m=end,recovered_m=recovered);s.add(run);s.flush()
                for depth in np.arange(start+.5,end,1):
                    if depth==12.5:continue
                    group=min(int(depth//12),2);center=[(2.1,12,2200),(2.6,50,4100),(3.1,100,6100)][group]
                    s.add(Reading(borehole_id=h.id,run_id=run.id,depth_m=float(depth),density=round(float(center[0]+rng.normal(0,.035)),4),susceptibility=round(float(center[1]+rng.normal(0,1.5)),4),velocity=round(float(center[2]+rng.normal(0,55)),3)))
            s.add(MissingInterval(borehole_id=h.id,start_m=12,end_m=13,state='observed',reason=''))
            legacy=Interpretation(borehole_id=h.id,state='historical',evidence={'note':'旧纸本区间来源，仅保留既有切样，不替代新GMM解释'});s.add(legacy);s.flush();st=Stratum(interpretation_id=legacy.id,start_m=0,end_m=12,lithology='旧编录砂岩',contact_note='纸本编录回录，仅保留历史取样依据');s.add(st);s.flush();sample=SampleInterval(borehole_id=h.id,stratum_id=st.id,code='CS-031-OLD',start_m=8,end_m=9,purpose='历史抗压试验',destructive=True,state='broken');s.add(sample);s.flush();s.add(Seal(sample_id=sample.id,code='CX031-001',state='broken',reason='运输交接发现铅封裂口，待现场核样重封',sealed_by='operator@liheng.local',snapshot={'code':sample.code,'start_m':8,'end_m':9,'source':'历史纸本'}))
            # 同孔一组：两块已完整封签交接的样袋，实验室已登记复测袋并逐袋签收。
            # 复测值故意与标签错开，演示“疑似贴反→整组暂扣→主管验明实物”。
            lab_samples=[]
            for code,start,end,d,sus,vel in [('CS-031-01',2,3,2.10,12.0,2200.0),('CS-031-02',14,15,2.60,50.0,4100.0)]:
                x=SampleInterval(borehole_id=h.id,stratum_id=st.id,code=code,start_m=start,end_m=end,purpose='抗压与薄片复测',destructive=True,state='transferred')
                s.add(x);s.flush();seal=Seal(sample_id=x.id,code='CX031-'+code[-2:],state='intact',reason='',sealed_by='operator@liheng.local',snapshot={'code':code,'start_m':start,'end_m':end});s.add(seal);s.flush()
                s.add(Custody(seal_id=seal.id,receiver='周岩 / 实验室收样员',destination='砾衡岩土试验室',condition='双方核对样号、孔深及铅封完整，样袋干燥无漏失',at='2026-11-18T09:10:00+00:00'))
                lab_samples.append((x.id,code))
            batch=ReceiptBatch(borehole_id=h.id,code='LAB-031-01',note='实验室收同孔一组样袋，按原切样物性配对',state='collecting',evidence={},holds=[],hold_summary='',created_by='operator@liheng.local',created_at='2026-11-18T10:00:00+00:00');s.add(batch);s.flush()
            for sid,_ in lab_samples:s.add(ReceiptSample(batch_id=batch.id,sample_id=sid,checked_in=True,checked_in_at='2026-11-18T10:05:00+00:00',checked_in_by='operator@liheng.local'))
            s.flush()
            for sid,code in lab_samples:
                rs=s.scalar(select(ReceiptSample).where(ReceiptSample.batch_id==batch.id,ReceiptSample.sample_id==sid));rs.seal_id=s.scalar(select(Seal.id).where(Seal.sample_id==sid))
            # 两袋标签对调：物性都像另一段的原位
            s.add(ReceiptBag(batch_id=batch.id,code='LAB-031-A',nominal_sample_id=lab_samples[0][0],density=2.597,susceptibility=50.6,velocity=4088.0,measured_by='operator@liheng.local',measured_at='2026-11-18T10:20:00+00:00'))
            s.add(ReceiptBag(batch_id=batch.id,code='LAB-031-B',nominal_sample_id=lab_samples[1][0],density=2.098,susceptibility=12.4,velocity=2206.0,measured_by='operator@liheng.local',measured_at='2026-11-18T10:22:00+00:00'))
    with Session()as s:return {cls.__tablename__:len(s.scalars(select(cls)).all())for cls in [User,Borehole,CoreRun,Reading,MissingInterval,Interpretation,Stratum,SampleInterval,Seal,Custody,ColumnRevision,ReceiptBatch,ReceiptSample,ReceiptBag,LabReceipt]}
if __name__=='__main__':print(json.dumps(seed(),ensure_ascii=False))
