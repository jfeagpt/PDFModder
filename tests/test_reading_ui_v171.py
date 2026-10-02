"""Contrato de los modos y portapapeles, sin proceso PDF ni red."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_tools_ui_v150 import NoPdfPool
from test_reading_canvas_v171 import make_canvas, center, wheel


@pytest.fixture
def reader(qtbot, monkeypatch):
    import pdfmodder.app as application
    monkeypatch.setattr(application, 'ProcessPoolExecutor', NoPdfPool)
    window = application.MainWindow()
    qtbot.addWidget(window)
    window.poller.stop()
    window.thumbnail_timer.stop()
    window.show()
    yield window
    window.state = {}
    window._allow_close = True
    window.close()


def load_fixture(reader, qtbot):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    canvas, lines = make_canvas(qtbot)
    image = QImage(540, 1200, QImage.Format_RGB32); image.fill(Qt.white)
    buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); image.save(buffer, 'PNG')
    reader.model = canvas.model
    reader.state = {'page_count': 2, 'issues': [], 'editing_prepared': False, 'validation_pending': True, 'copy_allowed': True}
    reader.canvas.set_page(bytes(buffer.data()), reader.model, 1.)
    reader._refresh_actions()
    return lines


def test_startup_reading_and_explicit_tools_without_document(reader):
    assert reader.application_mode == 'reading' and reader.canvas.reading_mode
    assert not reader.tools_scroll.isVisible() and not reader.tools_action.isChecked()
    assert all(not action.isVisible() for action in reader.mode_actions_v170.values())
    reader.tools_action.setChecked(True)
    assert reader.application_mode == 'editing' and reader.tools_scroll.isVisible()
    reader.reading_action.trigger()
    assert reader.application_mode == 'reading' and not reader.tools_scroll.isVisible()


def test_reading_copy_keyboard_and_context_no_editor(reader, qtbot):
    lines = load_fixture(reader, qtbot)
    qtbot.mouseDClick(reader.canvas.viewport(), Qt.LeftButton, pos=center(reader.canvas, lines['top'][1]))
    reader.canvas.setFocus()
    qtbot.keyClick(reader.canvas.viewport(), Qt.Key_C, Qt.ControlModifier)
    assert QApplication.clipboard().text() == 'UNO'
    assert not reader.canvas.editor.isVisible() and not reader._rich_active
    assert reader.copy_action_v170.isEnabled() and not reader.cut_action_v170.isEnabled()
    reader._clipboard_context_v170(reader.canvas.mapToGlobal(reader.canvas.rect().center()))
    assert [a.text() for a in reader._clipboard_menu_v170.actions()] == ['Copiar']
    reader._clipboard_menu_v170.close()
    reader.state['copy_allowed'] = False
    reader.clipboard_copy_v170()
    assert 'no permite copiar' in reader.last_error


def test_tools_requests_full_preparation_before_mutation(reader, qtbot, monkeypatch):
    load_fixture(reader, qtbot)
    requests = []
    monkeypatch.setattr(reader, '_submit', lambda command, payload=None, callback=None: requests.append((command,payload,callback)) or True)
    reader.tools_action.setChecked(True)
    assert requests[0][0] == 'prepare_editing'
    assert reader.application_mode == 'reading' and not reader.save_action.isEnabled()
    assert not reader._reading_command_allowed_v171('delete_pages')
    monkeypatch.setattr(reader, '_loaded_page', lambda result: None)
    reader.state['editing_prepared'] = True
    requests[0][2]({})
    assert reader.application_mode == 'editing' and reader.tools_scroll.isVisible()
    assert reader._reading_command_allowed_v171('delete_pages')


def test_wheel_page_bounds_and_mutation_commands_stay_guarded(reader, qtbot, monkeypatch):
    load_fixture(reader, qtbot)
    requested = []
    monkeypatch.setattr(reader, 'go_page', lambda number: requested.append(number))
    bar = reader.canvas.verticalScrollBar(); bar.setValue(bar.maximum())
    wheel(reader.canvas)
    assert requested == [1] and reader._wheel_scroll_edge_v171 == 'top'
    reader.page_number = 1
    reader._wheel_page_v171(1)
    assert requested == [1]
    assert reader._submit('image_apply', {}) is False
    assert reader._submit('delete_pages', {}) is False
