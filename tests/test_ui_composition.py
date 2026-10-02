"""Qt + worker integration for actual point placement and typography dialog."""
from hashlib import sha256
from pathlib import Path
import traceback

import pymupdf as fitz
from pypdf import PdfReader
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QToolButton
import pytest

from pdfmodder.app import MainWindow
from pdfmodder.dialogs import TextDialog
from pdfmodder.model import union

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def composing_editor(qtbot,tmp_path):
    history=tmp_path/'history'
    history.mkdir()
    window=MainWindow(config_path=tmp_path/'fonts.json',history_dir=history)
    window.thumbnail_timer.stop()
    qtbot.addWidget(window,before_close_func=lambda widget:setattr(widget,'_allow_close',True))
    window.show()
    yield window
    window._allow_close=True
    window.close()


def settled(qtbot,window):
    qtbot.waitUntil(lambda:not window.busy,timeout=30000)
    assert not window.last_error,window.last_error


def advanced_tool_button(window,name,action):
    window.advanced_tools_section.set_expanded(True)
    button=window.findChild(QToolButton,name)
    assert button is not None and button.defaultAction() is action
    window.tools_scroll.ensureWidgetVisible(button)
    assert button.isVisible() and button.isEnabled(),action.text()
    return button


def test_click_place_text_real_typography_dialog_preview_commit_save_and_reopen(qtbot,composing_editor,tmp_path):
    window=composing_editor
    source=ROOT/'examples'/'digital.pdf'
    original=source.read_bytes()
    original_hash=sha256(original).hexdigest()
    window.open_document(source)
    settled(qtbot,window)
    assert window.model and window.state['page_count']==2

    # Starting text placement while inspecting images must return to text mode.
    qtbot.mouseClick(advanced_tool_button(window,'toolSelectImages',window.image_mode_action),Qt.LeftButton)
    assert window.canvas.image_mode
    # The explicit font/dimension dialog remains in Advanced tools; the main
    # Add text action now starts the inline editor tested by workflow_v150.
    assert window.add_text_properties_action.isEnabled()
    qtbot.mouseClick(advanced_tool_button(window,'toolAddTextProperties',window.add_text_properties_action),Qt.LeftButton)
    assert window.canvas.placement_mode and not window.canvas.image_mode
    assert not window.save_action.isEnabled()
    assert window.state['history_index']==0

    # No engine calls or command mocks fill the new text: this QTimer drives the
    # actual modal widget after the asynchronous font catalogue returns.
    expected_text='Nota nueva: niño 125,50 €'
    accepted_values=[]
    modal_errors=[]
    placed_points=[]
    window.canvas.placement_clicked.connect(lambda x,y:placed_points.append((x,y)))
    timer=QTimer(window)
    timer.setInterval(25)

    def fill_dialog():
        dialog=QApplication.activeModalWidget()
        if not isinstance(dialog,TextDialog):
            return
        timer.stop()
        try:
            assert not dialog.existing
            assert dialog.windowTitle()=='Añadir texto'
            family_index=dialog.font_picker.family_box.findData('Courier')
            assert family_index>=0
            dialog.font_picker.family_box.setCurrentIndex(family_index)
            qtbot.mouseClick(dialog.font_picker.bold_box,Qt.LeftButton)
            assert dialog.font_picker.choice()['font_name']=='Courier-Bold'
            dialog.size_box.setValue(13.375)
            dialog.width_box.setValue(90.0)
            dialog.content.setFocus()
            qtbot.keyClicks(dialog.content,'Nota nueva: ')
            dialog.content.insertPlainText('niño 125,50 €')
            assert dialog.content.toPlainText()==expected_text
            accepted_values.append(dialog.values())
            qtbot.mouseClick(dialog.preview_button,Qt.LeftButton)
            assert dialog.result()==QDialog.Accepted
        except Exception:
            modal_errors.append(traceback.format_exc())
            dialog.reject()

    timer.timeout.connect(fill_dialog)
    timer.start()
    try:
        point=(55.,590.)
        window.canvas.ensureVisible(window.canvas.scene_rect((55,585,315,640)),20,20)
        viewport_point=window.canvas.viewport_point(point)
        qtbot.mouseClick(window.canvas.viewport(),Qt.LeftButton,pos=viewport_point)
        qtbot.waitUntil(lambda:bool(accepted_values or modal_errors or window.last_error),timeout=30000)
    finally:
        timer.stop()
    assert not modal_errors,'\n'.join(modal_errors)
    assert accepted_values and placed_points
    values=accepted_values[0]
    assert values['font_name']=='Courier-Bold' and values['font_file'] is None
    assert values['size']==13.375 and not values['allow_overlap']
    assert (values['x'],values['y'])==pytest.approx(placed_points[0],abs=.003)

    settled(qtbot,window)
    assert window.state['preview'] and window.state['history_index']==0
    assert not window.canvas.placement_mode and not window.canvas.image_mode
    assert window.last_report['verified'] and window.last_report['operation']=='insert_text'
    preview_text=''.join(g.text for g in window.model.glyphs)
    assert preview_text.count(expected_text)==1
    assert window.commit_button.isEnabled()
    window.tools_scroll.ensureWidgetVisible(window.commit_button)
    qtbot.mouseClick(window.commit_button,Qt.LeftButton)
    settled(qtbot,window)
    assert not window.state['preview'] and window.state['history_index']==1
    assert window.state['dirty']

    output=tmp_path/'ui-composed.pdf'
    window.save_as(output)
    settled(qtbot,window)
    assert output.is_file() and not window.state['dirty']
    assert sha256(source.read_bytes()).hexdigest()==original_hash
    independent=PdfReader(output,strict=True)
    assert len(independent.pages)==2
    assert independent.pages[0].extract_text().count(expected_text)==1
    assert '10/09/2026' in independent.pages[0].extract_text()
    with fitz.open(stream=original,filetype='pdf') as before, fitz.open(output) as after:
        assert before[1].get_text()==after[1].get_text()
        assert before[1].get_pixmap(matrix=fitz.Matrix(2,2)).samples==after[1].get_pixmap(matrix=fitz.Matrix(2,2)).samples
        assert len(after[0].search_for(expected_text))==1
        added=[(span,char) for span in after[0].get_texttrace() for char in span['chars']
               if span['font']=='Courier-Bold' and values['y']<=char[2][1]<=values['y']+40]
        assert ''.join(chr(char[0]) for span,char in added)==expected_text
        assert all(span['size']==pytest.approx(13.375,abs=.001) for span,char in added)
        visible=after[0].search_for(expected_text)[0]
        assert visible.x0==pytest.approx(values['x'],abs=.035)
        assert visible.y0==pytest.approx(values['y'],abs=.035)

    # Reopen through the real worker and select the added word with the mouse.
    window.open_document(output)
    settled(qtbot,window)
    assert window.state['history_index']==0
    joined=''.join(g.text for g in window.model.glyphs)
    offset=joined.index(expected_text)
    glyph=window.model.glyphs[offset]
    center=((glyph.bbox[0]+glyph.bbox[2])/2,(glyph.bbox[1]+glyph.bbox[3])/2)
    window.canvas.ensureVisible(window.canvas.scene_rect(glyph.bbox),20,20)
    qtbot.mouseClick(window.canvas.viewport(),Qt.LeftButton,pos=window.canvas.viewport_point(center))
    assert window.model.text(window.canvas.ids)=='Nota'
    assert window.format_action.isEnabled()
    assert glyph.font=='Courier-Bold' and glyph.size==pytest.approx(13.375,abs=.001)
