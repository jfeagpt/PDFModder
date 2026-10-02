"""Revisión de coincidencias y del PDF modificado, sin motor en la interfaz."""
from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,
    QCheckBox,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QSplitter,QScrollArea,QWidget)


class SearchReplaceDialog(QDialog):
    find_requested=Signal(object)
    preview_requested=Signal(object,str,bool)
    page_requested=Signal(int)
    apply_requested=Signal()

    def __init__(self,query='',selection=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Buscar y reemplazar · revisar coincidencias')
        self.resize(1050,760)
        self.selection=selection
        self.matches=[]
        self.found_parameters=None
        self.preview_valid=False
        self._preview_pixmap=QPixmap()
        outer=QVBoxLayout(self)
        form=QFormLayout()
        self.query=QLineEdit(query);self.query.setObjectName('replaceQuery')
        self.replacement=QLineEdit();self.replacement.setObjectName('replaceValue')
        self.scope=QComboBox();self.scope.addItems(['Todo el documento','Páginas indicadas','Selección actual'])
        if not selection:self.scope.model().item(2).setEnabled(False)
        self.pages=QLineEdit();self.pages.setPlaceholderText('Ejemplo: 1,3-5')
        self.pages.setEnabled(False)
        self.scope.currentIndexChanged.connect(lambda i:self.pages.setEnabled(i==1))
        for label,widget in [('Buscar',self.query),('Reemplazar por',self.replacement),('Ámbito',self.scope),('Páginas',self.pages)]:form.addRow(label,widget)
        outer.addLayout(form)
        opts=QHBoxLayout()
        self.case=QCheckBox('Distinguir mayúsculas');self.case.setChecked(True)
        self.whole=QCheckBox('Palabras completas')
        self.ocr=QCheckBox('Incluir capa OCR invisible')
        self.ocr.setToolTip('Sus cambios afectan al texto buscable; no cambian las letras dibujadas en una imagen.')
        self.auto=QCheckBox('Ajustar anchura');self.auto.setChecked(True)
        for widget in (self.case,self.whole,self.ocr,self.auto):opts.addWidget(widget)
        outer.addLayout(opts)
        self.find_button=QPushButton('Buscar todas las coincidencias');self.find_button.setObjectName('findAllMatches')
        self.find_button.clicked.connect(self.find)
        outer.addWidget(self.find_button)
        splitter=QSplitter()
        self.table=QTableWidget(0,5);self.table.setObjectName('replaceMatches')
        self.table.setHorizontalHeaderLabels(['Cambiar','Página','Texto','Contexto','Capa'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemChanged.connect(self.invalidate)
        self.table.currentCellChanged.connect(self.row_changed)
        self.table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.table)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        self.image=QLabel('La vista previa procede del PDF modificado.');self.image.setAlignment(Qt.AlignCenter)
        scroll.setWidget(self.image);splitter.addWidget(scroll)
        splitter.setSizes([570,450]);outer.addWidget(splitter,1)
        self.preview_zoom=QComboBox();self.preview_zoom.addItems(['Vista de página','Detalle ×2','Detalle ×3'])
        self.preview_zoom.currentIndexChanged.connect(self.draw_preview)
        outer.addWidget(self.preview_zoom)
        buttons=QHBoxLayout()
        self.all_button=QPushButton('Marcar todas');self.all_button.clicked.connect(lambda:self.check_all(True))
        self.none_button=QPushButton('Desmarcar');self.none_button.clicked.connect(lambda:self.check_all(False))
        self.one_button=QPushButton('Previsualizar esta');self.one_button.setObjectName('previewOneMatch')
        self.one_button.clicked.connect(lambda:self.preview(False))
        self.marked_button=QPushButton('Previsualizar marcadas');self.marked_button.setObjectName('previewMarkedMatches')
        self.marked_button.clicked.connect(lambda:self.preview(True))
        for widget in (self.all_button,self.none_button,self.one_button,self.marked_button):buttons.addWidget(widget)
        outer.addLayout(buttons)
        self.message=QLabel('Marca exactamente las apariciones que quieras cambiar.');self.message.setWordWrap(True)
        outer.addWidget(self.message)
        end=QHBoxLayout()
        self.apply_button=QPushButton('Aplicar cambios previsualizados');self.apply_button.setObjectName('applyReviewedMatches')
        self.apply_button.setEnabled(False);self.apply_button.clicked.connect(self.apply_requested)
        self.close_button=QPushButton('Cancelar');self.close_button.clicked.connect(self.reject)
        end.addWidget(self.apply_button);end.addWidget(self.close_button);outer.addLayout(end)
        for w in (self.query,self.replacement,self.pages):w.textChanged.connect(self.invalidate)
        for w in (self.case,self.whole,self.ocr,self.auto):w.toggled.connect(self.invalidate)
        self.scope.currentIndexChanged.connect(self.invalidate)

    def invalidate(self,*_):
        self.preview_valid=False;self.apply_button.setEnabled(False)

    def find(self):
        self.invalidate()
        if self.scope.currentIndex()==1 and not self.pages.text().strip():
            self.message.setText('Indica las páginas donde buscar.');return
        self.find_requested.emit({'query':self.query.text(),'pages':self.pages.text() if self.scope.currentIndex()==1 else None,
            'selection':self.selection if self.scope.currentIndex()==2 else None,
            'case_sensitive':self.case.isChecked(),'whole_word':self.whole.isChecked(),'include_ocr':self.ocr.isChecked()})

    def set_matches(self,matches):
        self.found_parameters=self.parameters_key()
        self.matches=matches;self.table.blockSignals(True);self.table.setRowCount(len(matches))
        for row,m in enumerate(matches):
            check=QTableWidgetItem();check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable|Qt.ItemIsSelectable);check.setCheckState(Qt.Unchecked)
            self.table.setItem(row,0,check)
            kind='OCR invisible' if m['ocr'] else 'Invisible no admitido' if m.get('unsupported_reason') else 'Visible'
            for col,value in enumerate((str(m['page']+1),m['text'],m['context'],kind),1):
                item=QTableWidgetItem(value)
                if m.get('unsupported_reason'):item.setToolTip(m['unsupported_reason'])
                self.table.setItem(row,col,item)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.message.setText(f'{len(matches)} coincidencias. Marca las que quieras modificar.')
        if matches:self.table.selectRow(0)

    def check_all(self,checked):
        for row in range(self.table.rowCount()):self.table.item(row,0).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def preview(self,marked):
        if self.parameters_key()!=self.found_parameters:
            self.message.setText('Los criterios cambiaron. Pulsa Buscar todas las coincidencias de nuevo.');return
        rows=([i for i in range(len(self.matches)) if self.table.item(i,0).checkState()==Qt.Checked]
              if marked else [self.table.currentRow()] if self.table.currentRow()>=0 else [])
        if not rows:self.message.setText('Selecciona una coincidencia o marca varias.');return
        self.preview_requested.emit([self.matches[i]['id'] for i in rows],self.replacement.text(),self.auto.isChecked())

    def parameters_key(self):
        return self.query.text(),self.scope.currentIndex(),self.pages.text(),self.case.isChecked(),self.whole.isChecked(),self.ocr.isChecked()

    def set_preview(self,png,report):
        pixmap=QPixmap();pixmap.loadFromData(png)
        self._preview_pixmap=pixmap;self.draw_preview()
        self.preview_valid=True;self.apply_button.setEnabled(True)
        self.message.setText(f"{report['match_count']} cambios previsualizados. Elige filas para revisar sus páginas. "+report.get('warning',''))

    def draw_preview(self,*_):
        if self._preview_pixmap.isNull():return
        width=440*(self.preview_zoom.currentIndex()+1)
        self.image.setPixmap(self._preview_pixmap.scaledToWidth(width,Qt.SmoothTransformation))
        self.image.setMinimumSize(self.image.pixmap().size())

    def row_changed(self,row,*_):
        if self.preview_valid and 0<=row<len(self.matches):self.page_requested.emit(self.matches[row]['page'])

    def set_busy(self,busy):
        for widget in (self.find_button,self.one_button,self.marked_button,self.all_button,self.none_button,
                       self.query,self.replacement,self.scope,self.pages,self.case,self.whole,self.ocr,self.auto,self.table,self.close_button):widget.setEnabled(not busy)
        self.apply_button.setEnabled(not busy and self.preview_valid)
        if not busy:self.pages.setEnabled(self.scope.currentIndex()==1)

    def set_error(self,error):
        self.set_busy(False);self.invalidate();self.message.setText(error)
