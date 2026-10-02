"""Prueba vertical del ejecutable mediante la GUI y su proceso PDF real.

No importa el motor en el proceso GUI ni necesita QtTest. Cada transición espera
la respuesta y el render de MainWindow, también cuando se ejecuta congelado.
"""
from __future__ import annotations

from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication
from . import __version__


def _digest(data):
    return sha256(data).hexdigest()


def _signature(model):
    """Compare all control-page glyphs and geometry, excluding the document hash."""
    return {
        "size": [model.width, model.height],
        "rotation": model.rotation,
        "cropbox": list(model.cropbox),
        "glyphs": [
            [glyph.text, list(glyph.origin), list(glyph.bbox), glyph.font,
             glyph.size, list(glyph.color), glyph.opacity, list(glyph.direction)]
            for glyph in model.glyphs
        ],
    }


class VerticalSmoke(QObject):
    def __init__(self, window, source, report_path):
        super().__init__(window)
        self.window = window
        self.source = Path(source).resolve()
        self.report_path = Path(report_path).resolve()
        self.output = self.report_path.parent / "smoke-editado.pdf"
        self.screenshot = self.report_path.with_suffix(".png")
        self.started = time.perf_counter()
        self.finished = False
        self.stage = "opening"
        self.steps = []
        self.safe_report = True
        self.source_hash = None
        self.control_signature = None
        self.control_render_hash = None
        self.original_origin = None
        self.original_size = None
        self.original_font = None
        self.preview_render_hash = None
        self.final_render_hash = None
        self.page_count = None
        self.edit_reports = []
        self.window.thumbnail_timer.stop()
        self.window.operation_finished.connect(self._operation)
        self.window.error_raised.connect(self.fail)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(55000)
        self.timeout.timeout.connect(self._timed_out)
        self.timeout.start()
        # Initial document opening is already queued by MainWindow. Validate
        # destinations before any event loop can reach a save/report operation.
        try:
            for target in (self.report_path, self.output, self.screenshot):
                same = target == self.source or (target.exists() and self.source.exists() and os.path.samefile(target,self.source))
                if same:
                    if target == self.report_path:
                        self.safe_report = False
                    raise ValueError("La prueba no puede escribir su informe, imagen o copia sobre el PDF de origen.")
            self.report_path.parent.mkdir(parents=True,exist_ok=True)
            self.source_hash = _digest(self.source.read_bytes())
        except Exception as exc:
            QTimer.singleShot(0,lambda error=str(exc):self.fail(error))

    def _require(self, condition, message):
        if not condition:
            raise AssertionError(message)

    def _step(self,name,**details):
        self.steps.append({"step":name,"ok":True,"elapsed_seconds":round(time.perf_counter()-self.started,3),**details})

    def _text(self,model):
        return "".join(glyph.text for glyph in model.glyphs)

    def _select(self,text):
        model = self.window.model
        joined = self._text(model)
        self._require(joined.count(text)==1,f"Se esperaba una única aparición de {text!r} en la página 1.")
        start = joined.index(text)
        # PageModel supplies individual Unicode characters for editable PDFs.
        selected = model.glyphs[start:start+len(text)]
        self._require("".join(g.text for g in selected)==text,"No se pudo aislar exactamente la fecha para la prueba.")
        self.window.canvas.set_selection([glyph.id for glyph in selected])
        return selected

    def _assert_date(self, *, moved):
        chosen = self._select("11/09/2026")
        self._require("10/09/2026" not in self._text(self.window.model),"La fecha anterior sigue presente en la página editada.")
        expected = (self.original_origin[0]+(12. if moved else 0.),self.original_origin[1]+(10. if moved else 0.))
        actual = chosen[0].origin
        self._require(all(abs(a-b)<.035 for a,b in zip(actual,expected)),f"La fecha no aparece en la posición esperada: {actual}, esperado {expected}.")
        self._require(chosen[0].font==self.original_font and abs(chosen[0].size-self.original_size)<.001,"La fecha cambió de fuente o tamaño.")
        return actual

    def _request_control(self,original):
        accepted = self.window._submit("page",{"number":1,"zoom":self.window.zoom,"original":original})
        self._require(accepted,"No se pudo solicitar la página de control al proceso PDF.")

    def _operation(self,command,result):
        if self.finished:
            return
        try:
            self._advance(command,result)
        except Exception as exc:
            self.fail(str(exc))

    def _advance(self,command,result):
        is_page = command=="page" and result.get("model") is not None
        if self.stage=="opening" and is_page and result["number"]==0:
            self.page_count = self.window.state["page_count"]
            self._require(self.page_count>=2,"La prueba vertical necesita digital.pdf con su segunda página de control.")
            self._require(not self.window.state.get("issues"),"El documento de prueba tiene restricciones de edición.")
            selected = self._select("10/09/2026")
            self.original_origin = selected[0].origin
            self.original_size = selected[0].size
            self.original_font = selected[0].font
            self._step("abrir_y_seleccionar",page_count=self.page_count,characters=len(selected),origin=list(self.original_origin))
            self.stage = "original_control"
            self._request_control(True)
        elif self.stage=="original_control" and is_page and result["number"]==1:
            self.control_signature = _signature(result["model"])
            self.control_render_hash = _digest(result["png"])
            self._step("registrar_pagina_2_original",render_sha256=self.control_render_hash)
            self.stage = "preview"
            self.window.preview_text("11/09/2026")
        elif self.stage=="preview" and is_page and result["number"]==0:
            self._require(self.window.state["preview"],"La escritura no produjo una previsualización pendiente.")
            self._require(self.window.state["history_index"]==0,"La vista previa se comprometió antes de aplicar.")
            self._require("11/09/2026" in self._text(result["model"]),"El PDF de previsualización no contiene la fecha nueva.")
            self._require(self.window.last_report and self.window.last_report.get("verified"),"Falta la validación del motor para el cambio de fecha.")
            self.edit_reports.append(self.window.last_report)
            self.preview_render_hash = _digest(result["png"])
            self._step("previsualizar_pdf_real",render_sha256=self.preview_render_hash)
            self.stage = "committed"
            self.window.commit()
        elif self.stage=="committed" and is_page and result["number"]==0:
            self._require(not self.window.state["preview"] and self.window.state["history_index"]==1,"La escritura no quedó como una operación de historial.")
            self._require(_digest(result["png"])==self.preview_render_hash,"El PDF aplicado difiere visualmente de su vista previa.")
            self._assert_date(moved=False)
            self._step("aplicar_fecha",history_index=1,preview_render_matches_commit=True)
            self.stage = "moved"
            self.window.move_selection(12.,10.)
        elif self.stage=="moved" and is_page and result["number"]==0:
            self._require(self.window.state["history_index"]==2,"El movimiento no produjo una operación única de historial.")
            origin = self._assert_date(moved=True)
            self._require(self.window.last_report and self.window.last_report.get("verified"),"Falta la validación del motor para el movimiento.")
            self.edit_reports.append(self.window.last_report)
            self.final_render_hash = _digest(result["png"])
            self._step("mover_fecha",dx_pt=12.,dy_pt=10.,origin=list(origin),render_sha256=self.final_render_hash)
            self.stage = "saved"
            self._require(self.window.save_as(self.output),"La GUI no inició el guardado de la copia.")
        elif self.stage=="saved" and command=="save":
            self._require(self.output.is_file() and not self.window.state["dirty"],"El guardado no terminó con una copia validada.")
            self._require(_digest(self.source.read_bytes())==self.source_hash,"El archivo original fue alterado.")
            self._step("guardar_copia",path=str(self.output),sha256=_digest(self.output.read_bytes()),source_unchanged=True)
            self.stage = "reopened"
            self._require(self.window.open_document(self.output),"La GUI no inició la reapertura de la copia.")
        elif self.stage=="reopened" and is_page and result["number"]==0:
            self._require(self.window.state["page_count"]==self.page_count,"El número de páginas cambió al reabrir.")
            self._assert_date(moved=True)
            self._require(_digest(result["png"])==self.final_render_hash,"La copia reabierta no se renderiza igual que el PDF de trabajo.")
            self._step("reabrir_y_verificar_texto_posicion_apariencia",text="11/09/2026",occurrences=1,render_matches_before_save=True)
            self.stage = "reopened_control"
            self._request_control(False)
        elif self.stage=="reopened_control" and is_page and result["number"]==1:
            self._require(_signature(result["model"])==self.control_signature,"Cambió el texto, estilo o geometría de la página 2 no editada.")
            self._require(_digest(result["png"])==self.control_render_hash,"Cambió el render de la página 2 no editada.")
            self._require("10/09/2026" in self._text(result["model"]),"Se eliminó otra aparición legítima de la fecha original.")
            self._step("verificar_pagina_2_intacta",glyphs_and_geometry_equal=True,render_equal=True,original_date_retained=True)
            self.stage = "complete"
            # The control read never replaces the visible edited page.
            QTimer.singleShot(150,self.finish)

    def fail(self,error):
        self.finish(error=str(error))

    def _timed_out(self):
        self.finish(error=f"Tiempo límite de 55 segundos excedido en el paso {self.stage}.",terminate=True)

    def finish(self,error=None,terminate=False):
        if self.finished:
            return
        self.finished = True
        self.timeout.stop()
        ok = error is None and self.stage=="complete"
        screenshot_saved = False
        try:
            if self.source_hash is not None:
                self._require(_digest(self.source.read_bytes())==self.source_hash,"El original no conserva su huella inicial.")
            if ok:
                self.window.statusBar().showMessage("Prueba completada · Copia guardada, reabierta y verificada")
                screenshot_saved = self.window.grab().save(str(self.screenshot))
                self._require(screenshot_saved,"No se pudo guardar la captura final de la ventana.")
        except Exception as exc:
            ok,error = False,str(exc)
        report = {
            "ok":ok,"error":error,"frozen":bool(getattr(sys,"frozen",False)),
            "app_version":__version__,
            "exe_sha256":_digest(Path(sys.executable).read_bytes()) if getattr(sys,"frozen",False) else None,
            "stage":self.stage,"elapsed_seconds":round(time.perf_counter()-self.started,3),
            "source":str(self.source),"source_sha256":self.source_hash,
            "output":str(self.output),"page_count":self.page_count,
            "glyph_count":len(self.window.model.glyphs) if self.window.model else 0,
            "screenshot":str(self.screenshot) if screenshot_saved else None,
            "steps":self.steps,"engine_validation_reports":self.edit_reports,
            "scope":"Corpus digital sintético; operación por GUI/worker, sin QtTest y sin motor en el proceso GUI",
        }
        try:
            if self.safe_report:
                self.report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        except Exception as exc:
            ok = False
            print(f"No se pudo escribir el informe smoke: {exc}",file=sys.stderr)
        self.window._allow_close = True
        if terminate:
            # A timed-out test must not remain alive waiting for ProcessPool's
            # atexit join. Only this application owns children in the smoke run.
            self.window._closed = True
            self.window.poller.stop()
            self.window.thumbnail_timer.stop()
            self.window.arrow_timer.stop()
            for process in multiprocessing.active_children():
                process.terminate()
                process.join(timeout=.3)
            self.window.pool.shutdown(wait=False,cancel_futures=True)
        self.window.close()
        QApplication.instance().exit(0 if ok else 1)
