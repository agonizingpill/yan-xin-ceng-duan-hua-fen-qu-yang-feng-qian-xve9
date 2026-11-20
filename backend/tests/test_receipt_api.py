"""HTTP 层：路由、角色权限、幂等回执与分组签收端到端。"""
import os
import tempfile
import uuid

import pytest

_tmp = tempfile.mkdtemp(prefix='core-strata-api-')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(_tmp, 'api.db')
os.environ.setdefault('REDIS_URL', 'redis://127.0.0.1:6399/0')
os.environ['SEED_DEMO'] = 'false'

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.database import Base, engine, Session
import src.models as M
from src.security import password_hash
from src.main import app

OPERATOR = {'email': 'operator@api.local', 'role': 'operator'}
SUPERVISOR = {'email': 'supervisor@api.local', 'role': 'supervisor'}
VIEWER = {'email': 'viewer@api.local', 'role': 'viewer'}


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session.begin() as s:
        for role in ('operator', 'supervisor', 'viewer'):
            s.add(M.User(email=role + '@api.local', password=password_hash('Core2026!'), role=role))
    yield


@pytest.fixture
def client():
    return TestClient(app)


def token(client, email):
    r = client.post('/auth/login', json={'email': email, 'password': 'Core2026!'})
    assert r.status_code == 200, r.text
    return r.json()['token']


def auth(client, email):
    return {'Authorization': 'Bearer ' + token(client, email)}


def seed_group(n_sample=2):
    """Two transferred samples with original readings and intact seals."""
    with Session.begin() as s:
        h = M.Borehole(code='BH-A', site='API孔', total_depth=36, cut_quota=6)
        s.add(h)
        s.flush()
        r = M.CoreRun(borehole_id=h.id, code='R01', start_m=0, end_m=36, recovered_m=36)
        s.add(r)
        s.flush()
        it = M.Interpretation(borehole_id=h.id, state='confirmed')
        s.add(it)
        s.flush()
        st = M.Stratum(interpretation_id=it.id, start_m=0, end_m=36, lithology='测试岩性', contact_note='测试完整层段')
        s.add(st)
        s.flush()
        specs = [('CS-A', 2, 3, [(2.5, 2.10, 12.0, 2200.0)]),
                 ('CS-B', 4, 5, [(4.5, 3.10, 100.0, 6100.0)])]
        ids = []
        for code, start, end, readings in specs[:n_sample]:
            for depth, d, su, v in readings:
                s.add(M.Reading(borehole_id=h.id, run_id=r.id, depth_m=depth,
                                density=d, susceptibility=su, velocity=v))
            sample = M.SampleInterval(borehole_id=h.id, stratum_id=st.id, code=code,
                                      start_m=start, end_m=end, purpose='测试取样',
                                      destructive=True, state='transferred')
            s.add(sample)
            s.flush()
            seal = M.Seal(sample_id=sample.id, code='CX-' + code, state='intact',
                          sealed_by='operator@api.local', snapshot={'code': code})
            s.add(seal)
            s.flush()
            s.add(M.Custody(seal_id=seal.id, receiver='实验室', destination='试验室',
                            condition='核对样号与铅封完整', at='2026-11-18T00:00:00+00:00'))
            ids.append(sample.id)
        return h.id, ids


def test_role_permissions_on_lab_routes(client):
    hid, ids = seed_group()
    viewer = auth(client, 'viewer@api.local')
    body = {'borehole_id': hid, 'code': 'RC-A', 'sample_ids': ids, 'note': '同孔一组'}
    assert client.post('/receipt-batches', json=body, headers=viewer).status_code == 403
    oper = auth(client, 'operator@api.local')
    assert client.post('/receipt-batches', json=body, headers=oper).status_code == 200


def test_http_full_flow_and_idempotent_receipt(client):
    hid, ids = seed_group()
    oper = auth(client, 'operator@api.local')
    sup = auth(client, 'supervisor@api.local')
    batch = client.post('/receipt-batches', json={'borehole_id': hid, 'code': 'RC-B', 'sample_ids': ids,
                                                  'note': '同孔一组'}, headers=oper).json()
    bid = batch['id']
    for sid, code, d, s_, v in [(ids[0], 'LAB-1', 2.10, 12.0, 2200.0), (ids[1], 'LAB-2', 3.10, 100.0, 6100.0)]:
        r = client.post(f'/receipt-batches/{bid}/bags', headers=oper,
                        json={'nominal_sample_id': sid, 'code': code, 'density': d,
                              'susceptibility': s_, 'velocity': v})
        assert r.status_code == 200, r.text
    # half check-in is resumable
    r1 = client.post(f'/receipt-batches/{bid}/check-in', headers=oper, json={'sample_ids': [ids[0]]})
    assert r1.status_code == 200 and r1.json()['checked'] == 1
    assert client.post(f'/receipt-batches/{bid}/match', headers=oper).status_code == 409
    r2 = client.post(f'/receipt-batches/{bid}/check-in', headers=oper, json={'sample_ids': ids})
    assert r2.json()['checked'] == 2
    assert client.post(f'/receipt-batches/{bid}/match', headers=oper).json()['state'] == 'matched'
    key = str(uuid.uuid4())
    first = client.post(f'/receipt-batches/{bid}/receipt', headers=oper, json={'idempotency_key': key})
    assert first.status_code == 200 and first.json()['replayed'] is False
    second = client.post(f'/receipt-batches/{bid}/receipt', headers=oper, json={'idempotency_key': key})
    assert second.json()['replayed'] is True
    assert second.json()['receipt']['id'] == first.json()['receipt']['id']
    # supervisor-only release
    assert client.post(f'/receipt-batches/{bid}/verify', headers=oper,
                       json={'reason': '主管验明实物后按袋上标签放行核对一致',
                             'assignment': [{'bag_id': 1, 'sample_id': ids[0]},
                                            {'bag_id': 2, 'sample_id': ids[1]}]}).status_code == 403


def test_register_exposes_lab_tables(client):
    hid, ids = seed_group()
    sup = auth(client, 'supervisor@api.local')
    data = client.get('/register', headers=sup).json()
    for key in ('receipt_batches', 'receipt_samples', 'receipt_bags', 'lab_receipts'):
        assert key in data


def test_break_seal_voids_receipt_via_http(client):
    hid, ids = seed_group()
    oper = auth(client, 'operator@api.local')
    sup = auth(client, 'supervisor@api.local')
    bid = client.post('/receipt-batches', json={'borehole_id': hid, 'code': 'RC-C', 'sample_ids': ids,
                                                'note': '同孔一组'}, headers=oper).json()['id']
    for sid, code, d, s_, v in [(ids[0], 'LAB-1', 2.10, 12.0, 2200.0), (ids[1], 'LAB-2', 3.10, 100.0, 6100.0)]:
        client.post(f'/receipt-batches/{bid}/bags', headers=oper,
                    json={'nominal_sample_id': sid, 'code': code, 'density': d, 'susceptibility': s_, 'velocity': v})
    client.post(f'/receipt-batches/{bid}/check-in', headers=oper, json={'sample_ids': ids})
    client.post(f'/receipt-batches/{bid}/match', headers=oper)
    receipt = client.post(f'/receipt-batches/{bid}/receipt', headers=oper,
                          json={'idempotency_key': 'http-key-' + str(uuid.uuid4())}).json()['receipt']
    with Session() as s:
        seal = s.scalar(select(M.Seal).where(M.Seal.sample_id == ids[0]))
    assert client.post(f'/seals/{seal.id}/break', headers=sup,
                       json={'reason': '运输中发现铅封断裂，需要重封核对'}).status_code == 200
    data = client.get('/register', headers=sup).json()
    batch = next(x for x in data['receipt_batches'] if x['id'] == bid)
    assert batch['state'] == 'held'
    old = next(x for x in data['lab_receipts'] if x['id'] == receipt['id'])
    assert old['state'] == 'void'
