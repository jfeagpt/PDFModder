"""Diálogos de herramientas; todas las operaciones PDF se ejecutan en el worker."""
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox,
    QSpinBox, QDoubleSpinBox, QDialogButtonBox, QFileDialog, QPushButton,
    QWidget, QHBoxLayout,
)

from .model import pt


class PageActionsV150Mixin:
    def _v150_file_dialog(self, callback):
        timer = self.thumbnail_timer
        active = timer.isActive()
        timer.stop()
        try:
            return callback()
        finally:
            if active:
                timer.start()

    def _v150_ready(self):
        return bool(self.state) and not self.busy and not self.state.get('preview')

    def _v150_pages(self):
        selected = sorted(self.pages.row(item) + 1 for item in self.pages.selectedItems())
        return ','.join(map(str, selected)) or str(self.page_number + 1)

    def _v150_dialog(self, title, note, button='Previsualizar'):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(470)
        layout = QVBoxLayout(dialog)
        label = QLabel(note)
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(button)
        buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog, form

    def _v150_range(self, form, label='Páginas', value=None):
        field = QLineEdit(self._v150_pages() if value is None else value)
        field.setPlaceholderText('Ejemplo: 1-3, 5')
        form.addRow(label, field)
        return field

    def _pages_preview_v150(self, result):
        self.last_report = result.get('report', {})
        self._restore_ids = self._restore_regions = None
        self._search_matches = []
        self._last_search = None
        self.canvas.search_rects = []
        self._thumbnail_pages.clear()
        self._thumbnail_order.clear()
        for index in range(self.pages.count()):
            self.pages.item(index).setIcon(QIcon())
        self.page_number = min(self.page_number, self.state['page_count'] - 1)
        self._notice('Vista previa del PDF modificado. Pulsa Aplicar para aceptar o Cancelar para conservar el estado anterior.')
        self.load_page()

    def choose_replace_pages_v150(self):
        if not self._v150_ready():
            return
        dialog, form = self._v150_dialog(
            'Reemplazar páginas',
            'Sustituye páginas completas, incluidas sus anotaciones. Elige el mismo número '
            'de páginas en ambos documentos. Podrás revisar y cancelar antes de aplicar.'
            + (' En un PDF etiquetado, el archivo de sustitución también debe tener etiquetas '
               'compatibles para conservar la accesibilidad.' if self.state.get('tagged') else ''))
        targets = self._v150_range(form, 'Páginas del documento actual')
        file_field = QLineEdit()
        file_field.setObjectName('replacementPdfPath')
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(file_field)
        browse = QPushButton('Examinar…')
        def choose():
            path, _ = QFileDialog.getOpenFileName(dialog, 'PDF de sustitución', '', 'Documentos PDF (*.pdf)')
            if path:
                file_field.setText(path)
        browse.clicked.connect(choose)
        row_layout.addWidget(browse)
        form.addRow('Archivo de sustitución', row)
        sources = self._v150_range(form, 'Páginas del archivo elegido', '1')
        if self._exec_edit_dialog(dialog) == QDialog.Accepted:
            if not file_field.text().strip():
                self._error('Selecciona el PDF con las páginas de sustitución.')
                return
            self._submit('preview_replace_pages_v150', {
                'expression': targets.text(), 'path': file_field.text().strip(),
                'source_expression': sources.text(),
            }, self._pages_preview_v150)

    def choose_rotate_pages_v150(self):
        if self._v150_ready():
            self._submit('organizer_info', callback=lambda info: QTimer.singleShot(0, lambda: self._rotate_dialog_v150(info)))

    def _rotate_dialog_v150(self, info):
        dialog, form = self._v150_dialog('Rotar páginas', 'Gira sólo las páginas elegidas. Revisa el resultado antes de aplicar.')
        direction = QComboBox()
        direction.setObjectName('pageRotationDirection')
        for label, value in [('90 grados hacia la derecha', 90), ('90 grados hacia la izquierda', 270), ('180 grados', 180)]:
            direction.addItem(label, value)
        form.addRow('Dirección', direction)
        pages = self._v150_range(form)
        parity = QComboBox()
        parity.setObjectName('pageRotationParity')
        parity.addItems(['Todas las páginas del rango', 'Sólo páginas impares', 'Sólo páginas pares'])
        form.addRow('Rotar', parity)
        orientation = QComboBox()
        orientation.setObjectName('pageRotationOrientation')
        orientation.addItems(['Todas las orientaciones', 'Sólo páginas verticales', 'Sólo páginas horizontales'])
        form.addRow('Orientación', orientation)
        if self._exec_edit_dialog(dialog) != QDialog.Accepted:
            return
        from .pageops import parse_pages
        try:
            selected = parse_pages(pages.text(), len(info['pages']))
            if parity.currentIndex():
                selected = [p for p in selected if (p + 1) % 2 == (1 if parity.currentIndex() == 1 else 0)]
            if orientation.currentIndex():
                portrait = orientation.currentIndex() == 1
                selected = [p for p in selected if (info['pages'][p]['height'] >= info['pages'][p]['width']) == portrait]
            if not selected:
                raise ValueError('Ninguna página coincide con el rango y los filtros elegidos.')
        except Exception as exc:
            self._error(str(exc))
            return
        plan = [dict(source='current', page=i, rotation=direction.currentData() if i in selected else 0)
                for i in range(len(info['pages']))]
        self._submit('organize_pages', {'plan': plan}, self._pages_preview_v150)

    def choose_insert_pages_v150(self):
        if not self._v150_ready():
            return
        path, _ = self._v150_file_dialog(lambda: QFileDialog.getOpenFileName(
            self, 'Insertar páginas desde archivo', '', 'Documentos PDF (*.pdf)'))
        if path:
            self._submit('organizer_info', {'path': path},
                         lambda info: QTimer.singleShot(0, lambda: self._insert_dialog_v150(info)))

    def _insert_dialog_v150(self, info):
        dialog, form = self._v150_dialog('Insertar páginas desde archivo',
            'Inserta las páginas elegidas sin modificar el archivo de origen. Revisa el orden final antes de aplicar.')
        form.addRow('Archivo', QLabel(Path(info['path']).name))
        source_pages = self._v150_range(form, 'Páginas a insertar', f"1-{len(info['pages'])}")
        location = QComboBox()
        location.setObjectName('insertPagesLocation')
        location.addItems(['Después de', 'Antes de'])
        form.addRow('Ubicación', location)
        anchor = QSpinBox()
        anchor.setObjectName('insertPagesAnchor')
        anchor.setRange(1, self.state['page_count'])
        anchor.setValue(self.page_number + 1)
        form.addRow('Página del documento actual', anchor)
        if self._exec_edit_dialog(dialog) != QDialog.Accepted:
            return
        from .pageops import parse_pages
        try:
            selected = parse_pages(source_pages.text(), len(info['pages']))
        except Exception as exc:
            self._error(str(exc))
            return
        position = anchor.value() if location.currentIndex() == 0 else anchor.value() - 1
        plan = [dict(source='current', page=i, rotation=0) for i in range(self.state['page_count'])]
        plan[position:position] = [dict(source=info['source_id'], page=i, rotation=0) for i in selected]
        self._submit('organize_pages', {'plan': plan, 'paths': {info['source_id']: info['path']}}, self._pages_preview_v150)

    def choose_crop_pages_v150(self):
        if not self._v150_ready():
            return
        dialog, form = self._v150_dialog(
            'Recortar páginas',
            'Oculta los márgenes indicados de la página visible, sin borrar contenido del PDF. '
            'El recorte no sirve para eliminar información confidencial. Las medidas siguen '
            'la orientación con la que ves cada página.')
        pages = self._v150_range(form)
        margins = []
        for label in ('Izquierda', 'Superior', 'Derecha', 'Inferior'):
            field = QDoubleSpinBox()
            field.setRange(0, 3000)
            field.setDecimals(2)
            field.setSuffix(' mm')
            field.setKeyboardTracking(False)
            form.addRow(label, field)
            margins.append(field)
        if self._exec_edit_dialog(dialog) == QDialog.Accepted:
            self._submit('preview_crop_pages_v150', {
                'expression': pages.text(), 'margins': tuple(pt(box.value()) for box in margins),
            }, self._pages_preview_v150)

    def choose_split_v150(self):
        if not self._v150_ready():
            return
        dialog, form = self._v150_dialog(
            'Dividir documento',
            'Crea varios PDF independientes y conserva el documento actual. Los grupos deben '
            'cubrir todas las páginas una sola vez; para un subconjunto usa Extraer.',
            'Elegir carpeta…')
        mode = QComboBox()
        mode.addItems(['Número de páginas por archivo', 'Grupos de páginas'])
        form.addRow('Dividir por', mode)
        number = QSpinBox()
        number.setRange(1, self.state['page_count'])
        form.addRow('Páginas por archivo', number)
        groups = QLineEdit()
        groups.setPlaceholderText('Ejemplo: 1-3;4-6;7')
        groups.setEnabled(False)
        form.addRow('Grupos separados por ;', groups)
        mode.currentIndexChanged.connect(lambda value: (number.setEnabled(value == 0), groups.setEnabled(value == 1)))
        if self._exec_edit_dialog(dialog) != QDialog.Accepted:
            return
        destination = self._v150_file_dialog(lambda: QFileDialog.getExistingDirectory(self, 'Carpeta para los PDF divididos'))
        if destination:
            self._submit('split_document_v150', {
                'destination': destination,
                'expression': groups.text() if mode.currentIndex() else None,
                'pages_per_part': number.value() if not mode.currentIndex() else None,
            }, self._files_created_v150)

    def choose_export_v150(self):
        if not self._v150_ready():
            return
        dialog, form = self._v150_dialog(
            'Exportar archivo a…',
            'Exportación local. TXT contiene el texto extraído; PNG/JPEG generan imágenes. '
            'SVG conserva dibujos vectoriales con las letras como contornos. Para conservar '
            'texto PDF editable usa Guardar como. No se ofrece conversión a Word o Excel.',
            'Elegir destino…')
        formats = QComboBox()
        for label, key in [('Texto UTF-8 (.txt)', 'txt'), ('Imagen PNG por página', 'png'),
                           ('Imagen JPEG por página', 'jpeg'), ('Vector SVG por página', 'svg')]:
            formats.addItem(label, key)
        form.addRow('Formato', formats)
        pages = self._v150_range(form, value=f"1-{self.state['page_count']}")
        dpi = QSpinBox()
        dpi.setRange(36, 600)
        dpi.setValue(144)
        dpi.setSuffix(' ppp')
        dpi.setEnabled(False)
        formats.currentIndexChanged.connect(lambda _: dpi.setEnabled(formats.currentData() in ('png', 'jpeg')))
        form.addRow('Resolución de imágenes', dpi)
        if self._exec_edit_dialog(dialog) != QDialog.Accepted:
            return
        if formats.currentData() == 'txt':
            suggested = Path(self.state['path']).with_suffix('.txt')
            destination, _ = self._v150_file_dialog(lambda: QFileDialog.getSaveFileName(self, 'Exportar texto', str(suggested), 'Texto UTF-8 (*.txt)'))
        else:
            destination = self._v150_file_dialog(lambda: QFileDialog.getExistingDirectory(self, 'Carpeta para páginas exportadas'))
        if destination:
            from .pageops import parse_pages
            try:
                selected = parse_pages(pages.text(), self.state['page_count'])
            except Exception as exc:
                self._error(str(exc))
                return
            self._submit('export_document_v150', {
                'destination': destination, 'format': formats.currentData(),
                'pages': selected, 'dpi': dpi.value(),
            }, self._files_created_v150)

    def _files_created_v150(self, result):
        report = result.get('report', result)
        files = report.get('files', result.get('files', []))
        paths = [item.get('path', '') if isinstance(item, dict) else str(item) for item in files]
        message = f'Exportación terminada: {len(paths)} archivo(s).'
        if paths:
            message += ' ' + str(Path(paths[0]).parent)
        warnings = report.get('warnings', [])
        if warnings:
            message += ' ' + ' '.join(map(str, warnings))
        self._notice(message)
