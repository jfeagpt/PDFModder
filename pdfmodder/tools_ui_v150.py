"""Local tools workspace with original pictograms and existing editor actions.

This layer composes Qt controls only. PDF mutations continue through the serial
worker, and shared QActions retain the application's capability checks.
"""
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QSizePolicy,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)


def tool_icon(kind):
    """Small original line drawings; no third-party icon files are bundled."""
    canvas = QPixmap(40, 40)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor('#3f6079'), 2.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(QColor('#ffffff'))
    if kind in ('zoom_in', 'zoom_out'):
        painter.drawLine(8, 20, 32, 20)
        if kind == 'zoom_in':
            painter.drawLine(20, 8, 20, 32)
    elif kind in ('image', 'images'):
        painter.drawRoundedRect(QRectF(5, 7, 29, 25), 2, 2)
        painter.setBrush(QColor('#e6ac37'))
        painter.drawEllipse(QPointF(26, 13), 3, 3)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(7, 28, 17, 17)
        painter.drawLine(17, 17, 23, 24)
        painter.drawLine(23, 24, 29, 20)
    elif kind == 'search':
        painter.drawEllipse(QRectF(6, 5, 22, 22))
        painter.drawLine(26, 26, 35, 35)
    elif kind in ('undo', 'redo', 'rotate'):
        painter.drawArc(QRectF(8, 8, 24, 24), 25 * 16, 285 * 16)
        painter.drawLine(8, 8, 8, 18)
        painter.drawLine(8, 18, 18, 18)
        if kind == 'redo':
            painter.end()
            return QIcon(canvas.transformed(QTransform().scale(-1, 1)))
    elif kind in ('flip_h', 'flip_v'):
        if kind == 'flip_v':
            painter.translate(40, 0)
            painter.rotate(90)
        painter.drawLine(20, 5, 20, 35)
        painter.drawLine(4, 20, 15, 20)
        painter.drawLine(4, 20, 10, 14)
        painter.drawLine(4, 20, 10, 26)
        painter.drawLine(25, 20, 36, 20)
        painter.drawLine(36, 20, 30, 14)
        painter.drawLine(36, 20, 30, 26)
    elif kind == 'crop':
        painter.drawLine(12, 4, 12, 29)
        painter.drawLine(12, 29, 36, 29)
        painter.drawLine(4, 11, 29, 11)
        painter.drawLine(29, 11, 29, 36)
    elif kind == 'tools':
        painter.drawLine(8, 11, 33, 11)
        painter.drawLine(8, 21, 33, 21)
        painter.drawLine(8, 31, 33, 31)
        for x, y in ((16, 11), (26, 21), (13, 31)):
            painter.setBrush(QColor('#f1c65e'))
            painter.drawEllipse(QPointF(x, y), 3, 3)
    else:
        painter.drawRoundedRect(QRectF(8, 4, 24, 32), 2, 2)
        if kind in ('edit', 'text'):
            painter.setFont(QFont('Arial', 13, QFont.Bold))
            painter.drawText(QRectF(9, 6, 22, 27), Qt.AlignCenter, 'T')
        elif kind == 'delete':
            painter.setPen(QPen(QColor('#bb4c45'), 3, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(14, 14, 26, 26)
            painter.drawLine(26, 14, 14, 26)
        elif kind in ('add', 'merge', 'insert'):
            painter.setPen(QPen(QColor('#438d68'), 2.8, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(13, 21, 27, 21)
            painter.drawLine(20, 14, 20, 28)
        elif kind in ('export', 'extract', 'replace'):
            painter.drawLine(15, 20, 35, 20)
            painter.drawLine(29, 14, 35, 20)
            painter.drawLine(29, 26, 35, 20)
        elif kind == 'split':
            painter.drawLine(3, 20, 37, 20)
        elif kind == 'save':
            painter.setBrush(QColor('#d6e8f2'))
            painter.drawRect(QRectF(13, 8, 14, 9))
            painter.drawRect(QRectF(13, 24, 14, 10))
        else:
            for y in (13, 20, 27):
                painter.drawLine(13, y, 27, y)
    painter.end()
    return QIcon(canvas)


class ToolSection(QWidget):
    def __init__(self, title, name, *, expanded=True, parent=None):
        super().__init__(parent)
        self._title=title
        self.setObjectName(name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QToolButton()
        self.header.setText(title)
        self.header.setObjectName(name + 'Header')
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setStyleSheet('QToolButton { text-align:left; padding:7px 4px; font-weight:600; border:1px solid #bfc5cc; background:#e4e7eb; }')
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(5, 5, 5, 8)
        self.body.setSpacing(3)
        layout.addWidget(self.header)
        layout.addWidget(self.content)
        self.header.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        self.content.setVisible(expanded)
        if getattr(self,'_section_icon_v170',None) is not None:
            self.header.setArrowType(Qt.NoArrow)
            self.header.setIcon(self._section_icon_v170)
            self.header.setText(self._title+('  ▾' if expanded else '  ▸'))
        else:
            self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        if self.header.isChecked() != expanded:
            self.header.setChecked(expanded)


class ToolsWorkspaceV150Mixin:
    def _tool_button_v150(self, layout, action, name, icon_kind=None):
        if icon_kind:
            action.setIcon(tool_icon(icon_kind))
        button = QToolButton()
        button.setObjectName(name)
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(20, 20))
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setStyleSheet('QToolButton { text-align:left; padding:5px; border:1px solid transparent; } QToolButton:hover { background:#e3edf8; border-color:#9bb7d4; } QToolButton:checked { background:#d9e8f5; border-color:#839fbe; }')
        layout.addWidget(button)
        self.addAction(action)
        return button

    def _new_tool_action_v150(self, text, callback):
        action = QAction(text, self)
        action.triggered.connect(callback)
        return action

    def _create_tools_workspace_v150(self, splitter, scroll, properties_panel):
        self.document_splitter = splitter
        self.tools_scroll = scroll
        self.tools_scroll.setObjectName('toolsPanel')
        self.tools_scroll.setMinimumWidth(285)
        self.tools_scroll.setMaximumWidth(390)
        self.tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # takeWidget keeps the existing properties and their signals alive.
        self.tools_scroll.takeWidget()
        properties_panel.setObjectName('advancedPropertiesPanel')
        self._combined_edit_v150 = True
        self._tools_syncing_v150 = False
        self.edit_content_action = self._new_tool_action_v150('Editar texto e imágenes', self._activate_content_v150)
        self.edit_content_action.setCheckable(True)
        self.edit_content_action.setChecked(True)
        self.image_mode_action.triggered.connect(self._explicit_image_mode_v150)
        self.export_document_action = self._new_tool_action_v150('Exportar archivo a…', lambda:self.choose_export_v150())
        self.replace_pages_action = self._new_tool_action_v150('Reemplazar páginas…', lambda:self.choose_replace_pages_v150())
        self.crop_pages_action = self._new_tool_action_v150('Recortar páginas…', lambda:self.choose_crop_pages_v150())
        self.split_document_action = self._new_tool_action_v150('Dividir documento…', lambda:self.choose_split_v150())
        self.rotate_pages_action = self._new_tool_action_v150('Rotar páginas…', lambda:self.choose_rotate_pages_v150())
        self.rotate_pages_action.setToolTip('Elige dirección, rango de páginas, pares/impares y orientación antes de previsualizar.')
        self.insert_pages_action = self._new_tool_action_v150('Insertar desde archivo…', lambda:self.choose_insert_pages_v150())
        self.insert_pages_action.setToolTip('Elige un PDF y la posición anterior o posterior donde insertar sus páginas.')
        self.thumbnail_action = self._new_tool_action_v150('Miniaturas de página', lambda value:self.pages.setVisible(value))
        self.thumbnail_action.setCheckable(True)
        self.thumbnail_action.setChecked(True)
        self.tools_action = self._new_tool_action_v150('Herramientas', lambda value:self.tools_scroll.setVisible(value))
        self.tools_action.setCheckable(True)
        self.tools_action.setChecked(True)
        self.tools_action.setIcon(tool_icon('tools'))

        tools_panel = QWidget()
        tools_panel.setObjectName('toolsWorkspace')
        layout = QVBoxLayout(tools_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.content_tools_section = ToolSection('Edición del contenido', 'contentToolsSection', expanded=False)
        self.format_tools_section = ToolSection('Formato', 'formatToolsSection', expanded=False)
        self.page_tools_section = ToolSection('Páginas', 'pageToolsSection', expanded=False)
        self.advanced_tools_section = ToolSection('Propiedades y herramientas avanzadas', 'advancedToolsSection', expanded=False)
        for section in (self.content_tools_section, self.format_tools_section, self.page_tools_section, self.advanced_tools_section):
            layout.addWidget(section)
        layout.addStretch()
        for action, name, kind in (
            (self.edit_content_action, 'toolEditContent', 'edit'),
            (self.add_text_action, 'toolAddText', 'text'),
            (self.add_image_action, 'toolAddImage', 'image'),
            (self.export_document_action, 'toolExportDocument', 'export'),
        ):
            self._tool_button_v150(self.content_tools_section.body, action, name, kind)
        self._create_format_panel_v150(self.format_tools_section.body)
        self.image_quick_controls = QWidget()
        self.image_quick_controls.setObjectName('imageQuickTools')
        image_row = QHBoxLayout(self.image_quick_controls)
        image_row.setContentsMargins(0, 0, 0, 0)
        for key, label, icon in (('flip_horizontal', 'Voltear horizontalmente', 'flip_h'),
                                 ('flip_vertical', 'Voltear verticalmente', 'flip_v'),
                                 ('left', 'Girar imagen a la izquierda', 'undo'),
                                 ('right', 'Girar imagen a la derecha', 'redo'),
                                 ('crop', 'Recortar imagen…', 'crop'),
                                 ('replace', 'Sustituir imagen…', 'replace')):
            button = QToolButton()
            button.setObjectName('quickImage_' + key)
            button.setIcon(tool_icon(icon))
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setIconSize(QSize(22, 22))
            button.clicked.connect(lambda _=False, operation=key:self._quick_image_v150(operation))
            image_row.addWidget(button)
        self.format_tools_section.body.addWidget(self.image_quick_controls)
        # Reparent the existing image controls, retaining all capability checks.
        self.format_tools_section.body.addWidget(self.image_box)
        self.format_tools_section.body.addWidget(self.rich_result)

        for action, name, kind in (
            (self.thumbnail_action, 'toolThumbnails', 'pages'),
            (self.rotate_pages_action, 'toolRotatePages', 'rotate'),
            (self.delete_pages_action, 'toolDeletePages', 'delete'),
            (self.extract_pages_action, 'toolExtractPages', 'extract'),
            (self.replace_pages_action, 'toolReplacePages', 'replace'),
            (self.crop_pages_action, 'toolCropPages', 'crop'),
            (self.split_document_action, 'toolSplitDocument', 'split'),
        ):
            self._tool_button_v150(self.page_tools_section.body, action, name, kind)
        insert_label = QLabel('Insertar páginas')
        insert_label.setStyleSheet('color:#5b6672; padding:6px 4px 2px; font-weight:600;')
        self.page_tools_section.body.addWidget(insert_label)
        self._tool_button_v150(self.page_tools_section.body, self.insert_pages_action, 'toolInsertPages', 'insert')
        self.merge_action.setText('Combinar archivos en PDF…')
        self._tool_button_v150(self.page_tools_section.body, self.merge_action, 'toolCombinePdfs', 'merge')
        self._tool_button_v150(self.page_tools_section.body, self.organize_action, 'toolOrganizePages', 'pages')

        for action, name, kind in (
            (self.replace_action, 'toolFindReplace', 'search'),
            (self.image_mode_action, 'toolSelectImages', 'images'),
            (self.objects_action, 'toolObjects', 'pages'),
            (self.copy_format_action, 'toolCopyFormat', 'text'),
            (self.paste_format_action, 'toolPasteFormat', 'add'),
            (self.compare_action, 'toolCompareOriginal', 'pages'),
            (self.highlight_action, 'toolHighlightChanges', 'edit'),
        ):
            self._tool_button_v150(self.advanced_tools_section.body, action, name, kind)
        self.add_text_properties_action = self._new_tool_action_v150('Agregar texto con propiedades…', lambda:self.begin_text_properties_v150())
        self._tool_button_v150(self.advanced_tools_section.body, self.add_text_properties_action, 'toolAddTextProperties', 'text')
        self.advanced_tools_section.body.addWidget(properties_panel)
        self.tools_scroll.setWidget(tools_panel)

        # Actions are now presented in the right tools panel. Keep one header.
        for bar in self.findChildren(QToolBar):
            if bar is not self.toolbar:
                self.removeToolBar(bar)
                bar.hide()
        for action in (self.copy_format_action, self.paste_format_action, self.objects_action,
                       self.compare_action, self.highlight_action):
            self.toolbar.removeAction(action)
        for action, kind in ((self.open_action, 'pages'), (self.save_action, 'save'),
                             (self.undo_action, 'undo'), (self.redo_action, 'redo'),
                             (self.zoom_out_action, 'zoom_out'), (self.zoom_in_action, 'zoom_in'),
                             (self.fit_page_action, 'pages'), (self.fit_width_action, 'pages'),
                             (self.search_action, 'search')):
            action.setIcon(tool_icon(kind))
        self.toolbar.setObjectName('documentToolbar')
        self.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.toolbar.setIconSize(QSize(22, 22))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        self.tools_toggle_button = QToolButton()
        self.tools_toggle_button.setObjectName('toolsToggle')
        self.tools_toggle_button.setDefaultAction(self.tools_action)
        self.tools_toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toolbar.addWidget(self.tools_toggle_button)
        splitter.setSizes([140, 980, 300])

        for action in (self.open_action, self.save_action, self.add_text_action, self.organize_action,
                       self.delete_pages_action, self.image_mode_action):
            action.changed.connect(self._refresh_tools_v150)
        self.operation_finished.connect(lambda *_:self._refresh_tools_v150())
        self.error_raised.connect(lambda *_:self._refresh_tools_v150())
        self.canvas.selection_changed.connect(lambda *_:self._refresh_tools_v150())
        self.canvas.image_selected.connect(lambda *_:self._refresh_tools_v150())
        self.canvas.image_rotate_requested.connect(self._rotate_image_v160)
        self.canvas.editor.cursorPositionChanged.connect(self._sync_format_v150)
        self.canvas.editor.textChanged.connect(self._sync_format_v150)
        self._refresh_tools_v150()

    def _create_format_panel_v150(self, layout):
        self.side_format_controls = QWidget()
        self.side_format_controls.setObjectName('sideFormatControls')
        form = QVBoxLayout(self.side_format_controls)
        form.setContentsMargins(0, 0, 0, 0)
        self.side_font = QComboBox()
        self.side_font.setObjectName('sideFontFamily')
        self.side_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.side_font.setMinimumContentsLength(12)
        self.side_font.activated.connect(lambda index:self.canvas.editor.change_face(self.side_font.itemData(index)))
        form.addWidget(self.side_font)
        row = QHBoxLayout()
        self.side_size = QDoubleSpinBox()
        self.side_size.setObjectName('sideFontSize')
        self.side_size.setRange(.5, 500)
        self.side_size.setDecimals(2)
        self.side_size.setSuffix(' pt')
        self.side_size.setKeyboardTracking(False)
        self.side_size.valueChanged.connect(lambda value:self.canvas.editor.merge_style(size=value))
        row.addWidget(self.side_size)
        self.side_style_buttons = {}
        for key, text, hint in (('bold', 'N', 'Negrita real'), ('italic', 'C', 'Cursiva real'), ('underline', 'S', 'Subrayado')):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setObjectName('sideStyle_' + key)
            button.setToolTip(hint)
            button.setFocusPolicy(Qt.NoFocus)
            if key == 'underline':
                button.clicked.connect(lambda:self.canvas.editor.merge_style(underline=not self.canvas.editor.current_style().get('underline', False)))
            else:
                button.clicked.connect(lambda _=False, variant=key:self.canvas.editor.toolbar.toggle_variant(variant))
            row.addWidget(button)
            self.side_style_buttons[key] = button
        self.side_color = QToolButton()
        self.side_color.setObjectName('sideTextColor')
        self.side_color.setText('Color')
        self.side_color.setFocusPolicy(Qt.NoFocus)
        self.side_color.clicked.connect(lambda:self.canvas.editor.toolbar._color())
        row.addWidget(self.side_color)
        form.addLayout(row)
        self.side_alignment = QComboBox()
        self.side_alignment.setObjectName('sideTextAlignment')
        for label, value in (('Alinear a la izquierda', 'left'), ('Centrar', 'center'), ('Alinear a la derecha', 'right'), ('Justificar', 'justify')):
            self.side_alignment.addItem(label, value)
        self.side_alignment.activated.connect(lambda _:self.canvas.editor.merge_paragraph(alignment=self.side_alignment.currentData()))
        form.addWidget(self.side_alignment)
        layout.addWidget(self.side_format_controls)
        self.side_format_hint = QLabel('Haz doble clic en el texto para modificar su formato por fragmentos.')
        self.side_format_hint.setWordWrap(True)
        self.side_format_hint.setStyleSheet('color:#637180; font-size:11px;')
        layout.addWidget(self.side_format_hint)
        self.side_format_button = self._tool_button_v150(layout, self.format_action, 'toolFontFormat', 'text')

    def _sync_format_v150(self):
        if not hasattr(self, 'side_font') or self._tools_syncing_v150:
            return
        editor = self.canvas.editor
        image_selected = bool(self.canvas.image_mode and self.canvas.selected_image())
        self.side_format_controls.setVisible(not image_selected)
        self.side_format_hint.setVisible(not image_selected)
        self.side_format_button.setVisible(not image_selected)
        active = bool(getattr(self, '_rich_active', False) and editor.rich_mode and not getattr(self, '_rich_accept_pending', False))
        self.side_format_controls.setEnabled(active)
        self.side_format_hint.setText('Formato de las letras seleccionadas; sin selección se aplica a lo que escribas.' if active else 'Haz doble clic en el texto para modificar su formato por fragmentos.')
        self._tools_syncing_v150 = True
        try:
            toolbar = editor.toolbar
            catalog = getattr(editor, '_catalog', []) if active else []
            if [self.side_font.itemData(i) for i in range(self.side_font.count())] != catalog:
                with QSignalBlocker(self.side_font):
                    self.side_font.clear()
                    for entry in catalog:
                        self.side_font.addItem(entry.get('name', ''), entry)
            if active:
                toolbar.sync_cursor()
                style = editor.current_style()
                with QSignalBlocker(self.side_font):
                    self.side_font.setCurrentIndex(toolbar.font_box.currentIndex())
                    self.side_font.setPlaceholderText(style.get('font_name') or 'Fuente original')
                with QSignalBlocker(self.side_size):
                    self.side_size.setValue(float(style.get('size', 12)))
                with QSignalBlocker(self.side_alignment):
                    self.side_alignment.setCurrentIndex(toolbar.align.currentIndex())
                for key, button in self.side_style_buttons.items():
                    with QSignalBlocker(button):
                        button.setChecked(getattr(toolbar, key).isChecked())
        finally:
            self._tools_syncing_v150 = False

    def _refresh_tools_v150(self):
        if not hasattr(self, 'edit_content_action'):
            return
        ready = bool(self.state) and not self.busy and not self.state.get('preview') and getattr(self,'application_mode','editing') == 'editing'
        writing = self.canvas.editor.isVisible() or getattr(self, '_rich_active', False) or getattr(self, '_rich_loading', False)
        editable = ready and not writing and not self.state.get('issues') and not self.compare_action.isChecked() and not getattr(self, '_placement', None)
        caps = self.state.get('page_capabilities', {})
        self.edit_content_action.setEnabled(editable)
        self.export_document_action.setEnabled(ready and not writing)
        self.rotate_pages_action.setEnabled(editable and caps.get('rotate', False))
        self.insert_pages_action.setEnabled(editable and caps.get('insert_pdf', False))
        self.replace_pages_action.setEnabled(editable and caps.get('replace_pdf', caps.get('insert_pdf', False)) and caps.get('delete', False))
        self.crop_pages_action.setEnabled(editable)
        self.split_document_action.setEnabled(editable and caps.get('extract', False))
        self.add_text_properties_action.setEnabled(self.add_text_action.isEnabled())
        image = self.canvas.selected_image()
        self.image_quick_controls.setVisible(bool(self.canvas.image_mode and image))
        self.image_quick_controls.setEnabled(editable and bool(image and image.get('editable')))
        self._sync_format_v150()

    def _quick_image_v150(self, operation):
        item = self.canvas.selected_image()
        if not item or self.busy or self.state.get('preview') or not item.get('editable'):
            return
        if operation in ('crop', 'replace'):
            self.edit_selected_image()
            return
        options = dict(item.get('image_operation') or {})
        if not options:
            # Preserve an ordinary instance's initial rotation / reflection.
            # Complex framed crops must already have a recovered operation.
            if item.get('framed'):
                self.edit_selected_image()
                return
            a, b, c, d, _, _ = item.get('matrix_pdf', (1., 0., 0., 1., 0., 0.))
            reflected = a*d-b*c < 0
            options = {'rotation': math.degrees(math.atan2(c/max(item.get('height_px', 1), 1)/(-1 if reflected else 1),
                                                          a/max(item.get('width_px', 1), 1))) % 360,
                       'flip_horizontal': False, 'flip_vertical': reflected, 'fit_mode': 'stretch',
                       'crop': (0., 0., 1., 1.)}
        if operation in ('flip_horizontal', 'flip_vertical'):
            options[operation] = not options.get(operation, False)
        else:
            options['rotation'] = (options.get('rotation', 0) + (90 if operation == 'right' else -90)) % 360
        self._submit('image', {**self._image_payload(), 'operation': 'edit', **options}, self._previewed)

    def _rotate_image_v160(self, image_id, angle):
        item = self.canvas.selected_image()
        if (not item or item['id'] != image_id or not item.get('editable') or self.busy
                or self.state.get('preview') or self.compare_action.isChecked()):
            return
        self._submit('image_apply', {**self._image_payload(image_id), 'operation': 'rotate',
                                    'rotation': angle}, self._edited)

    def _activate_content_v150(self):
        self._combined_edit_v150 = True
        self.edit_content_action.setChecked(True)
        self.image_mode_action.setChecked(False)
        self.toggle_image_mode(False)
        self.interaction_box.setCurrentIndex(self.interaction_box.findData('select'))
        self.canvas.setFocus()
        self._notice('Pulsa texto o una imagen para seleccionarlo. Doble clic: escribir. Arrastra para mover; usa los tiradores para cambiar el área o el tamaño.')

    def _explicit_image_mode_v150(self, checked):
        self._combined_edit_v150 = not checked
        self.edit_content_action.setChecked(not checked)

    def _choose_content_at_v150(self, event):
        canvas = self.canvas
        if (not getattr(self, '_combined_edit_v150', False) or not canvas.model or canvas.read_only
                or getattr(canvas, 'signature_rectangle_mode', False)
                or canvas.editor.isVisible() or canvas.zone_mode or canvas.placement_mode
                or event.button() != Qt.LeftButton or getattr(self, '_rich_active', False)):
            return
        position = event.position().toPoint()
        point = canvas.pdf_point(position)
        selected_image = canvas.selected_image()
        if selected_image and (canvas._handle_at(selected_image['rect'], position)
                               or canvas._rotation_handle_at(selected_image['rect'], position)):
            return
        if canvas.ids:
            from .model import union
            if canvas._handle_at(union(g.bbox for g in canvas.model.selected(canvas.ids)), position):
                return
        hit = canvas.model.hit(point)
        image = next((item for item in reversed(canvas.images) if item['rect'][0] <= point[0] <= item['rect'][2]
                      and item['rect'][1] <= point[1] <= item['rect'][3]), None)
        image_mode = bool(image and (not hit or hit.mode == 3 or hit.opacity <= 0))
        if canvas.image_mode != image_mode:
            with QSignalBlocker(self.image_mode_action):
                self.image_mode_action.setChecked(image_mode)
            self.toggle_image_mode(image_mode)

    def eventFilter(self, obj, event):
        if hasattr(self, 'tools_scroll'):
            if obj is self.canvas.viewport() and event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                self._choose_content_at_v150(event)
            elif obj is self.canvas.editor and event.type() in (QEvent.Show, QEvent.Hide):
                QTimer.singleShot(0, self._refresh_tools_v150)
        return super().eventFilter(obj, event)
