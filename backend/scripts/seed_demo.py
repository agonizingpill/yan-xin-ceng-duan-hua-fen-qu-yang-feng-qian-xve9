import json
import numpy as np
from sqlalchemy import select
from src.database import Session,Base,engine
from src.models import User,Borehole,CoreRun,Reading,MissingInterval,Interpretation,Stratum,SampleInterval,Seal,Custody,ColumnRevision
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
    with Session()as s:return {cls.__tablename__:len(s.scalars(select(cls)).all())for cls in [User,Borehole,CoreRun,Reading,MissingInterval,Interpretation,Stratum,SampleInterval,Seal,Custody,ColumnRevision]}
if __name__=='__main__':print(json.dumps(seed(),ensure_ascii=False))
