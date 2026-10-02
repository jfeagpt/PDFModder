"""Herramientas 0.8: diálogos locales que delegan toda operación PDF al worker."""
from collections import deque
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QEvent
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import (QToolBar,QGroupBox,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,
    QComboBox,QListWidget,QListWidgetItem,QMenu,QFileDialog,QDialog,QApplication,QWidget)
from .model import mm,pt,union


class AdvancedEditing:
    def _create_advanced_ui(self,panel_layout,form):
        self.auto_width_box=QCheckBox('Ajustar anchura al texto');self.auto_width_box.setObjectName('autoAreaWidth')
        self.auto_width_box.setChecked(True)
        self.auto_width_box.setToolTip('Ajusta el área de una línea sin cambiar tamaño ni escala. En párrafos se conserva la anchura definida para redistribuir.')
        form.insertRow(8,self.auto_width_box)
        self.auto_height_box=QCheckBox('Ajustar altura al texto');self.auto_height_box.setObjectName('autoAreaHeight')
        self.auto_height_box.setChecked(True)
        self.auto_height_box.setToolTip('Adapta la altura al insertar líneas o cambiar el formato, sin reducir letras. Se comprueban el borde de página, los recortes y los vecinos.')
        form.addRow(self.auto_height_box)
        self.allow_overlap_box=QCheckBox('Permitir superponer texto');self.allow_overlap_box.setObjectName('allowTextOverlap')
        self.allow_overlap_box.setToolTip('Permite colocar texto encima de otro. Ambos siguen siendo texto real; revisa la legibilidad en la vista previa.')
        form.addRow(self.allow_overlap_box)
        self.line_spacing_box=self._spin('lineSpacing',0,300,3);self.line_spacing_box.setSuffix(' pt');self.line_spacing_box.setSpecialValueText('Original / automático')
        self.paragraph_spacing_box=self._spin('paragraphSpacing',0,300,3);self.paragraph_spacing_box.setSuffix(' pt')
        self.paragraph_spacing_box.setToolTip('Espacio adicional entre párrafos separados por una línea en blanco.')
        form.addRow('Interlineado',self.line_spacing_box);form.addRow('Separación párrafos',self.paragraph_spacing_box)
        hint=QLabel('Intro: nueva línea. Ctrl+Intro: vista previa. Línea en blanco: nuevo párrafo. La anchura limita el ajuste entre líneas.')
        hint.setWordWrap(True);form.addRow(hint)
        self.ocr_mode_box=QCheckBox('Corregir sólo la capa OCR buscable')
        self.ocr_mode_box.setObjectName('ocrSearchableMode')
        self.ocr_mode_box.setToolTip('Para texto invisible elegido en Elementos: cambia la búsqueda, no las letras de una imagen escaneada.')
        form.addRow(self.ocr_mode_box)
        self.ocr_mode_box.toggled.connect(lambda _:self._refresh_actions())
        bar=QToolBar('Herramientas de revisión',self);self.addToolBarBreak();self.addToolBar(bar)
        self.replace_action=QAction('Buscar y reemplazar…',self);self.replace_action.setShortcut(QKeySequence('Ctrl+H'))
        self.replace_action.triggered.connect(self.open_replace);bar.addAction(self.replace_action)
        self.organize_action=QAction('Organizar páginas…',self);self.organize_action.triggered.connect(self.open_organizer);bar.addAction(self.organize_action)
        self.elements_box=QGroupBox('Elementos de la zona')
        layout=QVBoxLayout(self.elements_box)
        row=QHBoxLayout()
        self.zone_button=QPushButton('Seleccionar zona');self.zone_button.setCheckable(True);self.zone_button.setObjectName('selectElementZone')
        self.zone_button.toggled.connect(lambda active:setattr(self.canvas,'zone_mode',active))
        self.all_elements_button=QPushButton('Toda la página');self.all_elements_button.clicked.connect(self.all_elements)
        row.addWidget(self.zone_button);row.addWidget(self.all_elements_button);layout.addLayout(row)
        self.element_level=QComboBox()
        for label,value in [('Líneas','line'),('Palabras','word'),('Caracteres','character')]:self.element_level.addItem(label,value)
        self.element_level.currentIndexChanged.connect(lambda _:self.refresh_elements())
        layout.addWidget(self.element_level)
        self.element_list=QListWidget();self.element_list.setObjectName('zoneElementList');self.element_list.setMaximumHeight(175)
        self.element_list.currentItemChanged.connect(self.select_element);layout.addWidget(self.element_list)
        self.element_status=QLabel('Dibuja una zona para distinguir elementos superpuestos.');self.element_status.setWordWrap(True);layout.addWidget(self.element_status)
        next_button=QPushButton('Siguiente elemento de la zona');next_button.clicked.connect(self.next_element);layout.addWidget(next_button)
        panel_layout.insertWidget(4,self.elements_box)
        self._element_zone=None
        self.canvas.zone_selected.connect(self.zone_chosen)
        self.canvas.image_context_requested.connect(self.image_context)
        self.image_export_button=QPushButton('Guardar imagen…');self.image_export_button.clicked.connect(lambda:self.export_selected_image())
        self.image_edit_button=QPushButton('Recortar / girar / reemplazar…');self.image_edit_button.clicked.connect(lambda:self.edit_selected_image())
        self.image_box.layout().addRow(self.image_export_button);self.image_box.layout().addRow(self.image_edit_button)
        self.setAcceptDrops(True)
        self.canvas.setAcceptDrops(True);self.canvas.viewport().setAcceptDrops(True)
        QApplication.instance().installEventFilter(self)
        self._advanced_dialog=None

    def _refresh_advanced(self):
        if not hasattr(self,'replace_action'):return
        ready=bool(self.state) and not self.busy and not self.state.get('preview') and not self.canvas.editor.isVisible()
        editable=ready and not self.state.get('issues') and not self.compare_action.isChecked()
        self.replace_action.setEnabled(editable)
        page_caps=self.state.get('page_capabilities',{})
        self.organize_action.setEnabled(editable and page_caps.get('supported',not self.state.get('tagged')))
        self.organize_action.setToolTip(page_caps.get('reason') or 'Revisa el orden final antes de aplicar; se conserva la estructura compatible.')
        self.elements_box.setEnabled(ready)
        image=self.canvas.selected_image()
        self.image_export_button.setEnabled(ready and bool(image))
        self.image_edit_button.setEnabled(editable and bool(image and image.get('editable')))
        hidden=bool(self.model and self.canvas.ids and all(g.mode==3 for g in self.model.selected(self.canvas.ids)))
        self.ocr_mode_box.setEnabled(editable and hidden)
        ocr=hidden and self.ocr_mode_box.isChecked()
        for widget in (self.size_box,self.x_box,self.y_box,self.height_box,self.anchor_box,
                       self.reflow_box,self.line_spacing_box,self.paragraph_spacing_box):widget.setEnabled(not ocr)
        if ocr:self.line_reflow_box.setEnabled(False)

    def _extend_request(self,request):
        request.allow_overlap=self.allow_overlap_box.isChecked()
        if request.text is not None:
            if '\n' in request.text or '\r' in request.text:
                request.text=request.text.replace('\r\n','\n').replace('\r','\n')
                request.reflow=True
                request.line_reflow=False
            request.auto_height=self.auto_height_box.isChecked() and (request.reflow or request.size is not None)
            request.auto_width=self.auto_width_box.isChecked() and not request.reflow
            request.line_spacing=self.line_spacing_box.value() or None
            request.paragraph_spacing=self.paragraph_spacing_box.value()
            if self.model and any(g.mode==3 for g in self.model.selected(request.ids)):
                if not self.ocr_mode_box.isChecked():raise ValueError('Activa «Corregir sólo la capa OCR buscable». La imagen escaneada permanecerá igual.')
                request.ocr_mode='searchable'
                request.line_reflow=request.reflow=False
                request.line_spacing=None;request.paragraph_spacing=0.;request.height=None;request.size=None;request.anchor='left'
        return request

    def _advanced_page(self):
        self._element_zone=None
        self.refresh_elements()
        report=self.last_report or {}
        if report.get('auto_width') and report.get('page')==self.page_number:
            self.width_box.setValue(mm(report['area_width']))
        if report.get('auto_height') and report.get('page')==self.page_number:
            self.height_box.setValue(mm(report['area_height']))

    def all_elements(self):
        self._element_zone=None;self.canvas.zone_rect=None;self.canvas._draw_overlays();self.refresh_elements()

    def zone_chosen(self,rect):
        self._element_zone=rect;self.zone_button.setChecked(False);self.refresh_elements()

    def refresh_elements(self):
        if not hasattr(self,'element_list') or self.model is None:return
        from .elements import zone_elements
        records=zone_elements(self.model,self.canvas.images,self._element_zone,self.element_level.currentData())
        self.element_list.blockSignals(True);self.element_list.clear()
        for record in records:
            item=QListWidgetItem(record['label']);item.setData(Qt.UserRole,record)
            r=record['rect'];item.setToolTip(f'X {mm(r[0]):.3f} mm; Y {mm(r[1]):.3f} mm. '+record.get('reason',''))
            self.element_list.addItem(item)
        self.element_list.blockSignals(False)
        self.element_status.setText(f'{len(records)} elementos. Pulsa uno para seleccionarlo, incluso si está superpuesto.')

    def select_element(self,item,*_):
        if not item or self.busy:return
        record=item.data(Qt.UserRole)
        self.zone_button.setChecked(False)
        if record['kind']=='image':
            self.image_mode_action.setChecked(True);self.toggle_image_mode(True)
            match=next((i for i in self.canvas.images if i['id']==record['id']),None)
            if match:self.canvas.select_image(match)
        else:
            self.image_mode_action.setChecked(False);self.toggle_image_mode(False)
            self.canvas.set_selection(record['ids'])
            if record['ocr']:self._notice('Has seleccionado texto OCR invisible. Corregir la capa buscable no modifica la imagen escaneada.')
        self.canvas.ensureVisible(self.canvas.scene_rect(record['rect']),20,20)
        self._refresh_actions()

    def next_element(self):
        if self.element_list.count():self.element_list.setCurrentRow((self.element_list.currentRow()+1)%self.element_list.count())

    @staticmethod
    def _drop_paths(mime):
        if not mime.hasUrls():return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower()=='.pdf']

    def dragEnterEvent(self,event):
        if len(self._drop_paths(event.mimeData()))==1 and not self.busy:event.acceptProposedAction()
        else:event.ignore()

    def dragMoveEvent(self,event):self.dragEnterEvent(event)

    def dropEvent(self,event):
        paths=self._drop_paths(event.mimeData())
        if self.busy or len(paths)!=1:
            self._notice('Arrastra un único PDF para abrirlo. Para varios utiliza Organizar páginas o Combinar PDFs.');event.ignore();return
        if self._confirm_discard():
            self.canvas.editor.hide();self._editing_context=None
            self.open_document(paths[0]);event.acceptProposedAction()
        else:event.ignore()

    def eventFilter(self,obj,event):
        if (event.type() in (QEvent.DragEnter,QEvent.DragMove,QEvent.Drop) and
                isinstance(obj,QWidget) and obj.window() is self and self._drop_paths(event.mimeData())):
            if event.type() in (QEvent.DragEnter,QEvent.DragMove):self.dragEnterEvent(event);return True
            self.dropEvent(event);return True
        return super().eventFilter(obj,event)

    def image_context(self,image_id,position):
        if self.busy or self.state.get('preview'):return
        menu=QMenu(self);menu.setObjectName('imageContextMenu')
        save=menu.addAction('Guardar / exportar imagen…')
        edit=menu.addAction('Recortar / girar / reemplazar…')
        item=self.canvas.selected_image();edit.setEnabled(bool(item and item.get('editable')) and not self.state.get('issues'))
        selected=menu.exec(position)
        if selected==save:self.export_selected_image(image_id)
        elif selected==edit:self.edit_selected_image(image_id)

    def _image_payload(self,image_id=None):
        return {'page':self.page_number,'image_id':image_id or self.canvas.image_id,'revision':self.model.revision}

    def export_selected_image(self,image_id=None):
        if not self.canvas.selected_image() or self.busy:return
        payload=self._image_payload(image_id)
        def got(asset):
            path,_=QFileDialog.getSaveFileName(self,'Guardar imagen del PDF',f"imagen-pagina-{self.page_number+1}.{asset['ext']}",f"Imagen (*.{asset['ext']})")
            if path:self._submit('export_image',{**payload,'path':path},lambda r:self._notice('Imagen guardada: '+r['path']))
        self._submit('export_image',payload,got)

    def edit_selected_image(self,image_id=None):
        if not self.canvas.selected_image() or self.busy:return
        payload=self._image_payload(image_id)
        def got(asset):
            from .image_editor import ImageEditorDialog
            dialog=ImageEditorDialog(asset.get('preview_png') or asset['image_bytes'],self,
                                    frame_rect=asset.get('rect'),initial_operation=asset.get('image_operation'))
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:
                self._submit('image',{**payload,'operation':'edit',**dialog.operation()},self._previewed)
        self._submit('export_image',payload,got)

    def _start_dialog_jobs(self,dialog):
        queue=deque();timer=QTimer(dialog);timer.setInterval(30)
        active=[True]
        self._advanced_dialog=dialog
        def pump():
            if not active[0] or self.busy or not queue:return
            command,payload,callback=queue.popleft();dialog.set_busy(True)
            def ready(result):
                if active[0]:dialog.set_busy(False);callback(result)
            self._submit(command,payload,ready)
        def submit(command,payload,callback):queue.append((command,payload,callback));pump()
        def error(message):
            if active[0]:queue.clear();dialog.set_error(message)
        self.error_raised.connect(error)
        def close(*_):
            active[0]=False;queue.clear();timer.stop();self.error_raised.disconnect(error);self._advanced_dialog=None
        dialog.finished.connect(close);timer.timeout.connect(pump);timer.start()
        return submit

    def open_replace(self):
        if self.busy or not self.state:return
        from .search_dialog import SearchReplaceDialog
        selection={'page':self.page_number,'ids':self.canvas.ids[:],'revision':self.model.revision} if self.canvas.ids else None
        dialog=SearchReplaceDialog(self.search_box.text(),selection,self)
        submit=self._start_dialog_jobs(dialog)
        dialog.find_requested.connect(lambda params:submit('find_replacements',params,lambda r:dialog.set_matches(r['matches'])))
        dialog.preview_requested.connect(lambda ids,text,auto:submit('preview_replacements',{'match_ids':ids,'replacement':text,'auto_width':auto},lambda r:dialog.set_preview(r['png'],r['report'])))
        dialog.page_requested.connect(lambda number:submit('review_page',{'number':number},lambda r:dialog.set_preview(r['png'],r['report'])))
        def commit():
            def committed(result):dialog.accept();self._edited(result)
            submit('commit',{},committed)
        dialog.apply_requested.connect(commit)
        result=self._exec_edit_dialog(dialog)
        if result!=QDialog.Accepted:
            source=self.state.get('path')
            def discard_pending():
                if self._closed or self.state.get('path')!=source:return
                if self.busy:QTimer.singleShot(30,discard_pending);return
                if self.state.get('preview'):self._submit('cancel',callback=lambda _:self.load_page())
            discard_pending()

    def open_organizer(self):
        if self.busy:return
        def loaded(info):
            from .page_organizer import PageOrganizerDialog
            dialog=PageOrganizerDialog(info['pages'],self,capabilities=self.state.get('page_capabilities'))
            paths={};submit=self._start_dialog_jobs(dialog)
            def thumbnail(source,page):
                payload={'page':page}
                if source!='current':payload['path']=paths[source]
                submit('organizer_thumbnail',payload,lambda r:dialog.set_thumbnail(source,page,r['png']))
            dialog.thumbnail_requested.connect(thumbnail)
            def imports(new_paths,position):
                offset=[position]
                for path in new_paths:
                    def done(result):
                        paths[result['source_id']]=result['path']
                        dialog.add_source(result['source_id'],result['pages'],Path(result['path']).name,offset[0])
                        offset[0]+=len(result['pages'])
                    submit('organizer_info',{'path':path},done)
            dialog.import_requested.connect(imports)
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:
                self._submit('organize_pages',{'plan':dialog.plan(),'paths':paths},self._previewed)
        # Do not enter a modal loop inside the poller's own timeout callback:
        # Qt will not reenter that timer to receive subsequent thumbnail jobs.
        self._submit('organizer_info',{},lambda info:QTimer.singleShot(0,lambda:loaded(info)))
