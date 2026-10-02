"""Frozen-capable rich-editor acceptance through MainWindow and its PDF worker.

No QtTest or PDF engine is imported into the GUI process. Visible controls,
QTextCursor and normal asynchronous application commands drive the whole flow.
"""
from pathlib import Path
import os

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import QApplication

from .smoke import VerticalSmoke, _digest, _signature


class RichSmoke(VerticalSmoke):
    def __init__(self,window,source,report_path):
        super().__init__(window,source,report_path)
        self.output=self.report_path.parent/'smoke-v09-editado.pdf'
        self.initial_render_hash=None
        self.accepted_render_hash=None
        self.added_text='Texto nuevoSegunda líneaOtro párrafo'
        self.timeout.setInterval(180000)
        self.timeout.start()
        if self.output==self.source or (self.output.exists() and os.path.samefile(self.output,self.source)):
            QTimer.singleShot(0,lambda:self.fail('La copia de prueba coincide con el documento de origen.'))

    def _timed_out(self):
        self.finish(error=f'Tiempo límite de 180 segundos excedido en el paso {self.stage}.',terminate=True)

    def _range(self,start,end):
        cursor=self.window.canvas.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end,QTextCursor.KeepAnchor)
        self.window.canvas.editor.setTextCursor(cursor)
        return cursor

    def _edit_date(self):
        editor=self.window.canvas.editor
        self._require(editor.isVisible() and editor.rich_mode,'No se abrió el editor sobre la página.')
        self._require(not editor.textCursor().hasSelection(),'Entrar en edición seleccionó todo el texto.')
        self._require(editor.toolbar.accept.isVisible() and editor.toolbar.cancel.isVisible(),
                      'No aparecen los controles Aceptar / Cancelar junto al texto.')
        self._range(1,2).insertText('1')
        self._require(editor.toPlainText()=='11/09/2026','La escritura no sustituyó exclusivamente el carácter elegido.')
        self._range(0,2)
        editor.merge_style(color=(.8,0.,0.),underline=True,char_spacing=.15)
        chars=[(c,run) for run in editor.payload()['runs'] for c in run['text']]
        self._require(all(run['underline'] for _,run in chars[:2]),'Falta el formato del fragmento seleccionado.')
        self._require(all(not run.get('underline') for _,run in chars[2:]),'El subrayado afectó al resto de la fecha.')
        self._step('cursor_y_formato_por_fragmentos',selection=[0,2],text='11/09/2026',
                   font_preview_warning=editor.font_warning or None)

    def _verify_date(self):
        chosen=self._select('11/09/2026')
        self._require('10/09/2026' not in self._text(self.window.model),'Quedó la fecha antigua en la página editada.')
        self._require(all(g.color[0]>.7 and g.color[1]<.05 for g in chosen[:2]),'No se guardó el color de las dos cifras.')
        self._require(all(abs(g.size-self.original_size)<.001 for g in chosen),'La edición alteró el tamaño de letra.')
        self._require(all(g.font==self.original_font for g in chosen),'La edición sustituyó la fuente.')
        self._require(all(g.color[0]<.7 for g in chosen[2:]),'El formato del fragmento afectó a caracteres no seleccionados.')

    def _advance(self,command,result):
        is_page=command=='page' and result.get('model') is not None
        if self.stage=='opening' and is_page and result['number']==0:
            self.page_count=self.window.state['page_count']
            self._require(self.page_count>=2,'La prueba necesita digital.pdf y su página de control.')
            self.initial_render_hash=_digest(result['png'])
            selected=self._select('10/09/2026')
            self.original_font=selected[0].font;self.original_size=selected[0].size
            self.original_origin=selected[0].origin
            self._step('abrir_y_seleccionar',page_count=self.page_count,characters=len(selected))
            self.stage='original_control';self._request_control(True)
        elif self.stage=='original_control' and is_page and result['number']==1:
            self.control_signature=_signature(result['model'])
            self.control_render_hash=_digest(result['png'])
            self.stage='rich_selection';self.window.start_edit()
        elif self.stage=='rich_selection' and command=='rich_selection':
            self.stage='live_preview';self._edit_date()
        elif self.stage=='live_preview' and command=='rich_preview':
            self._require(result['report'].get('verified'),'La vista del PDF no tiene validación del motor.')
            self._require(self.window.state['history_index']==0 and not self.window.state['preview'],
                          'La vista en vivo modificó el historial antes de aceptar.')
            self.preview_render_hash=_digest(result['png']);self.edit_reports.append(result['report'])
            self._step('vista_previa_pdf_real',render_sha256=self.preview_render_hash,history_unchanged=True)
            self.stage='committed';self.window.canvas.editor.toolbar.accept.click()
        elif self.stage in ('committed','new_text_committed') and command=='rich_prepare':
            expected_history=0 if self.stage=='committed' else 1
            self._require(result.get('token') and result['report'].get('verified'),
                          'Aceptar no preparó una transacción validada.')
            self._require(result['state']['history_index']==expected_history and not result['state']['preview'],
                          'Preparar la aceptación alteró el documento o el historial antes de confirmar.')
            self._step('preparar_aceptacion_sin_modificar',history_index=expected_history,
                       transaction_validated=True)
        elif self.stage=='committed' and is_page and result['number']==0:
            self._require(self.window.state['history_index']==1,'La sesión de escritura no produjo una sola operación.')
            self._require(not self.window.canvas.editor.isVisible(),'El editor no se cerró al aceptar.')
            self._verify_date()
            self.accepted_render_hash=_digest(result['png'])
            self._require(self.accepted_render_hash==self.preview_render_hash,'El PDF aplicado difiere de la vista previa.')
            self.edit_reports.append(self.window.last_report)
            self._step('aceptar_fragmento',preview_matches_commit=True,history_index=1)
            self.stage='undo';self.window.history('undo')
        elif self.stage=='undo' and is_page and result['number']==0:
            self._require(self.window.state['history_index']==0,'Deshacer no recuperó el estado inicial.')
            self._require(_digest(result['png'])==self.initial_render_hash,'Deshacer no recuperó exactamente la apariencia.')
            self._step('deshacer_exacto',render_sha256=self.initial_render_hash)
            self.stage='redo';self.window.history('redo')
        elif self.stage=='redo' and is_page and result['number']==0:
            self._require(_digest(result['png'])==self.accepted_render_hash,'Rehacer cambió la apariencia aplicada.')
            self._verify_date();self._step('rehacer_exacto',history_index=self.window.state['history_index'])
            self._select('/09/2026')
            self.stage='copy_format';self.window.copy_text_format()
        elif self.stage=='copy_format' and command=='rich_selection':
            self._require(self.window._format_copy is not None,'No se copió el formato verificado.')
            self.window.begin_copied_text();self.window.placed(50,700)
            editor=self.window.canvas.editor
            self._require(editor.isVisible() and not editor.payload()['ids'],'No se abrió un cuadro nuevo de texto.')
            editor.insertPlainText('Texto nuevo')
            QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.ShiftModifier))
            editor.insertPlainText('Segunda línea')
            QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier))
            editor.insertPlainText('Otro párrafo')
            raw=''.join(run['text'] for run in editor.payload()['runs'])
            self._require(raw=='Texto nuevo\u2028Segunda línea\nOtro párrafo','Intro y Mayús+Intro no producen saltos diferentes.')
            self._step('anadir_con_formato_y_saltos',paragraph_and_soft_break_distinct=True)
            self.stage='new_text_preview'
        elif self.stage=='new_text_preview' and command=='rich_preview':
            self._require(result['report'].get('verified'),'No se validó el texto añadido.')
            self.preview_render_hash=_digest(result['png']);self.edit_reports.append(result['report'])
            self.stage='new_text_committed';self.window.canvas.editor.toolbar.accept.click()
        elif self.stage=='new_text_committed' and is_page and result['number']==0:
            self._require(self.window.state['history_index']==2,'Añadir el párrafo no produjo una única operación.')
            self._require(self.added_text in self._text(result['model']),'El texto añadido no existe como caracteres reales.')
            self.final_render_hash=_digest(result['png'])
            self._require(self.final_render_hash==self.preview_render_hash,'La inserción guardable difiere de su vista previa.')
            self.edit_reports.append(self.window.last_report)
            self._step('aceptar_texto_nuevo',history_index=2)
            self.stage='saved';self._require(self.window.save_as(self.output),'No se inició Guardar como.')
        elif self.stage=='saved' and command=='save':
            self._require(self.output.is_file() and not self.window.state['dirty'],'No se completó el guardado.')
            self._step('guardar_copia',path=str(self.output),sha256=_digest(self.output.read_bytes()))
            self.stage='reopened';self._require(self.window.open_document(self.output),'No se inició la reapertura.')
        elif self.stage=='reopened' and is_page and result['number']==0:
            self._require(self.window.state['page_count']==self.page_count,'La copia cambió el número de páginas.')
            self._verify_date()
            self._require(self.added_text in self._text(result['model']),'El texto nuevo desapareció al reabrir.')
            self._require(_digest(result['png'])==self.final_render_hash,'El guardado alteró la apariencia.')
            self._step('reabrir_pdf_real',render_equal=True,text_and_font_verified=True)
            self.stage='reopened_control';self._request_control(False)
        elif self.stage=='reopened_control' and is_page and result['number']==1:
            self._require(_signature(result['model'])==self.control_signature,'Cambió el contenido o formato de la página de control.')
            self._require(_digest(result['png'])==self.control_render_hash,'Cambió la imagen de la página de control.')
            self._require(_digest(self.source.read_bytes())==self.source_hash,'Se alteró el archivo de origen.')
            self._step('verificar_original_y_pagina_2',source_unchanged=True,control_page_identical=True)
            self.stage='cancel_selection';self._select('11/09/2026');self.window.start_edit()
        elif self.stage=='cancel_selection' and command=='rich_selection':
            editor=self.window.canvas.editor
            editor.insertPlainText('CANCELADO')
            editor.toolbar.cancel.click()
            self._require(not editor.isVisible() and not self.window.state['dirty'],'Cancelar alteró el documento guardado.')
            self._require('CANCELADO' not in self._text(self.window.model),'El borrador cancelado llegó al PDF.')
            self._step('cancelar_sin_modificar',history_unchanged=True)
            self.stage='complete';QTimer.singleShot(150,self.finish)
