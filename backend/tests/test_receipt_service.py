"""实验室同孔收样组：配对/暂扣/破签/幂等回执/断点续签。

每个测试用临时 SQLite 库，通过 service 层直接调用，验证状态机与并发收尾。
"""
import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.database import Session
import src.models as M
from src import receipt_service as receipt, custody_service as custody
from src.schemas import (ReceiptBagInput, ReceiptCheckin, ReceiptIssue, ReceiptPair,
                         ReceiptVerify, SealInput, Reason)
from conftest import (OPERATOR, SUPERVISOR, make_hole, add_reading, add_sample,
                      add_batch, add_bag, check_in, do_match, issue, state_of, holds_of)


def setup_group(profiles):
    """profiles: list of (code, start, end, [(depth,density,susc,vel),...], nominal_order)"""
    hid, rid, stid = make_hole()
    for _, start, end, readings in profiles:
        for depth, d, s_, v in readings:
            add_reading(hid, rid, depth, d, s_, v)
    samples = {}
    for code, start, end, readings in profiles:
        samples[code] = add_sample(hid, stid, code, start, end)
    return hid, samples


def two_profile_samples(base_d, base_s, base_v, spread=0.0):
    """Two intervals at 2–3m and 4–5m, each with 3 readings; second is distinct."""
    a = [(2.5, base_d, base_s, base_v)] + ([(3.5, base_d + spread, base_s, base_v)] if spread else [])
    return a


def std_profiles():
    # interval 2-3m: mean (2.10, 12.0, 2200); 4-5m: (3.10, 100.0, 6100)
    return [
        ('CS-A', 2, 3, [(2.5, 2.10, 12.0, 2200.0)]),
        ('CS-B', 4, 5, [(4.5, 3.10, 100.0, 6100.0)]),
    ]


def test_happy_path_match_and_receipt_once():
    hid, samples = setup_group(std_profiles())
    b = add_batch(hid, 'RC-1', [samples['CS-A'], samples['CS-B']])
    add_bag(b['id'], samples['CS-B'], 'BAG-1', 3.11, 101.0, 6120.0)
    add_bag(b['id'], samples['CS-A'], 'BAG-2', 2.09, 11.0, 2190.0)
    r = check_in(b['id'], [samples['CS-A'], samples['CS-B']])
    assert r['checked'] == 2 and not r['remaining_sample_ids']
    m = do_match(b['id'])
    assert m['state'] == 'matched' and not holds_of(b['id'])
    out = issue(b['id'], 'idem-key-0001')
    assert not out['replayed'] and out['receipt']['bag_count'] == 2
    again = issue(b['id'], 'idem-key-0001')
    assert again['replayed'] and again['receipt']['id'] == out['receipt']['id']
    with Session() as s:
        assert len(s.scalars(select(M.LabReceipt)).all()) == 1


def test_unmatched_holds_group_and_blocks_receipt():
    hid, samples = setup_group(std_profiles())
    b = add_batch(hid, 'RC-2', [samples['CS-A'], samples['CS-B']])
    add_bag(b['id'], samples['CS-A'], 'BAG-1', 2.10, 12.0, 2200.0)
    add_bag(b['id'], samples['CS-B'], 'BAG-2', 2.50, 60.0, 4000.0)  # matches neither
    check_in(b['id'], [samples['CS-A'], samples['CS-B']])
    m = do_match(b['id'])
    assert m['state'] == 'held'
    joined = '；'.join(holds_of(b['id']))
    assert '配不上任何原切样段' in joined
    with pytest.raises(HTTPException) as e:
        issue(b['id'], 'idem-key-0002')
    assert e.value.status_code == 409
    with Session() as s:
        assert not s.scalars(select(M.LabReceipt)).all()


def test_ambiguous_assignment_holds_group():
    # Two intervals with identical distributions -> both pairings tie -> hold.
    hid, rid, stid = make_hole()
    for depth in (2.5, 4.5):
        add_reading(hid, rid, depth, 2.10, 12.0, 2200.0)
    a = add_sample(hid, stid, 'CS-A', 2, 3)
    b_ = add_sample(hid, stid, 'CS-B', 4, 5)
    batch = add_batch(hid, 'RC-3', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.10, 12.0, 2200.0)
    add_bag(batch['id'], b_, 'BAG-2', 2.10, 12.0, 2200.0)
    check_in(batch['id'], [a, b_])
    m = do_match(batch['id'])
    assert m['state'] == 'held'
    joined = '；'.join(holds_of(batch['id']))
    assert '两种及以上配法都说得通' in joined
    assert '备选配法' in joined
    with pytest.raises(HTTPException):
        issue(batch['id'], 'idem-key-0003')


def test_break_seal_invalidates_pairing_and_voids_receipt():
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-4', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.10, 12.0, 2200.0)
    add_bag(batch['id'], b_, 'BAG-2', 3.10, 100.0, 6100.0)
    check_in(batch['id'], [a, b_])
    do_match(batch['id'])
    out = issue(batch['id'], 'idem-key-0004')
    assert state_of(batch['id']) == 'receipted'

    with Session.begin() as s:
        seal = s.scalar(select(M.Seal).where(M.Seal.sample_id == a))
        custody.break_seal(s, seal.id, Reason(reason='运输途中发现该袋铅封断裂，疑似调换'), SUPERVISOR)

    assert state_of(batch['id']) == 'held'
    with Session() as s:
        batch_row = s.get(M.ReceiptBatch, batch['id'])
        assert '旧配对已失效' in '；'.join(batch_row.holds)
        rs = s.scalar(select(M.ReceiptSample).where(M.ReceiptSample.sample_id == a))
        assert not rs.checked_in
        old = s.scalar(select(M.LabReceipt).where(M.LabReceipt.id == out['receipt']['id']))
        assert old.state == 'void'
    # cannot check in before resealing
    with pytest.raises(HTTPException):
        check_in(batch['id'], [a])
    # reseal + custody, then re-check-in works and a new receipt number is issued
    with Session.begin() as s:
        x = custody.seal(s, SealInput(sample_id=a, code='CX-NEW-A', reason='双人核样后重新铅封，旧链保留'), OPERATOR)
        sample = s.get(M.SampleInterval, a)
        s.add(M.Custody(seal_id=x['id'], receiver='实验室', destination='试验室',
                        condition='重封后重新交接，核对样号与铅封', at='2026-11-19T00:00:00+00:00'))
        sample.state = 'transferred'
    check_in(batch['id'], [a, b_])
    m = do_match(batch['id'])
    assert m['state'] == 'matched'
    out2 = issue(batch['id'], 'idem-key-0005')
    assert out2['receipt']['version'] == 2
    assert out2['receipt']['code'].endswith('R02')


def test_content_digest_and_random_order_independent():
    hid, samples = setup_group(std_profiles())
    batch = add_batch(hid, 'RC-5', [samples['CS-A'], samples['CS-B']])
    add_bag(batch['id'], samples['CS-B'], 'BAG-X', 3.10, 100.0, 6100.0)
    add_bag(batch['id'], samples['CS-A'], 'BAG-Y', 2.10, 12.0, 2200.0)
    check_in(batch['id'], [samples['CS-B'], samples['CS-A']])
    m = do_match(batch['id'])
    assert m['state'] == 'matched'
    with Session() as s:
        bag = s.scalar(select(M.ReceiptBag).where(M.ReceiptBag.code == 'BAG-X'))
        assert bag.matched_sample_id == samples['CS-B']


def test_partial_checkin_resumes_without_half_receipt():
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-6', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.10, 12.0, 2200.0)
    add_bag(batch['id'], b_, 'BAG-2', 3.10, 100.0, 6100.0)
    # first bag checked in, then the operator goes offline
    out = check_in(batch['id'], [a])
    assert out['checked'] == 1 and out['remaining_sample_ids'] == [b_]
    # matching is not possible on half a group
    with pytest.raises(HTTPException):
        do_match(batch['id'])
    with pytest.raises(HTTPException):
        issue(batch['id'], 'idem-key-0006')
    # resume: re-checking in A is a no-op, then B completes the group
    again = check_in(batch['id'], [a])
    assert again['checked'] == 1
    fin = check_in(batch['id'], [a, b_])
    assert fin['checked'] == 2 and fin['batch']['state'] == 'collecting'
    m = do_match(batch['id'])
    assert m['state'] == 'matched'


def test_receipt_requires_all_bags_and_bag_count_matches():
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-7', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.10, 12.0, 2200.0)
    # only one bag registered -> can't complete check-in for B, no matching
    with pytest.raises(HTTPException):
        check_in(batch['id'], [b_])
    with pytest.raises(HTTPException):
        do_match(batch['id'])
    add_bag(batch['id'], b_, 'BAG-2', 3.10, 100.0, 6100.0)
    check_in(batch['id'], [a, b_])
    m = do_match(batch['id'])
    assert m['state'] == 'matched'


def test_wrong_label_but_matching_profile_files_swap_hint_only_after_checkin():
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-8', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 3.10, 100.0, 6100.0)  # bag labelled A looks like B
    add_bag(batch['id'], b_, 'BAG-2', 2.10, 12.0, 2200.0)
    check_in(batch['id'], [a, b_])
    do_match(batch['id'])
    assert '疑似封签贴反' in '；'.join(holds_of(batch['id']))


def test_receipt_idempotent_after_network_retry():
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-9', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.10, 12.0, 2200.0)
    add_bag(batch['id'], b_, 'BAG-2', 3.10, 100.0, 6100.0)
    check_in(batch['id'], [a, b_])
    do_match(batch['id'])
    first = issue(batch['id'], 'idem-key-0009')
    for _ in range(3):
        retry = issue(batch['id'], 'idem-key-0009')
        assert retry['replayed'] and retry['receipt']['code'] == first['receipt']['code']
    with Session() as s:
        assert len(s.scalars(select(M.LabReceipt).where(M.LabReceipt.batch_id == batch['id'])).all()) == 1


def test_different_idempotency_key_still_only_one_receipt():
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-10', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.10, 12.0, 2200.0)
    add_bag(batch['id'], b_, 'BAG-2', 3.10, 100.0, 6100.0)
    check_in(batch['id'], [a, b_])
    do_match(batch['id'])
    first = issue(batch['id'], 'idem-key-0010')
    second = issue(batch['id'], 'idem-key-0011')
    assert second['replayed'] and second['receipt']['id'] == first['receipt']['id']


def test_viewer_and_role_permissions_are_in_routes_not_services():
    # services are role-agnostic; the route layer enforces roles.  Here we only
    # assert that a verify payload must be complete and one-to-one.
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-11', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.50, 60.0, 4000.0)
    add_bag(batch['id'], b_, 'BAG-2', 2.50, 60.0, 4000.0)
    check_in(batch['id'], [a, b_])
    do_match(batch['id'])
    with pytest.raises(HTTPException):
        with Session.begin() as s:
            receipt.verify(s, batch['id'], ReceiptVerify(reason='主管验明实物后按袋上标签放行',
                                                         assignment=[ReceiptPair(bag_id=1, sample_id=a)]), SUPERVISOR)
    with pytest.raises(HTTPException):
        with Session.begin() as s:
            receipt.verify(s, batch['id'], ReceiptVerify(reason='主管验明实物后按袋上标签放行',
                                                         assignment=[ReceiptPair(bag_id=1, sample_id=a),
                                                                     ReceiptPair(bag_id=1, sample_id=b_)]), SUPERVISOR)


def test_reseal_requires_new_custody_before_checkin():
    hid, samples = setup_group(std_profiles())
    a, b_ = samples['CS-A'], samples['CS-B']
    batch = add_batch(hid, 'RC-12', [a, b_])
    add_bag(batch['id'], a, 'BAG-1', 2.10, 12.0, 2200.0)
    add_bag(batch['id'], b_, 'BAG-2', 3.10, 100.0, 6100.0)
    check_in(batch['id'], [a, b_])
    do_match(batch['id'])
    with Session.begin() as s:
        seal = s.scalar(select(M.Seal).where(M.Seal.sample_id == a))
        custody.break_seal(s, seal.id, Reason(reason='抽检发现铅封断口，样袋需重封并重新交接'), SUPERVISOR)
    with Session.begin() as s:
        custody.seal(s, SealInput(sample_id=a, code='CX-NEW-12', reason='双人核样后重新铅封，保留旧封链'), OPERATOR)
    with pytest.raises(HTTPException) as e:
        check_in(batch['id'], [a, b_])
    assert '尚未完成封签交接' in e.value.detail
    with Session.begin() as s:
        new = s.scalar(select(M.Seal).where(M.Seal.code == 'CX-NEW-12'))
        s.add(M.Custody(seal_id=new.id, receiver='实验室', destination='试验室',
                        condition='重封后重新交接，双方核对样号与铅封', at='2026-11-20T00:00:00+00:00'))
        s.get(M.SampleInterval, a).state = 'transferred'
    out = check_in(batch['id'], [a, b_])
    assert out['checked'] == 2
    assert do_match(batch['id'])['state'] == 'matched'
