"""Frozen workflow for the 1.5.0 tools, using Qt controls and the real worker.

The PDF engine is never imported here. File pickers receive isolated test paths;
the tools' real configuration dialogs, worker operations and export validation
still run. No QtTest dependency is needed in the distributed application.
"""
from __future__ import annotations

import os
from pathlib import Path
import uuid

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication, QDialogButtonBox, QFileDialog, QFormLayout, QToolButton,
)

from .smoke import VerticalSmoke, _digest, _signature


class ToolsSmokeV150(VerticalSmoke):
    def __init__(self, window, source, report_path):
        super().__init__(window, source, report_path)
        self.output = self.report_path.parent / 'smoke-v150-editado.pdf'
        self.artifact_dir = self.report_path.parent / ('smoke-v150-files-' + uuid.uuid4().hex[:12])
        self.text_export = self.artifact_dir / 'texto.txt'
        self.split_directory = self.artifact_dir / 'partes'
        self.parts = []
        self.added_lines = ('Prueba PDF Modder 1.5.0', 'Texto nuevo verificable')
        self.added_text = ''.join(self.added_lines)
        self.text_render_hash = None
        self.crop_before = None
        self.crop_after = None
        self._modal_expected = None
        self._finalizing = False
        self._save_picker_original = None
        self._directory_picker_original = None
        self.dialog_timer = QTimer(self)
        self.dialog_timer.setInterval(20)
        self.dialog_timer.timeout.connect(self._answer_dialog)
        self.timeout.start(180000)
        self.window.resize(1366, 768)
        try:
            for target in (self.output, self.text_export, self.split_directory):
                self._require(target.resolve() != self.source and not (
                    target.exists() and os.path.samefile(target, self.source)),
                    'La prueba 1.5.0 no puede sobrescribir el PDF original.')
            self.artifact_dir.mkdir(parents=True, exist_ok=False)
            self.split_directory.mkdir()
            self._save_picker_original = QFileDialog.getSaveFileName
            self._directory_picker_original = QFileDialog.getExistingDirectory
            QFileDialog.getSaveFileName = staticmethod(self._save_picker)
            QFileDialog.getExistingDirectory = staticmethod(self._directory_picker)
        except Exception as exc:
            self._later(lambda message=str(exc): self.fail(message))

    def _save_picker(self, *_args, **_kwargs):
        self._require(self.stage == 'export_text', 'Apareció un diálogo de guardado no previsto en la prueba.')
        return str(self.text_export), 'Texto UTF-8 (*.txt)'

    def _directory_picker(self, *_args, **_kwargs):
        self._require(self.stage == 'split', 'Apareció un selector de carpeta no previsto en la prueba.')
        return str(self.split_directory)

    def _timed_out(self):
        self.finish(error=f'Tiempo límite de 180 segundos excedido en {self.stage}.', terminate=True)

    def _later(self, callback, delay=0):
        def guarded():
            if self.finished:
                return
            try:
                callback()
            except Exception as exc:
                self.fail(str(exc))
        QTimer.singleShot(delay, guarded)

    def _click_tool(self, name):
        button = self.window.findChild(QToolButton, name)
        self._require(button is not None and button.isEnabled(), f'La herramienta {name} no está disponible.')
        self.window.tools_scroll.ensureWidgetVisible(button)
        button.click()

    @staticmethod
    def _field(dialog, label):
        for form in dialog.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.LabelRole)
                if item and item.widget() and item.widget().text() == label:
                    return form.itemAt(row, QFormLayout.FieldRole).widget()
        raise AssertionError(f'No se encontró el campo {label!r} en {dialog.windowTitle()}.')

    def _tool_dialog(self, button, title, configure):
        self._require(self._modal_expected is None, 'Quedó un diálogo de prueba sin responder.')
        self._modal_expected = (title, configure)
        self.dialog_timer.start()
        # Opening a modal from operation_finished itself would nest the worker
        # poller. Let the completed callback return before opening the dialog.
        self._later(lambda:self._click_tool(button))

    def _answer_dialog(self):
        if self.finished or not self._modal_expected:
            self.dialog_timer.stop()
            return
        dialog = QApplication.activeModalWidget()
        title, configure = self._modal_expected
        if dialog is None or title not in dialog.windowTitle():
            return
        self.dialog_timer.stop()
        self._modal_expected = None
        try:
            configure(dialog)
            buttons = dialog.findChild(QDialogButtonBox)
            self._require(buttons is not None, 'El diálogo no ofrece botones de confirmación.')
            accept = buttons.button(QDialogButtonBox.Ok)
            self._require(accept is not None and accept.isEnabled(), 'El diálogo no permite aceptar los datos de prueba.')
            accept.click()
        except Exception as exc:
            dialog.reject()
            self.fail(str(exc))

    def _place_new_text(self, then):
        self._click_tool('toolAddText')
        canvas = self.window.canvas
        x, y = 50., 700.
        self._require(canvas.model.width > 300 and canvas.model.height > y + 55,
                      'El ejemplo no tiene el área libre de inserción requerida en (50, 700) pt.')
        canvas.ensureVisible(canvas.scene_rect((x-5, y-5, x+10, y+35)), 20, 20)
        position = canvas.viewport_point((x, y))
        self._require(canvas.viewport().rect().contains(position), 'El punto de inserción no es visible en la página.')
        local, global_position = QPointF(position), QPointF(canvas.viewport().mapToGlobal(position))
        QApplication.sendEvent(canvas.viewport(), QMouseEvent(
            QEvent.MouseButtonPress, local, global_position, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        QApplication.sendEvent(canvas.viewport(), QMouseEvent(
            QEvent.MouseButtonRelease, local, global_position, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self._await_editor(then)

    def _await_editor(self, then):
        if self.window.busy or not self.window.canvas.editor.isVisible():
            self._later(lambda:self._await_editor(then), 30)
            return
        editor = self.window.canvas.editor
        self._require(editor.rich_mode and not editor.payload().get('ids'), 'Agregar texto no abrió un cuadro nuevo sobre la página.')
        self._require(editor.toolbar.accept.isVisible() and editor.toolbar.cancel.isVisible(), 'No aparecen Aceptar y Cancelar junto al texto nuevo.')
        self._require(editor.current_style().get('font_name') == 'LiberationSans', 'La fuente inicial de texto nuevo no es la fuente explícita prevista.')
        then(editor)

    def _cancel_new_text(self, editor):
        editor.insertPlainText('BORRADOR CANCELADO 1.5.0')
        editor.toolbar.cancel.click()
        self._require(not editor.isVisible() and self.window.state['history_index'] == 0,
                      'Cancelar el texto nuevo modificó el historial.')
        self._require('BORRADOR CANCELADO' not in self._text(self.window.model), 'El borrador cancelado llegó al PDF.')
        self._step('agregar_texto_por_clic_y_cancelar',history_unchanged=True)
        self.stage = 'new_text_editor'
        self._later(lambda:self._place_new_text(self._write_new_text))

    def _write_new_text(self, editor):
        editor.insertPlainText(self.added_lines[0])
        QApplication.sendEvent(editor, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        editor.insertPlainText(self.added_lines[1])
        self._require(editor.toPlainText() == '\n'.join(self.added_lines), 'Intro no conservó las dos líneas de texto nuevo.')
        self._step('agregar_dos_lineas_en_la_pagina',font='LiberationSans',size_pt=12,default_explicit=True)
        self.stage = 'text_preview'

    def _check_added_text(self, model):
        text = self._text(model)
        self._require(text.count(self.added_text) == 1, 'El párrafo añadido falta o aparece duplicado.')
        self._require('BORRADOR CANCELADO' not in text, 'El texto cancelado permaneció en la copia.')

    def _crop(self, stage):
        self.stage = stage
        def configure(dialog):
            self._field(dialog, 'Páginas').setText('1')
            self._field(dialog, 'Izquierda').setValue(4.)
        self._tool_dialog('toolCropPages', 'Recortar páginas', configure)

    def _pending_crop(self, result):
        self._require(self.window.state['preview'] and self.window.state['history_index'] == 1,
                      'La vista del recorte alteró el historial antes de aplicar.')
        report = self.window.last_report or {}
        self._require(report.get('verified'), 'Falta la validación del recorte de página.')
        self.edit_reports.append(report)
        self.crop_after = tuple(result['model'].cropbox)
        self._require(abs(self.crop_after[0]-self.crop_before[0]-4*72/25.4) < .02,
                      'El CropBox no refleja los cuatro milímetros solicitados.')
        self._check_added_text(result['model'])
        self.preview_render_hash = _digest(result['png'])

    def _advance(self, command, result):
        is_page = command == 'page' and result.get('model') is not None
        main = is_page and result['number'] == 0
        if self.stage == 'opening' and main:
            self.page_count = self.window.state['page_count']
            self._require(self.page_count == 2, 'La prueba 1.5.0 necesita digital.pdf con dos páginas.')
            self._require(not self.window.state.get('issues'), 'El corpus de prueba presenta restricciones.')
            self.crop_before = tuple(result['model'].cropbox)
            self.window.tools_toggle_button.click()
            self._require(not self.window.tools_scroll.isVisible(), 'Herramientas no ocultó el panel derecho.')
            self.window.tools_toggle_button.click()
            self._require(self.window.tools_scroll.isVisible(), 'Herramientas no recuperó el panel derecho.')
            self._step('abrir_y_alternar_herramientas',page_count=self.page_count,window_width=self.window.width(),window_height=self.window.height())
            self.stage = 'original_control'
            self._request_control(True)
        elif self.stage == 'original_control' and is_page and result['number'] == 1:
            self.control_signature = _signature(result['model'])
            self.control_render_hash = _digest(result['png'])
            self.stage = 'cancel_text_editor'
            self._later(lambda:self._place_new_text(self._cancel_new_text))
        elif self.stage == 'text_preview' and command == 'rich_preview':
            self._require(result['report'].get('verified'), 'La vista del párrafo no fue validada por el motor.')
            self._require(self.window.state['history_index'] == 0 and not self.window.state['preview'],
                          'La vista en vivo aplicó el párrafo antes de aceptar.')
            self.preview_render_hash = _digest(result['png'])
            self.edit_reports.append(result['report'])
            self._step('previsualizar_texto_nuevo_real',render_sha256=self.preview_render_hash)
            self.stage = 'text_commit'
            self.window.canvas.editor.toolbar.accept.click()
        elif self.stage == 'text_commit' and command == 'rich_prepare':
            self._require(result.get('token') and result['report'].get('verified'), 'Aceptar no preparó una transacción validada.')
        elif self.stage == 'text_commit' and main:
            self._require(self.window.state['history_index'] == 1 and not self.window.state['preview'],
                          'La escritura no produjo una sola operación aceptada.')
            self._check_added_text(result['model'])
            self.text_render_hash = _digest(result['png'])
            self._require(self.text_render_hash == self.preview_render_hash, 'Aceptar cambió la apariencia de la vista previa.')
            self._step('aceptar_texto_nuevo',history_index=1,preview_matches_commit=True)
            self._crop('crop_cancel_preview')
        elif self.stage == 'crop_cancel_preview' and main:
            self._pending_crop(result)
            self.stage = 'crop_cancelled'
            self.window.cancel_step_button.click()
        elif self.stage == 'crop_cancelled' and main:
            self._require(not self.window.state['preview'] and self.window.state['history_index'] == 1,
                          'Cancelar el recorte modificó el historial.')
            self._require(tuple(result['model'].cropbox) == self.crop_before and _digest(result['png']) == self.text_render_hash,
                          'Cancelar el recorte no recuperó exactamente geometría y apariencia.')
            self._step('cancelar_recorte_exacto',cropbox_and_render_restored=True)
            self._crop('crop_apply_preview')
        elif self.stage == 'crop_apply_preview' and main:
            self._pending_crop(result)
            self.stage = 'crop_committed'
            self.window.apply_step_button.click()
        elif self.stage == 'crop_committed' and main:
            self._require(not self.window.state['preview'] and self.window.state['history_index'] == 2,
                          'El recorte no quedó como una operación del historial.')
            self.final_render_hash = _digest(result['png'])
            self._require(self.final_render_hash == self.preview_render_hash, 'El recorte aplicado difiere de la previsualización.')
            self._step('aplicar_recorte_desde_herramientas',margin_left_mm=4,history_index=2,preview_matches_commit=True)
            self.stage = 'export_text'
            self._tool_dialog('toolExportDocument', 'Exportar archivo', lambda dialog:self._field(dialog, 'Páginas').setText('1-2'))
        elif self.stage == 'export_text' and command == 'export_document_v150':
            self._require(self.text_export.is_file(), 'Exportar TXT no creó el archivo solicitado.')
            text = self.text_export.read_text(encoding='utf-8')
            self._require(all(line in text for line in self.added_lines), 'El TXT no contiene las dos líneas añadidas.')
            self._require('10/09/2026' in text and self.window.state['history_index'] == 2, 'Exportar alteró el contenido o el historial.')
            self._step('exportar_txt_desde_herramientas',path=str(self.text_export),sha256=_digest(self.text_export.read_bytes()),file_picker_path_supplied=True)
            self.stage = 'split'
            self._tool_dialog('toolSplitDocument', 'Dividir documento', lambda dialog:self._field(dialog, 'Páginas por archivo').setValue(1))
        elif self.stage == 'split' and command == 'split_document_v150':
            report = result.get('report', {})
            self._require(report.get('verified'), 'La división no devuelve validación del motor.')
            self.edit_reports.append(report)
            records = report.get('files', result.get('files', []))
            self.parts = [Path(item['path'] if isinstance(item, dict) else item).resolve() for item in records]
            self._require(len(self.parts) == 2 and all(path.is_file() for path in self.parts), 'Dividir no creó dos PDF de una página.')
            self._require(self.window.state['page_count'] == 2 and self.window.state['history_index'] == 2, 'Dividir modificó el documento de trabajo.')
            self._step('dividir_desde_herramientas',files=[str(path) for path in self.parts],original_working_state_retained=True,file_picker_path_supplied=True)
            self.stage = 'saved'
            self._require(self.window.save_as(self.output), 'No se inició el guardado de la copia 1.5.0.')
        elif self.stage == 'saved' and command == 'save':
            self._require(self.output.is_file() and not self.window.state['dirty'], 'El guardado no produjo una copia final validada.')
            self._require(_digest(self.source.read_bytes()) == self.source_hash, 'La prueba modificó el archivo original.')
            self._step('guardar_copia',path=str(self.output),sha256=_digest(self.output.read_bytes()),source_unchanged=True)
            self.stage = 'reopened'
            self._require(self.window.open_document(self.output), 'No se inició la reapertura de la copia.')
        elif self.stage == 'reopened' and main:
            self._require(self.window.state['page_count'] == self.page_count, 'El número de páginas cambió al reabrir.')
            self._check_added_text(result['model'])
            self._require(tuple(result['model'].cropbox) == self.crop_after and _digest(result['png']) == self.final_render_hash,
                          'La copia reabierta cambió el recorte o la apariencia.')
            self._step('reabrir_texto_y_recorte',text_selectable=True,cropbox_and_render_equal=True)
            self.stage = 'reopened_control'
            self._request_control(False)
        elif self.stage == 'reopened_control' and is_page and result['number'] == 1:
            self._require(_signature(result['model']) == self.control_signature and _digest(result['png']) == self.control_render_hash,
                          'La página no editada cambió en contenido, geometría o apariencia.')
            self._step('verificar_pagina_2_intacta',glyphs_and_geometry_equal=True,render_equal=True)
            self.stage = 'part_one'
            self._require(self.window.open_document(self.parts[0]), 'No se abrió la primera parte dividida.')
        elif self.stage == 'part_one' and main:
            self._require(self.window.state['page_count'] == 1, 'La primera parte no tiene exactamente una página.')
            self._check_added_text(result['model'])
            self._require(_digest(result['png']) == self.final_render_hash, 'Dividir alteró la apariencia de la página editada.')
            self._step('reabrir_primera_parte',page_count=1,text_and_render_equal=True)
            self.stage = 'part_two'
            self._require(self.window.open_document(self.parts[1]), 'No se abrió la segunda parte dividida.')
        elif self.stage == 'part_two' and main:
            self._require(self.window.state['page_count'] == 1, 'La segunda parte no tiene exactamente una página.')
            self._require(_signature(result['model']) == self.control_signature and _digest(result['png']) == self.control_render_hash,
                          'La segunda parte no conserva el texto y el render de la página original.')
            self._step('reabrir_segunda_parte',page_count=1,control_page_identical=True)
            self.stage = 'final_reopen'
            self._require(self.window.open_document(self.output), 'No se recuperó la copia final para la captura.')
        elif self.stage == 'final_reopen' and main:
            self._check_added_text(result['model'])
            self._require(_digest(result['png']) == self.final_render_hash, 'La captura final no corresponde al PDF validado.')
            self.window.tools_scroll.verticalScrollBar().setValue(0)
            self._step('original_conservado_y_copia_final',source_unchanged=_digest(self.source.read_bytes()) == self.source_hash)
            self.stage = 'complete'
            self._later(self.finish, 150)

    def finish(self, error=None, terminate=False):
        if self.finished or self._finalizing:
            return
        self._finalizing = True
        self.dialog_timer.stop()
        self._modal_expected = None
        if self._save_picker_original is not None:
            QFileDialog.getSaveFileName = self._save_picker_original
        if self._directory_picker_original is not None:
            QFileDialog.getExistingDirectory = self._directory_picker_original
        dialog = QApplication.activeModalWidget()
        if dialog is not None and dialog.parentWidget() is self.window:
            dialog.reject()
        super().finish(error=error, terminate=terminate)
