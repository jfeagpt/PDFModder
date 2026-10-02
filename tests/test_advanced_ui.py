from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QMimeData,QUrl,QPoint,QPointF
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtWidgets import QApplication,QDialog
from test_ui_line_edit import line_window,settled,double_click_sequence
from test_review_text import fixture
from pdfmodder.model import union,mm


def prepare(qtbot,window,tmp_path):
    source=tmp_path/'review.pdf';source.write_bytes(fixture())
    window.open_document(source);settled(qtbot,window)
    return source


def test_drop_pdf_into_document_view_opens_real_document(qtbot,line_window,tmp_path):
    window,_=line_window
    source=tmp_path/'dropped.pdf';source.write_bytes(fixture())
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(source))])
    entered=QDragEnterEvent(QPoint(40,40),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(window.canvas.viewport(),entered)
    assert entered.isAccepted()
    dropped=QDropEvent(QPointF(40,40),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(window.canvas.viewport(),dropped)
    assert dropped.isAccepted()
    settled(qtbot,window)
    assert Path(window.state['path'])==source.resolve()
    assert window.model.text([g.id for g in window.model.glyphs]).count('SOL')==2


def test_select_zone_lists_exact_text_and_auto_width_accepts_longer(qtbot,line_window,tmp_path):
    window,_=line_window;source=prepare(qtbot,window,tmp_path)
    original=source.read_bytes()
    qtbot.mouseClick(window.zone_button,Qt.LeftButton)
    start=window.canvas.viewport_point((43,64));end=window.canvas.viewport_point((75,84))
    qtbot.mousePress(window.canvas.viewport(),Qt.LeftButton,pos=start)
    qtbot.mouseMove(window.canvas.viewport(),end,delay=25)
    qtbot.mouseRelease(window.canvas.viewport(),Qt.LeftButton,pos=end)
    assert window.element_list.count()==1
    window.element_list.setCurrentRow(0)
    assert window.model.text(window.canvas.ids)=='SOL'
    old_width=window.width_box.value()
    double_click_sequence(qtbot,window.canvas,(50,74))
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=30000)
    assert not window.canvas.editor.textCursor().hasSelection()
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,'ESTRELLA')
    qtbot.mouseClick(window.canvas.editor.toolbar.accept,Qt.LeftButton)
    qtbot.waitUntil(lambda:not window.canvas.editor.isVisible(),timeout=30000)
    settled(qtbot,window)
    assert window.state['history_index']==1 and window.last_report['auto_width']
    assert window.width_box.value()>old_width
    assert 'ESTRELLA' in ''.join(g.text for g in window.model.glyphs)
    assert source.read_bytes()==original


def test_review_matches_dialog_preview_one_then_marked_commit_and_reopen(qtbot,line_window,tmp_path):
    window,_=line_window;source=prepare(qtbot,window,tmp_path)
    original=source.read_bytes()
    errors=[]
    def interact():
        d=QApplication.activeModalWidget()
        try:
            d.query.setText('SOL');d.replacement.setText('LUNA')
            qtbot.mouseClick(d.find_button,Qt.LeftButton);settled(qtbot,window)
            assert len(d.matches)==4
            d.table.selectRow(0)
            qtbot.mouseClick(d.one_button,Qt.LeftButton);settled(qtbot,window)
            assert d.preview_valid and not d.image.pixmap().isNull()
            assert window.state['history_index']==0 and window.state['preview']
            d.table.item(0,0).setCheckState(Qt.Checked)
            d.table.item(3,0).setCheckState(Qt.Checked)
            assert not d.apply_button.isEnabled()
            qtbot.mouseClick(d.marked_button,Qt.LeftButton);settled(qtbot,window)
            assert d.preview_valid and '2 cambios' in d.message.text()
            qtbot.mouseClick(d.apply_button,Qt.LeftButton)
            qtbot.waitUntil(lambda:not d.isVisible(),timeout=30000)
        except Exception as exc:errors.append(exc);d.reject()
    QTimer.singleShot(0,interact)
    window.open_replace()
    assert not errors,errors
    settled(qtbot,window)
    assert window.state['history_index']==1
    text=''.join(g.text for g in window.model.glyphs)
    assert text.count('LUNA')==1 and text.count('SOL')==1
    target=tmp_path/'replaced.pdf';window.save_as(target);settled(qtbot,window)
    window.open_document(target);settled(qtbot,window)
    assert ''.join(g.text for g in window.model.glyphs).count('LUNA')==1
    assert source.read_bytes()==original


def test_review_cancel_discards_pdf_preview(qtbot,line_window,tmp_path):
    window,_=line_window;prepare(qtbot,window,tmp_path)
    original_revision=window.model.revision
    errors=[]
    def interact():
        d=QApplication.activeModalWidget()
        try:
            d.query.setText('SOL');d.replacement.setText('LUNA')
            qtbot.mouseClick(d.find_button,Qt.LeftButton);settled(qtbot,window)
            qtbot.mouseClick(d.one_button,Qt.LeftButton);settled(qtbot,window)
            assert window.state['preview']
        except Exception as exc:errors.append(exc)
        finally:d.reject()
    QTimer.singleShot(0,interact);window.open_replace();settled(qtbot,window)
    assert not errors,errors
    assert not window.state['preview'] and window.model.revision==original_revision


def test_organizer_dialog_preview_and_commit_worker_mapping(qtbot,line_window,tmp_path):
    window,_=line_window;source=prepare(qtbot,window,tmp_path)
    errors=[]
    def interact():
        d=window._advanced_dialog
        if d is None:QTimer.singleShot(30,interact);return
        try:
            qtbot.waitUntil(lambda:not window.busy and d.page_list.isEnabled(),timeout=30000)
            d.page_list.setCurrentRow(1)
            d.move_selected(-1)
            d.rotate_selected()
            d.duplicate_selected()
            d.insert_blank()
            assert len(d.plan())==4
            qtbot.waitUntil(lambda:not window.busy and d.apply_button.isEnabled(),timeout=30000)
            d.accept()
        except Exception as exc:errors.append(exc);d.reject()
    QTimer.singleShot(30,interact);window.open_organizer()
    qtbot.waitUntil(lambda:window.state.get('preview') or bool(errors),timeout=30000)
    settled(qtbot,window)
    assert not errors,errors
    assert window.state['page_count']==4
    qtbot.mouseClick(window.apply_step_button,Qt.LeftButton);settled(qtbot,window)
    assert window.state['history_index']==1
    assert len(window.state['original_pages'])==4 and None in window.state['original_pages']
    window.undo_action.trigger();settled(qtbot,window)
    assert window.state['page_count']==2
