"""Exercise the new tools composition and interaction without a PDF worker."""
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QTextCursor
from PySide6.QtWidgets import QToolBar, QToolButton


class NoPdfPool:
    def __init__(self, *args, **kwargs):
        pass

    def submit(self, *args, **kwargs):
        if len(args) > 1 and args[1] == 'close':
            return None
        raise AssertionError('This UI test must not start a PDF worker')

    def shutdown(self, **kwargs):
        pass


@pytest.fixture
def tools_window(qtbot, monkeypatch):
    import pdfmodder.app as application
    monkeypatch.setattr(application, 'ProcessPoolExecutor', NoPdfPool)
    window = application.MainWindow()
    qtbot.addWidget(window)
    window.poller.stop()
    window.thumbnail_timer.stop()
    # This fixture exercises editing tools. Startup reading has its own tests.
    window.tools_action.setChecked(True)
    window.show()
    yield window
    window.state = {}
    window._allow_close = True
    window.close()


def test_tools_toggle_keeps_existing_actions_and_single_header(tools_window, qtbot):
    window = tools_window
    assert window.tools_scroll.isVisible()
    qtbot.mouseClick(window.tools_toggle_button, Qt.LeftButton)
    assert not window.tools_scroll.isVisible()
    qtbot.mouseClick(window.tools_toggle_button, Qt.LeftButton)
    assert window.tools_scroll.isVisible()
    assert [bar for bar in window.findChildren(QToolBar) if bar.isVisible()] == [window.toolbar]
    for name, action in [('toolAddText', window.add_text_action),
                         ('toolAddImage', window.add_image_action),
                         ('toolDeletePages', window.delete_pages_action),
                         ('toolFindReplace', window.replace_action),
                         ('toolObjects', window.objects_action),
                         ('toolCombinePdfs', window.merge_action)]:
        button = window.findChild(QToolButton, name)
        assert button.defaultAction() is action
        assert not action.icon().isNull()
    assert not window.advanced_tools_section.header.isChecked()
    window.advanced_tools_section.header.click()
    assert window.property_box.isVisible()
    assert window.findChild(QToolButton, 'toolFindReplace').isVisible()


def test_page_buttons_dispatch_real_entrypoints_and_respect_busy(tools_window, monkeypatch):
    window = tools_window
    called = []
    for method, value in [('choose_export_v150', 'export'), ('choose_replace_pages_v150', 'replace'),
                          ('choose_crop_pages_v150', 'crop'), ('choose_split_v150', 'split')]:
        monkeypatch.setattr(window, method, lambda operation=value:called.append(operation))
    window.state = {'page_capabilities': {'rotate': True, 'insert_pdf': True, 'delete': True, 'extract': True}}
    window._refresh_tools_v150()
    for action in (window.export_document_action, window.replace_pages_action,
                   window.crop_pages_action, window.split_document_action):
        assert action.isEnabled()
        action.trigger()
    assert called == ['export', 'replace', 'crop', 'split']
    window.future = object()
    window._refresh_tools_v150()
    assert not window.export_document_action.isEnabled()
    assert not window.replace_pages_action.isEnabled()
    assert not window.crop_pages_action.isEnabled()
    window.future = None
    window.state['page_capabilities'] = {'rotate': True, 'insert_pdf': False, 'delete': True, 'extract': False}
    window._refresh_tools_v150()
    assert window.rotate_pages_action.isEnabled()
    assert not window.insert_pages_action.isEnabled()
    assert not window.replace_pages_action.isEnabled()
    assert not window.split_document_action.isEnabled()


def _canvas_document(window):
    from pdfmodder.model import Glyph, PageModel
    glyph = Glyph(0, 'A', (20., 25.), (20., 15., 30., 27.), (20., 15., 30., 27.),
                  'Helvetica', 12., (0., 0., 0.), 1., 0, 0, 0)
    matrix = (1., 0., 0., 1., 0., 0.)
    model = PageModel(0, 200, 200, 0, matrix, matrix, (0., 0., 200., 200.), [glyph])
    png = QImage(200, 200, QImage.Format_RGB32)
    png.fill(Qt.white)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    png.save(buffer, 'PNG')
    window.model = model
    window.canvas.set_page(bytes(buffer.data()), model, 1.)
    window.canvas.images = [{'id': 'image-1', 'rect': (60., 60., 150., 130.), 'editable': True}]
    window.canvas.read_only = False


def test_combined_selection_switches_text_image_but_preserves_typing(tools_window, monkeypatch):
    window = tools_window
    _canvas_document(window)
    modes = []
    def set_mode(enabled):
        modes.append(enabled)
        window.canvas.image_mode = enabled
    monkeypatch.setattr(window, 'toggle_image_mode', set_mode)
    def press(point):
        pos = QPointF(window.canvas.viewport_point(point))
        event = QMouseEvent(QMouseEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        window._choose_content_at_v150(event)
    press((100., 100.))
    assert window.canvas.image_mode
    press((25., 22.))
    assert not window.canvas.image_mode
    window._rich_active = True
    press((100., 100.))
    assert not window.canvas.image_mode
    window._rich_active = False
    window._explicit_image_mode_v150(True)
    window.canvas.image_mode = True
    press((25., 22.))
    assert window.canvas.image_mode, 'Explicit image mode must still select overlapping images'
    assert modes == [True, False]


def test_side_format_applies_only_current_range(tools_window):
    window = tools_window
    editor = window.canvas.editor
    font = Path(__file__).resolve().parents[1] / 'assets/fonts/LiberationSans-Regular.ttf'
    entry = {'name': 'LiberationSans', 'family': 'Liberation Sans', 'variant': 'Regular',
             'path': str(font), 'editable': True, 'bold': False, 'italic': False}
    style = {'font_name': 'LiberationSans', 'font_xref': 7, 'font_resource': 'F1',
             'size': 12., 'color': (0., 0., 0.), 'opacity': 1., 'char_spacing': 0., 'underline': False}
    editor.load_payload({'page': 0, 'ids': list(range(7)), 'rect': (10., 10., 180., 60.),
                         'runs': [{'text': 'UNO DOS', **style}], 'revision': 'ui-test',
                         'font_previews': [{'font_xref': 7, **entry}], 'catalog': [entry]}, zoom=1.)
    window._rich_active = True
    cursor = editor.textCursor()
    cursor.setPosition(4)
    cursor.setPosition(7, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)
    window._sync_format_v150()
    assert window.side_format_controls.isEnabled()
    assert window.side_size.value() == 12.
    window.side_size.setValue(18.)
    runs = editor.payload()['runs']
    assert ''.join(run['text'] for run in runs) == 'UNO DOS'
    assert runs[0]['size'] == 12.
    assert runs[-1]['size'] == 18.
    window._rich_active = False
    window._sync_format_v150()
    assert not window.side_format_controls.isEnabled()


def test_image_quick_tools_preserve_crop_and_other_transform_properties(tools_window, monkeypatch):
    window = tools_window
    _canvas_document(window)
    item = window.canvas.images[0]
    item['image_operation'] = {'crop': (.1, .2, .9, .8), 'rotation': 17., 'fit_mode': 'fill',
                               'flip_horizontal': False, 'flip_vertical': True}
    window.canvas.image_id = item['id']
    window.canvas.image_mode = True
    window.state = {'page_capabilities': {}}
    window._refresh_tools_v150()
    assert window.image_quick_controls.isVisible()
    assert not window.side_format_controls.isVisible()
    calls = []
    monkeypatch.setattr(window, '_submit', lambda command, payload, callback:calls.append((command, payload)))
    window._quick_image_v150('right')
    assert calls[-1][0] == 'image'
    assert calls[-1][1]['rotation'] == 107.
    assert calls[-1][1]['crop'] == (.1, .2, .9, .8)
    assert calls[-1][1]['flip_vertical'] is True
    window._quick_image_v150('flip_horizontal')
    assert calls[-1][1]['flip_horizontal'] is True
    assert calls[-1][1]['rotation'] == 17.
    assert item['image_operation']['flip_horizontal'] is False
