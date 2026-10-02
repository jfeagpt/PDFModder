"""Aceptación nativa: PDF etiquetado, doble clic y justificación de una línea.

Usa eventos Qt normales y el proceso PDF de MainWindow. No importa el motor,
MuPDF ni QtTest en el proceso que mantiene la ventana.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPointF, QTimer, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from .model import union
from .smoke import VerticalSmoke, _digest, _signature


class TaggedSmoke(VerticalSmoke):
    def __init__(self, *args, **kwargs):
        self.extension_started = False
        super().__init__(*args, **kwargs)
        self.tagged_output = self.report_path.parent / "smoke-etiquetado-editado.pdf"
        self.before_line_render_hash = None
        self.before_line_revision = None
        self.line_render_hash = None
        self.line_revision = None
        self.line_bounds = None
        self.line_history_index = None
        self.vertical_output_hash = None
        self.timeout.start(90000)
        target = self.tagged_output.resolve()
        try:
            same = target == self.source or (
                target.exists() and self.source.exists() and os.path.samefile(target, self.source)
            )
            self._require(not same, "El destino de la prueba etiquetada coincide con el original.")
        except Exception as exc:
            QTimer.singleShot(0, lambda error=str(exc): self.fail(error))

    def _timed_out(self):
        self.finish(error=f"Tiempo límite de 90 segundos excedido en el paso {self.stage}.", terminate=True)

    def finish(self, error=None, terminate=False):
        if error is None and self.stage == "complete" and not self.extension_started:
            self.extension_started = True
            try:
                self._start_line_edit()
            except Exception as exc:
                super().finish(error=str(exc), terminate=terminate)
            return
        super().finish(error=error, terminate=terminate)

    def _glyphs(self, text):
        joined = self._text(self.window.model)
        self._require(joined.count(text) == 1, f"No hay una única aparición extraíble de {text!r}.")
        start = joined.index(text)
        result = self.window.model.glyphs[start:start + len(text)]
        self._require("".join(g.text for g in result) == text, "La selección no coincide con el texto buscado.")
        self._require(all(g.reliable for g in result), "El texto reabierto tiene una codificación ambigua.")
        return result

    def _require_tagged_report(self, report, *, justified=False):
        self._require(report and report.get("verified"), "Falta la validación PDF de la operación etiquetada.")
        accessibility = report.get("accessibility") or {}
        for key in ("verified", "structure_preserved", "logical_text_verified"):
            self._require(accessibility.get(key), f"Falta la comprobación de accesibilidad: {key}.")
        if justified:
            self._require(report.get("line_reflow") is True, "La sustitución no utilizó el ajuste del resto de la línea.")
            self._require(report.get("alignment") == "justified", "La línea no se justificó mediante sus espacios.")
            self._require(1 in accessibility.get("mcids", []), "La validación no incluye la etiqueta MCID 1 de la línea.")

    def _send_mouse(self, event_type, local, buttons):
        viewport = self.window.canvas.viewport()
        event = QMouseEvent(event_type, QPointF(local), QPointF(viewport.mapToGlobal(local)),
                            Qt.LeftButton, buttons, Qt.NoModifier)
        QApplication.sendEvent(viewport, event)

    @staticmethod
    def _send_key(widget, key, text="", modifiers=Qt.NoModifier):
        QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, key, modifiers, text))
        QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyRelease, key, modifiers, text))

    def _start_line_edit(self):
        self._require(self.window.model.number == 0, "La página visible cambió durante la lectura de control.")
        self._require(abs(self.window.zoom - 1.25) < .0001, "La prueba debe conservar zoom 125 %.")
        self._require(len(self.edit_reports) >= 2, "Faltan la sustitución y el movimiento verticales previos.")
        for report in self.edit_reports:
            self._require_tagged_report(report)
        self.before_line_render_hash = self.final_render_hash
        self.before_line_revision = self.window.model.revision
        self.line_history_index = self.window.state["history_index"]
        self.vertical_output_hash = _digest(self.output.read_bytes())
        selected = self._select("PALABRA")
        model = self.window.model
        line = model.selected(model.group(selected[0], "line"))
        self._require("".join(g.text for g in line) == "Mover PALABRA fin.",
                      "La línea etiquetada del corpus no contiene exactamente Mover PALABRA fin.")
        self.line_bounds = union(g.bbox for g in line)
        ids = self.window.canvas.ids[:]
        self.window.canvas.ensureVisible(self.window.canvas.scene_rect(union(g.bbox for g in selected)), 25, 25)
        first = selected[0]
        point = self.window.canvas.viewport_point(((first.bbox[0] + first.bbox[2]) / 2,
                                                   (first.bbox[1] + first.bbox[3]) / 2))
        # Match the native press/release/double-click/release sequence. The
        # preceding press is essential: it used to destroy line selections.
        self._send_mouse(QEvent.MouseButtonPress, point, Qt.LeftButton)
        self._send_mouse(QEvent.MouseButtonRelease, point, Qt.NoButton)
        self._send_mouse(QEvent.MouseButtonDblClick, point, Qt.LeftButton)
        self._send_mouse(QEvent.MouseButtonRelease, point, Qt.NoButton)
        editor = self.window.canvas.editor
        self._require(editor.isVisible(), "El doble clic no abrió el editor sobre la página.")
        self._require(self.window.canvas.ids == ids and editor.toPlainText() == "PALABRA",
                      "El doble clic cambió la selección anterior.")
        self._require(self.window.line_reflow_box.isChecked() and self.window.line_reflow_box.isEnabled(),
                      "El ajuste del resto de la línea no está disponible y activado por defecto.")
        self._step("doble_clic_nativo_etiquetado", selection_preserved=True, characters=len(ids), zoom=self.window.zoom)
        self._send_key(editor, Qt.Key_A, modifiers=Qt.ControlModifier)
        for char in "VOZ":
            self._send_key(editor, ord(char), char)
        self._require(editor.toPlainText() == "VOZ", "Los eventos de teclado no sustituyeron PALABRA por VOZ.")
        self.stage = "tagged_line_preview"
        self._send_key(editor, Qt.Key_Return, modifiers=Qt.ControlModifier)
        self._require(self.window.busy, "Ctrl+Enter no inició la previsualización en el proceso PDF.")

    def _assert_line(self):
        self._require("PALABRA" not in self._text(self.window.model), "El contenido sustituido sigue presente en la página 1.")
        first = self._glyphs("Mover")
        replacement = self._glyphs("VOZ")
        last = self._glyphs("fin.")
        bounds = union(g.bbox for g in first + replacement + last)
        self._require(abs(bounds[0] - self.line_bounds[0]) < .035 and abs(bounds[2] - self.line_bounds[2]) < .035,
                      f"La justificación cambió los extremos de la línea: {bounds}, antes {self.line_bounds}.")
        self._require(abs(bounds[1] - self.line_bounds[1]) < .035 and abs(bounds[3] - self.line_bounds[3]) < .035,
                      "La justificación cambió la altura o la línea base del texto.")
        return bounds

    def _advance(self, command, result):
        if not self.stage.startswith("tagged_"):
            super()._advance(command, result)
            return
        page = command == "page" and result.get("model") is not None
        main_page = page and result["number"] == 0
        if self.stage == "tagged_line_preview" and main_page:
            self._require(self.window.state["preview"] and self.window.state["history_index"] == self.line_history_index,
                          "La vista previa etiquetada alteró el historial antes de aplicar.")
            self._require_tagged_report(self.window.last_report, justified=True)
            bounds = self._assert_line()
            self.edit_reports.append(self.window.last_report)
            self.line_render_hash = _digest(result["png"])
            self.line_revision = self.window.model.revision
            self._step("previsualizar_linea_y_accesibilidad", line_reflow=True,
                       accessibility_verified=True, line_bounds=list(bounds), render_sha256=self.line_render_hash)
            self.stage = "tagged_line_commit"
            self.window.commit()
        elif self.stage == "tagged_line_commit" and main_page:
            self._require(not self.window.state["preview"] and self.window.state["history_index"] == self.line_history_index + 1,
                          "La sustitución justificada no quedó como una sola operación de historial.")
            self._require(_digest(result["png"]) == self.line_render_hash,
                          "El PDF aplicado difiere de la previsualización etiquetada.")
            self._assert_line()
            self._step("aplicar_sustitucion_etiquetada", history_index=self.window.state["history_index"], render_matches_preview=True)
            self.stage = "tagged_line_undo"
            self.window.history("undo")
        elif self.stage == "tagged_line_undo" and main_page:
            self._require(self.window.state["history_index"] == self.line_history_index,
                          "Deshacer no recuperó el índice anterior.")
            self._require(self.window.model.revision == self.before_line_revision and _digest(result["png"]) == self.before_line_render_hash,
                          "Deshacer no recuperó exactamente el PDF y su apariencia anteriores.")
            self._glyphs("PALABRA")
            self._require("VOZ" not in self._text(self.window.model), "Deshacer dejó contenido duplicado.")
            self._step("deshacer_linea_etiquetada", exact_revision_restored=True, render_equal=True)
            self.stage = "tagged_line_redo"
            self.window.history("redo")
        elif self.stage == "tagged_line_redo" and main_page:
            self._require(self.window.state["history_index"] == self.line_history_index + 1,
                          "Rehacer no recuperó la operación de línea.")
            self._require(self.window.model.revision == self.line_revision and _digest(result["png"]) == self.line_render_hash,
                          "Rehacer cambió los bytes o el render de la modificación.")
            self._assert_line()
            self._step("rehacer_linea_etiquetada", exact_revision_restored=True, render_equal=True)
            self.stage = "tagged_line_saved"
            self._require(self.window.save_as(self.tagged_output), "La GUI no inició el guardado del PDF etiquetado.")
        elif self.stage == "tagged_line_saved" and command == "save":
            self._require(self.tagged_output.is_file() and not self.window.state["dirty"], "El PDF etiquetado no se guardó correctamente.")
            self._require(_digest(self.source.read_bytes()) == self.source_hash, "El archivo original fue alterado.")
            self._require(_digest(self.output.read_bytes()) == self.vertical_output_hash, "El segundo guardado alteró la primera copia.")
            self._step("guardar_segunda_copia_etiquetada", path=str(self.tagged_output), source_and_first_copy_unchanged=True)
            self.stage = "tagged_line_reopened"
            self._require(self.window.open_document(self.tagged_output), "La GUI no inició la reapertura del PDF etiquetado.")
        elif self.stage == "tagged_line_reopened" and main_page:
            self._require(self.window.state["page_count"] == self.page_count and not self.window.state.get("issues"),
                          "La copia reabierta cambió de páginas o presenta restricciones nuevas.")
            self._require(_digest(result["png"]) == self.line_render_hash,
                          "La copia reabierta no coincide visualmente con la previsualización aplicada.")
            self._assert_line()
            self._assert_date(moved=True)
            selected = self._select("VOZ")
            self._require(all(g.reliable and g.mode == 0 for g in selected), "VOZ dejó de ser texto real editable al reabrir.")
            self._step("reabrir_texto_etiquetado", text="VOZ", occurrences=1, real_text=True, render_equal=True, line_endpoints_equal=True)
            self.stage = "tagged_line_control"
            self._request_control(False)
        elif self.stage == "tagged_line_control" and page and result["number"] == 1:
            self._require(_signature(result["model"]) == self.control_signature,
                          "Cambió el contenido o la geometría de la página 2 al editar la etiqueta.")
            self._require(_digest(result["png"]) == self.control_render_hash,
                          "Cambió la apariencia de la página 2 al editar la etiqueta.")
            self._require("10/09/2026" in self._text(result["model"]), "Se perdió la fecha legítima de la página de control.")
            self._step("verificar_control_tras_justificacion_etiquetada", glyphs_geometry_pixels_equal=True, original_date_retained=True)
            self.output = self.tagged_output
            self.stage = "complete"
            QTimer.singleShot(150, self.finish)
