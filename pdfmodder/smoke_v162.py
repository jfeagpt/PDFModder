"""Real mouse drag on the PDF, then preview, sign, save and reopen the widget."""
import tempfile

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog

from .smoke_v160 import test_certificate
from .smoke_v161 import SmokeV161


class SmokeV162(SmokeV161):
    def _begin_signature(self):
        try:
            self.secret_dir = tempfile.TemporaryDirectory(prefix='smoke-draw-sign-', dir=self.report_path.parent)
            path, password = test_certificate(self.secret_dir.name)
            self.stage = 'preparing_visible_signature'
            self.before_signature_state = dict(self.window.state)
            from .signing_ui import SignatureDialog
            timer = QTimer(self)
            self.signature_dialog_timer = timer

            def interact():
                if self.finished:
                    timer.stop()
                    return
                dialog = QApplication.activeModalWidget()
                try:
                    if self.stage == 'preparing_visible_signature' and isinstance(dialog, SignatureDialog):
                        self.signature_dialog = dialog
                        dialog.source.setCurrentIndex(dialog.source.findData('pfx'))
                        dialog.certificate.setText(str(path))
                        dialog.password.setText(password)
                        dialog.reason.setText('Prueba de selección mediante arrastre; certificado sintético')
                        dialog.visible_signature.setChecked(True)
                        self.stage = 'drawing_signature_rectangle'
                        dialog.draw_button.click()
                    elif self.stage == 'drawing_signature_rectangle' and getattr(self.window.canvas, 'signature_rectangle_mode', False):
                        canvas = self.window.canvas
                        # Choose a fit-like zoom before the drag so both corners
                        # are visible; it remains an actual rendered PDF page.
                        scene = canvas.scene()
                        canvas.ensureVisible(scene.sceneRect(), 0, 0)
                        start = canvas.mapFromScene(QPointF(56.7*canvas.zoom, 624.*canvas.zoom))
                        end = canvas.mapFromScene(QPointF(510.2*canvas.zoom, 779.5*canvas.zoom))
                        self._require(canvas.viewport().rect().contains(start) and canvas.viewport().rect().contains(end),
                                      'Los extremos del recuadro deben verse para realizar el arrastre.')
                        selected = []
                        canvas.signature_rectangle_selected.connect(selected.append)
                        def send(kind, position, button, buttons):
                            event = QMouseEvent(kind, QPointF(position),
                                QPointF(canvas.viewport().mapToGlobal(position)), button, buttons, Qt.NoModifier)
                            QApplication.sendEvent(canvas.viewport(), event)
                        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
                        send(QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton)
                        self._require(self.window.grab().save(str(self.report_path.parent/'smoke-v162-drawing.png')),
                                      'No se pudo registrar el recuadro dibujado.')
                        self.stage = 'rectangle_drawn'
                        send(QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton)
                        canvas.signature_rectangle_selected.disconnect(selected.append)
                        self._require(len(selected) == 1, 'El gesto debe seleccionar un único recuadro.')
                        # The dialog rounds numeric controls to 0.01 mm. Use its
                        # committed values as the same export/preview contract.
                        self.signature_rect = self.signature_dialog.appearance()['rect']
                        self._step('signature_rectangle_drawn_on_document', rect=self.signature_rect,
                                   page=self.window.page_number, zoom=canvas.zoom)
                    elif self.stage == 'rectangle_drawn' and dialog is self.signature_dialog:
                        timer.stop()
                        self._require(dialog.password.text() == password,
                                      'La selección del área ha perdido las credenciales del diálogo.')
                        self._require(not getattr(self.window, '_signature_placement_dialog', None),
                                      'La aplicación debe abandonar el modo de dibujo al soltar.')
                        self._require(self.window.toolbar.isEnabled(), 'Las herramientas no se han recuperado.')
                        self.stage = 'previewing_visible_signature'
                        dialog.preview_button.click()
                        self._require(self.window.busy and self.window._command == 'signature_preview',
                                      'La selección dibujada no se ha enviado a la vista previa real.')
                except Exception as exc:
                    timer.stop()
                    if isinstance(dialog, SignatureDialog):
                        dialog.reject()
                    self.fail(str(exc))

            timer.timeout.connect(interact)
            self.saved_picker = QFileDialog.getSaveFileName
            QFileDialog.getSaveFileName = staticmethod(lambda *a, **k:(str(self.signed_output), 'Documento PDF (*.pdf)'))
            timer.start(20)
            self.window.sign_action.trigger()
            self._step('signature_action_lists_windows_certificates')
        except Exception as exc:
            self.fail(str(exc))
