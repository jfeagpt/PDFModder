"""Qt text/typography dialogs; no PDF documents or font engines in the GUI."""
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .model import mm, pt


class FontPicker(QWidget):
    """Choose a real catalogued face or a user-supplied file, never faux styles."""

    def __init__(self, catalog, parent=None, initial_name=None):
        super().__init__(parent)
        self.catalog = [dict(entry) for entry in catalog]
        self._manual_path = None
        self._error = None
        self._current = None
        self.family_box = QComboBox()
        self.family_box.setObjectName('font_family')
        self.variant_box = QComboBox()
        self.variant_box.setObjectName('font_variant')
        self.bold_box = QCheckBox('Negrita')
        self.bold_box.setObjectName('font_bold')
        self.italic_box = QCheckBox('Cursiva')
        self.italic_box.setObjectName('font_italic')
        self.import_button = QPushButton('Elegir archivo TTF/OTF…')
        self.import_button.setObjectName('font_import')
        self.use_catalog_button = QPushButton('Usar catálogo')
        self.use_catalog_button.setVisible(False)
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName('font_status')
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid = QGridLayout(self)
        grid.setContentsMargins(0,0,0,0)
        grid.addWidget(QLabel('Familia'),0,0)
        grid.addWidget(self.family_box,0,1,1,3)
        grid.addWidget(QLabel('Variante real'),1,0)
        grid.addWidget(self.variant_box,1,1,1,3)
        grid.addWidget(self.bold_box,2,1)
        grid.addWidget(self.italic_box,2,2)
        buttons = QHBoxLayout()
        buttons.addWidget(self.import_button)
        buttons.addWidget(self.use_catalog_button)
        buttons.addStretch()
        grid.addLayout(buttons,3,0,1,4)
        grid.addWidget(self.status_label,4,0,1,4)
        self._families = {}
        for entry in self.catalog:
            family = entry.get('family') or entry.get('name') or 'Sin familia'
            self._families.setdefault(family, []).append(entry)
        for family in sorted(self._families, key=str.casefold):
            self.family_box.addItem(family, family)
        self.family_box.currentIndexChanged.connect(self._family_changed)
        self.variant_box.currentIndexChanged.connect(self._variant_changed)
        self.variant_box.activated.connect(self._variant_changed)
        self.bold_box.toggled.connect(self._style_changed)
        self.italic_box.toggled.connect(self._style_changed)
        self.import_button.clicked.connect(self._import_file)
        self.use_catalog_button.clicked.connect(self._use_catalog)
        match = next((entry for entry in self.catalog if entry.get('name') == (initial_name or 'Helvetica')), None)
        family = (match.get('family') or match.get('name')) if match else 'Helvetica'
        index = self.family_box.findData(family)
        if index >= 0:
            self.family_box.setCurrentIndex(index)
        self._family_changed()
        if match:
            index = next((i for i in range(self.variant_box.count()) if self.variant_box.itemData(i).get('name') == match['name']), -1)
            if index >= 0:
                self.variant_box.setCurrentIndex(index)
                self._variant_changed()

    def _family_changed(self, *_):
        self._manual_path = None
        family = self.family_box.currentData()
        entries = self._families.get(family, [])
        entries = sorted(entries, key=lambda entry: (bool(entry.get('bold')), bool(entry.get('italic')), str(entry.get('variant','')).casefold(), entry.get('name','')))
        with QSignalBlocker(self.variant_box):
            self.variant_box.clear()
            for entry in entries:
                variant = entry.get('variant') or entry.get('name') or 'Sin variante'
                label = f"{variant} · {entry.get('name','')}"
                if entry.get('editable') is False:
                    label += ' (no editable)'
                self.variant_box.addItem(label, entry)
            self.variant_box.setCurrentIndex(0 if entries else -1)
        self._variant_changed()

    def _variant_changed(self, *_):
        self._current = self.variant_box.currentData()
        self._error = None
        entry = self._current or {}
        with QSignalBlocker(self.bold_box), QSignalBlocker(self.italic_box):
            self.bold_box.setChecked(bool(entry.get('bold')))
            self.italic_box.setChecked(bool(entry.get('italic')))
        if not entry:
            self._error = 'No hay fuentes en el catálogo. Elige un archivo TTF/OTF.'
        elif entry.get('editable') is False:
            self._error = entry.get('status') or 'Esta fuente no permite incrustación editable.'
        path = entry.get('path')
        self.status_label.setText(self._error or (f"{entry.get('source','')} · {path or entry.get('name','')}. Los caracteres y permisos se validan al previsualizar."))

    def _style_changed(self, *_):
        if self._manual_path:
            return
        desired = (self.bold_box.isChecked(), self.italic_box.isChecked())
        matching = [i for i in range(self.variant_box.count())
                    if (bool(self.variant_box.itemData(i).get('bold')), bool(self.variant_box.itemData(i).get('italic'))) == desired]
        if matching:
            self.variant_box.setCurrentIndex(matching[0])
            self._variant_changed()
            return
        style = 'negrita cursiva' if all(desired) else 'negrita' if desired[0] else 'cursiva' if desired[1] else 'regular'
        self._error = f"Falta la variante {style} para «{self.family_box.currentText()}». Elige una variante disponible o importa el archivo exacto."
        self.status_label.setText(self._error)
        entry = self._current or {}
        with QSignalBlocker(self.bold_box), QSignalBlocker(self.italic_box):
            self.bold_box.setChecked(bool(entry.get('bold')))
            self.italic_box.setChecked(bool(entry.get('italic')))

    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Elegir variante de fuente', '', 'Fuentes TrueType/OpenType (*.ttf *.otf)')
        if path:
            self.set_font_file(path)

    def set_font_file(self, path):
        """Store a manual choice without parsing it; the worker validates it."""
        selected = Path(path)
        if selected.suffix.casefold() not in ('.ttf','.otf'):
            self._error = 'Elige un archivo TTF u OTF individual.'
            self.status_label.setText(self._error)
            return
        self._manual_path = str(selected)
        self._error = None
        for widget in (self.family_box, self.variant_box, self.bold_box, self.italic_box):
            widget.setEnabled(False)
        self.use_catalog_button.setVisible(True)
        self.status_label.setText(f"Archivo elegido: {selected.name}\nLa variante, licencia y caracteres del archivo se validarán al previsualizar.")

    def _use_catalog(self):
        self._manual_path = None
        for widget in (self.family_box, self.variant_box, self.bold_box, self.italic_box):
            widget.setEnabled(True)
        self.use_catalog_button.setVisible(False)
        self._variant_changed()

    def choice(self):
        if self._error:
            raise ValueError(self._error)
        if self._manual_path:
            return {'font_name': Path(self._manual_path).stem, 'font_file': self._manual_path}
        entry = self.variant_box.currentData()
        if not entry:
            raise ValueError('Elige una fuente o un archivo TTF/OTF.')
        if entry.get('editable') is False:
            raise ValueError(entry.get('status') or 'Esta fuente no permite edición.')
        return {'font_name': entry['name'], 'font_file': entry.get('path')}


class TextDialog(QDialog):
    def __init__(self, catalog, parent=None, text='', rect=(30,30,230,90), size=12,
                 font_name='Helvetica', color=(0,0,0), existing=False):
        super().__init__(parent)
        self.existing = existing
        self.setWindowTitle('Formato y texto de la selección' if existing else 'Añadir texto')
        self.setMinimumWidth(590)
        self.resize(670,650)
        # This conversion is only a GUI swatch. An untouched PDF colour must
        # remain untouched, especially for DeviceGray and DeviceCMYK text.
        self._color_changed = False
        if len(color) == 4:
            rgb = QColor.fromCmykF(*color).toRgb()
            self._color = (rgb.redF(),rgb.greenF(),rgb.blueF())
        elif len(color) == 1:
            self._color = (color[0],)*3
        else:
            self._color = tuple(color[:3])
        self._original_size = float(size)
        self._size_changed = False
        self.content = QPlainTextEdit(text)
        self.content.setObjectName('text_content')
        self.content.setPlaceholderText('Escribe el texto que aparecerá en el PDF…')
        self.content.setMinimumHeight(130)
        self.font_picker = FontPicker(catalog, self, initial_name=font_name)
        self.change_font = QCheckBox('Cambiar la fuente explícitamente')
        self.change_font.setObjectName('change_font')
        self.change_font.setChecked(not existing)
        self.change_font.setVisible(existing)
        self.font_picker.setEnabled(not existing)
        self.change_font.toggled.connect(self.font_picker.setEnabled)
        self.size_box = self._spin(1,300,3,size,' pt')
        self.size_box.setObjectName('text_size')
        self.size_box.valueChanged.connect(lambda *_: setattr(self,'_size_changed',True))
        self.x_box = self._spin(0,100000,3,mm(rect[0]),' mm')
        self.y_box = self._spin(0,100000,3,mm(rect[1]),' mm')
        self.width_box = self._spin(.001,100000,3,mm(rect[2]-rect[0]),' mm')
        self.height_box = self._spin(.001,100000,3,mm(rect[3]-rect[1]),' mm')
        for name in ('x','y','width','height'):
            getattr(self,f'{name}_box').setObjectName(f'text_{name}')
        self.x_box.setEnabled(not existing)
        self.y_box.setEnabled(not existing)
        self.align_box = QComboBox()
        self.align_box.setObjectName('text_alignment')
        for label,value in [('Izquierda','left'),('Centrada','center'),('Derecha','right')]:
            self.align_box.addItem(label,value)
        self.color_button = QPushButton()
        self.color_button.setObjectName('text_color')
        self.color_button.clicked.connect(self._choose_color)
        self._update_color()
        self.reflow_box = QCheckBox('Redistribuir palabras entre líneas dentro del área')
        self.reflow_box.setObjectName('text_reflow')
        self.reflow_box.setChecked(not existing)
        self.allow_overlap_box = QCheckBox('Permitir superponer texto' if existing else 'Permitir solapamiento sobre texto, imágenes o líneas')
        self.allow_overlap_box.setObjectName('text_overlap')
        self.allow_overlap_box.setChecked(False)
        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet('color: #b42318;')
        self.error_label.setObjectName('text_error')
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.preview_button = self.buttons.button(QDialogButtonBox.Ok)
        self.preview_button.setText('Previsualizar')
        self.preview_button.setObjectName('preview_text')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Contenido'))
        layout.addWidget(self.content,1)
        layout.addWidget(self.change_font)
        layout.addWidget(self.font_picker)
        properties = QGridLayout()
        for row,(a,b) in enumerate([
            (('Tamaño',self.size_box),('Color',self.color_button)),
            (('X',self.x_box),('Y',self.y_box)),
            (('Anchura',self.width_box),('Altura',self.height_box)),
        ]):
            properties.addWidget(QLabel(a[0]),row,0)
            properties.addWidget(a[1],row,1)
            properties.addWidget(QLabel(b[0]),row,2)
            properties.addWidget(b[1],row,3)
        properties.addWidget(QLabel('Alineación'),3,0)
        properties.addWidget(self.align_box,3,1,1,3)
        layout.addLayout(properties)
        layout.addWidget(self.reflow_box)
        layout.addWidget(self.allow_overlap_box)
        note = QLabel('La previsualización se genera desde el PDF modificado. El tamaño no se reduce automáticamente.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

    @staticmethod
    def _spin(minimum, maximum, decimals, value, suffix):
        widget = QDoubleSpinBox()
        widget.setRange(minimum,maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        widget.setSuffix(suffix)
        widget.setKeyboardTracking(False)
        return widget

    def _update_color(self):
        qcolor = QColor.fromRgbF(*self._color)
        self.color_button.setText(qcolor.name().upper())
        luminance = .2126*qcolor.redF()+.7152*qcolor.greenF()+.0722*qcolor.blueF()
        foreground = '#111111' if luminance > .55 else '#ffffff'
        self.color_button.setStyleSheet(f'background-color: {qcolor.name()}; color: {foreground}; padding: 5px;')

    def _choose_color(self):
        chosen = QColorDialog.getColor(QColor.fromRgbF(*self._color),self,'Color del texto')
        if chosen.isValid():
            self._color = (chosen.redF(),chosen.greenF(),chosen.blueF())
            self._color_changed = True
            self._update_color()

    def values(self):
        text = self.content.toPlainText()
        if not self.existing and not text.strip():
            raise ValueError('Escribe el texto que deseas añadir.')
        choice = self.font_picker.choice() if not self.existing or self.change_font.isChecked() else {'font_name':None,'font_file':None}
        return dict(text=text,x=pt(self.x_box.value()),y=pt(self.y_box.value()),
                    width=pt(self.width_box.value()),height=pt(self.height_box.value()),
                    size=self._original_size if self.existing and not self._size_changed else self.size_box.value(),
                    color=None if self.existing and not self._color_changed else self._color,
                    align=self.align_box.currentData(),
                    reflow=self.reflow_box.isChecked(),
                    allow_overlap=self.allow_overlap_box.isChecked(),
                    **choice)

    def accept(self):
        try:
            self.values()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.error_label.clear()
        super().accept()
