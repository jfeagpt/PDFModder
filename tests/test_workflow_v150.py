"""Real Qt tools -> serial PDF worker -> exported files, with synthetic inputs."""
from hashlib import sha256
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QFormLayout, QLineEdit, QToolButton

from pdfmodder.app import MainWindow
from pdfmodder.model import union
from test_ui import settled, ready_editor

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workflow(qtbot, tmp_path):
    picture = tmp_path / 'photo.png'
    image = Image.new('RGB', (120, 80), '#df9d37')
    for x in range(60):
        for y in range(80):
            image.putpixel((x, y), (45, 116, 172))
    image.save(picture)
    source = tmp_path / 'document.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=480, height=640)
        page.insert_font(fontname='Original', fontfile=str(ROOT / 'assets/fonts/LiberationSans-Regular.ttf'))
        page.insert_text((40, 65), 'Fecha 2025', fontname='Original', fontsize=14)
        page.insert_text((40, 145), 'Importe 100,00 EUR', fontname='Original', fontsize=12)
        page.insert_image((300, 40, 420, 120), filename=str(picture))
        for index in (2, 3):
            page = doc.new_page(width=480, height=640)
            page.insert_text((40, 65), f'PAGE {index} ORIGINAL', fontsize=14)
        doc.save(source)
    replacement = tmp_path / 'replacement.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=480, height=640)
        page.insert_text((40, 65), 'REPLACED PAGE', fontsize=14)
        doc.save(replacement)
    (tmp_path / 'history').mkdir()
    window = MainWindow(config_path=tmp_path / 'fonts.json', history_dir=tmp_path / 'history')
    window.resize(1366, 768)
    window.thumbnail_timer.stop()
    qtbot.addWidget(window, before_close_func=lambda w:setattr(w, '_allow_close', True))
    window.show()
    window.open_document(source)
    settled(qtbot, window)
    window.fit_page(False)
    settled(qtbot, window)
    yield window, source, picture, replacement
    window._allow_close = True
    window.close()


def click_tool(qtbot, window, name):
    button = window.findChild(QToolButton, name)
    assert button is not None and button.isEnabled(), name
    window.tools_scroll.ensureWidgetVisible(button)
    qtbot.mouseClick(button, Qt.LeftButton)


def page_click(qtbot, window, point, double=False):
    window.canvas.ensureVisible(window.canvas.scene_rect((point[0]-5, point[1]-5, point[0]+5, point[1]+5)), 20, 20)
    pixel = window.canvas.viewport_point(point)
    assert window.canvas.viewport().rect().contains(pixel)
    (qtbot.mouseDClick if double else qtbot.mouseClick)(window.canvas.viewport(), Qt.LeftButton, pos=pixel)
    return pixel


def text_point(window, text):
    chars = window.model.glyphs
    joined = ''.join(g.text for g in chars)
    start = joined.index(text)
    rect = union(g.bbox for g in chars[start:start + len(text)])
    return ((rect[0]+rect[2])/2, (rect[1]+rect[3])/2)


def dialog_field(dialog, text):
    for form in dialog.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.LabelRole)
            if item and item.widget() and item.widget().text() == text:
                return form.itemAt(row, QFormLayout.FieldRole).widget()
    raise AssertionError(f'No field {text!r} in {dialog.windowTitle()}')


def modal_tool(qtbot, window, name, title, configure):
    seen, errors = [], []
    timer = QTimer(window)
    def answer():
        dialog = QApplication.activeModalWidget()
        if dialog is None or title not in dialog.windowTitle():
            return
        timer.stop()
        try:
            configure(dialog)
            seen.append(dialog.windowTitle())
            buttons = dialog.findChild(QDialogButtonBox)
            qtbot.mouseClick(buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
        except Exception as exc:
            errors.append(exc)
            dialog.reject()
    timer.timeout.connect(answer)
    timer.start(10)
    try:
        click_tool(qtbot, window, name)
        qtbot.waitUntil(lambda:bool(seen or errors), timeout=30000)
    finally:
        timer.stop()
    assert not errors, errors
    assert seen, f'No dialog from {name}'
    settled(qtbot, window)


def test_tools_text_image_save_and_reopen_real_worker(qtbot, workflow, tmp_path, monkeypatch):
    window, source, picture, _ = workflow
    original = sha256(source.read_bytes()).hexdigest()
    qtbot.mouseClick(window.tools_toggle_button, Qt.LeftButton)
    assert not window.tools_scroll.isVisible()
    qtbot.mouseClick(window.tools_toggle_button, Qt.LeftButton)
    assert window.tools_scroll.isVisible()
    assert window.width() == 1366 and window.height() == 768
    assert window.canvas.viewport().width() >= 700

    click_tool(qtbot, window, 'toolEditContent')
    page_click(qtbot, window, (360., 80.))
    assert window.canvas.image_mode and window.canvas.selected_image()
    assert window.image_quick_controls.isVisible()
    assert not window.side_format_controls.isVisible()
    point = text_point(window, '2025')
    page_click(qtbot, window, point)
    assert not window.canvas.image_mode and window.model.text(window.canvas.ids) == '2025'
    page_click(qtbot, window, point, double=True)
    ready_editor(qtbot, window)
    assert window.canvas.editor.toolbar.accept.isVisible()
    assert window.canvas.editor.toolbar.cancel.isVisible()
    assert window.side_format_controls.isEnabled()
    qtbot.keyClick(window.canvas.editor, Qt.Key_A, modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor, '2026')
    qtbot.mouseClick(window.canvas.editor.toolbar.accept, Qt.LeftButton)
    settled(qtbot, window)
    assert window.state['history_index'] == 1
    assert '2026' in ''.join(g.text for g in window.model.glyphs)

    window.interaction_box.setCurrentIndex(window.interaction_box.findData('move'))
    point = text_point(window, '2026')
    start = page_click(qtbot, window, point)
    selected = window.model.selected(window.canvas.ids)
    original_origin = selected[0].origin
    finish = window.canvas.viewport_point((point[0]+35, point[1]+25))
    qtbot.mousePress(window.canvas.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(window.canvas.viewport(), pos=finish)
    qtbot.mouseRelease(window.canvas.viewport(), Qt.LeftButton, pos=finish)
    settled(qtbot, window)
    assert window.state['history_index'] == 2
    moved = [g for g in window.model.glyphs if g.text == '2' and g.origin[1] > original_origin[1]+20]
    assert moved

    click_tool(qtbot, window, 'toolAddText')
    page_click(qtbot, window, (40., 180.))
    ready_editor(qtbot, window)
    qtbot.keyClicks(window.canvas.editor, 'BORRADOR CANCELADO')
    qtbot.mouseClick(window.canvas.editor.toolbar.cancel, Qt.LeftButton)
    settled(qtbot, window)
    assert window.state['history_index'] == 2
    assert 'BORRADOR' not in ''.join(g.text for g in window.model.glyphs)
    click_tool(qtbot, window, 'toolAddText')
    page_click(qtbot, window, (40., 180.))
    ready_editor(qtbot, window)
    assert window.canvas.editor.rich_mode
    assert window.canvas.editor.current_style()['font_name'] == 'LiberationSans'
    qtbot.keyClicks(window.canvas.editor, 'Nota nueva')
    qtbot.keyClick(window.canvas.editor, Qt.Key_Return)
    qtbot.keyClicks(window.canvas.editor, 'Segunda linea')
    qtbot.keyClick(window.canvas.editor, Qt.Key_Return, modifier=Qt.ShiftModifier)
    qtbot.keyClicks(window.canvas.editor, 'Salto suave')
    qtbot.mouseClick(window.canvas.editor.toolbar.accept, Qt.LeftButton)
    settled(qtbot, window)
    assert 'Nota nueva' in ''.join(g.text for g in window.model.glyphs)
    assert 'Segunda linea' in ''.join(g.text for g in window.model.glyphs)
    assert 'Salto suave' in ''.join(g.text for g in window.model.glyphs)

    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_args, **_kwargs:(str(picture), 'PNG'))
    click_tool(qtbot, window, 'toolAddImage')
    page_click(qtbot, window, (70., 250.))
    settled(qtbot, window)
    assert window.state['preview'] and window.apply_step_button.isVisible()
    qtbot.mouseClick(window.apply_step_button, Qt.LeftButton)
    settled(qtbot, window)
    assert len(window.canvas.images) == 2
    added = max(window.canvas.images, key=lambda item:item['rect'][1])
    rect = added['rect']
    page_click(qtbot, window, ((rect[0]+rect[2])/2, (rect[1]+rect[3])/2))
    window.tools_scroll.ensureWidgetVisible(window.image_quick_controls)
    click_tool(qtbot, window, 'quickImage_flip_horizontal')
    settled(qtbot, window)
    assert window.state['preview']
    qtbot.mouseClick(window.apply_step_button, Qt.LeftButton)
    settled(qtbot, window)
    click_tool(qtbot, window, 'quickImage_right')
    settled(qtbot, window)
    assert window.state['preview']
    qtbot.mouseClick(window.apply_step_button, Qt.LeftButton)
    settled(qtbot, window)

    output = tmp_path / 'edited-v150.pdf'
    window.save_as(output)
    settled(qtbot, window)
    independent = PdfReader(output)
    assert len(independent.pages) == 3
    assert '2026' in independent.pages[0].extract_text()
    assert '2025' not in independent.pages[0].extract_text()
    assert 'Nota nueva' in independent.pages[0].extract_text()
    assert 'Segunda linea' in independent.pages[0].extract_text()
    assert 'PAGE 2 ORIGINAL' in independent.pages[1].extract_text()
    with fitz.open(source) as before, fitz.open(output) as after:
        assert len(after[0].get_image_info()) == 2
        transformed = max(after[0].get_image_info(), key=lambda item:item['bbox'][1])
        assert abs(transformed['transform'][1]) > 10 and abs(transformed['transform'][2]) > 10
        from pdfmodder.media import image_items
        frame = max(image_items(after, 0), key=lambda item:item['rect'][1])['rect']
        assert tuple(frame) == pytest.approx(tuple(rect), abs=.05)
        pix = after[0].get_pixmap(clip=fitz.Rect(rect), alpha=False)
        pixels = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        upper = pixels.getpixel((pix.width//2, pix.height//4))
        lower = pixels.getpixel((pix.width//2, 3*pix.height//4))
        assert upper == (223, 157, 55) and lower == (45, 116, 172)
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before[2].get_pixmap().samples == after[2].get_pixmap().samples
    assert sha256(source.read_bytes()).hexdigest() == original
    window.open_document(output)
    settled(qtbot, window)
    assert '2026' in ''.join(g.text for g in window.model.glyphs)
    window.tools_scroll.verticalScrollBar().setValue(0)
    window.grab().save(str(ROOT / 'tmp/v150-ui-private.png'))


def test_tools_pages_preview_cancel_commit_export_split(qtbot, workflow, tmp_path, monkeypatch):
    window, source, _, replacement = workflow
    original = sha256(source.read_bytes()).hexdigest()
    def crop(dialog):
        dialog_field(dialog, 'Páginas').setText('1')
        dialog_field(dialog, 'Izquierda').setValue(5.)
    modal_tool(qtbot, window, 'toolCropPages', 'Recortar páginas', crop)
    assert window.state['preview']
    assert window.model.cropbox[0] == pytest.approx(5*72/25.4, abs=.02)
    qtbot.mouseClick(window.cancel_step_button, Qt.LeftButton)
    settled(qtbot, window)
    assert window.model.cropbox[0] == 0
    modal_tool(qtbot, window, 'toolCropPages', 'Recortar páginas', crop)
    qtbot.mouseClick(window.apply_step_button, Qt.LeftButton)
    settled(qtbot, window)
    assert window.state['history_index'] == 1

    def replace(dialog):
        dialog_field(dialog, 'Páginas del documento actual').setText('2')
        dialog.findChild(QLineEdit, 'replacementPdfPath').setText(str(replacement))
        dialog_field(dialog, 'Páginas del archivo elegido').setText('1')
    modal_tool(qtbot, window, 'toolReplacePages', 'Reemplazar páginas', replace)
    assert window.state['preview']
    qtbot.mouseClick(window.cancel_step_button, Qt.LeftButton)
    settled(qtbot, window)
    assert window.state['history_index'] == 1
    modal_tool(qtbot, window, 'toolReplacePages', 'Reemplazar páginas', replace)
    qtbot.mouseClick(window.apply_step_button, Qt.LeftButton)
    settled(qtbot, window)
    assert window.state['history_index'] == 2

    exported = tmp_path / 'all-pages.txt'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_args, **_kwargs:(str(exported), 'TXT'))
    modal_tool(qtbot, window, 'toolExportDocument', 'Exportar archivo', lambda dialog:None)
    assert 'REPLACED PAGE' in exported.read_text(encoding='utf-8')
    assert 'PAGE 2 ORIGINAL' not in exported.read_text(encoding='utf-8')
    folder = tmp_path / 'split'
    folder.mkdir()
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *_args, **_kwargs:str(folder))
    modal_tool(qtbot, window, 'toolSplitDocument', 'Dividir documento', lambda dialog:None)
    files = sorted(folder.glob('*.pdf'))
    assert len(files) == 3
    assert all(len(PdfReader(path).pages) == 1 for path in files)
    assert any('REPLACED PAGE' in PdfReader(path).pages[0].extract_text() for path in files)
    output = tmp_path / 'page-operations.pdf'
    window.save_as(output)
    settled(qtbot, window)
    with fitz.open(output) as doc:
        assert doc[0].cropbox.x0 == pytest.approx(5*72/25.4, abs=.02)
        assert 'REPLACED PAGE' in doc[1].get_text()
        assert 'PAGE 3 ORIGINAL' in doc[2].get_text()
    assert sha256(source.read_bytes()).hexdigest() == original
    window.open_document(output)
    settled(qtbot, window)
    assert window.state['page_count'] == 3


def test_direct_rotate_and_insert_dialogs(qtbot, workflow, tmp_path, monkeypatch):
    window, source, _, replacement = workflow
    def rotate(dialog):
        dialog_field(dialog, 'Páginas').setText('1-3')
        dialog_field(dialog, 'Rotar').setCurrentIndex(2)
    modal_tool(qtbot, window, 'toolRotatePages', 'Rotar páginas', rotate)
    assert window.state['preview']
    qtbot.mouseClick(window.apply_step_button, Qt.LeftButton)
    settled(qtbot, window)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_args, **_kwargs:(str(replacement), 'PDF'))
    def insert(dialog):
        dialog_field(dialog, 'Páginas a insertar').setText('1')
        dialog_field(dialog, 'Página del documento actual').setValue(3)
    modal_tool(qtbot, window, 'toolInsertPages', 'Insertar páginas', insert)
    assert window.state['preview'] and window.state['page_count'] == 4
    qtbot.mouseClick(window.apply_step_button, Qt.LeftButton)
    settled(qtbot, window)
    output = tmp_path / 'rotated-inserted.pdf'
    window.save_as(output)
    settled(qtbot, window)
    with fitz.open(output) as doc:
        assert [page.rotation for page in doc] == [0, 90, 0, 0]
        assert 'REPLACED PAGE' in doc[3].get_text()
        assert 'PAGE 3 ORIGINAL' in doc[2].get_text()
    assert len(PdfReader(source).pages) == 3
