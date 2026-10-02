"""Recorrido del ejecutable: lector continuo, copia, edición y retirada de etiquetas."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys

from pypdf import PdfReader
from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from .reading_order_v180 import ordered_glyphs
from .smoke_v170 import SmokeV170


class SmokeV180(SmokeV170):
    def finish(self, error=None, terminate=False):
        if not error and self.extra_complete and self.stage == 'complete' and not getattr(self, '_untag_complete', False):
            self.stage = 'v180_final_save'
            self.window.save_as(self.report_path.parent / 'smoke-final-guardado.pdf')
            return
        super().finish(error, terminate)

    def _click_glyph(self, page, glyph, modifiers=Qt.NoModifier):
        view = self.window.reader
        rect = view._rects[page]
        position = view.mapFromScene(QPointF(
            rect.left() + (glyph.bbox[0] + glyph.bbox[2]) / 2 * view.zoom,
            rect.top() + (glyph.bbox[1] + glyph.bbox[3]) / 2 * view.zoom))
        for kind, buttons in ((QMouseEvent.MouseButtonPress, Qt.LeftButton),
                              (QMouseEvent.MouseButtonRelease, Qt.NoButton)):
            event = QMouseEvent(kind, QPointF(position),
                QPointF(view.viewport().mapToGlobal(position)), Qt.LeftButton, buttons, modifiers)
            QApplication.sendEvent(view.viewport(), event)

    def _exercise_reader(self):
        try:
            view = self.window.reader
            self._require(view.has_page(0) and view.has_page(1), 'No se precargaron las dos páginas')
            boundary = view._rects[1].top()
            bar = view.verticalScrollBar()
            bar.setValue(round(boundary - view.viewport().height() / 2))
            visible = view.mapToScene(view.viewport().rect()).boundingRect()
            self._require(visible.intersects(view._rects[0]) and visible.intersects(view._rects[1]),
                          'No aparecen simultáneamente el final y el inicio de las páginas')
            before = bar.value()
            position = view.viewport().rect().center()
            event = QWheelEvent(QPointF(position), QPointF(view.viewport().mapToGlobal(position)),
                QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            QApplication.sendEvent(view.viewport(), event)
            self._require(0 < bar.value() - before < view.viewport().height(),
                          'La rueda no desplaza continuamente el documento')
            self._require(view._rects[1].top() == boundary, 'La rueda recompuso las páginas')
            self._step('continuous_scroll_two_pages_visible')
            first = ordered_glyphs(view.model_for_page(0))[0]
            last = ordered_glyphs(view.model_for_page(1))[-1]
            view.go_page(0)
            self._click_glyph(0, first)
            view.go_page(1)
            self._click_glyph(1, last, Qt.ShiftModifier)
            endpoints = view.selection_endpoints()
            self._require(endpoints and endpoints['start']['page'] == 0 and endpoints['end']['page'] == 1,
                          'La selección no atraviesa páginas')
            self.stage = 'v180_copy'
            self.window.clipboard_copy_v170()
        except Exception as exc:
            self.fail(str(exc))

    def _advance(self, command, result):
        page = command == 'page' and result.get('model') is not None
        if self.stage == 'v180_final_save' and command == 'save':
            root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
            self._tag_source = root / 'examples/etiquetado.pdf'
            self._tag_hash = sha256(self._tag_source.read_bytes()).hexdigest()
            self.stage = 'v180_tag_open'
            self.window.open_document(self._tag_source)
            return
        if self.stage == 'v180_tag_open' and page:
            self._require(self.window.state['tagged'], 'No se detectaron las etiquetas del documento')
            self.window.tools_action.setChecked(True)
            self.stage = 'v180_tag_prepare'
            return
        if self.stage == 'v180_tag_prepare' and command == 'prepare_editing':
            self._require(self.window.remove_tags_action.isEnabled(), 'No se habilitó Quitar etiquetas')
            self.stage = 'v180_tag_preview'
            self.window._submit('remove_tags', callback=self.window._previewed)
            return
        if self.stage == 'v180_tag_preview' and page:
            self._require(self.window.state['preview'] and not self.window.state['tagged'] and
                          self.window.last_report['verified'], 'No se preparó la copia sin etiquetas')
            self.stage = 'v180_tag_commit'
            self.window.commit()
            return
        if self.stage == 'v180_tag_commit' and page:
            self._require(self.window.state['history_index'] == 1, 'Retirar etiquetas no se puede deshacer')
            self.stage = 'v180_tag_save'
            self._tag_output = self.report_path.parent / 'smoke-sin-etiquetas.pdf'
            self.window.save_as(self._tag_output)
            return
        if self.stage == 'v180_tag_save' and command == 'save':
            output = PdfReader(BytesIO(self._tag_output.read_bytes()))
            self._require('/StructTreeRoot' not in output.trailer['/Root'] and
                          sha256(self._tag_source.read_bytes()).hexdigest() == self._tag_hash,
                          'Las etiquetas siguen presentes o se alteró el original')
            self._step('remove_tags_real_preview_history_save_original_preserved')
            self._untag_complete = True
            self.stage = 'complete'
            QTimer.singleShot(0, self.finish)
            return
        if self.stage == 'opening' and page and not getattr(self, '_reader_tested', False):
            self._require(self.window.application_mode == 'reading' and
                          self.window.document_views.currentWidget() is self.window.reader,
                          'No inicia con el lector continuo')
            self._require(result['fonts'] == [] and result['images'] == [], 'No usa carga ligera')
            if self.window.reader.has_page(0) and self.window.reader.has_page(1):
                self.stage = 'v180_scroll'
                QTimer.singleShot(50, self._exercise_reader)
            return
        if self.stage == 'v180_copy' and command == 'reading_copy_range':
            self._require(QApplication.clipboard().text() == result['text'] and
                          result['text'].count('10/09/2026') == 2 and '\n\n' in result['text'],
                          'La copia perdió párrafos o una página')
            self._require(not self.window.canvas.editor.isVisible() and self.window.state['history_index'] == 0,
                          'La lectura modificó el PDF')
            self._step('select_and_copy_paragraphs_across_pages_without_editing')
            self._reader_tested = True
            self.window.reader.go_page(0)
            self.stage = 'opening'
            self.window.tools_action.setChecked(True)
            return
        if self.stage in ('opening', 'reopened') and page and self.window.application_mode == 'reading':
            self.window.tools_action.setChecked(True)
            return
        if command == 'prepare_editing':
            self._require(self.window.application_mode == 'editing' and self.window.state['editing_prepared'],
                          'Herramientas no preparó la edición')
            self._step('tools_prepare_editing', stage=self.stage)
            command = 'page'
        super()._advance(command, result)
