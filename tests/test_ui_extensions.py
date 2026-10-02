"""Qt interactions for image geometry and page-list/history integration."""
from pathlib import Path

from pypdf import PdfReader
from PySide6.QtCore import Qt
import pymupdf as fitz
import pytest

from test_ui import editor, settled


ROOT = Path(__file__).resolve().parents[1]


def drag(qtbot, editor, start, destination):
    first = editor.canvas.viewport_point(start)
    last = editor.canvas.viewport_point(destination)
    qtbot.mousePress(editor.canvas.viewport(), Qt.LeftButton, pos=first)
    qtbot.mouseMove(editor.canvas.viewport(), pos=last)
    qtbot.mouseRelease(editor.canvas.viewport(), Qt.LeftButton, pos=last)
    settled(qtbot, editor)


def test_ui_image_body_drag_handle_resize_keyboard_and_saved_geometry(qtbot, editor, tmp_path):
    editor.open_document(ROOT / "examples/digital.pdf")
    settled(qtbot, editor)
    editor.canvas.image_mode = True
    editor.canvas.lock_image_ratio = False
    image = editor.canvas.images[0]
    assert image["editable"]
    rect = image["rect"]
    editor.canvas.ensureVisible(editor.canvas.scene_rect(rect), 30, 30)
    center = ((rect[0]+rect[2])/2, (rect[1]+rect[3])/2)
    emitted = []
    editor.canvas.image_transform_requested.connect(lambda image_id, target: emitted.append((image_id, target)))
    drag(qtbot, editor, center, (center[0]-25, center[1]+12))
    assert editor.state["history_index"] == 1
    assert emitted
    moved = editor.canvas.images[0]["rect"]
    assert moved[0]-rect[0] == pytest.approx(-25, abs=.9)
    assert moved[1]-rect[1] == pytest.approx(12, abs=.9)
    assert moved[2]-moved[0] == pytest.approx(rect[2]-rect[0], abs=.04)

    editor.canvas.select_image(editor.canvas.images[0])
    editor.canvas.lock_image_ratio = False
    editor.canvas.ensureVisible(editor.canvas.scene_rect(moved), 30, 30)
    drag(qtbot, editor, moved[2:], (moved[2]+12, moved[3]+9))
    assert editor.state["history_index"] == 2
    resized = editor.canvas.images[0]["rect"]
    assert resized[:2] == pytest.approx(moved[:2], abs=.04)
    assert resized[2]-moved[2] == pytest.approx(12, abs=.9)
    assert resized[3]-moved[3] == pytest.approx(9, abs=.9)

    editor.canvas.select_image(editor.canvas.images[0])
    editor.canvas.setFocus()
    qtbot.keyClick(editor.canvas, Qt.Key_Right)
    qtbot.waitUntil(lambda: editor.busy or editor.state["history_index"] == 3, timeout=10000)
    settled(qtbot, editor)
    assert editor.state["history_index"] == 3
    nudged = editor.canvas.images[0]["rect"]
    assert nudged[0] > resized[0]
    assert nudged[1] == pytest.approx(resized[1], abs=.04)
    editor.undo_action.trigger()
    settled(qtbot, editor)
    assert editor.canvas.images[0]["rect"] == pytest.approx(resized, abs=.04)
    editor.redo_action.trigger()
    settled(qtbot, editor)
    assert editor.canvas.images[0]["rect"] == pytest.approx(nudged, abs=.04)

    output = tmp_path / "ui-image-geometry.pdf"
    editor.save_as(output)
    settled(qtbot, editor)
    with fitz.open(output) as doc:
        assert tuple(doc[0].get_image_info()[0]["bbox"]) == pytest.approx(nudged, abs=.04)
        assert len(doc[0].get_image_info()) == 1
    assert "10/09/2026" in PdfReader(output).pages[0].extract_text()


def test_ui_delete_undo_redo_extract_and_merge_page_list_original_mapping(qtbot, editor, tmp_path):
    editor.open_document(ROOT / "examples/digital.pdf")
    settled(qtbot, editor)
    assert editor.pages.count() == 2
    editor.delete_pages("1")
    settled(qtbot, editor)
    assert editor.pages.count() == 1
    assert editor.state["original_pages"] == [1]
    editor.compare_action.trigger()
    settled(qtbot, editor)
    assert editor.canvas.read_only
    assert "PÁGINA" in "".join(g.text for g in editor.model.glyphs)
    editor.compare_action.trigger()
    settled(qtbot, editor)

    editor.undo_action.trigger()
    settled(qtbot, editor)
    assert editor.pages.count() == 2 and editor.state["original_pages"] == [0, 1]
    editor.redo_action.trigger()
    settled(qtbot, editor)
    assert editor.pages.count() == 1 and editor.state["original_pages"] == [1]
    before = dict(editor.state)
    extracted = tmp_path / "ui-extracted.pdf"
    editor.extract_pages("1", extracted)
    settled(qtbot, editor)
    assert editor.state["history_index"] == before["history_index"]
    assert editor.state["page_count"] == before["page_count"]
    assert "PÁGINA DE CONTROL" in PdfReader(extracted).pages[0].extract_text()

    editor.merge_pdfs([ROOT / "examples/rotated_crop.pdf"])
    settled(qtbot, editor)
    assert editor.pages.count() == 2 and editor.state["original_pages"] == [1, None]
    item = editor.pages.item(1)
    editor.pages.scrollToItem(item)
    qtbot.mouseClick(editor.pages.viewport(), Qt.LeftButton, pos=editor.pages.visualItemRect(item).center())
    settled(qtbot, editor)
    assert editor.page_number == 1 and editor.model.rotation == 90
    assert not editor.compare_action.isEnabled()
    assert not editor.compare_action.isChecked()
    editor.undo_action.trigger()
    settled(qtbot, editor)
    assert editor.pages.count() == 1 and editor.page_number == 0
    editor.redo_action.trigger()
    settled(qtbot, editor)
    assert editor.pages.count() == 2 and editor.state["original_pages"] == [1, None]
