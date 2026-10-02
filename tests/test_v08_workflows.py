from pathlib import Path
import pymupdf as fitz
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication
from pdfmodder.model import mm
from test_ui_line_edit import line_window,settled
from test_advanced_ui import prepare


def test_paragraph_spacing_preview_overflow_and_recovery(qtbot,line_window,tmp_path):
    window,_=line_window;source=prepare(qtbot,window,tmp_path)
    window.canvas.set_selection([g.id for g in window.model.glyphs[:3]])
    window.reflow_box.setChecked(True)
    window.auto_height_box.setChecked(False)  # Explicit fixed-height area still detects overflow.
    window.width_box.setValue(mm(120));window.height_box.setValue(mm(30))
    window.line_spacing_box.setValue(16);window.paragraph_spacing_box.setValue(7)
    window.content.setPlainText('UNO DOS\nTRES\n\nCUATRO')
    # Reject an undersized area without losing the draft or changing history.
    qtbot.mouseClick(window.preview_button,Qt.LeftButton);qtbot.waitUntil(lambda:not window.busy,timeout=30000)
    assert 'altura' in window.last_error
    assert window.state['history_index']==0 and not window.state['preview']
    assert window.content.toPlainText()=='UNO DOS\nTRES\n\nCUATRO'
    window.last_error=None;window.height_box.setValue(mm(75))
    qtbot.mouseClick(window.preview_button,Qt.LeftButton);settled(qtbot,window)
    assert window.last_report['paragraph_layout']['paragraph_spacing']==7
    qtbot.mouseClick(window.apply_step_button,Qt.LeftButton);settled(qtbot,window)
    target=tmp_path/'paragraph.pdf';window.save_as(target);settled(qtbot,window)
    with fitz.open(target) as doc:
        spans=[s for b in doc[0].get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans']]
        ys=sorted({round(s['origin'][1],2) for s in spans if s['origin'][1]<155})
        assert ys==[80.,96.,135.]
        assert 'Vecino inalterado' in doc[0].get_text()


def test_closing_review_during_pending_preview_cancels_candidate(qtbot,line_window,tmp_path):
    window,_=line_window;prepare(qtbot,window,tmp_path)
    revision=window.model.revision;errors=[]
    def interact():
        dialog=QApplication.activeModalWidget()
        try:
            dialog.query.setText('SOL');dialog.replacement.setText('LUNA')
            qtbot.mouseClick(dialog.find_button,Qt.LeftButton);settled(qtbot,window)
            qtbot.mouseClick(dialog.one_button,Qt.LeftButton)
            assert window.busy
        except Exception as exc:errors.append(exc)
        finally:dialog.reject()
    QTimer.singleShot(0,interact);window.open_replace()
    qtbot.waitUntil(lambda:not window.busy and not window.state.get('preview'),timeout=30000)
    assert not errors,errors
    assert window.model.revision==revision and window.state['history_index']==0


def test_import_pages_at_selected_position_and_protect_inserted_source(qtbot,line_window,tmp_path):
    window,_=line_window;source=prepare(qtbot,window,tmp_path)
    external=tmp_path/'insert.pdf'
    with fitz.open() as doc:
        doc.new_page(width=300,height=200).insert_text((30,70),'PAGINA INSERTADA')
        doc.save(external)
    original=external.read_bytes();errors=[]
    def interact():
        dialog=window._advanced_dialog
        if dialog is None:QTimer.singleShot(30,interact);return
        try:
            qtbot.waitUntil(lambda:not window.busy and dialog.page_list.isEnabled(),timeout=30000)
            dialog.import_requested.emit([str(external)],1)
            qtbot.waitUntil(lambda:len(dialog.plan())==3 and not window.busy and dialog.apply_button.isEnabled(),timeout=30000)
            assert dialog.plan()[1]['source']!='current'
            dialog.accept()
        except Exception as exc:errors.append(exc);dialog.reject()
    QTimer.singleShot(30,interact);window.open_organizer()
    qtbot.waitUntil(lambda:window.state.get('preview') or bool(errors),timeout=30000)
    assert not errors,errors
    settled(qtbot,window)
    qtbot.mouseClick(window.apply_step_button,Qt.LeftButton);settled(qtbot,window)
    target=tmp_path/'organized.pdf';window.save_as(target);settled(qtbot,window)
    with fitz.open(target) as doc:
        assert len(doc)==3 and 'PAGINA INSERTADA' in doc[1].get_text()
        assert doc[1].rect.width==300
    window.save_as(external);qtbot.waitUntil(lambda:not window.busy,timeout=30000)
    assert window.last_error and external.read_bytes()==original
    assert window.state['page_count']==3
