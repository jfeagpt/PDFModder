from pathlib import Path
from io import BytesIO
import pytest
import pymupdf as fitz
from PIL import Image
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication,QFileDialog
from test_ui_line_edit import line_window,settled

ROOT=Path(__file__).resolve().parents[1]


def test_visible_text_with_ocr_preview_has_no_stale_hidden_date(qtbot,line_window,tmp_path):
    window,_=line_window
    source=ROOT/'examples/herramientas-v08.pdf'
    original=source.read_bytes();window.open_document(source);settled(qtbot,window)
    visible=[g for g in window.model.glyphs if g.mode==0]
    joined=''.join(g.text for g in visible);start=joined.index('10/09/2026')
    glyph=visible[start]
    window.canvas.mode='line'
    point=window.canvas.viewport_point(((glyph.bbox[0]+glyph.bbox[2])/2,(glyph.bbox[1]+glyph.bbox[3])/2))
    qtbot.mouseClick(window.canvas.viewport(),Qt.LeftButton,pos=point)
    assert window.model.text(window.canvas.ids)=='Fecha: 10/09/2026'
    assert all(g.mode==0 for g in window.model.selected(window.canvas.ids))
    window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=30000)
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,'Fecha: 11/09/2026')
    qtbot.mouseClick(window.preview_step_button,Qt.LeftButton);settled(qtbot,window)
    assert window.last_report['ocr_cleanup']['verified']
    assert 'duplicado OCR' in window.message.text()
    assert '10/09/2026' not in ''.join(g.text for g in window.model.glyphs)
    qtbot.mouseClick(window.apply_step_button,Qt.LeftButton);settled(qtbot,window)
    target=tmp_path/'visible-ocr.pdf';window.save_as(target);settled(qtbot,window)
    with fitz.open(target) as doc:
        assert doc[0].search_for('11/09/2026') and not doc[0].search_for('10/09/2026')
    assert source.read_bytes()==original


def test_hidden_ocr_element_requires_explicit_mode_and_preserves_scan_pixels(qtbot,line_window,tmp_path):
    window,_=line_window;source=ROOT/'examples/ocr-capa-buscable.pdf'
    window.open_document(source);settled(qtbot,window)
    window.anchor_box.setCurrentIndex(window.anchor_box.findData('right'))
    row=next(i for i in range(window.element_list.count()) if '10/09/2026' in window.element_list.item(i).text())
    window.element_list.setCurrentRow(row)
    assert all(g.mode==3 for g in window.model.selected(window.canvas.ids))
    with pytest.raises(ValueError,match='Activa'):
        window._request(text='Fecha: 11/09/2026',formatting=True,adjust_line=True)
    window.ocr_mode_box.setChecked(True)
    window.start_edit()
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=30000)
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,'Fecha: 11/09/2026')
    qtbot.mouseClick(window.preview_step_button,Qt.LeftButton);settled(qtbot,window)
    assert window.last_report['appearance_unchanged']
    assert window.last_report['ocr_mode']=='searchable'
    assert 'imagen' in window.message.text().lower()
    qtbot.mouseClick(window.apply_step_button,Qt.LeftButton);settled(qtbot,window)
    target=tmp_path/'ocr-buscable.pdf';window.save_as(target);settled(qtbot,window)
    with fitz.open(source) as old,fitz.open(target) as new:
        assert old[0].get_pixmap().samples==new[0].get_pixmap().samples
        assert new[0].search_for('11/09/2026') and not new[0].search_for('10/09/2026')


def test_image_context_exports_then_dialog_crops_rotates_replaces_one_instance(qtbot,line_window,tmp_path,monkeypatch):
    window,_=line_window;source=ROOT/'examples/herramientas-v08.pdf'
    window.open_document(source);settled(qtbot,window)
    item=window.canvas.images[0];other=window.canvas.images[1]
    rect=item['rect'];point=window.canvas.viewport_point(((rect[0]+rect[2])/2,(rect[1]+rect[3])/2))
    window.canvas.ensureVisible(window.canvas.scene_rect(rect),30,30)
    point=window.canvas.viewport_point(((rect[0]+rect[2])/2,(rect[1]+rect[3])/2))
    export=tmp_path/'export.png'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_args,**_kwargs:(str(export),'PNG'))
    errors=[]
    def choose_export():
        menu=QApplication.activePopupWidget()
        try:qtbot.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(menu.actions()[0]).center())
        except Exception as exc:errors.append(exc);menu.close()
    QTimer.singleShot(0,choose_export)
    event=QContextMenuEvent(QContextMenuEvent.Mouse,point,window.canvas.viewport().mapToGlobal(point))
    QApplication.sendEvent(window.canvas.viewport(),event)
    settled(qtbot,window)
    assert not errors and export.is_file()
    assert Image.open(export).size==(180,120)
    old_second=other['rect']
    def edit_dialog():
        dialog=QApplication.activeModalWidget()
        if dialog is None:QTimer.singleShot(30,edit_dialog);return
        try:
            replacement=BytesIO();Image.new('RGB',(80,40),'blue').save(replacement,'PNG')
            dialog.set_replacement(replacement.getvalue())
            dialog.crop_spins[2].setValue(50)
            dialog.rotation_box.setCurrentIndex(1)
            qtbot.mouseClick(dialog.preview_button,Qt.LeftButton)
        except Exception as exc:errors.append(exc);dialog.reject()
    QTimer.singleShot(30,edit_dialog);window.edit_selected_image()
    qtbot.waitUntil(lambda:window.state.get('preview') or bool(errors),timeout=30000);settled(qtbot,window)
    assert not errors,errors
    assert window.last_report['verified']
    qtbot.mouseClick(window.apply_step_button,Qt.LeftButton);settled(qtbot,window)
    assert window.canvas.images[0]['rect']==pytest.approx(rect,abs=.001)
    assert window.canvas.images[1]['rect']==pytest.approx(old_second,abs=.001)
    target=tmp_path/'image-edited.pdf';window.save_as(target);settled(qtbot,window)
    from pdfmodder.media import export_image_pdf
    result=export_image_pdf(target.read_bytes(),0,'0')
    assert (result['width_px'],result['height_px'])==(80,40)
    with Image.open(BytesIO(result['image_bytes'])) as selected:
        assert selected.convert('RGB').tobytes()==Image.new('RGB',(80,40),'blue').tobytes()
    assert export_image_pdf(target.read_bytes(),0,'1')['image_bytes']==export.read_bytes()
