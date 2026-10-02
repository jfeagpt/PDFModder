"""Fast selectable reading, preparation and preserved document restrictions."""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject
import pytest

from pdfmodder.model import EditError
from pdfmodder.worker import Session


@pytest.fixture
def source(tmp_path):
    path=tmp_path/'synthetic-reading.pdf'
    with fitz.open() as document:
        document.new_page().insert_text((50,70),'Selectable reading text')
        path.write_bytes(document.tobytes())
    return path


def test_reading_defers_analyses_and_prepare_materialises_full_page_without_new_history(source,tmp_path,monkeypatch):
    import pdfmodder.worker as worker
    import pdfmodder.engine as engine
    import pdfmodder.media as media
    import pdfmodder.tagged_pages as tagged_pages
    calls=[]
    class Resolver:
        def __init__(self,config_path=None):calls.append(('resolver',config_path))
        def inspect(self,document,page):calls.append(('fonts',page));return [{'name':'Synthetic font'}]
    monkeypatch.setattr(worker,'FontResolver',Resolver)
    monkeypatch.setattr(worker,'document_issues',lambda data,doc:calls.append(('document',len(data))) or [])
    monkeypatch.setattr(engine,'page_issues',lambda data,page:calls.append(('page_checks',page)) or [])
    monkeypatch.setattr('pdfmodder.clipping.annotate_font_resources',lambda data,page,model:calls.append(('resources',page)) or model)
    monkeypatch.setattr(media,'image_items',lambda doc,page:calls.append(('images',page)) or [{'id':'synthetic'}])
    monkeypatch.setattr(tagged_pages,'page_capabilities',lambda data:calls.append(('caps',len(data))) or {'supported':True,'delete':True,'reason':''})
    session=Session(source,reading=True,config_path=tmp_path/'fonts.json',history_dir=tmp_path)
    try:
        session.tagged=True  # Exercise the deferred tagged capability branch.
        history=session.history
        initial=history.current
        reading=session.page(0,reading=True)
        assert calls==[] and session.resolver is None
        assert reading['png'].startswith(b'\x89PNG') and reading['model'].glyphs
        assert reading['model'].revision==sha256(initial).hexdigest()
        assert reading['fonts']==reading['images']==[]
        assert reading['state']['validation_pending'] and not reading['state']['page_capabilities']['supported']
        prepared=session.prepare_editing(number=0)
        assert session.history is history and history.current==initial and history.index==0
        assert prepared['state']['editing_prepared'] and not prepared['state']['validation_pending']
        assert prepared['fonts']==[{'name':'Synthetic font'}] and prepared['images']==[{'id':'synthetic'}]
        assert {call[0] for call in calls}=={'document','resolver','page_checks','resources','fonts','images','caps'}
        assert prepared['model'] is not reading['model']
        count=len(calls)
        assert session.prepare_editing()['model'] is prepared['model']
        assert len(calls)==count
        current_reading=session.page(0,reading=True)
        assert current_reading['reading'] and current_reading['fonts']==current_reading['images']==[]
        assert current_reading['model'] is not prepared['model']
        assert len(calls)==count
        assert session.page(0)['fonts']==prepared['fonts']
    finally:
        session.close()


def test_dispatch_reading_and_prepare_protect_mutations_and_plain_copy(source,tmp_path,monkeypatch):
    import pdfmodder.worker as worker
    monkeypatch.setattr(worker,'_session',None)
    try:
        opened=worker.dispatch('open',{'path':str(source),'reading':True,'history_dir':str(tmp_path),
                                      'config_path':str(tmp_path/'fonts.json')})
        assert opened['state']['reading'] and worker.dispatch('font_catalog')['catalog']==[]
        page=worker.dispatch('page',{'number':0,'reading':True})
        ids=[g.id for g in page['model'].glyphs]
        copied=worker.dispatch('clipboard_copy',{'page':0,'ids':ids,'revision':page['model'].revision})
        assert copied['text']=='Selectable reading text' and copied['bundle']['kind']=='plain_text'
        assert worker._session.resolver is None
        for command,payload in (
                ('preview',{'request':{'page':0,'ids':ids,'text':'Must not edit'}}),
                ('edit_document_metadata',{'metadata':{'title':'Must not edit'}}),
                ('export_secure_pdf',{'path':str(tmp_path/'blocked.pdf'),'password':'test'}),
                ('save',{'path':str(tmp_path/'blocked.pdf')})):
            with pytest.raises(EditError,match='Activa las herramientas'):
                worker.dispatch(command,payload)
        assert not (tmp_path/'blocked.pdf').exists()
        prepared=worker.dispatch('prepare_editing',{'number':0})
        assert prepared['state']['editing_prepared'] and prepared['model'].revision==sha256(source.read_bytes()).hexdigest()
        assert not prepared['reading'] and prepared['fonts']
        worker.dispatch('open',{'path':str(source),'reading':True,'history_dir':str(tmp_path),
                                'config_path':str(tmp_path/'fonts.json')})
        reopened=worker.dispatch('page',{'number':0,'reading':True})
        assert reopened['reading'] and reopened['fonts']==[] and worker._session.resolver is None
        assert reopened['state']['history_index']==0 and not reopened['state']['dirty']
    finally:
        if worker._session is not None:worker.dispatch('close')


@pytest.mark.parametrize('kind',['encrypted','certified'])
def test_reading_does_not_bypass_password_signatures_or_edit_checks(source,tmp_path,kind):
    data=source.read_bytes()
    password=''
    if kind=='encrypted':
        with fitz.open(stream=data) as document:
            data=document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,user_pw='reader',owner_pw='owner',
                                 permissions=fitz.PDF_PERM_PRINT)
        password='reader'
    else:
        writer=PdfWriter(clone_from=PdfReader(BytesIO(data)))
        writer.root_object[NameObject('/Perms')]=DictionaryObject({NameObject('/Synthetic'):NumberObject(1)})
        stream=BytesIO();writer.write(stream);data=stream.getvalue()
    source.write_bytes(data)
    if password:
        with pytest.raises(EditError,match='PASSWORD_REQUIRED'):
            Session(source,reading=True,password='wrong',history_dir=tmp_path)
    session=Session(source,reading=True,password=password,history_dir=tmp_path,config_path=tmp_path/'fonts.json')
    try:
        assert session.page(0,reading=True)['model'].glyphs
        with pytest.raises(EditError,match='Activa las herramientas'):session.preview({'page':0,'ids':[0],'text':'X'})
        with pytest.raises(EditError,match='Activa las herramientas'):session.save(tmp_path/'blocked.pdf')
        if password:
            with pytest.raises(EditError,match='permisos'):session.copy_reading_selection(0,ids=[0])
        prepared=session.prepare_editing(0)
        assert prepared['state']['issues'] and not prepared['state']['page_capabilities']['supported']
        with pytest.raises(EditError):session.preview({'page':0,'ids':[0],'text':'X'})
        with pytest.raises(EditError):session.save(tmp_path/'blocked.pdf')
        assert source.read_bytes()==data and session.history.current==data
        assert not (tmp_path/'blocked.pdf').exists()
    finally:
        session.close()
