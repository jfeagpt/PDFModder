"""Visible semantic choices plus Qt/worker/save/reopen for tagged insertion."""
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from pdfmodder.accessibility_ui import AccessibilityDialog
from pdfmodder.dialogs import TextDialog
from pdfmodder.tagged import TaggedStructure
from tagged_corpus import make_tagged_pdf, audit_tagged
from test_ui import editor, settled


def test_explicit_order_description_or_decorative(qtbot):
    dialog = AccessibilityDialog(image=True)
    qtbot.addWidget(dialog)
    accept = dialog.buttons.button(QDialogButtonBox.Ok)
    assert not accept.isEnabled()
    dialog.order.setCurrentIndex(2)
    assert not accept.isEnabled()
    dialog.alt.setText('Mapa de cultivos')
    assert accept.isEnabled()
    assert dialog.values() == {'accessibility_order': 'page_end',
                               'alt_text': 'Mapa de cultivos', 'decorative': False}
    dialog.decorative.setChecked(True)
    assert not dialog.alt.isEnabled() and not dialog.order.isEnabled()
    assert dialog.values() == {'accessibility_order': None, 'alt_text': None, 'decorative': True}
    dialog.decorative.setChecked(False)
    dialog.alt.clear()
    assert not accept.isEnabled()


def test_tagged_ui_add_cancel_commit_undo_reopen(qtbot, editor, tmp_path):
    window = editor
    original = make_tagged_pdf(include_objr=True)
    source = tmp_path / 'tagged.pdf'
    source.write_bytes(original)
    window.open_document(source)
    settled(qtbot, window)
    assert window.add_text_action.isEnabled() and window.add_image_action.isEnabled()
    seen, errors = [], []
    mode = {'value': 'cancel'}
    timer = QTimer(window)
    def answer():
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            return
        try:
            if isinstance(dialog, TextDialog):
                dialog.content.setPlainText('Texto añadido accesible')
                dialog.width_box.setValue(90)
                dialog.height_box.setValue(12)
                seen.append('text')
                qtbot.mouseClick(dialog.preview_button, Qt.LeftButton)
            elif isinstance(dialog, AccessibilityDialog):
                seen.append('accessibility')
                if mode['value'] == 'cancel':
                    dialog.reject()
                else:
                    dialog.order.setCurrentIndex(2)
                    if dialog.is_image:
                        dialog.alt.setText('Ilustración azul añadida')
                    qtbot.mouseClick(dialog.buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
        except Exception as exc:
            errors.append(exc)
            dialog.reject()
    timer.timeout.connect(answer)
    timer.start(20)
    try:
        window.add_text_action.trigger()
        assert window._placement == 'text'
        window.placed(48, 350)
        qtbot.waitUntil(lambda: len(seen) >= 2, timeout=30000)
        settled(qtbot, window)
        assert not errors
        assert window.state['history_index'] == 0 and not window.state['preview']
        mode['value'] = 'accept'
        seen.clear()
        window.add_text_action.trigger()
        window.placed(48, 350)
        qtbot.waitUntil(lambda: len(seen) >= 2, timeout=30000)
        settled(qtbot, window)
        assert not errors and window.state['preview']
        qtbot.mouseClick(window.commit_button, Qt.LeftButton)
        settled(qtbot, window)
        assert window.state['history_index'] == 1
        png = BytesIO()
        Image.new('RGB', (20, 20), '#2266aa').save(png, format='PNG')
        window.add_image(png.getvalue(), (170, 210, 210, 250))
        settled(qtbot, window)
        assert not errors and window.state['preview']
        qtbot.mouseClick(window.commit_button, Qt.LeftButton)
        settled(qtbot, window)
        assert window.state['history_index'] == 2
        window.undo_action.trigger()
        settled(qtbot, window)
        assert window.state['history_index'] == 1
        window.redo_action.trigger()
        settled(qtbot, window)
        output = tmp_path / 'saved.pdf'
        window.save_as(output)
        settled(qtbot, window)
        TaggedStructure(output.read_bytes())
        before, after = audit_tagged(original), audit_tagged(output.read_bytes())
        assert 'Texto añadido accesible' in after['reading_order']
        assert 'Ilustración azul añadida' in after['reading_order']
        assert len(after['objrs']) == len(before['objrs'])
        window.open_document(output)
        settled(qtbot, window)
        assert window.state['tagged'] and not window.state['issues']
        assert source.read_bytes() == original
    finally:
        timer.stop()
