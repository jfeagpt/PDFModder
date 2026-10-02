"""Visible-signature controls, geometry and asynchronous preview/cancellation."""
import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from pdfmodder.signing_ui import SignatureDialog


CERTIFICATE = {'subject': 'CN=Persona de prueba', 'issuer': 'CN=Emisor de prueba',
               'thumbprint': 'A' * 40, 'store': 'CurrentUser', 'not_after': '2030-01-01'}
PAGES = [{'page': 0, 'width': 595., 'height': 842.}, {'page': 1, 'width': 842., 'height': 595.}]


def dialog(qtbot, **kwargs):
    window = SignatureDialog(certificates=[CERTIFICATE], pages=PAGES, **kwargs)
    qtbot.addWidget(window)
    window.show()
    return window


def png():
    image = QImage(120, 170, QImage.Format_RGB32)
    image.fill(0xffffffff)
    output = QBuffer()
    output.open(QIODevice.WriteOnly)
    assert image.save(output, 'PNG')
    return bytes(output.data())


def test_default_invisible_and_current_displayed_page_geometry(qtbot):
    window = dialog(qtbot, current_page=1)
    assert window.source.currentData() == 'windows'
    assert window.appearance() is None and not window.appearance_options.isVisible()
    window.visible_signature.setChecked(True)
    value = window.appearance()
    assert value['page'] == 1
    assert value['rect'][2] == pytest.approx(842 - 12 * 72 / 25.4, abs=.03)
    assert value['rect'][3] == pytest.approx(595 - 12 * 72 / 25.4, abs=.03)
    window.signature_x.setValue(10.)
    window.signature_y.setValue(20.)
    window.signature_width.setValue(100.)
    window.signature_height.setValue(40.)
    assert window.appearance()['rect'] == pytest.approx([v * 72 / 25.4 for v in (10, 20, 110, 60)])
    window.signature_page.setCurrentIndex(0)
    assert window.appearance()['page'] == 0


def test_preview_matches_options_and_stale_result_is_discarded(qtbot):
    window = dialog(qtbot)
    window.visible_signature.setChecked(True)
    requests = []
    window.preview_requested.connect(lambda payload, revision: requests.append((payload, revision)))
    window.preview_button.click()
    assert len(requests) == 1
    payload, revision = requests[0]
    assert payload['certificate_thumbprint'] == CERTIFICATE['thumbprint']
    assert payload['visible_signature'] == window.appearance()
    assert not window.buttons.button(QDialogButtonBox.Ok).isEnabled()
    window.reason.setText('Nuevo motivo')
    result = {'png': png(), 'appearance_png': png(), 'preview_only': True}
    window.receive_preview(result, revision)
    assert window._preview_result is None and 'cambiaron' in window.message.text()
    window.preview_button.click()
    window.receive_preview(result, requests[-1][1])
    assert window._preview_result is result and not window.preview_label.pixmap().isNull()
    assert window.buttons.button(QDialogButtonBox.Ok).isEnabled()
    window.signature_x.setValue(window.signature_x.value() + 1)
    assert window._preview_result is None and window.preview_label.pixmap().isNull()


def test_bounds_error_and_preview_failure_do_not_accept_or_lose_settings(qtbot):
    window = dialog(qtbot)
    window.visible_signature.setChecked(True)
    window.signature_x.setValue(200.)
    window.accept()
    assert window.result() != QDialog.Accepted and 'borde' in window.message.text()
    window.signature_x.setValue(10.)
    window.preview_button.click()
    assert window._preview_pending
    window.preview_failed('Certificado no disponible')
    assert window.signature_x.value() == 10. and window.visible_signature.isChecked()
    assert not window._preview_pending and window.preview_button.isEnabled()
    assert window.message.text() == 'Certificado no disponible'
    window.signature_width.setValue(40.)
    with pytest.raises(ValueError, match='al menos'):
        window.appearance()


def test_cancel_during_preview_and_optional_pfx_path(qtbot):
    window = dialog(qtbot)
    window.source.setCurrentIndex(window.source.findData('pfx'))
    window.certificate.setText('synthetic-only.p12')
    window.password.setText('synthetic-password')
    window.visible_signature.setChecked(True)
    assert window.signing_options()['certificate_path'] == 'synthetic-only.p12'
    window.preview_button.click()
    revision = window._preview_revision
    window.reject()
    window.receive_preview({'png': png()}, revision)
    assert window.result() == QDialog.Rejected and window._preview_result is None
    window.source.setCurrentIndex(window.source.findData('windows'))
    assert window.password.text() == ''


def test_tagged_restriction_keeps_invisible_signing_available(qtbot):
    window = dialog(qtbot, visible_signature_error='PDF etiquetado: firma sin sello visible disponible.')
    assert not window.visible_signature.isEnabled()
    assert window.signing_options()['visible_signature'] is None
    assert window.buttons.button(QDialogButtonBox.Ok).isEnabled()
    window.accept()
    assert window.result() == QDialog.Accepted
