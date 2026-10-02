"""Panel explícito de selección, grupos y orden de objetos de la página."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,
    QListWidgetItem,QAbstractItemView,QPushButton,QComboBox,QDoubleSpinBox,
    QLineEdit,QInputDialog,QDialogButtonBox)
from .model import mm,pt


class ObjectDialog(QDialog):
    def __init__(self,info,parent=None,selected_ids=(),selected_image=None):
        super().__init__(parent)
        self.setWindowTitle('Objetos y bloques · selección explícita')
        self.resize(760,620);self.info=info;self.result_request=None
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Selecciona varios textos e imágenes con Ctrl o Mayús. Arrastra las filas para fijar el orden de unión.'))
        self.items=QListWidget();self.items.setObjectName('objectItems')
        self.items.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items.setDragDropMode(QAbstractItemView.InternalMove)
        layout.addWidget(self.items)
        for item in info['items']:
            r=item['rect'];label=('Texto · ' if item['kind']=='text' else '')+item['label']
            row=QListWidgetItem(f'{label[:105]}   ({mm(r[0]):.1f}, {mm(r[1]):.1f} mm)')
            row.setData(Qt.UserRole,[item]);self.items.addItem(row)
            row.setSelected(bool(set(item.get('ids',[]))&set(selected_ids)) or item.get('image_id')==selected_image)
        for group in info.get('groups',[]):
            row=QListWidgetItem('Grupo · '+group['name']+('' if group['valid'] else ' · selección desactualizada'))
            row.setData(Qt.UserRole,group.get('items',[]));row.setData(Qt.UserRole+1,group['id'])
            row.setToolTip(group.get('reason','Grupo explícito guardado en este PDF.'))
            if not group['valid']:row.setFlags(row.flags() & ~Qt.ItemIsEnabled)
            self.items.addItem(row)
        groupbar=QHBoxLayout();self.group_name=QLineEdit('Grupo');self.group_name.setPlaceholderText('Nombre del grupo')
        groupbar.addWidget(self.group_name)
        self._button(groupbar,'Agrupar',lambda:self.choose('group'))
        self._button(groupbar,'Desagrupar',self.ungroup)
        self._button(groupbar,'Unir textos',lambda:self.choose('join'))
        self._button(groupbar,'Dividir texto…',self.split)
        layout.addLayout(groupbar)
        movement=QHBoxLayout();self.dx=self._spin();self.dy=self._spin()
        movement.addWidget(QLabel('Δ X mm'));movement.addWidget(self.dx)
        movement.addWidget(QLabel('Δ Y mm'));movement.addWidget(self.dy)
        self._button(movement,'Mover conjunto',lambda:self.choose('move'))
        layout.addLayout(movement)
        arrange=QHBoxLayout();self.alignment=QComboBox()
        for label,value in [('Izquierda','align_left'),('Centro horizontal','align_center'),('Derecha','align_right'),
                            ('Arriba','align_top'),('Centro vertical','align_middle'),('Abajo','align_bottom'),
                            ('Distribuir horizontalmente','distribute_x'),('Distribuir verticalmente','distribute_y')]:
            self.alignment.addItem(label,value)
        arrange.addWidget(self.alignment)
        self._button(arrange,'Previsualizar',lambda:self.choose(self.alignment.currentData()))
        self._button(arrange,'Traer delante',lambda:self.choose('front'))
        self._button(arrange,'Enviar detrás',lambda:self.choose('back'))
        layout.addLayout(arrange)
        self.message=QLabel('Las operaciones conservan el tamaño de letra. Revisa el PDF antes de aplicar; no se mueven elementos ajenos a la selección.')
        self.message.setWordWrap(True);layout.addWidget(self.message)
        close=QDialogButtonBox(QDialogButtonBox.Cancel);close.rejected.connect(self.reject);layout.addWidget(close)

    @staticmethod
    def _spin():
        widget=QDoubleSpinBox();widget.setRange(-2000,2000);widget.setDecimals(3);return widget

    def _button(self,row,label,callback):
        button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)

    def selection(self):
        # A group row and its individual members can both be selected. Keep
        # the user's visible row order, but never operate on a glyph or image
        # twice (particularly when joining fragments into a paragraph).
        result=[];seen_glyphs=set();seen_images=set()
        for index in range(self.items.count()):
            row=self.items.item(index)
            if not row.isSelected():continue
            for item in row.data(Qt.UserRole):
                if item['kind']=='text':
                    ids=[g for g in item.get('ids',[]) if g not in seen_glyphs]
                    if not ids:continue
                    seen_glyphs.update(ids);result.append(dict(item,ids=ids))
                else:
                    identity=item.get('image_id')
                    if identity in seen_images:continue
                    seen_images.add(identity);result.append(dict(item))
        return result

    def choose(self,operation,**extra):
        items=self.selection()
        if not items:self.message.setText('Selecciona los elementos que deseas modificar.');return
        if operation=='join' and any(i['kind']!='text' for i in items):
            self.message.setText('Para unir un párrafo selecciona solamente fragmentos de texto.');return
        request={'page':self.info['page'],'items':items,'operation':operation,'revision':self.info['revision']}
        if operation=='group':request['name']=self.group_name.text()
        if operation=='move':request.update(dx=pt(self.dx.value()),dy=pt(self.dy.value()))
        request.update(extra);self.result_request=request;self.accept()

    def ungroup(self):
        rows=self.items.selectedItems()
        if len(rows)!=1 or not rows[0].data(Qt.UserRole+1):
            self.message.setText('Selecciona una única fila de grupo para desagrupar.');return
        self.choose('group',group_id=rows[0].data(Qt.UserRole+1))

    def split(self):
        items=self.selection()
        if not items or any(i['kind']!='text' for i in items):
            self.message.setText('Selecciona sólo texto para dividirlo.');return
        ids=list(dict.fromkeys(g for item in items for g in item['ids']))
        if len(ids)<2:return
        at,ok=QInputDialog.getInt(self,'Dividir bloque','Número de caracteres del primer fragmento:',len(ids)//2,1,len(ids)-1)
        if ok:self.choose('group',split_at=at)


class ObjectEditing:
    def _init_objects(self):
        self.objects_action=self._action('Objetos y bloques…',self.open_objects,'Ctrl+G')

    def open_objects(self):
        if self.busy or not self.model or self.state.get('preview') or self.canvas.editor.isVisible():return
        def received(info):
            dialog=ObjectDialog(info,self,self.canvas.ids,self.canvas.image_id)
            if self._exec_edit_dialog(dialog)!=QDialog.Accepted:return
            request=dialog.result_request
            if request['operation']=='join':
                ids=list(dict.fromkeys(g for item in request['items'] for g in item['ids']))
                self.canvas.set_selection(ids)
                self.start_rich_edit(join_items=request['items'])
            elif request['operation']=='group':
                def grouped(result):
                    self._submit('commit',callback=self._edited)
                self._submit('object_operation',request,grouped)
            else:self._submit('object_operation',request,self._previewed)
        self._submit('object_info',{'page':self.page_number},received)
