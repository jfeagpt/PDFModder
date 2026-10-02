"""Select another page, cancel the drag and recover the original signing dialog."""
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pdfmodder.signing_ui import SignatureDialog
from test_signature_ui import CERTIFICATE
from test_ui import editor, settled


def test_rectangle_on_another_page_cancel_restores_dialog_and_document(qtbot, editor):
    window = editor
    window.open_document(Path(__file__).resolve().parents[1] / 'examples/digital.pdf')
    settled(qtbot, window)
    before = dict(window.state)
    mode, errors, original_rect = {'value': 'initial'}, [], []
    timer = QTimer(window)
    timer.setInterval(20)
    def answer():
        active = QApplication.activeModalWidget()
        try:
            if mode['value'] == 'initial' and isinstance(active, SignatureDialog):
                active.source.setCurrentIndex(active.source.findData('pfx'))
                active.certificate.setText('synthetic-only.p12')
                active.password.setText('synthetic-secret')
                active.visible_signature.setChecked(True)
                active.signature_page.setCurrentIndex(1)
                original_rect.append(active.appearance())
                mode['value'] = 'drawing'
                active.draw_button.click()
            elif mode['value'] == 'drawing' and window.canvas.signature_rectangle_mode:
                assert window.page_number == 1 and not window.toolbar.isEnabled()
                assert not window.save_action.isEnabled()
                mode['value'] = 'returning'
                window.cancel()
            elif mode['value'] == 'returning' and isinstance(active, SignatureDialog):
                assert active.appearance() == original_rect[0]
                assert active.password.text() == 'synthetic-secret'
                assert active.certificate.text() == 'synthetic-only.p12'
                assert window.toolbar.isEnabled() and window.tools_scroll.isEnabled()
                assert not window.canvas.signature_rectangle_mode
                active.reject()
                timer.stop()
                mode['value'] = 'complete'
        except Exception as exc:
            errors.append(exc)
            timer.stop()
            if isinstance(active, SignatureDialog):
                active.reject()
            mode['value'] = 'complete'
    timer.timeout.connect(answer)
    timer.start()
    try:
        window._choose_signature_certificate({'certificates':[CERTIFICATE], 'pages':[
            {'page':0, 'width':595., 'height':842.}, {'page':1, 'width':595., 'height':842.}]})
        qtbot.waitUntil(lambda: mode['value'] == 'complete', timeout=20000)
        settled(qtbot, window)
        assert not errors
        assert window.state == before
        assert getattr(window, '_signature_placement_dialog', None) is None
        assert window._placement is None and not window.canvas.signature_rectangle_mode
        assert window.sign_action.isEnabled()
    finally:
        timer.stop()
