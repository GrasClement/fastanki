import pytest
from anki.collection import Collection as AnkiCollection
from anki.scheduler.v3 import CardAnswer
from fastanki.collection import Collection
from test_apkg import build

pytestmark = pytest.mark.timeout(120)
USER, PASS = 'tester', 's3kret'

def phone(tmp_path, ep):
    "The official client, standing in for a phone: downloads the collection from the server"
    p = AnkiCollection(str(tmp_path/'phone.anki2'))
    auth = p.sync_login(USER, PASS, ep)
    p.sync_collection(auth, False)
    full_download(p, auth)
    return p, auth

def full_download(p, auth):
    p.close_for_full_sync(); p.full_upload_or_download(auth=auth, server_usn=None, upload=False); p.reopen(after_full_sync=True)

def answer(p, rating='GOOD'):
    for cid in p.find_cards(''):
        card = p.get_card(cid); card.start_timer()
        states = p.sched.col._backend.get_scheduling_states(cid)
        p.sched.answer_card(p.sched.build_answer(card=card, states=states, rating=getattr(CardAnswer, rating)))

def test_reviews_from_another_client_reach_us_by_delta_sync(tmp_path, server):
    ep = server
    col = Collection.open(tmp_path/'ours'/'collection.anki2')
    col.import_apkg(build(tmp_path/'1.apkg'))
    assert col.sync(user=USER, passw=PASS, endpoint=ep, upload=True) == 'full sync'
    p, auth = phone(tmp_path, ep)
    answer(p, 'GOOD'); answer(p, 'AGAIN')
    p.sync_collection(auth, False)
    assert col.sync() == 'success'

    rv = col.reviews()
    assert len(rv) == 6 and {r['guid'] for r in rv} == {'guid-a', 'guid-b'}
    assert [r['rating'] for r in rv if r['guid'] == 'guid-a'] == [3, 1]         # Good, Again (1-4 scale)
    assert all(r['time_ms'] > 1_700_000_000_000 and r['duration_ms'] >= 0 for r in rv)
    assert [r['time_ms'] for r in rv] == sorted(r['time_ms'] for r in rv)
    st = {(s['guid'], s['ord']): s for s in col.card_states()}
    assert st['guid-a', 0]['reps'] == 2 and st['guid-a', 0]['deck'] == 'Maths::Test'
    assert st['guid-b', 1]['reps'] == 2

    assert col.revlog_csv(tmp_path/'revlog.csv') == 6
    head, *rows = (tmp_path/'revlog.csv').read_text().splitlines()
    assert head == 'card_id,review_time,review_rating,review_state,review_duration'
    assert {r.split(',')[3] for r in rows} <= {'1', '2', '3'}
    col.close(); p.close()

def test_edit_a_deck_without_losing_the_study_data(tmp_path, server):
    ep = server
    col = Collection.open(tmp_path/'ours'/'collection.anki2')
    col.import_apkg(build(tmp_path/'1.apkg'))
    col.sync(user=USER, passw=PASS, endpoint=ep, upload=True)
    p, auth = phone(tmp_path, ep)
    answer(p)
    p.sync_collection(auth, False); col.sync()
    reviews0 = col.reviews()
    cards0 = {(s['guid'], s['ord']): s for s in col.card_states()}

    # text, tags, deck name: plain delta syncs, in both directions
    st = col.import_apkg(build(tmp_path/'2.apkg', verso='v2', tags=('p1', 'edited'), deck_name='Maths::Renamed'))
    assert (st['notes_updated'], st['decks_renamed'], st['schema_changed']) == (1, 1, False)
    assert col.sync() == 'success'
    p.sync_collection(auth, False)
    assert p.db.scalar('select count(*) from revlog') == len(reviews0)
    assert p.db.scalar("select name from decks where id=2059400110") == 'Maths\x1fRenamed'
    assert p.db.scalar("select flds from notes where guid='guid-a'").endswith('v2 é')

    # a template added to a notetype is a schema change: the delta is refused by the server, a full sync is needed
    assert col.sync() in ('success', 'noChanges')       # pull first: a full upload replaces the server copy
    st = col.import_apkg(build(tmp_path/'3.apkg', verso='v2', tags=('p1', 'edited'), deck_name='Elsewhere', deck_id=2059400111, inverse=True))
    assert (st['cards_new'], st['models_changed'], st['schema_changed'], st['cards_moved']) == (1, 1, True, 3)
    assert col.sync(upload=True) == 'full sync'         # not a bare sync(): that would download the server copy over the import
    assert col.reviews() == reviews0                    # history intact
    now = {(s['guid'], s['ord']): s for s in col.card_states()}
    for k, v in cards0.items(): assert {**now[k], 'deck': v['deck']} == v      # scheduling intact, only the deck differs
    assert now['guid-a', 1]['type'] == 0                # the new card is new

    r = p.sync_collection(auth, False)
    assert r.required == r.FULL_SYNC                    # the phone is told to download
    full_download(p, auth)
    assert p.db.scalar('select count(*) from revlog') == len(reviews0)
    assert (p.db.scalar('select count(*) from notes'), p.db.scalar('select count(*) from cards')) == (2, 4)
    assert p.db.scalar('select count(*) from cards where reps>0') == sum(1 for v in cards0.values() if v['reps'])
    col.close(); p.close()
