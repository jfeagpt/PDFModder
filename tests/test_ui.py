"""Interacción Qt real y reapertura independiente del PDF exportado."""
from hashlib import sha256
from pathlib import Path

import pymupdf
from pypdf import PdfReader
from PySide6.QtCore import Qt
import pytest

from pdfmodder.app import MainWindow
from pdfmodder.model import transform,union


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def editor(qtbot,tmp_path):
    (tmp_path/"history").mkdir()
    window = MainWindow(config_path=tmp_path/"fonts.json",history_dir=tmp_path/"history")
    window.thumbnail_timer.stop()  # This test targets editing, without thumbnail scheduling races.
    # pytest-qt closes registered widgets before yield fixtures finalize.
    # Avoid invoking the real unsaved-work question during automatic teardown.
    qtbot.addWidget(window,before_close_func=lambda w:setattr(w,'_allow_close',True))
    window.show()
    yield window
    window._allow_close = True
    window.close()


def settled(qtbot,window):
    qtbot.waitUntil(lambda:not window.busy and not getattr(window,'_rich_loading',False)
                   and not getattr(window,'_rich_accept_pending',False)
                   and getattr(window,'_rich_pending',None) is None
                   and not (getattr(window,'_rich_active',False) and window._rich_timer.isActive()),timeout=30000)
    assert not window.last_error,window.last_error


def ready_editor(qtbot,window):
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=30000)
    assert not window.canvas.editor.textCursor().hasSelection(), 'Entrar en edición no debe seleccionar todo'


def choose(qtbot,window,text):
    combined = "".join(g.text for g in window.model.glyphs).replace("\u00a0"," ")
    start = combined.index(text)
    glyph = window.model.glyphs[start]
    center = ((glyph.bbox[0]+glyph.bbox[2])/2,(glyph.bbox[1]+glyph.bbox[3])/2)
    screen = window.canvas.viewport_point(center)
    window.canvas.ensureVisible(window.canvas.scene_rect(glyph.bbox),20,20)
    screen = window.canvas.viewport_point(center)
    qtbot.mouseClick(window.canvas.viewport(),Qt.LeftButton,pos=screen)
    return glyph,screen


def test_full_ui_edit_drag_save_reopen_cancel_and_failed_save(qtbot,editor,tmp_path):
    source = ROOT/"examples"/"digital.pdf"
    original_hash = sha256(source.read_bytes()).hexdigest()
    editor.open_document(source)
    settled(qtbot,editor)
    assert editor.model and editor.state["page_count"] == 2
    glyph,point = choose(qtbot,editor,"10/09/2026")
    assert editor.model.text(editor.canvas.ids) == "10/09/2026"

    # Escape during a drag must not become a move when the mouse is released.
    editor.canvas.set_interaction_mode('move')
    cancelled_end = editor.canvas.viewport_point((glyph.origin[0]+18,glyph.origin[1]+18))
    qtbot.mousePress(editor.canvas.viewport(),Qt.LeftButton,pos=point)
    qtbot.mouseMove(editor.canvas.viewport(),pos=cancelled_end)
    qtbot.keyClick(editor.canvas,Qt.Key_Escape)
    qtbot.mouseRelease(editor.canvas.viewport(),Qt.LeftButton,pos=cancelled_end)
    qtbot.wait(210)
    assert editor.state["history_index"] == 0
    assert not editor.busy

    # A real on-page typing session, then Escape: zero committed edits.
    qtbot.mouseDClick(editor.canvas.viewport(),Qt.LeftButton,pos=point)
    ready_editor(qtbot,editor)
    qtbot.keyClick(editor.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(editor.canvas.editor,"99/99/9999")
    qtbot.keyClick(editor.canvas.editor,Qt.Key_Escape)
    assert not editor.canvas.editor.isVisible()
    assert editor.state["history_index"] == 0

    editor.start_edit()
    ready_editor(qtbot,editor)
    qtbot.keyClick(editor.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(editor.canvas.editor,"11/09/2026")
    qtbot.keyClick(editor.canvas.editor,Qt.Key_Return,modifier=Qt.ControlModifier)
    settled(qtbot,editor)
    assert not editor.state["preview"]
    assert "11/09/2026" in "".join(g.text for g in editor.model.glyphs)
    assert editor.state["history_index"] == 1

    # One drag produces one history entry. The canvas emits unrotated PDF units.
    moved_glyph,start = choose(qtbot,editor,"11/09/2026")
    # Drag inside the text box, away from the new edge/corner resize handles.
    bounds=union(g.bbox for g in editor.model.selected(editor.canvas.ids))
    center = ((bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2)
    start=editor.canvas.viewport_point(center)
    end = editor.canvas.viewport_point((center[0]+12,center[1]+10))
    deltas = []
    editor.canvas.move_requested.connect(lambda dx,dy:deltas.append((dx,dy)))
    qtbot.mousePress(editor.canvas.viewport(),Qt.LeftButton,pos=start)
    qtbot.mouseMove(editor.canvas.viewport(),pos=end)
    qtbot.mouseRelease(editor.canvas.viewport(),Qt.LeftButton,pos=end)
    settled(qtbot,editor)
    assert deltas
    assert editor.state["history_index"] == 2
    dx,dy = deltas[-1]
    assert dx == pytest.approx(12,abs=.85)
    assert dy == pytest.approx(10,abs=.85)

    editor.history("undo")
    settled(qtbot,editor)
    assert editor.state["history_index"] == 1
    editor.history("redo")
    settled(qtbot,editor)
    assert editor.state["history_index"] == 2

    # Source overwrite is rejected; the dirty working state remains usable.
    editor.save_as(source)
    qtbot.waitUntil(lambda:not editor.busy,timeout=30000)
    assert "original" in editor.last_error.lower()
    assert editor.state["dirty"]
    assert editor.state["history_index"] == 2
    output = tmp_path/"ui-edited.pdf"
    editor.save_as(output)
    settled(qtbot,editor)
    assert output.is_file() and not editor.state["dirty"]
    assert sha256(source.read_bytes()).hexdigest() == original_hash
    independent = PdfReader(str(output),strict=True)
    assert "11/09/2026" in independent.pages[0].extract_text()
    assert "10/09/2026" in independent.pages[1].extract_text()
    with pymupdf.open(output) as pdf:
        found = pdf[0].search_for("11/09/2026")
        assert len(found)==1
        assert found[0].x0 == pytest.approx(125+dx,abs=.035)
        assert found[0].y0 == pytest.approx(glyph.bbox[1]+dy,abs=.035)
        assert not pdf[0].search_for("10/09/2026")

    editor.open_document(output)
    settled(qtbot,editor)
    choose(qtbot,editor,"11/09/2026")
    editor.content.setFocus()
    qtbot.keyClick(editor.content,Qt.Key_Right)
    qtbot.wait(210)
    assert editor.state["history_index"] == 0
    assert not editor.busy
    editor.content.setPlainText("12/09/2026")
    qtbot.mouseClick(editor.preview_button,Qt.LeftButton)
    settled(qtbot,editor)
    qtbot.mouseClick(editor.commit_button,Qt.LeftButton)
    settled(qtbot,editor)
    assert "12/09/2026" in "".join(g.text for g in editor.model.glyphs)
    assert editor.state["history_index"] == 1


def test_canvas_rotated_crop_zoom_selection_and_comparison(qtbot,editor):
    editor.open_document(ROOT/"examples"/"rotated_crop.pdf")
    settled(qtbot,editor)
    assert editor.model.rotation == 90
    for zoom in (.75,1.5):
        editor.set_zoom(zoom)
        settled(qtbot,editor)
        glyph,point = choose(qtbot,editor,"10/09/2026")
        assert editor.model.text(editor.canvas.ids)=="10/09/2026"
        hit = editor.canvas.pdf_point(point)
        assert glyph.bbox[0] <= hit[0] <= glyph.bbox[2]
        assert glyph.bbox[1] <= hit[1] <= glyph.bbox[3]
    editor.compare_action.trigger()
    settled(qtbot,editor)
    assert editor.canvas.read_only
    assert not editor.property_box.isEnabled()
    assert "ORIGINAL" in editor.windowTitle()


def test_typing_session_cannot_retarget_other_text(qtbot,editor):
    editor.open_document(ROOT/"examples"/"digital.pdf")
    settled(qtbot,editor)
    choose(qtbot,editor,"10/09/2026")
    initial=editor.canvas.ids[:]
    editor.start_edit()
    ready_editor(qtbot,editor)
    qtbot.keyClick(editor.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(editor.canvas.editor,"11/09/2026")
    other=next(g for g in editor.model.glyphs if g.origin==(48.,197.))
    point=editor.canvas.viewport_point(((other.bbox[0]+other.bbox[2])/2,(other.bbox[1]+other.bbox[3])/2))
    qtbot.mouseClick(editor.canvas.viewport(),Qt.LeftButton,pos=point)
    assert editor.canvas.ids==initial
    assert not editor.zoom_box.isEnabled() and not editor.pages.isEnabled()
    qtbot.keyClick(editor.canvas,Qt.Key_Right)
    qtbot.wait(220)
    # Live rendering may be in progress; it must never commit a move/edit.
    settled(qtbot,editor)
    assert editor.state['history_index']==0 and editor._rich_active
    qtbot.keyClick(editor.canvas.editor,Qt.Key_Return,modifier=Qt.ControlModifier)
    settled(qtbot,editor)
    assert not editor.state['preview'] and editor.state['history_index']==1
    assert '11/09/2026' in ''.join(g.text for g in editor.model.glyphs)
    assert ''.join(g.text for g in editor.model.glyphs).count('TOTAL')==3


def test_thumbnails_do_not_interrupt_typing_or_drag(qtbot,editor):
    editor.open_document(ROOT/"examples"/"digital.pdf")
    settled(qtbot,editor)
    choose(qtbot,editor,"10/09/2026")
    editor._thumbnail_pages.clear()
    editor.canvas._press=(125.,125.)
    editor._load_visible_thumbnail()
    assert not editor.busy
    editor.canvas._press=None
    editor.start_edit()
    ready_editor(qtbot,editor)
    editor._load_visible_thumbnail()
    assert not editor.busy and editor.canvas.editor.isVisible()
    editor.cancel()
