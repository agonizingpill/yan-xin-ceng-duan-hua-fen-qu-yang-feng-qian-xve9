import os,time,logging
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from .database import Session
from .models import Interpretation,Reading,Borehole
from .common import get,pack
from .layer_model import fit_layers
r=Redis.from_url(os.environ['REDIS_URL'],decode_responses=True)
logging.basicConfig(level=logging.INFO)
while True:
    Path('/artifacts/core-heartbeat').write_text(str(time.time()))
    item=r.blpop('core-interpret',timeout=2)
    if not item:continue
    id=int(item[1])
    try:
        with Session.begin()as s:
            preview=get(s,Interpretation,id);get(s,Borehole,preview.borehole_id,True);x=get(s,Interpretation,id,True)
            if x.state!='queued':continue
            rows=[pack(z)for z in s.scalars(select(Reading).where(Reading.borehole_id==x.borehole_id).order_by(Reading.depth_m))]
            x.evidence=fit_layers(rows);x.state='ready';x.error='';logging.info('interpreted %s k=%s',id,x.evidence['chosen_k'])
    except Exception as e:
        logging.exception('interpretation failed')
        with Session.begin()as s:
            x=get(s,Interpretation,id,True);x.state='failed';x.error=str(e)[:550]
