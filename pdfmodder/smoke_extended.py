"""Aceptación del paquete: composición, imágenes, páginas y guardado real."""
from pathlib import Path
from PySide6.QtCore import QTimer,QByteArray,QBuffer,QIODevice
from PySide6.QtGui import QImage,QColor,QPainter
from .smoke import VerticalSmoke,_signature,_digest


class ExtendedSmoke(VerticalSmoke):
    def __init__(self,*args,**kwargs):
        self.extension_started=False
        super().__init__(*args,**kwargs)
        self.extracted=self.report_path.parent/'smoke-extraidas.pdf'
        self.final_output=self.report_path.parent/'smoke-ampliado.pdf'
        for target in (self.extracted,self.final_output):
            if target.resolve()==self.source:
                QTimer.singleShot(0,lambda:self.fail('El destino de prueba coincide con el original.'))

    def finish(self,error=None,terminate=False):
        if error is None and self.stage=='complete' and not self.extension_started:
            self.extension_started=True
            self.stage='ext_text_preview'
            self.window.insert_text({'x':48.,'y':600.,'width':270.,'height':42.,
                'text':'NUEVO: año, café y 25,50 €','font_name':'Helvetica-Bold',
                'size':13.25,'color':(0.,.2,.5),'align':'left','reflow':True})
            return
        super().finish(error,terminate)

    def _advance(self,command,result):
        if not self.stage.startswith('ext_'):
            super()._advance(command,result)
            return
        page=command=='page' and result.get('model') is not None
        if self.stage=='ext_text_preview' and page:
            self._require(self.window.state['preview'],'No se previsualizó el texto añadido.')
            self._require('NUEVO: año, café y 25,50 €' in self._text(self.window.model),'Falta el texto añadido.')
            self._step('agregar_texto_negrita_color',size=13.25,font='Helvetica-Bold')
            self.stage='ext_text_commit'
            self.window.commit()
        elif self.stage=='ext_text_commit' and page:
            image=QImage(80,40,QImage.Format_RGBA8888)
            image.fill(QColor(0,0,255))
            painter=QPainter(image)
            painter.fillRect(0,0,40,40,QColor(255,80,0))
            painter.end()
            data=QByteArray()
            buffer=QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer,'PNG')
            buffer.close()
            self.stage='ext_image_preview'
            self.window.add_image(bytes(data),(330.,580.,490.,660.))
        elif self.stage=='ext_image_preview' and page:
            self._require(len(result['images'])==2,'No se añadió exactamente una imagen.')
            self.stage='ext_image_commit'
            self.window.commit()
        elif self.stage=='ext_image_commit' and page:
            item=self.window.canvas.selected_image()
            self._require(item and item['editable'],'La nueva imagen no se puede seleccionar/modificar.')
            self._step('agregar_imagen_real',images=2)
            self.stage='ext_image_transformed'
            self.window.transform_image(item['id'],(360.,640.,460.,690.))
        elif self.stage=='ext_image_transformed' and page:
            item=self.window.canvas.selected_image()
            self._require(item and all(abs(a-b)<.035 for a,b in zip(item['rect'],(360,640,460,690))),'No coincide la imagen movida/redimensionada.')
            self._step('mover_y_redimensionar_imagen',rect=list(item['rect']))
            self.stage='ext_extracted'
            self.window.extract_pages('2',self.extracted)
        elif self.stage=='ext_extracted' and command=='extract_pages':
            self._require(self.extracted.is_file() and self.window.state['page_count']==2,'Extraer alteró el documento de trabajo.')
            self._step('extraer_pagina_pdf',path=str(self.extracted))
            self.stage='ext_deleted'
            self.window.delete_pages('2')
        elif self.stage=='ext_deleted' and page:
            self._require(self.window.state['page_count']==1 and self.window.pages.count()==1,'Eliminar no actualizó las páginas.')
            self._step('eliminar_pagina',page_count=1)
            self.stage='ext_undo'
            self.window.history('undo')
        elif self.stage=='ext_undo' and page:
            self._require(self.window.state['page_count']==2,'Deshacer no recuperó la página eliminada.')
            self._step('deshacer_eliminacion',page_count=2)
            self.stage='ext_merged'
            self.window.merge_pdfs([self.extracted])
        elif self.stage=='ext_merged' and page:
            self._require(self.window.state['page_count']==3 and self.window.pages.count()==3,'La unión no añadió una página.')
            self._require(self.window.state['original_pages']==[0,1,None],'La unión perdió el mapa de comparación.')
            self._step('combinar_pdf',page_count=3)
            self.stage='ext_saved'
            self.final_render_hash=_digest(result['png'])
            self.window.save_as(self.final_output)
        elif self.stage=='ext_saved' and command=='save':
            self._require(self.final_output.is_file(),'No se guardó el PDF ampliado.')
            self.stage='ext_reopened'
            self.output=self.final_output
            self.window.open_document(self.final_output)
        elif self.stage=='ext_reopened' and page and result['number']==0:
            self._require(self.window.state['page_count']==3,'Cambió el número de páginas al reabrir.')
            self.page_count=3
            self._require('NUEVO: año, café y 25,50 €' in self._text(result['model']),'El texto nuevo dejó de ser extraíble.')
            self._require(_digest(result['png'])==self.final_render_hash,'El resultado guardado no coincide con el PDF de trabajo.')
            item=next((item for item in result['images'] if all(abs(a-b)<.035 for a,b in zip(item['rect'],(360,640,460,690)))),None)
            self._require(item and item['editable'],'La imagen no sigue siendo editable después de reabrir.')
            self.window.canvas.select_image(item)
            self._step('reabrir_pdf_ampliado',page_count=3,real_text=True,editable_image=True,render_equal=True)
            self.stage='ext_control'
            self._require(self.window._submit('page',{'number':2,'zoom':self.window.zoom}),'No se pudo comprobar la página combinada.')
        elif self.stage=='ext_control' and page and result['number']==2:
            self._require(_signature(result['model'])==self.control_signature,'La página extraída/combinada cambió de contenido o geometría.')
            self._require(_digest(result['png'])==self.control_render_hash,'La página extraída/combinada cambió de apariencia.')
            self._step('verificar_pagina_extraida_y_combinada',glyphs_geometry_pixels_equal=True)
            self.stage='complete'
            QTimer.singleShot(150,self.finish)
