"""Herramientas Qt de composición y páginas; el motor permanece en el worker."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction,QColor,QImageReader,QIcon
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QPushButton,QDialogButtonBox,QDoubleSpinBox,QCheckBox,QLineEdit,QListWidget,
    QFileDialog,QToolBar,QGroupBox,QMessageBox,QAbstractItemView)
from .model import pt,mm,union


class ImageDialog(QDialog):
    def __init__(self,rect,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Tamaño y posición de imagen')
        layout=QVBoxLayout(self)
        form=QFormLayout()
        self.boxes=[]
        values=(rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1])
        for name,label,value in zip(('imageX','imageY','imageWidth','imageHeight'),('X','Y','Anchura','Altura'),values):
            box=QDoubleSpinBox()
            box.setObjectName(name)
            box.setDecimals(3)
            box.setRange(0. if len(self.boxes)<2 else .1,3000.)
            box.setSuffix(' mm')
            box.setValue(mm(value))
            form.addRow(label,box)
            self.boxes.append(box)
        layout.addLayout(form)
        self.ratio=values[2]/max(values[3],.01)
        self.lock=QCheckBox('Conservar proporciones')
        self.lock.setChecked(True)
        layout.addWidget(self.lock)
        self.boxes[2].valueChanged.connect(lambda value:self._ratio(3,value/self.ratio))
        self.boxes[3].valueChanged.connect(lambda value:self._ratio(2,value*self.ratio))
        note=QLabel('La imagen se incorpora al contenido PDF. Si la colocas encima de otro contenido, lo cubrirá visualmente.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Previsualizar')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _ratio(self,index,value):
        if self.lock.isChecked():
            self.boxes[index].blockSignals(True)
            self.boxes[index].setValue(value)
            self.boxes[index].blockSignals(False)

    def rect(self):
        x,y,w,h=(pt(box.value()) for box in self.boxes)
        return (x,y,x+w,y+h)


class MergeDialog(QDialog):
    def __init__(self,parent=None,has_document=False):
        super().__init__(parent)
        self.setWindowTitle('Combinar archivos PDF')
        self.resize(630,380)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Los archivos se incorporarán en este orden:'))
        self.files=QListWidget()
        self.files.setObjectName('mergeFileList')
        layout.addWidget(self.files)
        row=QHBoxLayout()
        for label,callback in (('Añadir PDFs…',self.add_files),('Subir',lambda:self.move(-1)),('Bajar',lambda:self.move(1)),('Quitar',self.remove)):
            button=QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.append=QCheckBox('Añadir al final del documento de trabajo actual')
        self.append.setChecked(has_document)
        self.append.setEnabled(has_document)
        layout.addWidget(self.append)
        metadata=QLabel('El resultado conserva los metadatos del documento actual o, si creas uno nuevo, del primer PDF. Los archivos de origen se mantienen intactos.')
        metadata.setWordWrap(True)
        layout.addWidget(metadata)
        self.error=QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Combinar')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Elegir PDFs','','Documentos PDF (*.pdf)')
        self.files.addItems(paths)

    def remove(self):
        if self.files.currentRow()>=0:
            self.files.takeItem(self.files.currentRow())

    def move(self,delta):
        i=self.files.currentRow()
        if 0<=i+delta<self.files.count():
            item=self.files.takeItem(i)
            self.files.insertItem(i+delta,item)
            self.files.setCurrentRow(i+delta)

    def paths(self):
        return [self.files.item(i).text() for i in range(self.files.count())]

    def validate(self):
        minimum=1 if self.append.isChecked() else 2
        if self.files.count()<minimum:
            self.error.setText(f'Selecciona al menos {minimum} archivos PDF.')
        else:
            self.accept()


class ExtendedEditing:
    def _exec_edit_dialog(self,dialog):
        # A nested modal event loop still runs QTimers. Avoid scheduling a
        # thumbnail while the user accepts a dialog: _submit would be busy and
        # could silently discard that request. These dialogs open only at idle.
        timer=getattr(self,'thumbnail_timer',None)
        active=bool(timer and timer.isActive())
        if active:
            timer.stop()
        try:
            return dialog.exec()
        finally:
            if active:
                timer.start()

    def _create_extended_ui(self,panel_layout):
        self._placement=None
        self._font_catalog=None
        self._text_draft=None
        self._restore_image_rect=None
        self._image_data=None
        bar=QToolBar('Editar y organizar',self)
        bar.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(bar)
        def action(label,slot,checkable=False):
            a=QAction(label,self)
            a.setCheckable(checkable)
            a.triggered.connect(slot)
            bar.addAction(a)
            return a
        self.add_text_action=action('Agregar texto',self.begin_text)
        self.format_action=action('Tipografía / formato…',self.format_selection)
        self.add_image_action=action('Agregar imagen…',self.begin_image)
        self.image_mode_action=action('Seleccionar imágenes',self.toggle_image_mode,True)
        bar.addSeparator()
        self.delete_pages_action=action('Eliminar páginas…',lambda:self.page_dialog('delete'))
        self.extract_pages_action=action('Extraer páginas…',lambda:self.page_dialog('extract'))
        self.merge_action=action('Combinar PDFs…',self.choose_merge)
        self.pages.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.image_box=QGroupBox('Imagen seleccionada')
        form=QFormLayout(self.image_box)
        self.image_info=QLabel('Activa Seleccionar imágenes y pulsa una imagen.')
        self.image_info.setWordWrap(True)
        form.addRow(self.image_info)
        self.image_props_button=QPushButton('Posición / tamaño…')
        self.image_props_button.clicked.connect(self.image_properties)
        form.addRow(self.image_props_button)
        self.image_lock=QCheckBox('Conservar proporciones al arrastrar')
        self.image_lock.setChecked(True)
        self.image_lock.toggled.connect(lambda value:setattr(self.canvas,'lock_image_ratio',value))
        form.addRow(self.image_lock)
        self.image_remove_button=QPushButton('Eliminar imagen seleccionada')
        self.image_remove_button.clicked.connect(lambda:self.delete_image(self.canvas.image_id))
        form.addRow(self.image_remove_button)
        panel_layout.insertWidget(3,self.image_box)
        self.image_box.hide()
        self.canvas.placement_clicked.connect(self.placed)
        self.canvas.image_selected.connect(self.image_selection_changed)
        self.canvas.image_transform_requested.connect(self.transform_image)
        self.canvas.image_delete_requested.connect(self.delete_image)

    def _refresh_extended(self):
        if not hasattr(self,'add_text_action'):
            return
        ready=bool(self.state) and not self.busy and not self.state.get('preview') and not self.canvas.editor.isVisible()
        editable=ready and not self.state.get('issues') and not self.compare_action.isChecked()
        tagged=bool(self.state.get('tagged'))
        placing=bool(self._placement)
        for action in (self.add_text_action,self.add_image_action,self.image_mode_action):
            action.setEnabled(editable and not placing)
            action.setToolTip('El contenido nuevo requiere elegir su orden de lectura; las imágenes informativas necesitan una descripción.' if tagged and action is not self.image_mode_action else action.text().replace('&',''))
        capabilities=self.state.get('page_capabilities',{})
        for action,key in ((self.delete_pages_action,'delete'),(self.extract_pages_action,'extract')):
            allowed=capabilities.get(key,not tagged)
            action.setEnabled(editable and not placing and allowed)
            action.setToolTip(capabilities.get('reason') or 'Se conservarán las etiquetas de las páginas restantes.' if tagged else action.text().replace('&',''))
        self.format_action.setEnabled(editable and bool(self.canvas.ids) and not placing)
        self.merge_action.setEnabled(not self.busy and not self.canvas.editor.isVisible() and not self.state.get('preview') and not placing and not tagged)
        self.merge_action.setToolTip('PDF etiquetado: combinar necesita remapear las etiquetas y todavía no está disponible.' if tagged else 'Combinar PDFs…')
        self.image_box.setVisible(self.canvas.image_mode)
        im=self.canvas.selected_image()
        self.image_props_button.setEnabled(editable and bool(im and im.get('editable')))
        self.image_remove_button.setEnabled(self.image_props_button.isEnabled())
        if placing:
            for action in (self.open_action,self.save_action,self.undo_action,self.redo_action,self.compare_action,self.fit_page_action,self.fit_width_action,self.search_action):
                action.setEnabled(False)
            self.pages.setEnabled(False)
            self.zoom_box.setEnabled(False)
            self.property_box.setEnabled(False)
            self.cancel_button.setEnabled(not self.busy)

    def _sync_page_list(self):
        if not self.state:
            return
        count=self.state['page_count']
        self.page_number=max(0,min(self.page_number,count-1))
        if self.pages.count()!=count:
            from PySide6.QtWidgets import QListWidgetItem
            from PySide6.QtCore import QSize
            self.pages.blockSignals(True)
            self.pages.clear()
            for i in range(count):
                item=QListWidgetItem(f'Página {i+1}')
                item.setSizeHint(QSize(118,158))
                item.setTextAlignment(Qt.AlignHCenter)
                self.pages.addItem(item)
            self.pages.setCurrentRow(self.page_number)
            self.pages.blockSignals(False)
            self._thumbnail_pages.clear()
            self._thumbnail_order.clear()

    def _catalog(self,callback):
        if self._font_catalog is not None:
            callback(self._font_catalog)
        else:
            def loaded(result):
                self._font_catalog=result['catalog']
                callback(self._font_catalog)
            self._submit('font_catalog',callback=loaded)

    def begin_text(self):
        if self.canvas.image_mode:
            self.image_mode_action.setChecked(False)
            self.toggle_image_mode(False)
        self._placement='text'
        self.canvas.placement_mode=True
        self.canvas.setCursor(Qt.CrossCursor)
        self._notice('Pulsa en la página donde comenzará el texto nuevo. Escape cancela.')
        self._refresh_actions()

    def begin_image(self):
        path,_=QFileDialog.getOpenFileName(self,'Elegir imagen','','Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        if not path:
            return
        try:
            if Path(path).stat().st_size>50*1024*1024:
                raise ValueError('La imagen supera el límite de 50 MB.')
            self._image_data=Path(path).read_bytes()
            reader=QImageReader(path)
            size=reader.size()
            if not reader.canRead() or not size.isValid() or size.width()<=0 or size.height()<=0:
                raise ValueError('No se pueden leer las dimensiones de esta imagen. Elige un archivo de imagen válido.')
            self._image_ratio=size.width()/size.height() if size.isValid() else 1.5
            transformation=reader.transformation()
            if int(getattr(transformation,'value',transformation))&4:
                self._image_ratio=1/self._image_ratio
            self._placement='image'
            self.canvas.placement_mode=True
            self.canvas.setCursor(Qt.CrossCursor)
            self._notice('Pulsa en la página para situar la imagen. Después podrás ajustar tamaño y posición.')
            self._refresh_actions()
        except (OSError,ValueError,TypeError) as exc:
            self._error(str(exc))

    def _cancel_placement(self):
        self._placement=None
        self.canvas.placement_mode=False
        self.canvas.unsetCursor()
        self._refresh_actions()

    def placed(self,x,y):
        kind=self._placement
        if not self.model:
            self._cancel_placement()
            return
        page_width=self.model.cropbox[2]-self.model.cropbox[0]
        page_height=self.model.cropbox[3]-self.model.cropbox[1]
        if not (0<=x<page_width and 0<=y<page_height):
            self._error('Pulsa dentro del área visible de la página. Escape cancela la colocación.')
            return
        self._cancel_placement()
        if kind=='text':
            self._catalog(lambda catalog:self.text_dialog(catalog,x,y))
        elif kind=='copied_text':
            self.place_copied_text(x,y)
        elif kind=='image':
            width=min(pt(60),page_width-x,(page_height-y)*self._image_ratio)
            dialog=ImageDialog((x,y,x+width,y+width/self._image_ratio),self)
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:
                self.add_image(self._image_data,dialog.rect())

    def text_dialog(self,catalog,x,y):
        from .dialogs import TextDialog
        draft=self._text_draft or {}
        width=min(pt(75),self.model.cropbox[2]-self.model.cropbox[0]-x)
        height=min(pt(25),self.model.cropbox[3]-self.model.cropbox[1]-y)
        dialog=TextDialog(catalog,self,text=draft.get('text',''),rect=(x,y,x+width,y+height),size=draft.get('size',12),font_name=draft.get('font_name') or 'Helvetica',color=draft.get('color') or (0,0,0))
        if draft.get('font_file'):
            dialog.font_picker.set_font_file(draft['font_file'])
        if draft.get('align') in ('left','center','right'):
            dialog.align_box.setCurrentIndex(dialog.align_box.findData(draft['align']))
        if 'reflow' in draft:
            dialog.reflow_box.setChecked(draft['reflow'])
        if 'allow_overlap' in draft:
            dialog.allow_overlap_box.setChecked(draft['allow_overlap'])
        if self._exec_edit_dialog(dialog)==QDialog.Accepted:
            values=dialog.values()
            self._text_draft=values.copy()
            self.insert_text(values)

    def insert_text(self,values):
        accessibility=self._new_content_accessibility()
        if accessibility is None:
            return
        request={**values,**accessibility,'page':self.page_number,'revision':self.model.revision}
        self._restore_ids=None
        self._submit('insert_text',{'request':request},self._previewed)

    def _new_content_accessibility(self,*,image=False):
        if not self.state.get('tagged'):
            return {}
        from .accessibility_ui import AccessibilityDialog
        dialog=AccessibilityDialog(self,image=image)
        if self._exec_edit_dialog(dialog)!=QDialog.Accepted:
            self._notice('Contenido nuevo cancelado. El documento conserva su estado anterior.')
            return None
        return dialog.values()

    def format_selection(self):
        context=(self.page_number,self.model.revision,tuple(self.canvas.ids))
        def show(catalog):
            if context!=(self.page_number,self.model.revision,tuple(self.canvas.ids)):
                self._error('La selección cambió mientras se consultaban las fuentes. Selecciona de nuevo.')
                return
            from .dialogs import TextDialog
            selected=self.model.selected(self.canvas.ids)
            if not selected:
                self._error('Selecciona texto antes de cambiar su formato.')
                return
            if len({(g.font,g.size,g.color,g.opacity,g.direction,g.mode) for g in selected})>1:
                self._error('La selección mezcla estilos. Selecciona un tramo uniforme para cambiar su tipografía; el grupo completo sí se puede mover.')
                return
            first=selected[0]
            rect=union(g.bbox for g in selected)
            dialog=TextDialog(catalog,self,text=self.model.text(self.canvas.ids),rect=rect,size=first.size,font_name=first.font,color=first.color,existing=True)
            dialog.allow_overlap_box.setChecked(self.allow_overlap_box.isChecked())
            anchor=self.anchor_box.currentData()
            if anchor=='decimal':
                dialog.align_box.addItem(f'Decimal ({self.decimal_box.currentText()})','decimal')
            index=dialog.align_box.findData(anchor)
            if index>=0:
                dialog.align_box.setCurrentIndex(index)
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:
                values=dialog.values()
                # A deliberate typography dialog never redistributes the
                # unselected remainder of a line as a side effect.
                request=self._request(text=values['text'],formatting=True,adjust_line=False)
                for field in ('width','height','size','font_name','font_file','color','reflow','allow_overlap'):
                    setattr(request,field,values[field])
                request.reflow=request.reflow or '\n' in request.text
                request.auto_height=self.auto_height_box.isChecked() and (request.reflow or request.size is not None or bool(request.font_name or request.font_file))
                request.anchor=values['align']
                self._restore_ids=self.canvas.ids[:]
                self._submit('preview',{'request':request},self._previewed)
        self._catalog(show)

    def toggle_image_mode(self,checked):
        self.canvas.image_mode=checked
        self.mode_box.setEnabled(not checked)
        if checked:
            self.canvas.set_selection([])
            self._notice('Pulsa una imagen. Arrastra su interior para moverla o el tirador azul para redimensionarla.')
        else:
            self.canvas.select_image(None)
        self._refresh_actions()

    def image_selection_changed(self,item):
        if not hasattr(self,'image_info'):
            return
        if item:
            rect=item['rect']
            self.image_info.setText(f"{item.get('width_px','?')} × {item.get('height_px','?')} píxeles\nX {mm(rect[0]):.3f} · Y {mm(rect[1]):.3f} mm\n{mm(rect[2]-rect[0]):.3f} × {mm(rect[3]-rect[1]):.3f} mm\n"+('Imagen editable' if item.get('editable') else item.get('reason','No se puede aislar esta imagen.')))
        else:
            self.image_info.setText('Selecciona una imagen en la página.')
        self._refresh_actions()

    def add_image(self,data,rect):
        accessibility=self._new_content_accessibility(image=True)
        if accessibility is None:
            return
        self.image_mode_action.setChecked(True)
        self.toggle_image_mode(True)
        payload={'operation':'add','page':self.page_number,'image_bytes':data,'rect':rect,'revision':self.model.revision,**accessibility}
        self._submit('image',payload,self._previewed)

    def transform_image(self,image_id,rect,preview=False):
        payload={'operation':'transform','page':self.page_number,'image_id':image_id,'rect':rect,'revision':self.model.revision}
        self._submit('image' if preview else 'image_apply',payload,self._previewed if preview else self._edited)

    def delete_image(self,image_id):
        if not image_id:
            return
        self._submit('image',{'operation':'delete','page':self.page_number,'image_id':image_id,'revision':self.model.revision},self._previewed)

    def image_properties(self):
        item=self.canvas.selected_image()
        if item:
            dialog=ImageDialog(item['rect'],self)
            if self._exec_edit_dialog(dialog)==QDialog.Accepted:
                self.transform_image(item['id'],dialog.rect(),preview=True)

    def page_dialog(self,operation):
        dialog=QDialog(self)
        dialog.setWindowTitle('Eliminar páginas de la copia' if operation=='delete' else 'Extraer páginas a otro PDF')
        layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Documento de {self.state['page_count']} páginas. Indica números y rangos, por ejemplo: 1,3-5."))
        selected=[self.pages.row(item)+1 for item in self.pages.selectedItems()]
        expression=QLineEdit(','.join(str(i) for i in selected) or str(self.page_number+1))
        expression.setObjectName('pageRange')
        layout.addWidget(expression)
        layout.addWidget(QLabel('Eliminar se puede deshacer. Extraer conserva intacto el documento de trabajo.'))
        note=QLabel('Los marcadores de páginas excluidas se retirarán de la copia. Los enlaces desde páginas conservadas a páginas excluidas bloquean la operación.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Eliminar de la copia' if operation=='delete' else 'Elegir destino…')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if self._exec_edit_dialog(dialog)!=QDialog.Accepted:
            return
        if operation=='delete':
            self.delete_pages(expression.text())
        else:
            source=Path(self.state['path'])
            path,_=QFileDialog.getSaveFileName(self,'Guardar páginas extraídas',str(source.with_name(source.stem+'_paginas.pdf')),'Documento PDF (*.pdf)')
            if path:
                self.extract_pages(expression.text(),path)

    def delete_pages(self,expression):
        self._submit('delete_pages',{'expression':expression},self._edited)

    def extract_pages(self,expression,path):
        self._submit('extract_pages',{'expression':expression,'path':str(path)},lambda result:self._notice(f"Páginas extraídas y verificadas: {result['path']}"))

    def choose_merge(self):
        dialog=MergeDialog(self,bool(self.state))
        if self._exec_edit_dialog(dialog)==QDialog.Accepted:
            if dialog.append.isChecked():
                self.merge_pdfs(dialog.paths())
            elif self._confirm_discard():
                self.combine_pdfs(dialog.paths())

    def merge_pdfs(self,paths):
        self._submit('merge',{'paths':[str(p) for p in paths]},self._edited)

    def combine_pdfs(self,paths):
        payload={'paths':[str(p) for p in paths]}
        for name in ('config_path','history_dir'):
            if getattr(self,name):
                payload[name]=str(getattr(self,name))
        def combined(result):
            self.model=None
            self.page_number=0
            self.compare_action.setChecked(False)
            self._edited(result)
        self._submit('combine',payload,combined)
