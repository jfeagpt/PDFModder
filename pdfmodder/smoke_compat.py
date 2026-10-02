"""Frozen checks for tags, paint order, color state and original font resources.

The generated corpus is read from examples. PDF objects stay in the application
worker; this driver only uses the normal controls, returned models and reports.
"""
from pathlib import Path
import os

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor

from .smoke import VerticalSmoke, _digest, _signature


class CompatibilitySmoke(VerticalSmoke):
    def __init__(self, window, source, report_path):
        super().__init__(window, source, report_path)
        self.neutral_source = self.source.with_name('compat-estado-neutro-v091.pdf')
        self.subsets_source = self.source.with_name('compat-subconjuntos-v091.pdf')
        self.truetype_source = self.source.with_name('compat-truetype-v092.pdf')
        self.tagged_output = self.report_path.parent / 'compat-etiquetado-editado.pdf'
        self.extracted_output = self.report_path.parent / 'compat-etiquetado-extraido.pdf'
        self.reduced_output = self.report_path.parent / 'compat-etiquetado-eliminada.pdf'
        self.restored_output = self.report_path.parent / 'compat-etiquetado-restaurado.pdf'
        self.neutral_output = self.report_path.parent / 'compat-estado-neutro-editado.pdf'
        self.subsets_output = self.report_path.parent / 'compat-subconjuntos-editado.pdf'
        self.truetype_page_output = self.report_path.parent / 'compat-truetype-pagina-editado.pdf'
        self.output = self.report_path.parent / 'compat-truetype-panel-editado.pdf'
        self.neutral_hash = None
        self.subsets_hash = None
        self.truetype_hash = None
        self.context = 'tagged'
        self.control_models = {}
        self.control_renders = {}
        self.accepted_renders = {}
        self.initial_revisions = {}
        self.timeout.setInterval(180000)
        self.timeout.start()
        try:
            self.neutral_hash = _digest(self.neutral_source.read_bytes())
            self.subsets_hash = _digest(self.subsets_source.read_bytes())
            self.truetype_hash = _digest(self.truetype_source.read_bytes())
            for target in (self.report_path, self.screenshot, self.tagged_output, self.extracted_output, self.reduced_output,
                           self.restored_output, self.neutral_output, self.subsets_output, self.truetype_page_output, self.output):
                for source_path in (self.source, self.neutral_source, self.subsets_source, self.truetype_source):
                    if target == source_path or (target.exists() and os.path.samefile(target, source_path)):
                        if target == self.report_path:
                            self.safe_report = False
                        self._require(False, 'La prueba de compatibilidad no puede sobrescribir un origen.')
        except Exception as exc:
            QTimer.singleShot(0, lambda error=str(exc): self.fail(error))

    def _timed_out(self):
        self.finish(error=f'Tiempo límite de 180 segundos excedido en {self.stage}.', terminate=True)

    def _begin_edit(self):
        if self.context.startswith('truetype_'):
            self.old_text, self.new_text = '68,48', '70,48'
        else:
            self.old_text, self.new_text = ('2025', '2026') if self.context == 'subsets' else ('10/09/2026', '11/09/2026')
        selected = self._select(self.old_text)
        self.original_size = selected[0].size
        self.original_font = selected[0].font
        self.original_origin = selected[0].origin
        if self.context == 'truetype_panel':
            self.window.content.setPlainText(self.new_text)
            self._require(self.window.preview_button.isEnabled(), 'No se habilitó la vista previa del panel de propiedades.')
            self.stage = 'panel_preview'
            self.window.preview_button.click()
        else:
            self.stage = 'rich_selection'
            self.window.start_edit()

    def _replace(self):
        editor = self.window.canvas.editor
        self._require(editor.isVisible() and editor.rich_mode, 'El documento no llegó al editor compatible sobre la página.')
        self._require(not editor.textCursor().hasSelection(), 'El editor seleccionó automáticamente todo el contenido.')
        cursor = editor.textCursor()
        if self.context.startswith('truetype_'):
            cursor.select(QTextCursor.Document)
            editor.setTextCursor(cursor)
            cursor.insertText(self.new_text)
        else:
            changed_index = 3 if self.context == 'subsets' else 1
            cursor.setPosition(changed_index)
            cursor.setPosition(changed_index + 1, QTextCursor.KeepAnchor)
            editor.setTextCursor(cursor)
            cursor.insertText(self.new_text[changed_index])
        self._require(editor.toPlainText() == self.new_text, 'La edición no produjo exactamente el texto elegido.')
        self.stage = 'rich_preview'

    def _assert_text(self):
        chosen = self._select(self.new_text)
        self._require(self.old_text not in self._text(self.window.model), 'Quedó el texto anterior en la página editada.')
        self._require(all(abs(a-b) < .035 for a, b in zip(chosen[0].origin, self.original_origin)), 'La edición desplazó el origen del texto.')
        self._require(all(abs(g.size-self.original_size) < .001 for g in chosen), 'La edición cambió el tamaño de letra.')
        self._require(all(g.font == self.original_font for g in chosen), 'Se perdió la identidad tipográfica del texto editado.')

    def _target(self):
        return {'tagged': self.tagged_output, 'neutral': self.neutral_output, 'subsets': self.subsets_output,
                'truetype_pagina': self.truetype_page_output, 'truetype_panel': self.output}[self.context]

    def _verify_accepted(self, result):
        self._require(self.window.state['history_index'] == 1, 'La escritura no se guardó como una única operación.')
        self._require(not self.window.state['preview'], 'Aceptar dejó una previsualización sin confirmar.')
        self._assert_text()
        report = self.window.last_report
        self._require(report and report.get('verified'), 'Falta la validación del PDF aplicado.')
        if self.context == 'tagged':
            accessibility = report.get('accessibility', {})
            self._require(accessibility.get('verified') and accessibility.get('structure_preserved')
                          and accessibility.get('logical_text_verified'), 'No se verificaron estructura, etiquetas y texto lógico.')
            self._require(accessibility.get('actual_text_updates', 0) > 0, 'No se actualizó ActualText.')
        elif self.context == 'subsets':
            self._require(any(info.get('complementary_subset_of') for info in report.get('fonts', {}).values()),
                          'No se ejercitó la reutilización verificada de un subconjunto CFF complementario.')
        elif self.context.startswith('truetype_'):
            self._require(any(info.get('mapping_only') and info.get('program_unchanged')
                              and info.get('original_resource_unchanged') for info in report.get('fonts', {}).values()),
                          'No se verificó la ampliación Unicode sin modificar el programa TrueType original.')
            if self.context == 'truetype_panel':
                self._require(report.get('native_panel'), 'El panel no utilizó la ruta de recursos Type0 originales.')
        self.accepted_renders[self.context] = _digest(result['png'])
        self._require(self.accepted_renders[self.context] == self.preview_render_hash, 'Aplicar cambió la imagen de la vista previa.')
        self.edit_reports.append(report)
        self._step(f'{self.context}_aceptar_texto', preview_matches_commit=True,
                   accessibility=report.get('accessibility'),
                   original_synthetic_outline_font=self.context == 'subsets')

    def _verify_control(self, result):
        context = self.context
        self._require(_signature(result['model']) == self.control_models[context], 'Cambió el contenido de la página de control.')
        self._require(_digest(result['png']) == self.control_renders[context], 'Cambió la apariencia de la página de control.')
        self._step(f'{context}_pagina_control_intacta', text_and_render_identical=True)

    def _advance(self, command, result):
        is_page = command == 'page' and result.get('model') is not None
        if self.stage in ('opening', 'neutral_opening') and is_page and result['number'] == 0:
            self.page_count = self.window.state['page_count']
            self._require(self.page_count == 2 and not self.window.state['issues'], 'El corpus requiere dos páginas sin restricciones documentales.')
            self._require(bool(self.window.state['tagged']) == (self.context == 'tagged'), 'El documento de prueba no coincide con su caso.')
            if self.context == 'tagged':
                capabilities = self.window.state.get('page_capabilities', {})
                self._require(all(capabilities.get(key) for key in ('delete', 'extract', 'reorder', 'rotate')), 'Se bloquearon herramientas compatibles de páginas etiquetadas.')
                self._require(self.window.delete_pages_action.isEnabled() and self.window.extract_pages_action.isEnabled()
                              and self.window.organize_action.isEnabled(), 'La interfaz no habilitó las herramientas verificadas.')
                self._require(self.window.add_text_action.isEnabled() and self.window.add_image_action.isEnabled(),
                              'No se habilitó la inserción con elección explícita de accesibilidad.')
            self.initial_revisions[self.context] = self.window.model.revision
            self._step(f'{self.context}_abrir', page_count=self.page_count, page_capabilities=self.window.state.get('page_capabilities'))
            self.stage = 'original_control'
            self._request_control(True)
        elif self.stage == 'original_control' and is_page and result['number'] == 1:
            self.control_models[self.context] = _signature(result['model'])
            self.control_renders[self.context] = _digest(result['png'])
            self._begin_edit()
        elif self.stage == 'rich_selection' and command == 'rich_selection':
            self._replace()
        elif self.stage == 'rich_preview' and command == 'rich_preview':
            self._require(result['report'].get('verified'), 'El motor no validó la vista previa.')
            self._require(self.window.state['history_index'] == 0, 'La vista previa alteró el historial.')
            self.preview_render_hash = _digest(result['png'])
            self._step(f'{self.context}_vista_pdf_real', render_sha256=self.preview_render_hash)
            self.stage = 'accepted'
            self.window.canvas.editor.toolbar.accept.click()
        elif self.stage == 'panel_preview' and is_page and result['number'] == 0:
            self._require(self.window.state['preview'] and self.window.state['history_index'] == 0,
                          'La vista del panel alteró el historial antes de aplicar.')
            self._require(self.window.last_report.get('verified'), 'La vista del panel no fue validada.')
            self.preview_render_hash = _digest(result['png'])
            self._step('truetype_panel_vista_pdf_real', render_sha256=self.preview_render_hash)
            self.stage = 'accepted'
            self.window.commit_button.click()
        elif self.stage == 'accepted' and command == 'rich_prepare':
            self._require(result.get('token') and result['state']['history_index'] == 0, 'Preparar la aceptación alteró el historial.')
        elif self.stage == 'accepted' and is_page and result['number'] == 0:
            self._verify_accepted(result)
            self.stage = 'saved'
            self._require(self.window.save_as(self._target()), 'No comenzó Guardar como.')
        elif self.stage == 'saved' and command == 'save':
            target = self._target()
            self._require(target.is_file() and not self.window.state['dirty'], 'No se guardó el documento modificado.')
            self._step(f'{self.context}_guardar', path=str(target), sha256=_digest(target.read_bytes()))
            if self.context == 'tagged':
                self.stage = 'extracted'
                self.window.extract_pages('1', self.extracted_output)
            else:
                self.stage = 'reopened'
                self._require(self.window.open_document(target), 'No comenzó la reapertura de la copia.')
        elif self.stage == 'extracted' and command == 'extract_pages':
            self._require(self.extracted_output.is_file() and self.window.state['history_index'] == 1
                          and self.window.state['page_count'] == 2, 'Extraer páginas alteró el trabajo actual.')
            self._step('tagged_extraer', path=str(self.extracted_output), history_unchanged=True)
            self.stage = 'deleted'
            self.window.delete_pages('2')
        elif self.stage == 'deleted' and is_page and result['number'] == 0:
            self._require(self.window.state['page_count'] == 1 and self.window.state['history_index'] == 2, 'No se eliminó exclusivamente la segunda página.')
            self._require(_digest(result['png']) == self.accepted_renders['tagged'], 'Eliminar otra página cambió la página retenida.')
            self.edit_reports.append(self.window.last_report)
            self._step('tagged_eliminar_pagina', retained_page_identical=True)
            self.stage = 'reduced_saved'
            self._require(self.window.save_as(self.reduced_output), 'No se guardó la copia con una página.')
        elif self.stage == 'reduced_saved' and command == 'save':
            self._step('tagged_guardar_pagina_restante', path=str(self.reduced_output))
            self.stage = 'undo'
            self.window.history('undo')
        elif self.stage == 'undo' and is_page and result['number'] == 0:
            self._require(self.window.state['page_count'] == 2 and self.window.state['history_index'] == 1, 'Deshacer no recuperó las dos páginas.')
            self._require(_digest(result['png']) == self.accepted_renders['tagged'], 'Deshacer alteró la página editada.')
            self.stage = 'restored_saved'
            self._require(self.window.save_as(self.restored_output), 'No se guardó el estado recuperado.')
        elif self.stage == 'restored_saved' and command == 'save':
            self._require(self.restored_output.read_bytes() == self.tagged_output.read_bytes(), 'Deshacer no recuperó exactamente los bytes guardables.')
            self._step('tagged_deshacer_exacto', saved_bytes_identical=True)
            self.stage = 'reopened'
            self._require(self.window.open_document(self.restored_output), 'No comenzó la reapertura del PDF etiquetado.')
        elif self.stage == 'reopened' and is_page and result['number'] == 0:
            self._assert_text()
            self._require(self.window.state['page_count'] == 2, 'Cambió el número de páginas al reabrir.')
            self._require(_digest(result['png']) == self.accepted_renders[self.context], 'Guardar y reabrir alteró la apariencia.')
            self._step(f'{self.context}_reabrir', real_text_verified=True, render_identical=True)
            self.stage = 'final_control'
            self._request_control(False)
        elif self.stage == 'final_control' and is_page and result['number'] == 1:
            self._verify_control(result)
            if self.context == 'tagged':
                self.context = 'neutral'
                self.stage = 'neutral_opening'
                self._require(self.window.open_document(self.neutral_source), 'No comenzó la apertura del PDF de estado neutro.')
            elif self.context == 'neutral':
                self.context = 'subsets'
                self.stage = 'neutral_opening'
                self._require(self.window.open_document(self.subsets_source), 'No comenzó la apertura del PDF de subconjuntos CFF.')
            elif self.context == 'subsets':
                self.context = 'truetype_pagina'
                self.stage = 'neutral_opening'
                self._require(self.window.open_document(self.truetype_source), 'No comenzó la apertura de la fuente TrueType sin cmap.')
            elif self.context == 'truetype_pagina':
                self.context = 'truetype_panel'
                self.stage = 'neutral_opening'
                self._require(self.window.open_document(self.truetype_source), 'No comenzó la edición TrueType desde el panel.')
            else:
                self._require(_digest(self.source.read_bytes()) == self.source_hash, 'Se alteró el original etiquetado.')
                self._require(_digest(self.neutral_source.read_bytes()) == self.neutral_hash, 'Se alteró el original de estado neutro.')
                self._require(_digest(self.subsets_source.read_bytes()) == self.subsets_hash, 'Se alteró el original de subconjuntos CFF.')
                self._require(_digest(self.truetype_source.read_bytes()) == self.truetype_hash, 'Se alteró el original de recursos TrueType.')
                self._step('originales_intactos', tagged_sha256=self.source_hash, neutral_sha256=self.neutral_hash,
                           subsets_sha256=self.subsets_hash, truetype_sha256=self.truetype_hash)
                self.stage = 'complete'
                QTimer.singleShot(150, self.finish)
