"""Intro, extensión vertical y solapamiento elegido a través de PDF real y Qt."""
from dataclasses import replace
from io import BytesIO
import pymupdf as fitz
import pytest
from pypdf import PdfReader
from PySide6.QtCore import Qt
from pdfmodder.engine import edit_pdf,extract_page
from pdfmodder.model import EditRequest,EditError,union
from test_review_text import fixture,choose
from test_ui_line_edit import line_window,settled


def test_auto_height_retains_width_size_and_neighbors():
    data=fixture();model,selected=choose(data)
    request=EditRequest(0,[g.id for g in selected],text='SOL\nMAR',width=80,height=17,
                        reflow=True,auto_height=True,line_spacing=18)
    output,report=edit_pdf(data,request)
    assert report['auto_height'] and report['area_height']>30
    text=PdfReader(BytesIO(output)).pages[0].extract_text()
    assert 'MAR' in text and 'Vecino inalterado' in text
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert all(abs(g.size-12)<.001 for g in extract_page(doc,0,output).glyphs)
    with pytest.raises(EditError,match='altura'):
        edit_pdf(data,replace(request,auto_height=False))
    with pytest.raises(EditError,match='fuera|solapa|cruza'):
        edit_pdf(data,replace(request,line_spacing=400))


def test_overlap_is_opt_in_and_neighbor_stays_in_place():
    data=fixture();model,selected=choose(data)
    request=EditRequest(0,[g.id for g in selected],dy=80)
    with pytest.raises(EditError,match='solapa'):
        edit_pdf(data,request)
    output,report=edit_pdf(data,replace(request,allow_overlap=True))
    assert report['overlap_count'] and report['warning']
    with fitz.open(stream=output,filetype='pdf') as doc:
        result=extract_page(doc,0,output)
        assert len(result.glyphs)==len(model.glyphs)
        assert sum(g.text=='S' and abs(g.origin[1]-160)<.01 for g in result.glyphs)==2
        assert not any(abs(g.origin[1]-80)<.01 for g in result.glyphs)
    again,second_report=edit_pdf(output,EditRequest(0,[g.id for g in result.glyphs[:3]],dy=15,allow_overlap=True))
    assert second_report['verified']
    with fitz.open(stream=again,filetype='pdf') as doc:
        repeated=extract_page(doc,0,again)
        assert sum(g.text=='S' and abs(g.origin[1]-160)<.01 for g in repeated.glyphs)==1
        assert sum(g.text=='S' and abs(g.origin[1]-175)<.01 for g in repeated.glyphs)==1


def test_enter_opens_new_line_preview_commit_undo_redo_reopen(qtbot,line_window,tmp_path):
    window,_=line_window
    source=tmp_path/'enter-original.pdf';source.write_bytes(fixture())
    original=source.read_bytes()
    window.open_document(source);settled(qtbot,window)
    window.canvas.set_selection([g.id for g in window.model.glyphs[:3]])
    old_height=window.height_box.value()
    window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=30000)
    assert not window.canvas.editor.textCursor().hasSelection()
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,'SOL')
    qtbot.keyClick(window.canvas.editor,Qt.Key_Return)
    qtbot.keyClicks(window.canvas.editor,'SAL')
    assert window.canvas.editor.toPlainText()=='SOL\nSAL'
    qtbot.keyClick(window.canvas.editor,Qt.Key_Return,modifier=Qt.ControlModifier)
    settled(qtbot,window)
    assert window.state['history_index']==1 and window.last_report['auto_height']
    assert window.height_box.value()>old_height
    assert window.state['history_index']==1
    window.history('undo');settled(qtbot,window)
    assert 'SAL' not in ''.join(g.text for g in window.model.glyphs)
    window.history('redo');settled(qtbot,window)
    target=tmp_path/'enter-edited.pdf'
    window.save_as(target);settled(qtbot,window)
    window.open_document(target);settled(qtbot,window)
    assert 'SAL' in ''.join(g.text for g in window.model.glyphs)
    assert source.read_bytes()==original


def test_overlap_checkbox_applies_to_moves(qtbot,line_window,tmp_path):
    window,_=line_window
    source=tmp_path/'overlap.pdf';source.write_bytes(fixture())
    window.open_document(source);settled(qtbot,window)
    window.canvas.set_selection([g.id for g in window.model.glyphs[:3]])
    assert not window._request(dy=80).allow_overlap
    window.allow_overlap_box.setChecked(True)
    window.snap_box.setChecked(False)
    window.move_selection(0,80);settled(qtbot,window)
    assert window.state['history_index']==1 and window.last_report['overlap_count']


def test_clipped_typography_dialog_newline_bold_size_preview(qtbot,line_window,tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from pdfmodder.dialogs import TextDialog
    from test_native_layout import fragmented_fixture
    window,_=line_window
    source=tmp_path/'native-format.pdf';source.write_bytes(fragmented_fixture())
    window.open_document(source);settled(qtbot,window)
    window.canvas.set_selection([g.id for g in window.model.glyphs[:3]])
    errors=[]
    timer=QTimer(window);timer.setInterval(25)
    def fill():
        dialog=QApplication.activeModalWidget()
        if not isinstance(dialog,TextDialog):return
        timer.stop()
        try:
            qtbot.mouseClick(dialog.change_font,Qt.LeftButton)
            dialog.font_picker.family_box.setCurrentIndex(dialog.font_picker.family_box.findData('Courier'))
            dialog.font_picker.bold_box.setChecked(True)
            dialog.size_box.setValue(11.25)
            dialog.width_box.setValue(30)
            dialog.content.setFocus()
            dialog.content.selectAll()
            qtbot.keyClicks(dialog.content,'SOL')
            qtbot.keyClick(dialog.content,Qt.Key_Return)
            qtbot.keyClicks(dialog.content,'MAR')
            qtbot.mouseClick(dialog.preview_button,Qt.LeftButton)
        except Exception as exc:
            errors.append(exc);dialog.reject()
    timer.timeout.connect(fill);timer.start()
    try:
        window.format_selection()
        qtbot.waitUntil(lambda:bool(errors) or not timer.isActive(),timeout=30000)
        settled(qtbot,window)
    finally:timer.stop()
    assert not errors,errors
    assert window.state['preview'] and window.last_report['verified']
    assert window.last_report['manual_format']['font']=='Courier-Bold'
    assert window.last_report['manual_format']['size']==11.25
    assert window.last_report['auto_height']
    window.commit();settled(qtbot,window)
    target=tmp_path/'native-format-output.pdf'
    window.save_as(target);settled(qtbot,window)
    text=PdfReader(target).pages[0].extract_text()
    # pypdf may infer trailing whitespace from the restored native cursor.
    assert text.splitlines()[0].strip()=='SOL' and text.splitlines()[1].startswith('MAR')
    assert 'LUNA' in text and 'FIN' in text
