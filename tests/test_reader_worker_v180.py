from hashlib import sha256
from pathlib import Path

import pymupdf as fitz
import pytest

from pdfmodder.model import EditError
from pdfmodder.worker import Session, dispatch


@pytest.fixture
def reading_pdf(tmp_path):
    path=tmp_path/'paragraphs.pdf'
    with fitz.open() as document:
        for index in range(3):
            page=document.new_page(width=500+index*20,height=720)
            page.insert_text((50,75),f'First paragraph page {index+1}')
            page.insert_text((50,165),f'Second paragraph page {index+1}')
        document[2].set_rotation(90)
        path.write_bytes(document.tobytes())
    return path


def test_copy_crosses_paragraphs_and_pages_without_rendering_or_editing(reading_pdf,tmp_path,monkeypatch):
    from pdfmodder.reading_order_v180 import ordered_glyphs
    session=Session(reading_pdf,reading=True,history_dir=tmp_path)
    try:
        first=session.page(0,reading=True)['model']
        last=session.page(2,reading=True)['model']
        first_glyphs=ordered_glyphs(first);last_glyphs=ordered_glyphs(last)
        revision=sha256(reading_pdf.read_bytes()).hexdigest()
        monkeypatch.setattr(session,'page',lambda *a,**kw:pytest.fail('Copy must not render pages'))
        copied=session.reading_copy_range({'page':0,'id':first_glyphs[0].id},
                                          {'page':2,'id':last_glyphs[-1].id},revision)
        assert all(f'{paragraph} paragraph page {page}' in copied['text']
                   for paragraph in ('First','Second') for page in (1,2,3))
        assert '\n\n' in copied['text']
        assert session.resolver is None and session.history.index==0
        with pytest.raises(EditError,match='cambió'):
            session.reading_copy_range({'page':0,'id':first_glyphs[0].id},
                                       {'page':2,'id':last_glyphs[-1].id},'stale')
        info=session.reading_info()
        assert info['page_geometries'][0]=={'width':500.,'height':720.}
        assert info['page_geometries'][2]=={'width':720.,'height':540.}
        assert not session.state()['dirty']
    finally:session.close()


def test_remove_tags_preview_cancel_history_save_and_reopen(tmp_path,monkeypatch):
    import pdfmodder.worker as worker
    path=Path(__file__).resolve().parents[1]/'examples/etiquetado.pdf'
    original=path.read_bytes()
    monkeypatch.setattr(worker,'_session',None)
    try:
        dispatch('open',{'path':str(path),'config_path':str(tmp_path/'fonts.json'),'history_dir':str(tmp_path)})
        assert worker._session.state()['tagged']
        preview=dispatch('remove_tags')
        assert preview['report']['verified'] and preview['state']['preview'] and not preview['state']['tagged']
        assert dispatch('cancel')['state']['tagged']
        dispatch('remove_tags');committed=dispatch('commit')
        assert committed['state']['dirty'] and not committed['state']['tagged']
        assert dispatch('undo')['state']['tagged']
        assert not dispatch('redo')['state']['tagged']
        destination=tmp_path/'without-tags.pdf'
        dispatch('save',{'path':str(destination)})
        reopened=dispatch('open',{'path':str(destination),'reading':True,'history_dir':str(tmp_path)})
        assert not reopened['state']['tagged'] and path.read_bytes()==original
    finally:
        if worker._session is not None:dispatch('close')
