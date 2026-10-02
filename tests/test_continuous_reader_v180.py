"""Continuous scrolling, multi-page copying and bounded reading caches."""
from PySide6.QtCore import QBuffer, QIODevice, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtWidgets import QApplication

from pdfmodder.continuous_reader_v180 import ContinuousReader
from pdfmodder.model import Glyph, PageModel
from pdfmodder.reading_order_v180 import ordered_glyphs, selection_text


def model(number, specs=None, height=600.):
    specs = specs or [("Primer párrafo", 35., 90., 1, 1), ("Segundo párrafo", 35., 160., 2, 2)]
    glyphs, rows = [], []
    for text, left, top, block, line in specs:
        row = []
        for index, char in enumerate(text):
            x = left + index * 9.
            rect = (x, top, x + 9., top + 14.)
            glyph = Glyph(2000 - len(glyphs) * 7, char, (x, top + 11.), rect, rect,
                          "Helvetica", 11., (0., 0., 0.), 1., block, line, 0)
            row.append(glyph)
            glyphs.append(glyph)
        rows.append(row)
    matrix = (1., 0., 0., 1., 0., 0.)
    return PageModel(number, 320., height, 0, matrix, matrix,
                     (0., 0., 320., height), glyphs[::2][::-1] + glyphs[1::2][::-1]), rows


def png(width=320, height=600):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(Qt.white)
    buffer = QBuffer()
    assert buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def reader(qtbot, count=3):
    view = ContinuousReader()
    qtbot.addWidget(view)
    view.resize(500, 460)
    view.show()
    view.reset_document([{"width": 320., "height": 600.} for _ in range(count)], zoom=1.)
    QApplication.processEvents()
    return view


def position(view, page, glyph):
    rect = view._rects[page]
    x0, y0, x1, y1 = glyph.bbox
    return view.mapFromScene(QPointF(rect.left() + (x0 + x1) / 2. * view.zoom,
                                    rect.top() + (y0 + y1) / 2. * view.zoom))


def wheel(view):
    point = view.viewport().rect().center()
    event = QWheelEvent(QPointF(point), QPointF(view.viewport().mapToGlobal(point)),
                        QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), event)
    QApplication.processEvents()


def test_wheel_reveals_next_page_progressively_without_page_jump(qtbot):
    view = reader(qtbot)
    requested = []
    view.pages_requested.connect(requested.append)
    scroll = view.verticalScrollBar()
    second_top = view._rects[1].top()
    scroll.setValue(int(second_top - view.viewport().height() + 5))
    QApplication.processEvents()
    first_visible = view._rects[1].intersected(view.mapToScene(view.viewport().rect()).boundingRect()).height()
    before = scroll.value()
    wheel(view)
    after_visible = view._rects[1].intersected(view.mapToScene(view.viewport().rect()).boundingRect()).height()
    assert scroll.value() > before
    assert 0 < first_visible < after_visible < view._rects[1].height()
    assert scroll.value() < second_top
    assert all(len(numbers) <= 4 for numbers in requested)


def test_drag_can_select_paragraphs_and_continue_on_another_page(qtbot):
    view = reader(qtbot)
    first, first_rows = model(0)
    second, second_rows = model(1)
    view.set_page(0, png(), first, 1.)
    view.set_page(1, png(), second, 1.)
    qtbot.mousePress(view.viewport(), Qt.LeftButton, pos=position(view, 0, first_rows[0][0]))
    qtbot.mouseMove(view.viewport(), pos=position(view, 0, first_rows[1][-1]))
    assert view.selection_text() == "Primer párrafo\n\nSegundo párrafo"
    view.go_page(1)
    qtbot.mouseMove(view.viewport(), pos=position(view, 1, second_rows[0][5]))
    qtbot.mouseRelease(view.viewport(), Qt.LeftButton, pos=position(view, 1, second_rows[0][5]))
    assert view.selected_page_numbers() == [0, 1]
    assert view.selection_text() == "Primer párrafo\n\nSegundo párrafo\n\nPrimer"
    assert view.selection_endpoints() == {
        "start": {"page": 0, "id": first_rows[0][0].id},
        "end": {"page": 1, "id": second_rows[0][5].id},
    }


def test_shift_click_extends_to_another_page_and_ctrl_c_requests_copy(qtbot):
    view = reader(qtbot)
    first, rows = model(0)
    last, last_rows = model(2)
    view.set_page(0, png(), first, 1.)
    view.set_page(2, png(), last, 1.)
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=position(view, 0, rows[0][1]))
    assert view.selection_text() == "Primer"
    view.go_page(2)
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, Qt.ShiftModifier,
                     pos=position(view, 2, last_rows[0][5]))
    assert view.selected_page_numbers() == [0, 1, 2]
    # A missing middle page must be completed by the worker before copying.
    import pytest
    with pytest.raises(ValueError, match="Faltan páginas"):
        view.selection_text()
    copies = []
    view.copy_requested.connect(lambda: copies.append(True))
    qtbot.keyClick(view, Qt.Key_C, Qt.ControlModifier)
    assert copies == [True]
    qtbot.keyClick(view, Qt.Key_Escape)
    assert view.selection_endpoints() is None


def test_cache_limits_images_and_retains_selection_endpoints(qtbot):
    view = reader(qtbot, count=20)
    first, rows = model(0)
    last, last_rows = model(19)
    view.set_page(0, png(), first, 1.)
    view.set_page(19, png(), last, 1.)
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=position(view, 0, rows[0][1]))
    view.go_page(19)
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, Qt.ShiftModifier,
                     pos=position(view, 19, last_rows[0][5]))
    for number in range(1, 19):
        current, _ = model(number)
        view.set_page(number, png(), current, .5)
    assert len(view.loaded_page_numbers()) <= 8
    assert view.image_cache_bytes <= 32 * 1024 * 1024
    assert len(view.models) <= 10
    assert view.model_for_page(0) is first
    assert view.model_for_page(19) is last
    assert view.selected_page_numbers() == list(range(20))
    assert view.zoom == 1.


def test_cache_memory_limit_and_zoom_preserve_visible_pdf_anchor(qtbot):
    view = reader(qtbot)
    for number in range(3):
        current, _ = model(number)
        view.set_page(number, png(1600, 3000), current, 5.)
    assert view.image_cache_bytes <= view.MAX_IMAGE_BYTES
    view.go_page(1)
    view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 160)
    center = view.mapToScene(view.viewport().rect().center())
    relative = (center.y() - view._rects[1].top()) / view.zoom
    view.set_zoom(1.5)
    center_after = view.mapToScene(view.viewport().rect().center())
    relative_after = (center_after.y() - view._rects[1].top()) / view.zoom
    assert abs(relative_after - relative) < 2.
    assert not view.has_page(1, 1.5)


def test_reading_order_separates_columns_and_keeps_paragraph_breaks():
    current, rows = model(0, [
        ("Título general de la página", 20., 10., 0, 0),
        ("Izquierda uno", 20., 80., 1, 1),
        ("Izquierda dos", 20., 130., 2, 2),
        ("Derecha uno", 190., 80., 3, 3),
        ("Derecha dos", 190., 130., 4, 4),
    ])
    assert selection_text(current) == (
        "Título general de la página\n\nIzquierda uno\n\nIzquierda dos\n\nDerecha uno\n\nDerecha dos")
    assert ordered_glyphs(current)[0].id == rows[0][0].id


def test_small_visible_pages_do_not_evict_each_other_or_request_forever(qtbot):
    view = reader(qtbot, count=18)
    view.reset_document([{"width": 320., "height": 12.} for _ in range(18)], zoom=.1)
    QApplication.processEvents()
    visible = view.visible_page_numbers()
    assert len(visible) > 8
    requested = []
    view.pages_requested.connect(requested.append)
    for number in visible:
        current, _ = model(number, height=12.)
        view.set_page(number, png(32, 2), current, .1)
    QApplication.processEvents()
    assert all(view.has_page(number, .1) for number in visible)
    assert not requested
    assert view.image_cache_bytes <= view.MAX_IMAGE_BYTES


def test_search_reveal_scrolls_to_match_and_draws_only_loaded_visible_matches(qtbot):
    view = reader(qtbot)
    second, rows = model(1)
    view.set_search_matches([{"page": 1, "rect": rows[1][0].bbox}])
    view.reveal_rect(1, rows[1][0].bbox)
    assert view._pending_reveal is not None
    view.set_page(1, png(), second, 1.)
    QApplication.processEvents()
    assert view._pending_reveal is None
    point = position(view, 1, rows[1][0])
    assert view.viewport().rect().contains(point)
    assert len(view._search_overlays) == 1
