from pathlib import Path
from hashlib import sha256
import pymupdf as fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from pdfmodder.app import MainWindow

ROOT=Path(__file__).resolve().parents[1]


def idle(qtbot,window):
    qtbot.waitUntil(lambda:not window.busy and window._rich_pending is None and not window._rich_timer.isActive(),timeout=60000)


def select(window,text):
    chars=window.model.glyphs;joined=''.join(g.text for g in chars);at=joined.index(text)
    window.canvas.set_selection([g.id for g in chars[at:at+len(text)]])


@pytest.fixture
def window(qtbot,tmp_path):
    (tmp_path/'history').mkdir()
    widget=MainWindow(config_path=tmp_path/'fonts.json',history_dir=tmp_path/'history')
    widget.thumbnail_timer.stop();qtbot.addWidget(widget,before_close_func=lambda w:setattr(w,'_allow_close',True));widget.show()
    widget.open_document(ROOT/'examples/digital.pdf');idle(qtbot,widget)
    assert not widget.last_error,widget.last_error
    assert widget.model is not None
    yield widget
    widget._allow_close=True;widget.close()


def test_rich_live_range_accept_roundtrip_undo(qtbot,window,tmp_path):
    original=sha256((ROOT/'examples/digital.pdf').read_bytes()).hexdigest()
    select(window,'10/09/2026');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=60000)
    editor=window.canvas.editor
    assert not editor.textCursor().hasSelection()
    cursor=editor.textCursor();cursor.setPosition(0);cursor.setPosition(2,QTextCursor.KeepAnchor);editor.setTextCursor(cursor)
    cursor.insertText('11')
    cursor.setPosition(0);cursor.setPosition(2,QTextCursor.KeepAnchor);editor.setTextCursor(cursor)
    editor.merge_style(color=(.8,0,0),underline=True,char_spacing=.15)
    idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index']==0 and not window.state['preview']
    editor.accept_draft();idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index']==1
    assert not editor.isVisible()
    assert '11/09/2026' in ''.join(g.text for g in window.model.glyphs)
    selected=[g for g in window.model.glyphs if g.text in '11' and g.color[0]>.7 and g.color[1]<.1]
    assert len(selected)>=2
    saved=tmp_path/'rich.pdf';window.save_as(saved);idle(qtbot,window)
    with fitz.open(saved) as doc:assert '11/09/2026' in doc[0].get_text()
    window.history('undo');idle(qtbot,window)
    assert '10/09/2026' in ''.join(g.text for g in window.model.glyphs)
    window.history('redo');idle(qtbot,window)
    assert '11/09/2026' in ''.join(g.text for g in window.model.glyphs)
    assert sha256((ROOT/'examples/digital.pdf').read_bytes()).hexdigest()==original


def test_failed_rich_accept_retains_draft_and_cancel(qtbot,window):
    select(window,'10/09/2026');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=60000)
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.select(QTextCursor.Document);editor.setTextCursor(cursor)
    editor.merge_style(font_name='FUENTE_QUE_NO_EXISTE',font_file=None,font_xref=None,font_resource=None)
    editor.accept_draft();idle(qtbot,window)
    assert window.last_error and editor.isVisible()
    assert editor.toPlainText()=='10/09/2026' and window.state['history_index']==0
    window.cancel();idle(qtbot,window)
    assert not editor.isVisible() and not window.state['dirty']


def test_copy_format_add_text_without_python_font_substitution(qtbot,window):
    select(window,'10/09/2026');window.copy_text_format();idle(qtbot,window)
    assert window._format_copy is not None
    style=window._format_copy['style']
    window.begin_copied_text();window.placed(50,700)
    assert window.canvas.editor.isVisible()
    window.canvas.editor.insertPlainText('Texto nuevo')
    window.canvas.editor.accept_draft();idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index']==1
    text=[g for g in window.model.glyphs if 700<g.origin[1]<735 and 49<g.origin[0]<263]
    assert ''.join(g.text for g in text)=='Texto nuevo'
    assert all(abs(g.size-style['size'])<.01 for g in text)
    assert all(g.font==style['font_name'] and tuple(g.color)==pytest.approx(style['color'],abs=.001) for g in text)


def open_small_document(qtbot,window,tmp_path,lines):
    path=tmp_path/'layout.pdf'
    with fitz.open() as document:
        page=document.new_page(width=400,height=300)
        for point,text in lines:page.insert_text(point,text,fontsize=12)
        document.save(path)
    window.open_document(path);idle(qtbot,window)
    assert not window.last_error
    return path


def test_cancel_discards_preview_already_in_worker(qtbot,window):
    select(window,'10/09/2026');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=60000)
    before=window.canvas._pixmap_item.pixmap().toImage()
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.setPosition(0);cursor.setPosition(2,QTextCursor.KeepAnchor)
    cursor.insertText('12')
    window._rich_timer.stop();window._rich_pump()
    assert window.busy and window._command=='rich_preview'
    window.cancel();idle(qtbot,window)
    assert not editor.isVisible() and not window._rich_active
    assert window.state['history_index']==0 and not window.state['dirty']
    assert '10/09/2026' in ''.join(g.text for g in window.model.glyphs)
    assert window.canvas._pixmap_item.pixmap().toImage()==before


def test_cancel_during_acceptance_validation_never_commits(qtbot,window):
    select(window,'10/09/2026');window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=60000)
    editor=window.canvas.editor
    cursor=editor.textCursor();cursor.setPosition(0);cursor.setPosition(2,QTextCursor.KeepAnchor)
    cursor.insertText('13')
    editor.accept_draft();window._rich_timer.stop();window._rich_pump()
    assert window.busy and window._command=='rich_prepare'
    assert editor.isReadOnly() and not editor.toolbar.size_box.isEnabled()
    window.cancel();idle(qtbot,window)
    assert not window._rich_active and not editor.isVisible()
    assert window.state['history_index']==0 and not window.state['dirty']
    assert '10/09/2026' in ''.join(g.text for g in window.model.glyphs)


def test_join_uses_explicit_row_order_and_keeps_each_fragment_once(qtbot,window,tmp_path):
    source=open_small_document(qtbot,window,tmp_path,[((35,50),'UNO'),((35,75),'DOS'),((35,150),'VECINO')])
    initial=source.read_bytes()
    select(window,'UNO');first=window.canvas.ids[:]
    select(window,'DOS');second=window.canvas.ids[:]
    window.canvas.set_selection(first+second)
    window.start_rich_edit([{'kind':'text','ids':second},{'kind':'text','ids':first}])
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=60000)
    assert window.canvas.editor.toPlainText()=='DOS UNO'
    window.canvas.editor.accept_draft();idle(qtbot,window)
    assert not window.last_error,window.last_error
    assert window.state['history_index']==1
    saved=tmp_path/'joined.pdf';window.save_as(saved);idle(qtbot,window)
    with fitz.open(saved) as doc:
        content=doc[0].get_text()
        assert ' '.join(content.split())=='DOS UNO VECINO'
        assert content.count('DOS')==1 and content.count('UNO')==1
        lines=[line for b in doc[0].get_text('dict')['blocks'] if b['type']==0 for line in b['lines']]
        assert all(''.join(s['text'] for s in line['spans']).strip() for line in lines)
        assert 'VECINO' in content
    assert source.read_bytes()==initial


def test_resizing_text_reflows_saved_pdf_without_scaling_font(qtbot,window,tmp_path):
    open_small_document(qtbot,window,tmp_path,[((35,50),'uno dos tres cuatro'),((35,150),'VECINO')])
    select(window,'uno dos tres cuatro')
    bounds=window.model.selected(window.canvas.ids)[0].bbox
    window.resize_text_area((35,bounds[1],110,110))
    idle(qtbot,window)
    assert window.canvas.editor.isVisible() and not window.last_error,window.last_error
    window.canvas.editor.accept_draft();idle(qtbot,window)
    assert not window.last_error,window.last_error
    saved=tmp_path/'resized.pdf';window.save_as(saved);idle(qtbot,window)
    with fitz.open(saved) as document:
        spans=[s for b in document[0].get_text('dict')['blocks'] if b['type']==0
               for line in b['lines'] for s in line['spans'] if s['origin'][1]<120]
        assert len({round(s['origin'][1],2) for s in spans})>=2
        assert all(s['size']==pytest.approx(12,abs=.01) for s in spans)
        assert all(s['bbox'][2]<=110.1 for s in spans)
        assert 'VECINO' in document[0].get_text()
