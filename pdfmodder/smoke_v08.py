"""Frozen acceptance for v0.8 through MainWindow and its real PDF worker.

No PDF engine or QtTest is imported into the GUI. Each stage waits for the
actual worker result and (where appropriate) the displayed PDF page.
"""
from __future__ import annotations

import os
from PySide6.QtCore import QTimer

from .model import EditRequest
from .smoke import VerticalSmoke,_digest,_signature


class AdvancedSmoke(VerticalSmoke):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.output=self.report_path.parent/'smoke-v08-editado.pdf'
        self.image_output=self.report_path.parent/'smoke-v08-imagen.png'
        self.timeout.start(55000)
        self.main_signature=None
        self.main_render=None
        try:
            for target in (self.output,self.image_output):
                self._require(target.resolve()!=self.source and not (
                    target.exists() and os.path.samefile(target,self.source)),
                    'La prueba 0.8 no puede guardar sobre el PDF original.')
        except Exception as exc:
            QTimer.singleShot(0,lambda error=str(exc):self.fail(error))

    def _send(self,command,payload=None,callback=None):
        self._require(self.window._submit(command,payload,callback),
                      f'No se pudo iniciar {command} en el paso {self.stage}.')

    def _visible(self,model):
        return ''.join(g.text for g in model.glyphs if g.mode!=3 and g.opacity>0)

    def _choose_visible(self,text):
        glyphs=[g for g in self.window.model.glyphs if g.mode!=3 and g.opacity>0]
        joined=''.join(g.text for g in glyphs)
        self._require(joined.count(text)==1,f'La selección visible {text!r} no es única.')
        start=joined.index(text)
        selected=glyphs[start:start+len(text)]
        self._require(''.join(g.text for g in selected)==text,'No se aisló la selección por caracteres.')
        self.window.canvas.set_selection([g.id for g in selected])
        return selected

    def _preview_request(self,text,**options):
        request=EditRequest(0,self.window.canvas.ids[:],text=text,
                            revision=self.window.model.revision,**options)
        self._send('preview',{'request':request},self.window._previewed)

    def _pending(self,result,index):
        self._require(self.window.state['preview'] and self.window.state['history_index']==index,
                      'La vista previa alteró el historial antes de Aplicar.')
        report=self.window.last_report or {}
        self._require(report.get('verified'),'Falta la validación real del motor.')
        self.edit_reports.append(report)
        self.preview_render_hash=_digest(result['png'])
        return report

    def _committed(self,result,index):
        self._require(not self.window.state['preview'] and self.window.state['history_index']==index,
                      'La operación no quedó como una única transacción de historial.')
        self._require(_digest(result['png'])==self.preview_render_hash,
                      'El PDF aplicado no coincide con la vista previa real.')

    def _assert_date_ocr(self,model):
        self._require(self._visible(model).count('11/09/2026')==1,'La fecha visible nueva falta o se duplicó.')
        self._require('10/09/2026' not in self._text(model),'Quedó la fecha anterior en el texto o en el OCR.')
        self._require(any(g.mode==3 for g in model.glyphs),'Se retiró indiscriminadamente toda la capa OCR.')

    def _assert_main(self,result):
        model=result['model']
        text=self._visible(model)
        self._assert_date_ocr(model)
        self._require(text.count('LUNA')==1 and text.count('SOL')==1,
                      'Cambió una coincidencia no marcada o falta la sustitución marcada.')
        self._require('Parrafo editado' in text and 'Segunda linea' in text and
                      'Este parrafo se puede redistribuir.' not in text,
                      'No se conservó la edición del párrafo.')
        self._require('Vecino que debe conservarse.' in text,'Se alteró el texto vecino.')
        images=result.get('images',[])
        self._require(len(images)==2,'Cambió la cantidad de instancias de imagen en la página principal.')
        self._require((images[0]['width_px'],images[0]['height_px'])==(96,144),
                      'El recorte y giro no tienen las dimensiones de píxel solicitadas.')
        self._require(tuple(images[0]['rect'])==self.image_rect,'Cambió la caja de la imagen editada.')
        self._require((images[1]['width_px'],images[1]['height_px'])==(180,120),
                      'Se alteró la segunda instancia compartida de la imagen.')

    def _advance(self,command,result):
        page=command=='page' and result.get('model') is not None
        main=page and result['number']==0
        if self.stage=='opening' and main:
            self.page_count=self.window.state['page_count']
            self._require(self.page_count==2,'La prueba requiere herramientas-v08.pdf con dos páginas.')
            self._require(not self.window.state.get('issues'),'El corpus sintético presenta restricciones.')
            selected=self._choose_visible('10/09/2026')
            self._require(self._text(result['model']).count('10/09/2026')==2,'Falta el duplicado OCR de prueba.')
            self.original_origin=selected[0].origin
            self.original_font,self.original_size=selected[0].font,selected[0].size
            self.image_rect=tuple(result['images'][0]['rect'])
            self._step('abrir_seleccionar_fecha_visible_con_ocr',visible_characters=len(selected),page_count=2)
            self.stage='date_preview'
            self._preview_request('11/09/2026',auto_width=True,line_reflow=False)
        elif self.stage=='date_preview' and main:
            report=self._pending(result,0)
            self._require(report.get('ocr_cleanup',{}).get('removed_characters',0)>0,
                          'La fecha se editó sin comprobar la retirada del duplicado OCR.')
            self._require(report.get('auto_width'),'La fecha no ejercitó la anchura automática.')
            self._assert_date_ocr(result['model'])
            date=self._choose_visible('11/09/2026')
            self._require(date[0].font==self.original_font and abs(date[0].size-self.original_size)<.001 and
                          all(abs(a-b)<.035 for a,b in zip(date[0].origin,self.original_origin)),
                          'La fecha cambió de fuente, tamaño o posición.')
            self._step('previsualizar_fecha_y_retirar_ocr_duplicado',removed_ocr=report['ocr_cleanup']['removed_characters'])
            self.stage='date_commit'
            self.window.commit()
        elif self.stage=='date_commit' and main:
            self._committed(result,1)
            self._step('aplicar_fecha_ocr',single_history_entry=True)
            self.stage='matches'
            self._send('find_replacements',{'query':'SOL','whole_word':True})
        elif self.stage=='matches' and command=='find_replacements':
            matches=sorted(result['matches'],key=lambda m:(m['page'],m['origins'][0]))
            self._require(len(matches)==3 and [m['page'] for m in matches]==[0,0,1],
                          'La búsqueda no enumeró las tres apariciones de SOL en las dos páginas.')
            self.match_ids=[matches[0]['id'],matches[2]['id']]
            self._step('revisar_tres_coincidencias_marcar_dos',matches=3,chosen=2,pages=[0,1])
            self.stage='matches_preview_main'
            self._send('preview_replacements',{'match_ids':self.match_ids,'replacement':'LUNA','auto_width':True},self.window._previewed)
        elif self.stage=='matches_preview_main' and main:
            report=self._pending(result,1)
            self._require(report.get('match_count')==2 and len(report.get('edits',[]))==2,
                          'La sustitución no validó exactamente las dos coincidencias marcadas.')
            self._require(self._visible(result['model']).count('LUNA')==1 and self._visible(result['model']).count('SOL')==1,
                          'La previsualización cambió la coincidencia que quedó sin marcar.')
            self._step('previsualizar_coincidencia_pagina_1',unselected_SOL_retained=True)
            self.stage='matches_preview_other'
            self._send('review_page',{'number':1})
        elif self.stage=='matches_preview_other' and command=='review_page':
            text=self._visible(result['model'])
            self._require(text.count('LUNA')==1 and 'SOL' not in text,'La segunda coincidencia no aparece en la vista previa.')
            self._require(result['state']['preview'] and result['state']['history_index']==1,
                          'Revisar otra página alteró el historial.')
            self._step('previsualizar_coincidencia_pagina_2',render_sha256=_digest(result['png']))
            self.stage='matches_commit'
            self.window.commit()
        elif self.stage=='matches_commit' and main:
            self._committed(result,2)
            self._step('aplicar_dos_reemplazos_en_una_transaccion',history_index=2)
            self.stage='image_asset'
            self._send('export_image',{'page':0,'image_id':'0','revision':self.window.model.revision})
        elif self.stage=='image_asset' and command=='export_image':
            self.original_asset_hash=_digest(result['image_bytes'])
            self._require(result['ext']=='png' and (result['width_px'],result['height_px'])==(180,120),
                          'La exportación no corresponde al recurso sintético original.')
            self.stage='image_export'
            self._send('export_image',{'page':0,'image_id':'0','revision':self.window.model.revision,'path':str(self.image_output)})
        elif self.stage=='image_export' and command=='export_image':
            self._require(self.image_output.is_file() and _digest(self.image_output.read_bytes())==self.original_asset_hash,
                          'El archivo de imagen exportado no conserva los bytes del recurso leído.')
            self._step('exportar_imagen_original',path=str(self.image_output),sha256=self.original_asset_hash)
            self.stage='image_preview'
            self._send('image',{'operation':'edit','page':0,'image_id':'0','revision':self.window.model.revision,
                               'crop':(.1,.1,.9,.9),'rotation':90},self.window._previewed)
        elif self.stage=='image_preview' and main:
            report=self._pending(result,2)
            self._require(report.get('instance_only') and report.get('original_box_preserved'),
                          'La imagen no confirmó aislamiento de instancia y caja original.')
            self._require((result['images'][0]['width_px'],result['images'][0]['height_px'])==(96,144),
                          'El PDF de vista previa no contiene los píxeles recortados y girados.')
            self._step('previsualizar_recorte_giro_instancia',rotation=90,crop=[.1,.1,.9,.9])
            self.stage='image_commit'
            self.window.commit()
        elif self.stage=='image_commit' and main:
            self._committed(result,3)
            self._step('aplicar_recorte_giro',single_history_entry=True)
            self.stage='image_shared_same'
            self._send('export_image',{'page':0,'image_id':'1','revision':self.window.model.revision})
        elif self.stage=='image_shared_same' and command=='export_image':
            self._require(_digest(result['image_bytes'])==self.original_asset_hash,'Cambió el recurso de otra instancia de la misma página.')
            self.stage='image_shared_other'
            self._send('export_image',{'page':1,'image_id':'0','revision':self.window.model.revision})
        elif self.stage=='image_shared_other' and command=='export_image':
            self._require(_digest(result['image_bytes'])==self.original_asset_hash,'Cambió el recurso compartido en otra página.')
            self._step('verificar_imagenes_compartidas_intactas',same_page=True,other_page=True)
            self._choose_visible('Este parrafo se puede redistribuir.')
            self.stage='paragraph_preview'
            self._preview_request('Parrafo editado\n\nSegunda linea',width=450,height=70,reflow=True,
                                  line_spacing=16,paragraph_spacing=6,line_reflow=False)
        elif self.stage=='paragraph_preview' and main:
            report=self._pending(result,3)
            self._require(report.get('paragraph_layout')=={'line_spacing':16,'paragraph_spacing':6,'width':450,'height':70},
                          'No se aplicaron las dimensiones y separación del párrafo solicitadas.')
            self._assert_main(result)
            self._step('previsualizar_parrafo_interlineado_saltos',line_spacing_pt=16,paragraph_spacing_pt=6)
            self.stage='paragraph_commit'
            self.window.commit()
        elif self.stage=='paragraph_commit' and main:
            self._committed(result,4)
            self._assert_main(result)
            self.before_organizer_revision=self.window.model.revision
            self.before_organizer_hash=_digest(result['png'])
            self._step('aplicar_parrafo',history_index=4)
            self.stage='organizer_info'
            self._send('organizer_info')
        elif self.stage=='organizer_info' and command=='organizer_info':
            self._require(len(result['pages'])==2 and result['source_id']=='current','No se cargó el orden inicial de páginas.')
            plan=[{'source':'current','page':1,'rotation':90},
                  {'source':'current','page':0,'rotation':0},
                  {'source':'current','page':0,'rotation':0},
                  {'source':'blank','width':595,'height':842,'rotation':0}]
            self._step('revisar_orden_final_paginas',page_map=[1,0,0,None],rotation_first=90)
            self.stage='organizer_preview'
            self._send('organize_pages',{'plan':plan},self.window._previewed)
        elif self.stage=='organizer_preview' and main:
            report=self._pending(result,4)
            self._require(self.window.state['page_count']==4 and report.get('page_map')==[1,0,0,None],
                          'El organizador no previsualizó el orden, duplicado e inserción solicitados.')
            self._require(result['model'].rotation==90 and self._visible(result['model']).count('LUNA')==1,
                          'La primera página no es la antigua página de control girada.')
            self._step('previsualizar_reordenar_duplicar_girar_insertar',pages=4)
            self.stage='organizer_commit'
            self.window.commit()
        elif self.stage=='organizer_commit' and main:
            self._committed(result,5)
            self.page_count=4
            self.organized_revision=self.window.model.revision
            self.organized_hash=_digest(result['png'])
            self._step('aplicar_organizador_en_una_transaccion',history_index=5)
            self.stage='undo'
            self.window.history('undo')
        elif self.stage=='undo' and main:
            self._require(self.window.state['page_count']==2 and self.window.state['history_index']==4 and
                          self.window.model.revision==self.before_organizer_revision and
                          _digest(result['png'])==self.before_organizer_hash,'Deshacer no recuperó exactamente PDF, páginas y render previos.')
            self._step('deshacer_organizador_exactamente',revision_and_render_equal=True)
            self.stage='redo'
            self.window.history('redo')
        elif self.stage=='redo' and main:
            self._require(self.window.state['page_count']==4 and self.window.state['history_index']==5 and
                          self.window.model.revision==self.organized_revision and _digest(result['png'])==self.organized_hash,
                          'Rehacer no recuperó exactamente el PDF organizado.')
            self._step('rehacer_organizador_exactamente',revision_and_render_equal=True)
            self.stage='save'
            self._require(self.window.save_as(self.output),'No se inició Guardar como.')
        elif self.stage=='save' and command=='save':
            self._require(self.output.is_file() and not self.window.state['dirty'],'El guardado no produjo una copia validada.')
            self._step('guardar_copia_v08',path=str(self.output),sha256=_digest(self.output.read_bytes()))
            self.stage='reopen'
            self._require(self.window.open_document(self.output),'No se inició la reapertura de la copia.')
        elif self.stage=='reopen' and main:
            self._require(self.window.state['page_count']==4 and result['model'].rotation==90 and
                          _digest(result['png'])==self.organized_hash,'La copia reabierta no conserva las páginas, giro y apariencia.')
            self._require(self._visible(result['model']).count('LUNA')==1,'La página reordenada perdió su texto nuevo.')
            self._step('reabrir_pagina_reordenada_girada',pages=4,render_equal=True)
            self.stage='reopen_main'
            self.window.go_page(1)
        elif self.stage=='reopen_main' and page and result['number']==1:
            self._assert_main(result)
            self.main_signature,self.main_render=_signature(result['model']),_digest(result['png'])
            self._require(self.main_render==self.before_organizer_hash,'La página principal cambió visualmente al organizar y reabrir.')
            self._step('reabrir_fecha_ocr_parrafo_coincidencias_imagen',render_equal=True)
            self.stage='reopen_duplicate'
            self._send('page',{'number':2,'zoom':self.window.zoom})
        elif self.stage=='reopen_duplicate' and page and result['number']==2:
            self._assert_main(result)
            self._require(_signature(result['model'])==self.main_signature and _digest(result['png'])==self.main_render,
                          'La página duplicada no conserva el contenido y apariencia de la instancia original.')
            self._step('verificar_pagina_duplicada',glyphs_and_render_equal=True)
            self.stage='reopen_blank'
            self._send('page',{'number':3,'zoom':self.window.zoom})
        elif self.stage=='reopen_blank' and page and result['number']==3:
            self._require(not result['model'].glyphs and not result.get('images') and
                          result['model'].width==595 and result['model'].height==842,
                          'La página insertada no está vacía o tiene dimensiones distintas.')
            self._require(_digest(self.source.read_bytes())==self.source_hash,'El original no conserva sus bytes.')
            self._step('verificar_pagina_insertada_y_original',blank=True,source_unchanged=True)
            self.stage='complete'
            QTimer.singleShot(150,self.finish)
