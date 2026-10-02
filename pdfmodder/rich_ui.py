"""Connect the rich drafting surface to the single PDF worker.

Every preview starts at the immutable history snapshot. Late results are
discarded by generation; accepting always validates the latest draft again.
"""
from copy import deepcopy
from PySide6.QtCore import Qt,QTimer,QRect
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox,QLabel,QGroupBox,QVBoxLayout
from .model import union,transform_rect,pt


class RichEditing:
    def _init_rich(self,panel_layout):
        self._rich_active=False;self._rich_loading=False;self._rich_generation=0
        self._rich_serial=0;self._rich_pending=None;self._rich_accept_pending=False
        self._format_copy=None;self._rich_initial_png=None
        self._rich_timer=QTimer(self);self._rich_timer.setSingleShot(True)
        self._rich_timer.timeout.connect(self._rich_pump)
        self.canvas.rich_changed.connect(self._rich_changed)
        self.canvas.rich_accept.connect(self._rich_accept)
        self.canvas.text_resize_requested.connect(self.resize_text_area)
        self.interaction_box=QComboBox();self.interaction_box.setObjectName('interactionMode')
        for label,value in [('Seleccionar','select'),('Escribir','write'),('Mover','move')]:
            self.interaction_box.addItem(label,value)
        self.interaction_box.currentIndexChanged.connect(lambda _:self.canvas.set_interaction_mode(self.interaction_box.currentData()))
        self.toolbar.addWidget(self.interaction_box)
        self.copy_format_action=self._action('Copiar formato',self.copy_text_format)
        self.paste_format_action=self._action('Añadir con formato copiado',self.begin_copied_text)
        self.paste_format_action.setEnabled(False)
        self.rich_result=QGroupBox('Vista del PDF que se guardará')
        layout=QVBoxLayout(self.rich_result)
        self.rich_result_image=QLabel();self.rich_result_image.setAlignment(Qt.AlignCenter)
        self.rich_result_message=QLabel('Escribe para generar la vista del PDF.');self.rich_result_message.setWordWrap(True)
        layout.addWidget(self.rich_result_image);layout.addWidget(self.rich_result_message)
        panel_layout.insertWidget(1,self.rich_result);self.rich_result.hide()

    def start_rich_edit(self,join_items=None):
        if not self.model or not self.canvas.ids or self.state.get('preview'):return
        if self.busy:
            if self._thumbnail_busy:
                context=(self.page_number,self.model.revision,tuple(self.canvas.ids))
                def retry():
                    if not self._closed and self.model and context==(self.page_number,self.model.revision,tuple(self.canvas.ids)):
                        if self.busy:QTimer.singleShot(50,retry)
                        else:self.start_rich_edit(join_items)
                QTimer.singleShot(50,retry)
            return
        self._rich_loading=True;self._rich_generation+=1;generation=self._rich_generation
        self._rich_initial_png=getattr(self,'_page_png',None)
        context=(self.page_number,self.model.revision,tuple(self.canvas.ids))
        def ready(payload):
            self._rich_loading=False
            if generation!=self._rich_generation or context!=(self.page_number,self.model.revision,tuple(self.canvas.ids)):return
            payload=deepcopy(payload)
            if join_items:
                # Explicit row order is chosen by the user, never inferred from
                # proximity. Each selected fragment is concatenated only once.
                original=payload['runs'];text=''.join(r['text'] for r in original)
                index_by_id={c.get('id'):c['index'] for c in payload.get('carets',[]) if 'id' in c}
                if index_by_id:
                    chars=[]
                    for r in original:
                        chars += [dict(r,text=c) for c in r['text']]
                    joined=[]
                    for item in join_items:
                        part=[chars[index_by_id[g]] for g in item['ids'] if g in index_by_id]
                        if joined and part:joined.append(dict(part[0],text=' '))
                        joined.extend(part)
                    payload['runs']=joined
                else:
                    for run in payload['runs']:
                        run['text']=run['text'].replace('\u2028',' ').replace('\n',' ')
                payload['paragraphs']=[{'index':0}]
                payload['carets']=[]
            payload['auto_width']=bool(self.auto_width_box.isChecked() and not join_items)
            payload['auto_height']=bool(self.auto_height_box.isChecked())
            payload['allow_overlap']=bool(self.allow_overlap_box.isChecked())
            self._open_rich_payload(payload)
        self._submit('rich_selection',{'page':self.page_number,'ids':self.canvas.ids[:]},ready)

    def _open_rich_payload(self,payload):
        self._rich_active=True;self._rich_pending=None;self._rich_accept_pending=False;self._rich_serial=0
        self._rich_initial_png=getattr(self,'_page_png',None)
        self._editing_context=(self.page_number,self.model.revision,tuple(self.canvas.ids))
        self.canvas.read_only=False
        self.canvas.start_rich_editor(payload,payload.get('catalog'))
        self.rich_result.show();self.rich_result_image.clear()
        self.rich_result_message.setText('Borrador: la vista PDF aparecerá al escribir. Aceptar vuelve a validar el contenido.')
        self._notice('Escribir: arrastra para seleccionar letras. Intro: párrafo · Mayús+Intro: línea · ✓ Aceptar: Ctrl+Intro · × Cancelar: Esc.')
        self._refresh_actions()

    def _rich_changed(self,payload):
        if not self._rich_active:return
        self._rich_serial+=1;self._rich_pending=deepcopy(payload)
        self.rich_result_message.setText('Actualizando el PDF… El borrador aún no está aplicado.')
        self._rich_timer.start(350)

    def _rich_accept(self,payload):
        if not self._rich_active or self._rich_accept_pending:return
        self._rich_serial+=1;self._rich_pending=deepcopy(payload);self._rich_accept_pending=True
        self.canvas.editor.set_accepting(True)
        self.canvas.editor.toolbar.status.setText('Validando el último borrador para aceptar…')
        self._rich_timer.start(0)

    def _rich_pump(self):
        if not self._rich_active or self._rich_pending is None or self._closed:return
        if self.busy:self._rich_timer.start(50);return
        payload=self._rich_pending;self._rich_pending=None
        generation=self._rich_generation;serial=self._rich_serial;accept=self._rich_accept_pending
        def finished(result):
            if generation!=self._rich_generation:return
            if accept:
                # Validation may be expensive: only the later, fast commit
                # changes history. Escape can discard a prepared result.
                if not self._rich_active or serial!=self._rich_serial:return
                def committed(value):
                    if generation!=self._rich_generation:return
                    self._end_rich();self._edited(value)
                self._submit('rich_commit',{'token':result['token']},committed)
                return
            if serial!=self._rich_serial:return
            self.canvas.set_live_preview(result['png'],'PDF validado · ✓ Aceptar para incorporarlo al historial.')
            report=result.get('report',{})
            rect=report.get('new_bounds') or report.get('rect') or payload.get('rect')
            if rect and self.model:
                display=transform_rect(rect,self.model.rotation_matrix)
                scale=result.get('zoom',self.zoom)
                pixmap=QPixmap();pixmap.loadFromData(result['png'],'PNG')
                cropped=pixmap.copy(QRect(int(display[0]*scale)-5,int(display[1]*scale)-5,
                    max(1,int((display[2]-display[0])*scale)+10),max(1,int((display[3]-display[1])*scale)+10)))
                self.rich_result_image.setPixmap(cropped.scaled(330,190,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            self.rich_result_message.setText('PDF real validado. El tamaño de letra se conserva; Aceptar incorpora una sola operación.')
        self._submit('rich_prepare' if accept else 'rich_preview',{'request':payload,'zoom':self.zoom},finished)

    def _rich_failed(self,command,message):
        if command=='rich_selection':self._rich_loading=False
        if self._rich_active and command in ('rich_preview','rich_apply','rich_prepare','rich_commit'):
            self._rich_accept_pending=False;self.canvas.editor.set_accepting(False)
            self.canvas.editor.toolbar.status.setText(message)
            self.rich_result_message.setText('Borrador no validado: '+message)

    def _end_rich(self):
        self._rich_generation+=1;self._rich_active=False;self._rich_loading=False
        self._rich_pending=None;self._rich_accept_pending=False;self._rich_timer.stop()
        self.canvas.editor.hide();self.canvas.editor.set_accepting(False);self.rich_result.hide()
        self._editing_context=None

    def cancel_rich(self):
        if not (self._rich_active or self._rich_loading):return False
        if self._rich_accept_pending and self.busy and self._command=='rich_commit':
            self._notice('La aceptación ya está en curso. Cuando termine, Deshacer recuperará el estado anterior.')
            return True
        self._end_rich()
        if self._rich_initial_png:self.canvas.set_live_preview(self._rich_initial_png)
        self._notice('Edición cancelada. El PDF y el historial conservan su estado anterior.')
        self._refresh_actions();return True

    def resize_text_area(self,rect):
        if self.busy or not self.model or not self.canvas.ids:return
        self._rich_generation+=1;generation=self._rich_generation
        def loaded(payload):
            if generation!=self._rich_generation:return
            payload.update(rect=list(rect),width=rect[2]-rect[0],height=rect[3]-rect[1],auto_width=False,auto_height=False)
            self._open_rich_payload(payload)
            self._rich_changed(self.canvas.editor.payload())
        self._submit('rich_selection',{'page':self.page_number,'ids':self.canvas.ids[:]},loaded)

    def copy_text_format(self):
        if self.busy or not self.model or not self.canvas.ids:return
        revision=self.model.revision
        def ready(payload):
            styles=[{k:v for k,v in r.items() if k!='text'} for r in payload['runs'] if r['text'].strip()]
            def same(a,b):
                keys=set(a)|set(b)
                for key in keys:
                    x,y=a.get(key),b.get(key)
                    if isinstance(x,(int,float)) and isinstance(y,(int,float)):
                        tolerance=.035 if key=='char_spacing' else .00001
                        if abs(x-y)>tolerance:return False
                    elif x!=y:return False
                return True
            if not styles or any(not same(s,styles[0]) for s in styles):
                self._error('Selecciona letras con un solo formato para copiar su tipografía.');return
            self._format_copy={'style':styles[0],'payload':payload,'revision':revision,'page':self.page_number}
            self.paste_format_action.setEnabled(True)
            self._notice('Formato copiado del primer carácter, con su recurso verificado. Pulsa «Añadir con formato copiado» y elige la posición.')
        self._submit('rich_selection',{'page':self.page_number,'ids':self.canvas.ids[:]},ready)

    def begin_copied_text(self):
        if not self._format_copy or self.busy or not self.model:return
        if self._format_copy['revision']!=self.model.revision or self._format_copy['page']!=self.page_number:
            self._error('El documento o la página cambió. Copia de nuevo el formato para verificar su recurso.');return
        self._placement='copied_text';self.canvas.placement_mode=True;self.canvas.setCursor(Qt.CrossCursor)
        self._notice('Pulsa en la página para añadir texto con la fuente y propiedades copiadas.')

    def place_copied_text(self,x,y):
        payload=deepcopy(self._format_copy['payload']);width=min(pt(75),self.model.cropbox[2]-self.model.cropbox[0]-x)
        height=min(pt(25),self.model.cropbox[3]-self.model.cropbox[1]-y)
        payload.update(ids=[],rect=[x,y,x+width,y+height],width=width,height=height,runs=[dict(self._format_copy['style'],text='')],
                       paragraphs=[{'index':0}],carets=[],auto_width=False,auto_height=False)
        self.canvas.set_selection([])
        self._rich_generation+=1;self._open_rich_payload(payload)
