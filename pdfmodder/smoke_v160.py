"""One frozen regression journey plus the new local signing/export path.

An ephemeral, self-signed test identity is generated only under --smoke-v160.
No personal certificate is inspected and no key is retained in the delivery.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog
from .smoke import VerticalSmoke, _digest


def test_certificate(folder):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PDF Modder TEST ONLY')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True,
             key_encipherment=False, data_encipherment=False, key_agreement=False,
             key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256()))
    password = 'synthetic-smoke-password'
    path = Path(folder) / 'synthetic-only.p12'
    path.write_bytes(pkcs12.serialize_key_and_certificates(b'TEST ONLY', key, certificate,
        None, serialization.BestAvailableEncryption(password.encode())))
    return path, password


class SmokeV160(VerticalSmoke):
    def __init__(self, window, source, report_path):
        super().__init__(window, source, report_path)
        self.timeout.start(120000)
        self.signature_started = False
        self.signature_verified = False
        self.secret_dir = None
        self.signature_dialog_timer = None
        self.saved_picker = None
        self.signed_output = self.report_path.parent / 'smoke-v160-firmado.pdf'
        self._require(self.signed_output.resolve() != self.source, 'La prueba no puede sobrescribir el original.')

    def _advance(self, command, result):
        if self.stage == 'opening' and command == 'page':
            w = self.window
            self._require(not w.highlight_action.isChecked() and not w.canvas.highlight_changes,
                          'El resaltado debe comenzar desactivado.')
            self._require(all(not s.header.isChecked() for s in
                (w.content_tools_section,w.format_tools_section,w.page_tools_section)),
                'Los tres paneles deben comenzar plegados.')
            self._require(w.zoom_in_action.isEnabled() and w.zoom_out_action.isEnabled(),
                          'Faltan las acciones de zoom directo.')
            self._require(w.sign_action.isEnabled(), 'La acción Firmar debe estar disponible.')
            self._step('defaults_and_signing_action')
        if self.stage == 'signing' and command == 'sign_pdf':
            self._restore_picker()
            proof = result['signature']
            self._require(proof['cryptographic_integrity'] and proof['covers_entire_file'],
                          'Firma inválida o cobertura incompleta.')
            self._require(not proof['trust_verified'] and not proof['trusted_timestamp'],
                          'No se debe atribuir confianza a la identidad sintética.')
            self._require(_digest(self.signed_output.read_bytes()) == proof['signed_sha256'],
                          'El archivo guardado no coincide con los bytes firmados.')
            self.edit_reports.append(proof)
            self._step('signed_copy_verified_offline')
            self.stage = 'reopen_signed'
            QTimer.singleShot(0, lambda:self.window.open_document(self.signed_output))
            return
        if self.stage == 'reopen_signed':
            if command == 'page':
                self._require('11/09/2026' in self._text(self.window.model),
                              'El texto editado no aparece al reabrir la copia firmada.')
                self._require(bool(self.window.state['issues']) and not self.window.save_action.isEnabled(),
                              'La copia firmada debe protegerse frente a la edición ordinaria.')
                self._step('reopened_signature_protected_original_unchanged')
                self.signature_verified = True
                self.output = self.signed_output
                self.stage = 'complete'
                self.finish()
            return
        super()._advance(command, result)

    def _begin_signature(self):
        try:
            self.secret_dir = tempfile.TemporaryDirectory(prefix='smoke-sign-', dir=self.report_path.parent)
            path, password = test_certificate(self.secret_dir.name)
            self.stage = 'signing'
            from .signing_ui import SignatureDialog
            timer = QTimer(self)
            self.signature_dialog_timer = timer
            def fill_dialog():
                dialog = QApplication.activeModalWidget()
                if isinstance(dialog, SignatureDialog):
                    timer.stop()
                    index = dialog.source.findData('pfx')
                    if index < 0:
                        dialog.reject()
                        self.fail('No existe la vía de certificado sintético PFX para la prueba.')
                        return
                    dialog.source.setCurrentIndex(index)
                    dialog.certificate.setText(str(path))
                    dialog.password.setText(password)
                    dialog.reason.setText('Prueba automática; certificado sin identidad verificada')
                    self._step('signature_dialog_test_pfx_selected')
                    dialog.accept()
            timer.timeout.connect(fill_dialog)
            self.saved_picker = QFileDialog.getSaveFileName
            QFileDialog.getSaveFileName = staticmethod(lambda *a, **k:(str(self.signed_output), 'Documento PDF (*.pdf)'))
            timer.start(20)
            self.window.sign_action.trigger()
            self._require(self.window.busy and self.window._command == 'list_signing_certificates',
                          'El botón Firmar no solicitó los certificados al proceso PDF.')
            self._step('signature_action_lists_windows_certificates')
        except Exception as exc:
            self.fail(str(exc))

    def _restore_picker(self):
        if self.signature_dialog_timer:
            self.signature_dialog_timer.stop()
        if self.saved_picker:
            QFileDialog.getSaveFileName = self.saved_picker
            self.saved_picker = None

    def fail(self, error):
        # Opening the signed copy intentionally announces its read-only guard.
        # Accept only that exact, expected notice; render/worker errors still fail.
        issues = self.window.state.get('issues', [])
        if (self.stage == 'reopen_signed' and issues and str(error) == '\n'.join(issues)
                and any('firma digital' in issue or 'firmas digitales' in issue for issue in issues)):
            self._step('signed_document_read_only_notice')
            return
        super().fail(error)

    def finish(self, error=None, terminate=False):
        if error is None and self.stage == 'complete' and not self.signature_started:
            self.signature_started = True
            self.stage = 'preparing_signature'
            QTimer.singleShot(0, self._begin_signature)
            return
        if self.secret_dir:
            self.secret_dir.cleanup()
            self.secret_dir = None
        self._restore_picker()
        super().finish(error=error, terminate=terminate)
