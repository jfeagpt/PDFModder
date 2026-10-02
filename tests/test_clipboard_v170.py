"""Portapapeles real: aislamiento de instancias, historial y foco de entrada."""
from hashlib import sha256
from pathlib import Path
from io import BytesIO

import pymupdf as fitz
import pytest
from PIL import Image
from PySide6.QtCore import Qt, QMimeData
from PySide6.QtWidgets import QApplication

from pdfmodder.clipboard_ops_v170 import copy_selection_v170, apply_clipboard_v170
from pdfmodder.clipboard_ui_v170 import bundle_mime_v170, mime_bundle_v170
from pdfmodder.worker import Session
from pdfmodder.model import EditError
from pdfmodder.media import image_items
from test_tools_ui_v150 import tools_window


def ids_for(model,text,last=False):
    joined=''.join(g.text for g in model.glyphs)
    offset=joined.rindex(text) if last else joined.index(text)
    return [g.id for g in model.glyphs[offset:offset+len(text)]]


def test_copy_paste_delete_and_exact_history(tmp_path):
    source=Path(__file__).resolve().parents[1]/'examples/digital.pdf'
    source_hash=sha256(source.read_bytes()).hexdigest()
    (tmp_path/'history').mkdir()
    session=Session(source,config_path=tmp_path/'fonts.json',history_dir=tmp_path/'history')
    try:
        model=session.page(0)['model']
        original=session.history.current
        copied=copy_selection_v170(session,0,ids=ids_for(model,'10/09/2026'),revision=model.revision)
        assert session.history.current==original
        with pytest.raises(EditError,match='enlace'):
            apply_clipboard_v170(session,'paste',0,revision=model.revision,bundle=copied['bundle'],point=(72,650))
        assert session.history.current==original
        apply_clipboard_v170(session,'paste',0,revision=model.revision,bundle=copied['bundle'],point=(220,690))
        model=session.page(0)['model']
        assert ''.join(g.text for g in model.glyphs).count('10/09/2026')==2
        pasted=session.history.current
        apply_clipboard_v170(session,'delete',0,revision=model.revision,ids=ids_for(model,'10/09/2026',True))
        assert ''.join(g.text for g in session.page(0)['model'].glyphs).count('10/09/2026')==1
        session.navigate_history()
        assert session.history.current==pasted
        session.navigate_history()
        assert session.history.current==original
        session.navigate_history(True)
        assert session.history.current==pasted and sha256(source.read_bytes()).hexdigest()==source_hash
    finally:
        session.close()


def test_image_copy_delete_one_of_shared_instances_and_paste(tmp_path):
    image=BytesIO()
    Image.new('RGB',(24,16),'#2370b5').save(image,'PNG')
    document=fitz.open()
    page=document.new_page()
    xref=page.insert_image(fitz.Rect(30,40,120,100),stream=image.getvalue())
    page.insert_image(fitz.Rect(200,40,290,100),xref=xref)
    source=tmp_path/'shared-images.pdf'
    source.write_bytes(document.tobytes())
    document.close()
    (tmp_path/'history').mkdir()
    session=Session(source,config_path=tmp_path/'fonts.json',history_dir=tmp_path/'history')
    try:
        with fitz.open(stream=session.history.current,filetype='pdf') as doc:items=image_items(doc,0)
        model=session.page(0)['model']
        copied=copy_selection_v170(session,0,image_id=items[0]['id'],revision=model.revision)
        apply_clipboard_v170(session,'delete',0,image_id=items[0]['id'],revision=model.revision)
        with fitz.open(stream=session.history.current,filetype='pdf') as doc:
            remaining=image_items(doc,0)
            assert len(remaining)==1 and remaining[0]['rect']==items[1]['rect']
        model=session.page(0)['model']
        apply_clipboard_v170(session,'paste',0,bundle=copied['bundle'],revision=model.revision,point=(30,200))
        with fitz.open(stream=session.history.current,filetype='pdf') as doc:
            assert len(image_items(doc,0))==2
    finally:
        session.close()


def test_native_input_shortcuts_take_priority_and_object_mime_roundtrip(qtbot,tools_window):
    window=tools_window
    backup=QMimeData()
    clipboard=QApplication.clipboard()
    for name in clipboard.mimeData().formats():backup.setData(name,clipboard.mimeData().data(name))
    try:
        window.search_box.setEnabled(True)
        window.search_box.setText('texto del campo')
        window.search_box.setFocus()
        window.search_box.selectAll()
        qtbot.keyClick(window.search_box,Qt.Key_X,modifier=Qt.ControlModifier)
        assert window.search_box.text()=='' and clipboard.text()=='texto del campo'
        qtbot.keyClick(window.search_box,Qt.Key_V,modifier=Qt.ControlModifier)
        assert window.search_box.text()=='texto del campo'
        assert not window.busy and not window.state
        payload={'bundle':{'version':1,'kind':'image','image_bytes':b'bytes de prueba','rect':(0,0,10,20)}}
        assert mime_bundle_v170(bundle_mime_v170(payload))['image_bytes']==b'bytes de prueba'
    finally:
        clipboard.setMimeData(backup)
