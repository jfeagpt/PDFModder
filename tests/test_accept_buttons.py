"""Aceptar una escritura mediante controles visibles, sin conocer un atajo."""
from dataclasses import replace
from pathlib import Path
import pymupdf as fitz
from PySide6.QtCore import Qt
from pdfmodder.model import Glyph,PageModel
from test_ui_line_edit import line_window,settled,double_click_sequence,center,glyph_for
from test_ui import ready_editor


def test_visible_inline_accept_commits_once_and_cancel_preserves_document(qtbot,line_window,tmp_path):
    window,_=line_window
    source=tmp_path/'aceptar.pdf'
    with fitz.open() as pdf:
        pdf.new_page().insert_text((48,750),'Fecha 10/09/2026',fontsize=12)
        pdf.save(source)
    window.open_document(source)
    settled(qtbot,window)
    window.canvas.set_selection(window.model.group(glyph_for(window,'10/09/2026'),'word'))
    window.canvas.ensureVisible(window.canvas.scene_rect(window.model.selected(window.canvas.ids)[0].bbox),20,20)
    window.start_edit()
    ready_editor(qtbot,window)
    assert window.edit_steps.isVisible()
    assert window.canvas.editor.toolbar.accept.isVisible()
    assert window.canvas.editor.toolbar.cancel.isVisible()
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,'11/09/2026')
    qtbot.mouseClick(window.canvas.editor.toolbar.accept,Qt.LeftButton)
    settled(qtbot,window)
    assert not window.state['preview'] and window.state['history_index']==1
    region=window.last_report['destination_regions'][0]
    assert window.canvas.viewport().rect().contains(window.canvas.viewport_point(((region[0]+region[2])/2,(region[1]+region[3])/2)))
    assert not window.edit_steps.isVisible()
    window.canvas.set_selection(window.model.group(glyph_for(window,'11/09/2026'),'word'))
    window.start_edit()
    ready_editor(qtbot,window)
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,'12/09/2026')
    qtbot.mouseClick(window.canvas.editor.toolbar.cancel,Qt.LeftButton)
    assert not window.canvas.editor.isVisible()
    assert window.state['history_index']==1
    assert '11/09/2026' in ''.join(g.text for g in window.model.glyphs)


def test_click_selects_visible_font_instead_of_ocr_layer():
    g=Glyph(0,'4',(20.,20.),(19.,10.,26.,22.),(19.,10.,26.,22.),'Arial-BoldMT',10.,(0.,0.,0.),1.,0,0,0)
    hidden=replace(g,id=1,font='GlyphLessFont',mode=3,bbox=(20.,10.,24.,22.))
    matrix=(1.,0.,0.,1.,0.,0.)
    model=PageModel(0,100,100,0,matrix,matrix,(0,0,100,100),[hidden,g])
    assert model.hit((22.,16.)).id==g.id
    assert model.selected([hidden.id])==[hidden], 'La capa invisible sigue presente para validar integridad'


def test_inspector_selects_direct_resource_not_another_font_with_zero_xref(qtbot,line_window,tmp_path):
    from io import BytesIO
    from pypdf import PdfReader,PdfWriter
    from pypdf.generic import DictionaryObject
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QComboBox,QPlainTextEdit
    window,_=line_window
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_text((50,100),'NORMAL',fontname='helv')
        page.insert_text((50,140),'NEGRITA',fontname='hebo')
        writer=PdfWriter(clone_from=PdfReader(BytesIO(pdf.tobytes())))
    fonts=writer.pages[0]['/Resources']['/Font']
    for key in list(fonts):
        fonts[key]=DictionaryObject(dict(fonts[key]))
    source=tmp_path/'fuentes-directas.pdf'
    writer.write(source)
    window.open_document(source)
    settled(qtbot,window)
    chosen=[g for g in window.model.glyphs if g.origin[1]==140]
    assert all(g.font_xref is None and g.font_resource=='/hebo' for g in chosen)
    window.canvas.set_selection([g.id for g in chosen])
    captured={}
    timer=QTimer(window)
    def capture_dialog():
        dialog=QApplication.activeModalWidget()
        if dialog is None or dialog.objectName()!='fontInspectorDialog':return
        captured['choice']=dialog.findChild(QComboBox,'fontInspectorChoice').currentText()
        captured['details']=dialog.findChild(QPlainTextEdit,'fontInspectorDetails').toPlainText()
        timer.stop()
        dialog.accept()
    timer.timeout.connect(capture_dialog)
    timer.start(20)
    window.font_inspector()
    settled(qtbot,window)
    assert '/hebo' in captured['choice'] and 'Helvetica-Bold' in captured['choice']
    assert 'Recurso de la selección: /hebo' in captured['details']
    assert 'Recurso de la selección: /helv ' not in captured['details']
