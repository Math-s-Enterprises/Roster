"""Real API regressions with synthetic shops; no live database or integrations."""
import asyncio
from datetime import date, timedelta

import pytest

from tests.test_api import auth, register
from app.services.scheduler import DAYS


def _setup(client):
    headers = auth(register(client))
    shop = client.put('/api/shop', json={
        'departments': ['Shop Floor', 'Deli'], 'supervisory_roles': [],
    }, headers=headers).json()
    person = client.post('/api/employees', json={
        'name': 'Shared Person', 'email': None, 'role': 'Cashier', 'age': 30,
        'hourly_rate': 15, 'max_weekly_hours': 40, 'preferred_days_off': [],
        'departments': ['Shop Floor', 'Deli'],
    }, headers=headers)
    assert person.status_code == 201, person.text
    today = date.today()
    # Always future, even when this suite is run years after the bug was fixed.
    monday = today + timedelta(days=14 - today.weekday())
    return headers, shop['shop_id'], person.json()['employee_id'], monday


def _store(shop_id, eid, rid, group, monday, day, start, end, **extra):
    from app import db
    row = {
        'shop_id': shop_id, 'roster_id': rid, 'department': group,
        'week_start': monday.isoformat(), 'version': 'v1.0', 'approved': False,
        'created_at': monday.isoformat(), 'archived': False,
        'shifts': [{'employee_id': eid, 'day': day, 'start': start, 'end': end}],
        **extra,
    }
    asyncio.run(db.rosters.insert_one(row))
    return row


@pytest.mark.parametrize('offset,other_day,current_day', [
    (0, 'mon', 'tue'), (-7, 'sun', 'mon'), (7, 'mon', 'sun'),
])
def test_generation_never_overlaps_another_group_across_midnight(client, offset, other_day, current_day):
    headers, shop_id, eid, monday = _setup(client)
    hours = [{ 'day': d, 'open': '00:00', 'close': '08:00', 'closed': d != current_day}
             for d in DAYS]
    start, end = '22:00', '06:00'
    if offset == 7:
        hours = [{ 'day': d, 'open': '22:00', 'close': '06:00', 'closed': d != current_day}
                 for d in DAYS]
        start, end = '00:00', '08:00'
    configured = client.put('/api/shop', json={
        'hours': hours, 'min_shift_hours': 4, 'max_shift_hours': 8,
    }, headers=headers)
    assert configured.status_code == 200, configured.text
    _store(shop_id, eid, 'other', 'Deli', monday + timedelta(days=offset), other_day, start, end)
    generated = client.post('/api/roster/generate', json={
        'week_start': monday.isoformat(), 'department': 'Shop Floor',
    }, headers=headers)
    assert generated.status_code == 200, generated.text
    assert not [s for s in generated.json()['shifts']
                if s['employee_id'] == eid and s['day'] == current_day and s.get('start')], generated.text


@pytest.mark.parametrize('offset,other_day,current_day', [
    (0, 'mon', 'tue'), (-7, 'sun', 'mon'), (7, 'mon', 'sun'),
])
@pytest.mark.parametrize('force', [False, True])
def test_overlap_cannot_be_approved_even_with_password(client, offset, other_day, current_day, force):
    headers, shop_id, eid, monday = _setup(client)
    other_start, other_end, start, end = '22:00', '06:00', '00:00', '08:00'
    if offset == 7:
        other_start, other_end, start, end = '00:00', '08:00', '22:00', '06:00'
    _store(shop_id, eid, 'other', 'Deli', monday + timedelta(days=offset),
           other_day, other_start, other_end)
    _store(shop_id, eid, 'current', 'Shop Floor', monday, current_day, start, end)
    audit = client.get('/api/rosters/current/audit', headers=headers).json()
    assert any(b['rule'] == 'double_booked' for b in audit['blocking']), audit
    assert audit['can_force'] is False
    refused = client.post('/api/rosters/current/approve?acknowledge_gaps=true',
                          json={'force': force, 'password': 'password123'}, headers=headers)
    assert refused.status_code == 409, refused.text
    assert 'with or without' in refused.text


@pytest.mark.parametrize('offset,other_day,current_day', [(0, 'mon', 'tue'), (-7, 'sun', 'mon')])
def test_manual_overlap_names_the_other_group_and_times(client, offset, other_day, current_day):
    headers, shop_id, eid, monday = _setup(client)
    _store(shop_id, eid, 'other', 'Deli', monday + timedelta(days=offset), other_day, '22:00', '06:00')
    _store(shop_id, eid, 'current', 'Shop Floor', monday, current_day, '12:00', '20:00')
    response = client.put('/api/rosters/current', json={'shifts': [{
        'employee_id': eid, 'day': current_day, 'start': '00:00', 'end': '08:00',
    }]}, headers=headers)
    assert response.status_code == 409, response.text
    assert 'Deli' in response.text and '22:00-06:00' in response.text


def test_adjacent_weeks_do_not_spend_this_weeks_hours_or_days(client):
    headers, shop_id, eid, monday = _setup(client)
    # The same weekday in a different week is neither a duplicate nor this week's pay.
    _store(shop_id, eid, 'other', 'Deli', monday - timedelta(days=7), 'sun', '09:00', '17:00')
    _store(shop_id, eid, 'current', 'Shop Floor', monday, 'sun', '09:00', '17:00')
    response = client.get('/api/rosters/current', headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['shop_week_hours'][eid] == 7.2
    audit = client.get('/api/rosters/current/audit', headers=headers).json()
    assert not audit['blocking']
    saved = client.put('/api/rosters/current', json={'shifts': [{
        'employee_id': eid, 'day': 'sun', 'start': '09:00', 'end': '17:00',
    }]}, headers=headers)
    assert saved.status_code == 200, saved.text


def test_previous_sunday_shifts_are_returned_without_other_shop_data(client):
    headers, shop_id, eid, monday = _setup(client)
    _store(shop_id, eid, 'previous', 'Deli', monday - timedelta(days=7), 'sun', '22:00', '06:00')
    _store('unrelated-shop', eid, 'private', 'Deli', monday - timedelta(days=7), 'sun', '23:00', '07:00',
           created_at='9999-01-01')
    _store(shop_id, eid, 'current', 'Shop Floor', monday, 'mon', '12:00', '20:00')
    for path in ['/api/rosters/current', '/api/rosters?week_start=' + monday.isoformat()]:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        row = response.json() if isinstance(response.json(), dict) else response.json()[0]
        assert any(s['roster_id'] == 'previous' and s['week_offset'] == -7
                   for s in row['external_shifts']), row
        assert not any(s['roster_id'] == 'private' for s in row['external_shifts'])


def test_many_draft_versions_cannot_hide_a_boundary_commitment(client, monkeypatch):
    from app import db
    from app.tenancy import ScopedCollection
    headers, shop_id, eid, monday = _setup(client)
    _store(shop_id, eid, 'previous', 'Deli', monday - timedelta(days=7), 'sun', '22:00', '06:00')
    _store(shop_id, eid, 'current', 'Shop Floor', monday, 'mon', '00:00', '08:00')
    asyncio.run(db.rosters.insert_many([{
        'shop_id': shop_id, 'roster_id': f'draft-{index}', 'department': 'Shop Floor',
        'week_start': monday.isoformat(), 'created_at': '9999-01-01', 'shifts': [],
    } for index in range(501)]))
    original_find = ScopedCollection.find

    async def bounded_find(scope, extra=None, **kwargs):
        rows = await original_find(scope, extra, **kwargs)
        # mongomock's to_list ignores length; model the real Motor page limit.
        return rows[:kwargs.get('limit', 100)]

    monkeypatch.setattr(ScopedCollection, 'find', bounded_find)
    audit = client.get('/api/rosters/current/audit', headers=headers).json()
    assert any(b['rule'] == 'double_booked' for b in audit['blocking']), audit


@pytest.mark.parametrize('start', ['06:00', '17:00'])
def test_non_overlapping_boundary_shifts_are_not_hard_blocked(client, start):
    headers, shop_id, eid, monday = _setup(client)
    _store(shop_id, eid, 'other', 'Deli', monday - timedelta(days=7), 'sun', '22:00', '06:00')
    _store(shop_id, eid, 'current', 'Shop Floor', monday, 'mon', start, '21:00' if start == '17:00' else '14:00')
    audit = client.get('/api/rosters/current/audit', headers=headers).json()
    assert not audit['blocking'], audit
    response = client.post('/api/rosters/current/approve?acknowledge_gaps=true', headers=headers)
    assert response.status_code == 200, response.text


def test_previous_week_does_not_consume_hours_or_prevent_a_rested_later_shift(client):
    headers, shop_id, eid, monday = _setup(client)
    client.put(f'/api/employees/{eid}', json={
        'name': 'Shared Person', 'email': None, 'role': 'Cashier', 'age': 30,
        'hourly_rate': 15, 'max_weekly_hours': 8, 'departments': ['Shop Floor', 'Deli'],
    }, headers=headers)
    response = client.put('/api/shop', json={
        'hours': [{'day': d, 'open': '17:00', 'close': '21:00', 'closed': d != 'mon'} for d in DAYS],
        'min_shift_hours': 4, 'max_shift_hours': 8,
    }, headers=headers)
    assert response.status_code == 200, response.text
    _store(shop_id, eid, 'other', 'Deli', monday - timedelta(days=7), 'sun', '22:00', '06:00')
    result = client.post('/api/roster/generate', json={
        'week_start': monday.isoformat(), 'department': 'Shop Floor',
    }, headers=headers)
    assert result.status_code == 200, result.text
    assert [(s['day'], s['start'], s['end']) for s in result.json()['shifts']] == [('mon', '17:00', '21:00')]


def test_overlap_guard_is_not_tied_to_this_year(client):
    headers, shop_id, eid, _ = _setup(client)
    anchor = date(date.today().year + 50, 1, 1)
    monday = anchor + timedelta(days=(7 - anchor.weekday()) % 7)
    _store(shop_id, eid, 'other', 'Deli', monday - timedelta(days=7), 'sun', '22:00', '06:00')
    _store(shop_id, eid, 'current', 'Shop Floor', monday, 'mon', '00:00', '08:00')
    response = client.post('/api/rosters/current/approve?acknowledge_gaps=true',
                          json={'force': True, 'password': 'password123'}, headers=headers)
    assert response.status_code == 409, response.text


def test_sick_cover_cannot_bypass_a_previous_week_overnight_commitment(client):
    headers, shop_id, eid, monday = _setup(client)
    absent = client.post('/api/employees', json={
        'name': 'Absent Person', 'role': 'Cashier', 'age': 30, 'hourly_rate': 15,
        'max_weekly_hours': 40, 'departments': ['Shop Floor'],
    }, headers=headers).json()['employee_id']
    _store(shop_id, eid, 'other', 'Deli', monday - timedelta(days=7), 'sun', '22:00', '06:00')
    _store(shop_id, absent, 'current', 'Shop Floor', monday, 'mon', '00:00', '08:00', approved=True)
    options = client.get('/api/rosters/current/cover', params={
        'employee_id': absent, 'day': 'mon',
    }, headers=headers)
    assert options.status_code == 200, options.text
    assert eid not in [p['employee_id'] for p in options.json()['candidates']]
    response = client.post('/api/rosters/current/sick', json={
        'employee_id': absent, 'day': 'mon', 'cover_employee_id': eid,
    }, headers=headers)
    assert response.status_code == 409, response.text
    assert 'Deli' in response.text
