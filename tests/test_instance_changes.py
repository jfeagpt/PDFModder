"""A duplicate inherits old changes; later edits belong only to its instance."""
import pymupdf as fitz
import pytest

from pdfmodder.composition import AddTextRequest
from pdfmodder.model import EditRequest
from pdfmodder.search_replace import find_matches
from pdfmodder.worker import Session
from test_review_text import fixture


def page(number, rotation=0):
    return dict(source='current', page=number, rotation=rotation)


@pytest.fixture
def session(tmp_path):
    path=tmp_path/'source.pdf'
    path.write_bytes(fixture())
    value=Session(path,config_path=tmp_path/'fonts.json',history_dir=tmp_path)
    try:
        yield value
    finally:
        value.close()


def replace_first(session,number,old,new):
    match=next(m for m in find_matches(session.history.current,old) if m['page']==number)
    return session.preview(EditRequest(number,match['ids'],text=new,auto_width=True,revision=match['revision']))


def changes(session,number,original=False):
    return session.page(number,zoom=.2,thumbnail=True,original=original)['changes']


def test_reordered_duplicate_inherits_previous_edits_but_not_later_sibling_edits_and_undo(session):
    replace_first(session,0,'SOL','LUNA');session.commit()
    inherited=changes(session,0)
    assert inherited and changes(session,1)==[]
    edited_before_clone=session.history.current
    session.organize_pages([page(1),page(0),page(0,90)])
    clone_keys=session._instance_keys()
    assert len(set(clone_keys))==3 and session._page_keys()==[1,0,0]
    assert changes(session,0)==[]
    assert changes(session,1)==changes(session,2)==inherited
    assert changes(session,2,original=True)==inherited
    session.commit()
    cloned=session.history.current

    result=replace_first(session,1,'LUNA','NUBE')
    assert result['report']['_instance_key']==clone_keys[1]
    assert result['report']['_page_key']==0
    assert len(changes(session,1))>len(inherited)
    assert changes(session,2)==inherited and changes(session,0)==[]
    assert changes(session,1,original=True)==changes(session,1)
    session.commit()
    final=session.history.current
    with fitz.open(stream=final,filetype='pdf') as doc:
        assert 'NUBE' in doc[1].get_text() and 'LUNA' not in doc[1].get_text()
        assert 'LUNA' in doc[2].get_text() and 'NUBE' not in doc[2].get_text()

    session.navigate_history()
    assert session.history.current==cloned and session._instance_keys()==clone_keys
    assert changes(session,1)==changes(session,2)==inherited
    session.navigate_history()
    assert session.history.current==edited_before_clone and session._page_keys()==[0,1]
    assert changes(session,0)==inherited and changes(session,1)==[]
    session.navigate_history(True);session.navigate_history(True)
    assert session.history.current==final and session._instance_keys()==clone_keys
    assert len(changes(session,1))>len(changes(session,2))


def test_insert_image_move_and_review_batch_mark_the_exact_duplicate_instance(session):
    session.organize_pages([page(0),page(0),page(1)]);session.commit()
    identities=session._instance_keys()
    assert changes(session,0)==changes(session,1)==[]

    result=session.insert_text(AddTextRequest(1,200,270,150,30,'Texto nuevo',size=10))
    assert result['report']['_instance_key']==identities[1]
    session.commit()
    assert changes(session,1) and changes(session,0)==changes(session,2)==[]

    image=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,4,4),False)
    image.clear_with(127)
    result=session.image_operation('add',1,rect=(220,310,260,350),image_bytes=image.tobytes('png'))
    assert result['report']['_instance_key']==identities[1]
    session.commit()
    assert changes(session,0)==changes(session,2)==[]

    match=next(m for m in find_matches(session.history.current,'SOL') if m['page']==1)
    result=session.preview(EditRequest(1,match['ids'],dy=20,revision=match['revision']))
    assert result['report']['_instance_key']==identities[1]
    session.commit()
    before=changes(session,1)

    matches=session.find_replacements(query='SOL')['matches']
    selected=[next(m['id'] for m in matches if m['page']==number) for number in (0,2)]
    result=session.preview_replacements(selected,'LUNA')
    assert {edit['_instance_key'] for edit in result['report']['edits']}=={identities[0],identities[2]}
    assert changes(session,1)==before
    assert changes(session,0) and changes(session,2)
    session.cancel()
    assert changes(session,1)==before and changes(session,0)==changes(session,2)==[]


def test_delete_merge_and_blank_insertion_preserve_instance_mapping(session,tmp_path):
    session.organize_pages([page(1),page(0),page(0)]);session.commit()
    before=session._instance_keys()
    session.delete_pages('1')
    assert session._instance_keys()==before[1:] and session._page_keys()==[0,0]
    annex=tmp_path/'annex.pdf';annex.write_bytes(fixture())
    session.merge([str(annex)])
    merged=session._instance_keys()
    assert len(merged)==len(set(merged))==4 and merged[:2]==before[1:]
    assert session.state()['original_pages']==[0,0,None,None]
    session.organize_pages([page(3),dict(source='blank',width=100,height=200,rotation=90),page(1),page(0),page(2)])
    final=session._instance_keys()
    assert final[0]==merged[3] and final[2:]==[merged[1],merged[0],merged[2]]
    assert final[1] not in merged
    assert all(changes(session,index)==[] for index in range(5))
    session.cancel()
    assert session._instance_keys()==merged


def test_clone_changes_survive_history_trimming_and_nested_duplication(session):
    session.history.max_states=2
    replace_first(session,0,'SOL','LUNA');session.commit()
    inherited=changes(session,0)
    session.organize_pages([page(0),page(0),page(1)]);session.commit()
    replace_first(session,0,'LUNA','NUBE');session.commit()
    assert session.history.dropped>0
    assert changes(session,1)==inherited
    session.organize_pages([page(1),page(1),page(0),page(2)]);session.commit()
    assert changes(session,0)==changes(session,1)==inherited
    assert len(changes(session,2))>len(inherited)
    replace_first(session,0,'LUNA','ROCA');session.commit()
    assert len(changes(session,0))>len(inherited) and changes(session,1)==inherited


def test_cancelled_clone_and_new_undo_branch_do_not_reuse_instance_identity(session):
    initial=session._instance_keys()
    session.organize_pages([page(0),page(0),page(1)])
    cancelled=session._instance_keys()[1]
    session.cancel()
    assert session._instance_keys()==initial
    session.organize_pages([page(0),page(0),page(1)]);session.commit()
    committed=session._instance_keys()[1]
    assert committed!=cancelled
    session.navigate_history()
    session.organize_pages([page(0),page(0),page(1)]);session.commit()
    assert session._instance_keys()[1] not in (cancelled,committed)
    assert not session.state()['redo']
