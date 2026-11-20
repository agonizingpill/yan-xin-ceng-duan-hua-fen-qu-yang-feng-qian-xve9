import os
import tempfile

DB = os.path.join(tempfile.mkdtemp(prefix='core-strata-test-'), 'test.db')
os.environ['DATABASE_URL'] = 'sqlite:///' + DB
os.environ.setdefault('REDIS_URL', 'redis://127.0.0.1:6399/0')
os.environ['SEED_DEMO'] = 'false'

import pytest
from sqlalchemy import select
from src.database import Base, engine, Session
import src.models as M
from src.security import password_hash
from src import receipt_service as receipt, custody_service as custody


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session.begin() as s:
        for role in ('operator', 'supervisor', 'viewer'):
            s.add(M.User(email=role + '@test.local', password=password_hash('x'), role=role))
    yield
    Base.metadata.drop_all(engine)


OPERATOR = {'email': 'operator@test.local', 'role': 'operator'}
SUPERVISOR = {'email': 'supervisor@test.local', 'role': 'supervisor'}


def make_hole(depth=36):
    with Session.begin() as s:
        h = M.Borehole(code='BH-T', site='测试孔', total_depth=depth, cut_quota=10)
        s.add(h)
        s.flush()
        r = M.CoreRun(borehole_id=h.id, code='R01', start_m=0, end_m=depth, recovered_m=depth)
        s.add(r)
        s.flush()
        it = M.Interpretation(borehole_id=h.id, state='confirmed')
        s.add(it)
        s.flush()
        st = M.Stratum(interpretation_id=it.id, start_m=0, end_m=depth,
                       lithology='测试岩性', contact_note='测试用完整层段')
        s.add(st)
        s.flush()
        return h.id, r.id, st.id


def add_reading(hid, rid, depth, density, susc, vel):
    with Session.begin() as s:
        s.add(M.Reading(borehole_id=hid, run_id=rid, depth_m=depth,
                        density=density, susceptibility=susc, velocity=vel))


def add_sample(hid, stratum_id, code, start, end, state='transferred', seal=True):
    """Create a cut interval with an original measured profile and, if asked,
    a current intact seal plus a receipt of custody."""
    with Session.begin() as s:
        sample = M.SampleInterval(borehole_id=hid, stratum_id=stratum_id, code=code,
                                  start_m=start, end_m=end, purpose='测试取样', destructive=True,
                                  state=state)
        s.add(sample)
        s.flush()
        sid = sample.id
        if seal:
            sl = M.Seal(sample_id=sid, code='CX-' + code, state='intact', sealed_by=OPERATOR['email'],
                        snapshot={'code': code})
            s.add(sl)
            s.flush()
            s.add(M.Custody(seal_id=sl.id, receiver='实验室', destination='试验室',
                            condition='核对样号与铅封完整', at='2026-11-18T00:00:00+00:00'))
        return sid


def add_batch(hid, code, sample_ids):
    with Session.begin() as s:
        from src.schemas import ReceiptBatchInput
        return receipt.create(s, ReceiptBatchInput(borehole_id=hid, code=code,
                                                   sample_ids=sample_ids, note='同孔一组'), OPERATOR)


def add_bag(bid, nominal, code, density, susc, vel):
    with Session.begin() as s:
        from src.schemas import ReceiptBagInput
        return receipt.add_bag(s, bid, ReceiptBagInput(nominal_sample_id=nominal, code=code,
                                                       density=density, susceptibility=susc,
                                                       velocity=vel), OPERATOR)


def check_in(bid, ids, user=OPERATOR):
    with Session.begin() as s:
        from src.schemas import ReceiptCheckin
        return receipt.check_in(s, bid, ReceiptCheckin(sample_ids=ids), user)


def do_match(bid, user=SUPERVISOR):
    with Session.begin() as s:
        return receipt.match(s, bid, user)


def issue(bid, key, user=OPERATOR):
    with Session.begin() as s:
        return receipt.issue_receipt(s, bid, key, user)


def state_of(bid):
    with Session() as s:
        return s.get(M.ReceiptBatch, bid).state


def holds_of(bid):
    with Session() as s:
        return s.get(M.ReceiptBatch, bid).holds
