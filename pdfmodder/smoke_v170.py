"""Recorrido dirigido del ejecutable: edición y nuevas funciones con PDF sintético."""
from io import BytesIO
from pathlib import Path

from PySide6.QtCore import QMimeData, QTimer
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader

from .smoke import VerticalSmoke


class SmokeV170(VerticalSmoke):
    def __init__(self,*args):
        super().__init__(*args)
        self.extra_started=False
        self.extra_complete=False
        self.backup_clipboard=QMimeData()
        original=QApplication.clipboard().mimeData()
        for name in original.formats() if original else []:
            self.backup_clipboard.setData(name,original.data(name))
        self.secure_path=self.report_path.parent/'smoke-v170-protegido.pdf'
        self.timeout.setInterval(90000)
        self.timeout.start()

    def finish(self,error=None,terminate=False):
        if not error and self.stage=='complete' and not self.extra_started:
            self.extra_started=True
            self.stage='v170_properties'
            for name in ('document_properties_action','document_security_action','copy_action_v170',
                         'cut_action_v170','paste_action_v170','delete_action_v170','update_action_v170'):
                action=getattr(self.window,name,None)
                self._require(action is not None and not action.icon().isNull(),f'Falta acción/icono {name}')
            self._require(set(self.window.mode_actions_v170)=={'select','write','move'},'Faltan botones de modos')
            self._step('toolbar_modes_and_icons')
            self._require(self.window._submit('document_properties'),'No se consultan propiedades')
            return
        if self.finished:return
        QApplication.clipboard().setMimeData(self.backup_clipboard)
        super().finish(error,terminate)

    def _advance(self,command,result):
        page=command=='page' and result.get('model') is not None and result['number']==0
        if self.stage=='v170_properties' and command=='document_properties':
            self._require(result['page_count']==2 and result['editable'],'Propiedades incompatibles')
            self._step('inspect_properties',page_count=result['page_count'])
            self.stage='v170_metadata_preview'
            self.window._submit('edit_document_metadata',{'metadata':{'title':'Prueba PDF Modder 1.7.0',
                                'author':'Corpus sintético','creationDate':'D:20261001120000+02\'00\''}},self.window._previewed)
        elif self.stage=='v170_metadata_preview' and page:
            self._require(self.window.state['preview'] and self.window.state['history_index']==0,'Metadatos sin vista previa')
            self.stage='v170_metadata_commit'
            self.window.commit()
        elif self.stage=='v170_metadata_commit' and page:
            self._require(self.window.state['history_index']==1,'Metadatos sin historial')
            self.stage='v170_metadata_verify'
            self.window._submit('document_properties')
        elif self.stage=='v170_metadata_verify' and command=='document_properties':
            self._require(result['metadata']['title']=='Prueba PDF Modder 1.7.0' and result['metadata']['author']=='Corpus sintético','Metadatos incorrectos')
            self._step('edit_metadata_and_commit',history_index=1)
            self.stage='v170_security'
            self.window._submit('export_secure_pdf',{'path':str(self.secure_path),'mode':'password','password':'Clave-sintetica-170'})
        elif self.stage=='v170_security' and command=='export_secure_pdf':
            reader=PdfReader(BytesIO(self.secure_path.read_bytes()))
            self._require(reader.is_encrypted and not reader.decrypt('incorrecta'),'La copia no está protegida')
            self._require(bool(reader.decrypt('Clave-sintetica-170')) and len(reader.pages)==2,'No se abre con la credencial')
            self._require('11/09/2026' in reader.pages[0].extract_text() and reader.metadata.title=='Prueba PDF Modder 1.7.0','La copia cifrada perdió contenido')
            self._require(self.window.state['history_index']==1,'La exportación alteró el trabajo')
            self._step('export_password_and_independent_decryption',history_unchanged=True)
            self.stage='v170_copy'
            self._select('11/09/2026')
            self.window.canvas.setFocus()
            self.window.clipboard_copy_v170()
        elif self.stage=='v170_copy' and command=='clipboard_copy':
            self._require(result.get('bundle',{}).get('kind')=='text','No se copió texto con formato')
            self._step('copy_formatted_pdf_text')
            self.stage='v170_paste'
            self.window.clipboard_paste_v170()
            self.window.placed(220.,690.)
        elif self.stage=='v170_paste' and page:
            text=self._text(self.window.model)
            self._require(text.count('11/09/2026')==2,'No se pegó una sola copia')
            self._require(self.window.state['history_index']==2,'Pegar debe ser una unidad de historial')
            start=text.rindex('11/09/2026')
            self.window.canvas.set_selection([g.id for g in self.window.model.glyphs[start:start+10]])
            self.stage='v170_delete'
            self.window.canvas.setFocus()
            self.window.clipboard_delete_v170()
        elif self.stage=='v170_delete' and page:
            self._require(self._text(self.window.model).count('11/09/2026')==1,'Eliminar no aisló la copia')
            self._require(self.window.state['history_index']==3,'Eliminar sin historial')
            self._step('paste_and_delete_preserve_original_occurrence')
            self.stage='v170_undo'
            self.window.history('undo')
        elif self.stage=='v170_undo' and page:
            self._require(self._text(self.window.model).count('11/09/2026')==2,'Deshacer no recuperó la copia')
            self.stage='v170_redo'
            self.window.history('redo')
        elif self.stage=='v170_redo' and page:
            self._require(self._text(self.window.model).count('11/09/2026')==1,'Rehacer perdió aislamiento')
            self._step('clipboard_undo_redo')
            self.extra_complete=True
            self.stage='complete'
            QTimer.singleShot(0,self.finish)
        else:
            super()._advance(command,result)
