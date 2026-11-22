import genanki, pytest
from fastanki.collection import Collection

pytestmark = pytest.mark.timeout(120)

QR = genanki.Model(1607392319, 'T-QR', fields=[{'name':'Id'}, {'name':'Recto'}, {'name':'Verso'}], sort_field_index=1,
    templates=[{'name':'C1', 'qfmt':'{{Recto}}', 'afmt':'{{Recto}}<hr id=answer>{{Verso}}'},
               {'name':'C2', 'qfmt':'{{Verso}}', 'afmt':'{{Verso}}<hr id=answer>{{Recto}}'}])
CLOZE = genanki.Model(1607392320, 'T-Cloze', model_type=genanki.Model.CLOZE, fields=[{'name':'Id'}, {'name':'Text'}],
    sort_field_index=1, templates=[{'name':'Cloze', 'qfmt':'{{cloze:Text}}', 'afmt':'{{cloze:Text}}'}])

def build(path, verso='v1', media=None, deck_name='Maths::Test', deck_id=2059400110, inverse=False, tags=('p1',)):
    "genanki gives every note a fresh id at each build; only the guids are stable. The 'é' is deliberate: non-ASCII must survive."
    qr = genanki.Model(1607392319, 'T-QR', fields=[{'name':'Id'}, {'name':'Recto'}, {'name':'Verso'}], sort_field_index=1,
        templates=QR.templates[:2 if inverse else 1])
    deck = genanki.Deck(deck_id, deck_name)
    deck.add_note(genanki.Note(qr, ['a', 'Q $x^2$?', f'{verso} é'], tags=list(tags), guid='guid-a'))
    deck.add_note(genanki.Note(CLOZE, ['b', '{{c1::one}} and {{c2::two}}'], tags=['p2'], guid='guid-b'))
    genanki.Package(deck, media_files=media or []).write_to_file(str(path))
    return path

def count(col, table): return col.q1(f'select count(*) from {table}')

def test_import_creates_notes_cards_notetypes_decks_media(tmp_path):
    img = tmp_path/'fig.png'; img.write_bytes(b'\x89PNG-fake')
    with Collection.open(tmp_path/'c.anki2') as col:
        st = col.import_apkg(build(tmp_path/'a.apkg', media=[str(img)]))
        assert (st['notes_new'], st['cards_new'], st['models_new'], st['decks_new'], st['media']) == (2, 3, 2, 1, 1)
        assert not st['schema_changed']
        assert (count(col, 'notes'), count(col, 'cards')) == (2, 3)
        assert col.q1("select count(*) from notes where guid in ('guid-a','guid-b')") == 2
        assert col.q1('select name from decks where id=2059400110') == 'Maths\x1fTest'
        assert (col.path.with_suffix('.media')/'fig.png').exists()
        # derived columns are Anki's own, not the package's
        n = col.find_notes(Id='a')[0]
        assert col.q1('select sfld from notes where id=?', n.id) == 'Q $x^2$?'

def test_reimport_matches_by_guid_not_id(tmp_path):
    with Collection.open(tmp_path/'c.anki2') as col:
        col.import_apkg(build(tmp_path/'a.apkg'))
        nid = col.q1("select id from notes where guid='guid-a'")
        cids = sorted(r[0] for r in col.q('select id from cards'))
        st = col.import_apkg(build(tmp_path/'b.apkg'))              # rebuilt: new ids in the package, same content
        assert (st['notes_new'], st['notes_updated'], st['notes_same'], st['cards_new']) == (0, 0, 2, 0)
        st = col.import_apkg(build(tmp_path/'c.apkg', verso='v2', tags=('p1', 'edited')))
        assert (st['notes_new'], st['notes_updated'], st['notes_same']) == (0, 1, 1)
        assert col.q1("select id from notes where guid='guid-a'") == nid
        assert 'v2' in col.q1('select flds from notes where id=?', nid)
        assert 'edited' in col.q1('select tags from notes where id=?', nid)
        assert sorted(r[0] for r in col.q('select id from cards')) == cids
        assert (count(col, 'notes'), count(col, 'cards')) == (2, 3)

def test_import_never_deletes(tmp_path):
    with Collection.open(tmp_path/'c.anki2') as col:
        col.import_apkg(build(tmp_path/'a.apkg'))
        keep = col.add(Front='mine', Back='untouched')
        col.import_apkg(build(tmp_path/'b.apkg'))
        assert col.get_note(keep.id)['Front'] == 'mine' and count(col, 'notes') == 3

def test_deck_rename_and_card_move_keep_scheduling(tmp_path):
    with Collection.open(tmp_path/'c.anki2') as col:
        col.import_apkg(build(tmp_path/'a.apkg'))
        col.con.execute("update cards set type=2, queue=2, ivl=9, reps=4, lapses=1, due=123")
        before = col.q('select id, ivl, reps, lapses, due from cards order by id')
        st = col.import_apkg(build(tmp_path/'b.apkg', deck_name='Maths::Renamed'))
        assert (st['decks_renamed'], st['cards_moved']) == (1, 0)
        assert col.q1('select name from decks where id=2059400110') == 'Maths\x1fRenamed'
        st = col.import_apkg(build(tmp_path/'c.apkg', deck_name='Elsewhere', deck_id=2059400111))
        assert (st['decks_new'], st['cards_moved'], st['notes_same']) == (1, 3, 2)
        assert col.q('select id, ivl, reps, lapses, due from cards order by id') == before

def test_filtered_deck_cards_are_not_moved(tmp_path):
    with Collection.open(tmp_path/'c.anki2') as col:
        col.import_apkg(build(tmp_path/'a.apkg'))
        col.con.execute('update cards set odid=did where ord=0 and nid=(select id from notes where guid=?)', ('guid-a',))
        col.con.execute('update cards set did=1 where odid!=0')
        st = col.import_apkg(build(tmp_path/'b.apkg'))
        assert st['cards_moved'] == 0

def test_new_template_adds_a_card_and_marks_schema_change(tmp_path):
    with Collection.open(tmp_path/'c.anki2') as col:
        col.import_apkg(build(tmp_path/'a.apkg'))
        col.con.execute('update col set scm=1')
        old = sorted(r[0] for r in col.q('select id from cards'))
        st = col.import_apkg(build(tmp_path/'b.apkg', inverse=True))
        assert (st['cards_new'], st['models_changed'], st['schema_changed']) == (1, 1, True)
        assert col.q1('select scm from col') > 1
        assert set(old) < set(r[0] for r in col.q('select id from cards'))

def test_text_only_changes_to_a_notetype_are_not_a_schema_change(tmp_path):
    with Collection.open(tmp_path/'c.anki2') as col:
        col.import_apkg(build(tmp_path/'a.apkg'))
        qr = genanki.Model(1607392319, 'T-QR', fields=[{'name':'Id'}, {'name':'Recto'}, {'name':'Verso'}], sort_field_index=1, css='.card{color:red}',
            templates=QR.templates[:1])
        deck = genanki.Deck(2059400110, 'Maths::Test')
        deck.add_note(genanki.Note(qr, ['a', 'Q $x^2$?', 'v1 é'], tags=['p1'], guid='guid-a'))
        genanki.Package(deck).write_to_file(str(tmp_path/'b.apkg'))
        st = col.import_apkg(tmp_path/'b.apkg')
        assert (st['models_changed'], st['schema_changed']) == (1, False)

def test_media_renamed_by_fastanki_is_refused(tmp_path):
    img = tmp_path/'Fig.png'; img.write_bytes(b'x')
    with Collection.open(tmp_path/'c.anki2') as col:
        col.add_media(b'other', 'Fig.png')            # same lowercased name, different content -> stored under a hash name
        with pytest.raises(ValueError, match='stored as'):
            col.import_apkg(build(tmp_path/'a.apkg', media=[str(img)]))
        assert count(col, 'notes') == 0              # nothing half-imported

def test_modern_apkg_is_refused(tmp_path):
    import zipfile
    p = tmp_path/'m.apkg'
    with zipfile.ZipFile(p, 'w') as z: z.writestr('collection.anki21b', b'x'); z.writestr('meta', b'')
    with Collection.open(tmp_path/'c.anki2') as col, pytest.raises(ValueError, match='modern'): col.import_apkg(p)
