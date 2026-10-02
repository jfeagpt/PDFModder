"""Reading gestures select visible text without requesting document changes."""

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtWidgets import QApplication

from pdfmodder.canvas import PdfCanvas
from pdfmodder.model import Glyph, PageModel


def make_canvas(qtbot, *, reading=True):
    """Build a scrollable page entirely in memory, with scrambled extraction order."""
    lines = {}
    glyphs = []
    specs = (
        ("top", "UNO DOS", 60., 80., 1, 30),
        ("bottom", "SEGUNDA", 60., 128., 1, 10),
        ("other_block", "AJENO", 60., 104., 9, 20),
        ("right", "DERECHA", 330., 80., 1, 40),
    )
    for name, text, left, top, block, line in specs:
        lines[name] = []
        for index, char in enumerate(text):
            x = left + index * 12.
            rect = (x, top, x + 12., top + 18.)
            glyph = Glyph(
                1000 - len(glyphs) * 7, char, (x, top + 14.), rect, rect,
                "Helvetica", 12., (0., 0., 0.), 1., block, line, 0,
            )
            lines[name].append(glyph)
            glyphs.append(glyph)
    # Neither numeric IDs nor the extraction list encode reading order.
    glyphs = glyphs[1::2][::-1] + glyphs[::2][::-1]
    matrix = (1., 0., 0., 1., 0., 0.)
    model = PageModel(
        0, 540., 1200., 0, matrix, matrix,
        (0., 0., 540., 1200.), glyphs, revision="reading-fixture",
    )
    image = QImage(540, 1200, QImage.Format_RGB32)
    image.fill(Qt.white)
    buffer = QBuffer()
    assert buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    png = bytes(buffer.data())
    buffer.close()

    canvas = PdfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(650, 360)
    canvas.set_page(png, model, 1.)
    if reading:
        canvas.reading_mode = True
    canvas.show()
    QApplication.processEvents()
    return canvas, lines


def center(canvas, glyph):
    x0, y0, x1, y1 = glyph.bbox
    return canvas.viewport_point(((x0 + x1) / 2., (y0 + y1) / 2.))


def drag(qtbot, canvas, first, last):
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=center(canvas, first))
    qtbot.mouseMove(canvas.viewport(), pos=center(canvas, last))
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=center(canvas, last))


def wheel(canvas, *, angle=(0, -120), pixel=(0, 0), modifiers=Qt.NoModifier):
    position = canvas.viewport().rect().center()
    event = QWheelEvent(
        QPointF(position), QPointF(canvas.viewport().mapToGlobal(position)),
        QPoint(*pixel), QPoint(*angle), Qt.NoButton, modifiers,
        Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(canvas.viewport(), event)


def test_reading_click_and_double_click_select_words_in_read_only_canvas(qtbot):
    canvas, lines = make_canvas(qtbot, reading=False)
    assert canvas.reading_mode is False
    assert canvas.page_navigation_enabled is False
    canvas.reading_mode = True
    canvas.read_only = True
    canvas.mode = "block"
    edits = []
    canvas.edit_requested.connect(lambda: edits.append(True))

    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, pos=center(canvas, lines["top"][1]))
    assert set(canvas.ids) == {glyph.id for glyph in lines["top"][:3]}
    assert canvas.reading_text() == "UNO"

    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, pos=center(canvas, lines["top"][5]))
    assert set(canvas.ids) == {glyph.id for glyph in lines["top"][4:]}
    assert canvas.reading_text() == "DOS"

    qtbot.mouseDClick(canvas.viewport(), Qt.LeftButton, pos=center(canvas, lines["top"][1]))
    assert canvas.reading_text() == "UNO"
    assert not edits
    assert not canvas.editor.isVisible()


@pytest.mark.parametrize("reverse", [False, True])
def test_reading_drag_selects_partial_multiline_range_in_geometry_order(qtbot, reverse):
    canvas, lines = make_canvas(qtbot)
    canvas.read_only = True
    canvas.mode = "block"
    first, last = lines["top"][1], lines["bottom"][3]
    if reverse:
        first, last = last, first
    drag(qtbot, canvas, first, last)

    expected = lines["top"][1:] + lines["bottom"][:4]
    assert set(canvas.ids) == {glyph.id for glyph in expected}
    assert canvas.reading_text() == "NO DOS\nSEGU"
    assert not canvas._border_move
    assert canvas._press is None


@pytest.mark.parametrize("target", ["other_block", "right"])
def test_reading_drag_cannot_cross_block_or_column(qtbot, target):
    canvas, lines = make_canvas(qtbot)
    drag(qtbot, canvas, lines["top"][1], lines[target][3])

    left_ids = {glyph.id for glyph in lines["top"] + lines["bottom"]}
    assert canvas.ids
    assert set(canvas.ids) <= left_ids
    assert not set(canvas.ids) & {glyph.id for glyph in lines[target]}


@pytest.mark.parametrize("interaction_mode", ["select", "write", "move"])
def test_reading_gestures_and_keys_never_request_document_changes(qtbot, interaction_mode):
    canvas, lines = make_canvas(qtbot)
    canvas.set_interaction_mode(interaction_mode)
    changes = []
    for name in (
        "move_requested", "edit_requested", "delete_requested",
        "arrow_requested", "text_resize_requested",
    ):
        getattr(canvas, name).connect(lambda *args, signal=name: changes.append((signal, args)))
    before = [(glyph.id, glyph.origin, glyph.bbox) for glyph in canvas.model.glyphs]
    canvas.set_selection([glyph.id for glyph in lines["top"][:3]])
    # Exercise an existing selection's edge and resize corner, then its text.
    for point in ((78., 80.), (96., 98.)):
        first = canvas.viewport_point(point)
        last = canvas.viewport_point((point[0] + 35., point[1] + 25.))
        qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=first)
        qtbot.mouseMove(canvas.viewport(), pos=last)
        qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=last)
        canvas.set_selection([glyph.id for glyph in lines["top"][:3]])
    drag(qtbot, canvas, lines["top"][1], lines["top"][5])
    assert canvas.ids
    for key in (
        Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
        Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2, Qt.Key_Delete, Qt.Key_Backspace,
    ):
        qtbot.keyClick(canvas, key)

    assert not changes
    assert [(glyph.id, glyph.origin, glyph.bbox) for glyph in canvas.model.glyphs] == before
    assert not canvas.editor.isVisible()


def test_wheel_scrolls_to_boundary_before_turning_page_and_respects_active_tools(qtbot):
    canvas, _ = make_canvas(qtbot)
    canvas.page_navigation_enabled = True
    requested = []
    canvas.wheel_page_requested.connect(requested.append)
    scroll = canvas.verticalScrollBar()
    assert scroll.maximum() > 0

    scroll.setValue(scroll.maximum() // 2)
    previous = scroll.value()
    wheel(canvas)
    assert scroll.value() > previous
    assert not requested

    scroll.setValue(scroll.maximum() - 1)
    wheel(canvas)
    assert scroll.value() == scroll.maximum()
    assert not requested
    wheel(canvas)
    assert requested == [1]

    scroll.setValue(scroll.minimum() + 1)
    wheel(canvas, angle=(0, 120))
    assert scroll.value() == scroll.minimum()
    assert requested == [1]
    wheel(canvas, angle=(0, 120))
    assert requested == [1, -1]

    scroll.setValue(scroll.maximum())
    canvas.page_navigation_enabled = False
    wheel(canvas)
    canvas.page_navigation_enabled = True
    wheel(canvas, modifiers=Qt.ControlModifier)
    wheel(canvas, angle=(120, 0))
    assert requested == [1, -1]

    canvas.editor.show()
    assert canvas.editor.isVisible()
    wheel(canvas)
    canvas.editor.hide()
    canvas.placement_mode = True
    wheel(canvas)
    canvas.placement_mode = False
    canvas.begin_signature_rectangle()
    wheel(canvas)
    canvas.end_signature_rectangle()
    assert requested == [1, -1]

    # High-resolution trackpads may supply only a vertical pixel delta.
    scroll.setValue(scroll.maximum())
    wheel(canvas, angle=(0, 0), pixel=(0, -35))
    assert requested == [1, -1, 1]
