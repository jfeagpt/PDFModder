"""Recorrido del binario: leer/copiar, rueda, herramientas y edición real."""
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from .smoke_v170 import SmokeV170


class SmokeV171(SmokeV170):
    def _wheel(self, direction):
        canvas = self.window.canvas
        bar = canvas.verticalScrollBar()
        bar.setValue(bar.maximum() if direction > 0 else bar.minimum())
        position = canvas.viewport().rect().center()
        event = QWheelEvent(QPointF(position), QPointF(canvas.viewport().mapToGlobal(position)),
                            QPoint(), QPoint(0, -120 if direction > 0 else 120), Qt.NoButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(canvas.viewport(), event)

    def _advance(self, command, result):
        page = command == 'page' and result.get('model') is not None
        if self.stage == 'opening' and page and result['number'] == 0 and not getattr(self, '_reader_tested', False):
            self._require(self.window.application_mode == 'reading' and not self.window.tools_action.isChecked(), 'No inicia en Lectura')
            self._require(result['fonts'] == [] and result['images'] == [] and self.window.state['validation_pending'], 'No usa carga ligera')
            self._select('10/09/2026')
            self.window.clipboard_copy_v170()
            self._require(QApplication.clipboard().text() == '10/09/2026', 'No copia texto en Lectura')
            self._require(not self.window.canvas.editor.isVisible() and self.window.state['history_index'] == 0, 'Leer activó edición')
            self._step('reading_startup_select_copy_no_edit')
            self.stage = 'v171_wheel_next'
            self._wheel(1)
            return
        if self.stage == 'v171_wheel_next' and page:
            self._require(result['number'] == 1 and self.window.page_number == 1, 'La rueda no avanzó de página')
            self._step('wheel_next_page')
            self.stage = 'v171_wheel_previous'
            self._wheel(-1)
            return
        if self.stage == 'v171_wheel_previous' and page:
            self._require(result['number'] == 0 and self.window.page_number == 0, 'La rueda no retrocedió de página')
            self._step('wheel_previous_page')
            self._reader_tested = True
            self.stage = 'opening'
        if self.stage in ('opening', 'reopened') and page and self.window.application_mode == 'reading':
            self.window.tools_action.setChecked(True)
            return
        if command == 'prepare_editing':
            self._require(self.window.application_mode == 'editing' and self.window.state['editing_prepared'], 'Herramientas no preparó edición')
            self._step('tools_prepare_editing', stage=self.stage)
            command = 'page'
        super()._advance(command, result)
