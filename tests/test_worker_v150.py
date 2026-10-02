"""Transaction/history and safe publication for the v1.5.0 worker commands."""
from pathlib import Path

import pytest

from pdfmodder.model import EditError
from pdfmodder.worker import Session
from test_pageops import fixture_pdf, texts


@pytest.fixture
def session(tmp_path):
    source=tmp_path/'original.pdf'
    source.write_bytes(fixture_pdf(links=False))
    current=Session(source,config_path=tmp_path/'fonts.json',history_dir=tmp_path)
    try:
        yield current
    finally:
        current.close()


def test_crop_preview_cancel_commit_undo_redo_preserves_original_maps(session):
    before=session.original
    keys=session._instance_keys()
    preview=session.preview_crop_pages_v150('1,3',(5,6,7,8))
    cropped=session.pending
    assert preview['state']['original_pages']==[0,1,2]
    assert preview['state']['comparison_geometry_changed']==[True,False,True]
    assert session.history.current==before
    assert session._instance_keys()==keys
    session.cancel()
    assert session.state()['comparison_geometry_changed']==[False]*3
    assert session.history.current==before
    session.preview_crop_pages_v150('1,3',(5,6,7,8))
    session.commit()
    assert session.history.current==cropped
    session.navigate_history()
    assert session.history.current==before
    assert session.state()['comparison_geometry_changed']==[False]*3
    session.navigate_history(redo=True)
    assert session.history.current==cropped
    assert session._instance_keys()==keys
    assert Path(session.path).read_bytes()==before


def test_crop_highlights_have_correct_current_and_original_coordinate_frames(session):
    instance=session._instance_keys()[0]
    first=(50.,80.,100.,95.)
    session.history.push(session.history.current,{'_instance_key':instance,'source_regions':[first]})
    session.preview_crop_pages_v150('1',(5,6,7,8))
    session.commit()
    assert session._instance_changes()[instance]==[(45.,74.,95.,89.)]
    assert session._instance_changes(original=True)[instance]==[first]
    later=(60.,90.,80.,105.)
    session.history.push(session.history.current,{'_instance_key':instance,'destination_regions':[later]})
    assert session._instance_changes()[instance][-1]==later
    assert session._instance_changes(original=True)[instance][-1]==(65.,96.,85.,111.)
    original=session.page(0,thumbnail=True,original=True)
    current=session.page(0,thumbnail=True)
    assert current['comparison_geometry_changed'] and original['comparison_warning']
    assert original['changes'][0]==first and current['changes'][0]==(45.,74.,95.,89.)


def test_replacement_preview_history_provenance_and_source_protection(session,tmp_path):
    other=tmp_path/'replacement.pdf'
    other.write_bytes(fixture_pdf('NEW',count=1,links=False))
    original=session.original
    keys=session._instance_keys()
    result=session.preview_replace_pages_v150('2',str(other),'1')
    assert result['state']['preview']
    assert result['state']['original_pages']==[0,None,2]
    assert session._instance_keys()[0]==keys[0] and session._instance_keys()[1]!=keys[1]
    session.commit()
    replaced=session.history.current
    assert 'NEW' in texts(replaced)[1]
    with pytest.raises(EditError,match='original'):
        session.save(str(other))
    session.navigate_history()
    assert session.history.current==original and session._instance_keys()==keys
    session.navigate_history(True)
    assert session.history.current==replaced
    assert session.state()['original_pages']==[0,None,2]
    with pytest.raises(EditError,match='no existe en el original'):
        session.page(1,original=True)


def test_split_publishes_valid_outputs_without_changing_history(session,tmp_path):
    before=session.history.current
    state=session.state()
    result=session.split_document_v150(str(tmp_path/'parts'),pages_per_part=2)
    paths=[Path(f['path']) for f in result['files']]
    assert [p.name for p in paths]==['parte-001.pdf','parte-002.pdf']
    assert [t for p in paths for t in texts(p.read_bytes())]==texts(before)
    assert session.history.current==before and session.state()==state
    assert Path(session.path).read_bytes()==before


def test_split_does_not_overwrite_existing_outputs_or_publish_partial_collision(session,tmp_path):
    folder=tmp_path/'parts';folder.mkdir()
    target=folder/'parte-002.pdf';target.write_bytes(b'existing file')
    with pytest.raises(EditError,match='ya existe'):
        session.split_document_v150(str(folder),pages_per_part=2)
    assert target.read_bytes()==b'existing file'
    assert not (folder/'parte-001.pdf').exists()
    assert session.history.current==session.original


def test_split_destination_cannot_overwrite_original_even_if_target_name_matches(tmp_path):
    source=tmp_path/'parte-001.pdf'
    original=fixture_pdf(links=False,count=2);source.write_bytes(original)
    session=Session(source,config_path=tmp_path/'fonts.json',history_dir=tmp_path)
    try:
        with pytest.raises(EditError,match='original'):
            session.split_document_v150(str(tmp_path),pages_per_part=1)
        assert source.read_bytes()==original
        assert not (tmp_path/'parte-002.pdf').exists()
    finally:
        session.close()


def test_export_resolves_page_expression_blocks_original_and_existing_file(session,tmp_path):
    target=tmp_path/'selected.txt'
    result=session.export_document_v150(str(target),'txt',pages='2')
    assert result['report']['pages']==[1]
    text=target.read_text(encoding='utf-8')
    assert 'PAGINA 2' in text and 'PAGINA 1' not in text
    with pytest.raises(EditError,match='ya existe'):
        session.export_document_v150(str(target),'txt')
    assert target.read_text(encoding='utf-8')==text
    with pytest.raises(EditError,match='original'):
        session.export_document_v150(session.path,'txt')
    assert session.history.current==session.original


def test_pending_preview_blocks_export_and_split_until_accept_or_cancel(session,tmp_path):
    session.preview_crop_pages_v150('1',(1,1,1,1))
    preview=session.pending
    with pytest.raises(EditError,match='Aplica o cancela'):
        session.export_document_v150(str(tmp_path/'text.txt'),'txt')
    with pytest.raises(EditError,match='Aplica o cancela'):
        session.split_document_v150(str(tmp_path/'parts'),pages_per_part=1)
    assert session.pending==preview


def test_commands_are_dispatched_through_existing_commit_protocol(session,tmp_path,monkeypatch):
    from pdfmodder import worker
    monkeypatch.setattr(worker,'_session',session)
    result=worker.dispatch('preview_crop_pages_v150',{'expression':'1','margins':(1,2,3,4)})
    assert result['state']['preview']
    worker.dispatch('commit')
    result=worker.dispatch('split_document_v150',{'destination':str(tmp_path/'parts'),'expression':'1;2-3'})
    assert len(result['files'])==2
    result=worker.dispatch('export_document_v150',{'destination':str(tmp_path/'text.txt'),'format':'txt'})
    assert len(result['files'])==1
    other=tmp_path/'other.pdf';other.write_bytes(fixture_pdf('NEW',count=1,links=False))
    result=worker.dispatch('preview_replace_pages_v150',{'expression':'2','path':str(other),'source_expression':'1'})
    assert result['state']['preview'] and result['state']['original_pages']==[0,None,2]
