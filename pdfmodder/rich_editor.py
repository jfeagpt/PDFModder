"""Qt rich drafting surface. Font identities and PDF units survive editing.

The worker remains the authority for font permissions, coverage and saved PDF
layout. This module never opens a PDF and never invents a bold/italic face.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from PySide6.QtCore import QByteArray, Qt, Signal, QSignalBlocker
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QKeySequence, QRawFont, QShortcut, QTextBlockFormat,
                          QTextCharFormat, QTextCursor, QTextFormat, QTextOption)
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDoubleSpinBox,
    QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QToolButton,
    QVBoxLayout, QStyle)


STYLE_PROPERTY = int(QTextFormat.UserProperty) + 91
PARAGRAPH_PROPERTY = int(QTextFormat.UserProperty) + 92
_FONT_CACHE = {}


def register_face(entry):
    """Register supplied bytes/path, never resolve a face merely by family."""
    data = entry.get('buffer') or entry.get('font_buffer')
    path = entry.get('path') or entry.get('font_file')
    key = sha256(bytes(data)).hexdigest() if data else str(path or '')
    if not key:
        return None
    if key not in _FONT_CACHE:
        number = (QFontDatabase.addApplicationFontFromData(QByteArray(bytes(data)))
                  if data else QFontDatabase.addApplicationFont(path))
        families = QFontDatabase.applicationFontFamilies(number) if number >= 0 else []
        _FONT_CACHE[key] = (number, families)
    number, families = _FONT_CACHE[key]
    if not families:
        return None
    metadata = entry.get('metadata') or {}
    family = metadata.get('family') or entry.get('family')
    family = family if family in families else families[0]
    font = QFont(family)
    raw = QRawFont(QByteArray(bytes(data)), 12.) if data else QRawFont(str(path), 12.)
    variant = raw.styleName() if raw.isValid() else metadata.get('variant') or entry.get('variant')
    styles = QFontDatabase.styles(family)
    if variant in styles:
        font.setStyleName(variant)
    elif len(styles) == 1:
        font.setStyleName(styles[0])
    # Set real face style so Qt does not request a regular face of a registered
    # bold family (or synthesize bold on top of a regular face).
    if raw.isValid():
        font.setWeight(QFont.Weight(raw.weight()))
        font.setStyle(raw.style())
    else:
        if entry.get('bold'):
            font.setWeight(QFont.Bold)
        if entry.get('italic'):
            font.setItalic(True)
    font.setStyleStrategy(QFont.NoFontMerging)
    font.setHintingPreference(QFont.PreferNoHinting)
    return font


class PageEditor(QTextEdit):
    preview = Signal(str)  # Legacy editing API.
    cancelled = Signal()
    rich_changed = Signal(object)
    rich_accept = Signal(object)
    visibility_changed = Signal(bool)
    notice = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rich_mode = False
        self._loading = False
        self._payload = {}
        self._faces = {}
        self._catalog = []
        self._scale = 1.
        self._qt_scale = 1.
        self._original_carets = []
        self._missing_fonts = set()
        self.font_warning = ''
        self._draft_changed = False
        self.pdf_view = False
        self._preview_effect = QGraphicsOpacityEffect(self)
        self._preview_effect.setOpacity(1.)
        self.setGraphicsEffect(self._preview_effect)
        self.setAcceptRichText(False)  # Paste text, not arbitrary HTML/fonts.
        self.setTabChangesFocus(False)
        self.setFrameShape(QFrame.NoFrame)
        self.document().setDocumentMargin(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet('QTextEdit { background: white; border: 1px solid #0075b0; }')
        self.textChanged.connect(self._on_changed)
        self.toolbar = EditorToolbar(self, parent)
        self.toolbar.hide()
        self.visibility_changed.connect(self.toolbar.setVisible)
        self.cursorPositionChanged.connect(self.toolbar.sync_cursor)
        self.selectionChanged.connect(self.toolbar.sync_cursor)

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        self.toolbar.hide()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ControlModifier:
                self.accept_draft()
                return
            if event.modifiers() & Qt.ShiftModifier:
                self.textCursor().insertText('\u2028')
                return
        # Qt's built-in Ctrl+B/I can synthesize unsupported faces; use the
        # same verified catalogue selection as the toolbar instead.
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_B:
                self.toolbar.toggle_variant('bold'); return
            if event.key() == Qt.Key_I:
                self.toolbar.toggle_variant('italic'); return
            if event.key() == Qt.Key_U:
                self.merge_style(underline=not self.current_style().get('underline', False)); return
        super().keyPressEvent(event)

    def set_pdf_view(self, enabled):
        self.pdf_view = bool(enabled)
        self._preview_effect.setOpacity(0. if self.pdf_view else 1.)
        self.setReadOnly(self.pdf_view)
        with QSignalBlocker(self.toolbar.pdf_button):
            self.toolbar.pdf_button.setChecked(self.pdf_view)
        self.toolbar.pdf_button.setText('Volver a escribir' if self.pdf_view else 'Ver PDF real')
        self.toolbar.mode_label.setText('PDF real' if self.pdf_view else 'Escribir')
        if not enabled:
            self.setFocus()

    def accept_draft(self):
        if self.rich_mode:
            self.rich_accept.emit(self.payload())
        else:
            self.preview.emit(self.toPlainText())

    def set_accepting(self, accepting):
        self.setReadOnly(bool(accepting) or self.pdf_view)
        toolbar=self.toolbar
        for control in (toolbar.font_box,toolbar.size_box,toolbar.bold,toolbar.italic,
                        toolbar.underline,toolbar.color,toolbar.spacing,toolbar.paragraph_panel,
                        toolbar.pdf_button,toolbar.accept):
            control.setEnabled(not accepting)

    def load_payload(self, payload, catalog=None, zoom=1.):
        self._loading = True
        try:
            self.rich_mode = True
            self.set_pdf_view(False)
            self._payload = deepcopy(payload)
            self._catalog = [dict(item) for item in (catalog or payload.get('catalog') or [])]
            self._scale = float(zoom)
            # PDF pt becomes zoom pixels. Qt points otherwise include device DPI.
            self._qt_scale = self._scale * 72. / self.logicalDpiY()
            self.setLineWrapMode(QTextEdit.NoWrap if payload.get('auto_width') else QTextEdit.WidgetWidth)
            self._faces = {}
            self._missing_fonts = set()
            self.font_warning = ''
            missing = []
            for entry in payload.get('font_previews', []):
                name = entry.get('font_name') or entry.get('name')
                face = register_face(entry)
                if face:
                    self._faces[(name, entry.get('font_xref'))] = face
                else:
                    missing.append(name)
            self.clear()
            cursor = self.textCursor()
            cursor.beginEditBlock()
            for run in payload.get('runs', []):
                charformat = self.format_for(run)
                cursor.setCharFormat(charformat)
                cursor.insertText(run.get('text', ''), charformat)
            cursor.endEditBlock()
            for paragraph in payload.get('paragraphs', []):
                block = self.document().findBlockByNumber(int(paragraph.get('index', 0)))
                if block.isValid():
                    c = QTextCursor(block)
                    c.setBlockFormat(self.paragraph_format(paragraph))
            self.document().setDocumentMargin(0)
            cursor.setPosition(0)
            self.setTextCursor(cursor)
            self.document().clearUndoRedoStacks()
            self._original_carets = deepcopy(payload.get('carets') or [])
            self._draft_changed = False
            self.toolbar.set_catalog(self._catalog)
            self.toolbar.sync_cursor()
            missing = sorted(set(missing) | self._missing_fonts)
            if missing:
                self.font_warning = 'Qt no puede mostrar la fuente exacta: ' + ', '.join(str(x) for x in missing) + '. Ver PDF real muestra la apariencia definitiva.'
                self.notice.emit(self.font_warning)
        finally:
            self._loading = False

    def format_for(self, run):
        style = {key: deepcopy(value) for key, value in run.items() if key != 'text'}
        char = QTextCharFormat()
        char.setProperty(STYLE_PROPERTY, style)
        name = style.get('font_name')
        key = (name, style.get('font_xref'))
        face = self._faces.get(key)
        if face is None and not style.get('font_xref'):
            entry = next((e for e in self._catalog if e.get('name') == name), None)
            face = register_face(entry) if entry else None
            if face:
                self._faces[key] = face
        if face:
            char.setFont(face)
        else:
            self._missing_fonts.add(str(name or 'sin identificar'))
        # An unavailable native subset is explicitly reported above. Native
        # PDF preview is authoritative; no substitute font enters the request.
        char.setFontPointSize(float(style.get('size') or 12.) * self._qt_scale)
        color = style.get('color') or (0., 0., 0.)
        if len(color) == 4:
            value = QColor.fromCmykF(*color)
        elif len(color) == 1:
            value = QColor.fromRgbF(color[0], color[0], color[0])
        else:
            value = QColor.fromRgbF(*color[:3])
        value.setAlphaF(float(style.get('opacity', 1.)))
        char.setForeground(value)
        char.setFontUnderline(bool(style.get('underline', False)))
        char.setFontLetterSpacingType(QFont.AbsoluteSpacing)
        char.setFontLetterSpacing(float(style.get('char_spacing', 0.)) * self._scale)
        return char

    def paragraph_format(self, values):
        fmt = QTextBlockFormat()
        fmt.setProperty(PARAGRAPH_PROPERTY, deepcopy(values))
        fmt.setAlignment({'left': Qt.AlignLeft, 'center': Qt.AlignHCenter,
                          'right': Qt.AlignRight, 'justify': Qt.AlignJustify}.get(values.get('alignment'), Qt.AlignLeft))
        for name, setter in [('left_indent', fmt.setLeftMargin), ('right_indent', fmt.setRightMargin),
                ('first_indent', fmt.setTextIndent), ('space_before', fmt.setTopMargin), ('space_after', fmt.setBottomMargin)]:
            setter(float(values.get(name) or 0.) * self._scale)
        if values.get('line_spacing'):
            fmt.setLineHeight(float(values['line_spacing']) * self._scale, QTextBlockFormat.FixedHeight)
        tabs = []
        for stop in values.get('tab_stops') or []:
            tab = QTextOption.Tab()
            tab.position = float(stop) * self._scale
            tab.type = QTextOption.LeftTab
            tabs.append(tab)
        if tabs:
            fmt.setTabPositions(tabs)
        return fmt

    def current_style(self):
        fmt = self.textCursor().charFormat()
        result = dict(fmt.property(STYLE_PROPERTY) or {})
        if not result and self._payload.get('runs'):
            result = {k: deepcopy(v) for k, v in self._payload['runs'][0].items() if k != 'text'}
        return result

    def merge_style(self, **values):
        if not self.rich_mode:
            return
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        if start == end:
            style = {**self.current_style(), **values}
            self.setCurrentCharFormat(self.format_for(style))
        else:
            # Apply only requested properties to every affected fragment,
            # preserving every unrelated style in mixed selections.
            segments=[]
            block=self.document().findBlock(start)
            while block.isValid() and block.position()<end:
                iterator=block.begin()
                while not iterator.atEnd():
                    fragment=iterator.fragment()
                    if fragment.isValid():
                        a,b=max(start,fragment.position()),min(end,fragment.position()+fragment.length())
                        if a<b:
                            style=dict(fragment.charFormat().property(STYLE_PROPERTY) or self.current_style())
                            segments.append((a,b,style))
                    iterator+=1
                block=block.next()
            with QSignalBlocker(self):
                cursor.beginEditBlock()
                for a,b,style in segments:
                    probe=QTextCursor(self.document())
                    probe.setPosition(a)
                    probe.setPosition(b,QTextCursor.KeepAnchor)
                    style.update(values)
                    probe.setCharFormat(self.format_for(style))
                cursor.endEditBlock()
            self.setTextCursor(cursor)
            self._on_changed()
        self.toolbar.sync_cursor()
        self.setFocus()

    def change_face(self, entry):
        if entry.get('editable') is False:
            self.notice.emit(entry.get('status') or 'La fuente no permite edición.'); return False
        face = self._faces.get((entry.get('name'), None)) or register_face(entry)
        if not face:
            self.notice.emit('No se puede cargar la variante exacta para mostrarla. Elige una fuente TTF/OTF disponible.'); return False
        self._faces[(entry['name'], None)] = face
        self.merge_style(font_name=entry['name'], font_file=entry.get('path') or entry.get('font_file'),
                         font_xref=None, font_resource=None)
        return True

    def merge_paragraph(self, **values):
        cursor = self.textCursor()
        cursor.beginEditBlock()
        block = self.document().findBlock(cursor.selectionStart())
        last = self.document().findBlock(cursor.selectionEnd()).blockNumber()
        while block.isValid() and block.blockNumber() <= last:
            c = QTextCursor(block)
            current = dict(c.blockFormat().property(PARAGRAPH_PROPERTY) or {})
            current.update(values)
            current['index'] = block.blockNumber()
            c.setBlockFormat(self.paragraph_format(current))
            block = block.next()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setFocus()

    def payload(self):
        output = {key: deepcopy(self._payload[key]) for key in
            ('page', 'ids', 'rect', 'revision', 'width', 'height', 'allow_overlap', 'auto_width', 'auto_height')
            if key in self._payload}
        runs, paragraphs = [], []
        block = self.document().begin()
        while block.isValid():
            p = dict(block.blockFormat().property(PARAGRAPH_PROPERTY) or {})
            p['index'] = block.blockNumber()
            paragraphs.append(p)
            iterator = block.begin()
            last_style = self.current_style()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    style = dict(fragment.charFormat().property(STYLE_PROPERTY) or last_style)
                    last_style = style
                    text = fragment.text()
                    if text:
                        if runs and {k: v for k, v in runs[-1].items() if k != 'text'} == style:
                            runs[-1]['text'] += text
                        else:
                            runs.append({'text': text, **style})
                iterator += 1
            if block.next().isValid():
                if runs:
                    runs[-1]['text'] += '\n'
                else:
                    runs.append({'text': '\n', **last_style})
            block = block.next()
        output.update(runs=runs, paragraphs=paragraphs)
        return output

    def place_caret_pdf(self, point):
        """First click uses source glyph geometry, not a guessed Qt font width."""
        if not self._original_carets:
            return False
        x, y = point
        def distance(item):
            r = item['bbox']
            return max(r[0]-x, 0, x-r[2]) ** 2 + 4 * max(r[1]-y, 0, y-r[3]) ** 2
        closest = min(self._original_carets, key=distance)
        rect = closest['bbox']
        index = int(closest['index']) + (1 if x > (rect[0]+rect[2])/2 else 0)
        # Engine indices count Unicode code points; Qt cursor positions count
        # UTF-16 units (a non-BMP character consumes two).
        text=''.join(run.get('text','') for run in self._payload.get('runs',[]))
        index=len(text[:index].encode('utf-16-le'))//2
        cursor = self.textCursor()
        cursor.setPosition(min(index, self.document().characterCount()-1))
        self.setTextCursor(cursor)
        return True

    def _on_changed(self):
        if self._loading or not self.rich_mode:
            return
        self._draft_changed = True
        self.rich_changed.emit(self.payload())


class EditorToolbar(QFrame):
    """Persistent nearby controls; toolbar focus never destroys text range."""
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setObjectName('inlineFormatToolbar')
        self.setStyleSheet('QFrame#inlineFormatToolbar { background: #f7faff; border: 1px solid #0075b0; border-radius: 4px; }')
        self.setMaximumWidth(760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)
        row = QHBoxLayout()
        self.mode_label = QLabel('Escribir')
        row.addWidget(self.mode_label)
        self.font_box = QComboBox()
        self.font_box.setObjectName('inlineFont')
        self.font_box.setMaximumWidth(185)
        self.font_box.setToolTip('Familia y variante reales; se valida la fuente al aplicar')
        self.font_box.activated.connect(self._choose_face)
        row.addWidget(self.font_box)
        self.size_box = self._spin(.5, 500, 2, ' pt', 'inlineSize')
        self.size_box.setMaximumWidth(90)
        self.size_box.valueChanged.connect(lambda v: editor.merge_style(size=v))
        row.addWidget(self.size_box)
        self.bold = self._button('N', lambda: self.toggle_variant('bold'), 'Negrita real · Ctrl+B', check=True)
        self.italic = self._button('C', lambda: self.toggle_variant('italic'), 'Cursiva real · Ctrl+I', check=True)
        self.underline = self._button('S', lambda: editor.merge_style(underline=not editor.current_style().get('underline', False)), 'Subrayar · Ctrl+U', check=True)
        for widget in (self.bold, self.italic, self.underline):
            row.addWidget(widget)
        self.color = self._button('Color', self._color, 'Color del tramo seleccionado')
        row.addWidget(self.color)
        self.spacing = self._spin(-20, 100, 2, ' pt', 'inlineCharacterSpacing')
        self.spacing.setMaximumWidth(90)
        self.spacing.setToolTip('Espaciado entre caracteres')
        self.spacing.valueChanged.connect(lambda v: editor.merge_style(char_spacing=v))
        row.addWidget(self.spacing)
        self.paragraph_toggle = self._button('¶', self._toggle_paragraph, 'Sangrías, tabulaciones e interlineado')
        row.addWidget(self.paragraph_toggle)
        layout.addLayout(row)
        self.paragraph_panel = QFrame()
        grid = QGridLayout(self.paragraph_panel)
        grid.setContentsMargins(0, 2, 0, 2)
        self.paragraph_controls = {}
        controls = [('Sangría izq.', 'left_indent', 0), ('Sangría der.', 'right_indent', 0),
                    ('Primera línea', 'first_indent', -500), ('Antes', 'space_before', 0),
                    ('Después', 'space_after', 0), ('Interlineado', 'line_spacing', 0)]
        for index, (label, key, minimum) in enumerate(controls):
            spin = self._spin(minimum, 500, 2, ' pt', 'paragraph_' + key)
            if key == 'line_spacing':
                spin.setSpecialValueText('Automático')
            spin.valueChanged.connect(lambda value, field=key: editor.merge_paragraph(**{field: value}))
            grid.addWidget(QLabel(label), index // 3, (index % 3)*2)
            grid.addWidget(spin, index // 3, (index % 3)*2+1)
            self.paragraph_controls[key] = spin
        self.align = QComboBox()
        for label, value in [('Izquierda', 'left'), ('Centro', 'center'), ('Derecha', 'right'), ('Justificada', 'justify')]:
            self.align.addItem(label, value)
        self.align.activated.connect(lambda _: editor.merge_paragraph(alignment=self.align.currentData()))
        grid.addWidget(self.align, 2, 0, 1, 2)
        from PySide6.QtWidgets import QLineEdit
        self.tabs = QLineEdit()
        self.tabs.setObjectName('inlineTabStops')
        self.tabs.setPlaceholderText('Tabulaciones en pt: 36; 72; 108')
        self.tabs.editingFinished.connect(self._tabs_changed)
        grid.addWidget(self.tabs, 2, 2, 1, 4)
        layout.addWidget(self.paragraph_panel)
        self.paragraph_panel.hide()
        actions = QHBoxLayout()
        self.accept = QPushButton('Aceptar · Ctrl+Intro')
        self.accept.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.accept.setObjectName('inlineAccept')
        self.accept.clicked.connect(self.accept_draft)
        self.cancel = QPushButton('Cancelar · Esc')
        self.cancel.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
        self.cancel.setObjectName('inlineCancel')
        self.cancel.clicked.connect(editor.cancelled)
        actions.addWidget(self.accept)
        actions.addWidget(self.cancel)
        self.pdf_button = QPushButton('Ver PDF real')
        self.pdf_button.setObjectName('inlineRealPdf')
        self.pdf_button.setCheckable(True)
        self.pdf_button.setToolTip('Ver el PDF renderizado por el motor; vuelve a escribir para continuar editando')
        self.pdf_button.toggled.connect(editor.set_pdf_view)
        actions.addWidget(self.pdf_button)
        hint = QLabel('Intro: párrafo · Mayús+Intro: salto de línea')
        hint.setStyleSheet('color: #456; font-size: 10px;')
        actions.addWidget(hint)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setStyleSheet('color: #9c3426; font-size: 11px;')
        layout.addWidget(self.status)
        editor.notice.connect(self.status.setText)
        for sequence, callback in [('Ctrl+Return',self.accept_draft), ('Ctrl+Enter',self.accept_draft), ('Escape',editor.cancelled.emit)]:
            shortcut=QShortcut(QKeySequence(sequence),self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)

    def accept_draft(self):
        for control in (self.size_box,self.spacing,*self.paragraph_controls.values()):
            # Clicking Aceptar may already have moved focus off the edited
            # spinbox; commit pending numeric text regardless of focus owner.
            control.interpretText()
        if not self._tabs_changed():
            return
        self.editor.accept_draft()

    @staticmethod
    def _spin(minimum, maximum, decimals, suffix, name):
        spin = QDoubleSpinBox()
        spin.setObjectName(name)
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        return spin

    def _button(self, text, callback, tooltip, check=False):
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCheckable(check)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(callback)
        return button

    def set_catalog(self, catalog):
        with QSignalBlocker(self.font_box):
            self.font_box.clear()
            for entry in catalog:
                self.font_box.addItem(entry.get('name', ''), entry)

    def sync_cursor(self):
        if not self.editor.rich_mode:
            return
        style = self.editor.current_style()
        entry = next((e for e in self.editor._catalog if e.get('name') == style.get('font_name')), {})
        for control, value in [(self.size_box, style.get('size', 12)), (self.spacing, style.get('char_spacing', 0))]:
            with QSignalBlocker(control):
                control.setValue(float(value or 0))
        for control, value in [(self.bold, entry.get('bold', False)), (self.italic, entry.get('italic', False)),
                                (self.underline, style.get('underline', False))]:
            with QSignalBlocker(control):
                control.setChecked(bool(value))
        index = next((i for i in range(self.font_box.count()) if self.font_box.itemData(i).get('name') == style.get('font_name')), -1)
        with QSignalBlocker(self.font_box):
            self.font_box.setCurrentIndex(index)
            self.font_box.setPlaceholderText(style.get('font_name') or 'Fuente original')
        paragraph = dict(self.editor.textCursor().blockFormat().property(PARAGRAPH_PROPERTY) or {})
        for key, control in self.paragraph_controls.items():
            with QSignalBlocker(control):
                control.setValue(float(paragraph.get(key) or 0))
        with QSignalBlocker(self.align):
            self.align.setCurrentIndex(max(0, self.align.findData(paragraph.get('alignment', 'left'))))
        if not self.tabs.hasFocus():
            self.tabs.setText('; '.join(f'{x:g}' for x in paragraph.get('tab_stops') or []))
        self.mode_label.setText('Formato del tramo' if self.editor.textCursor().hasSelection() else 'Escribir')

    def _choose_face(self, index):
        entry = self.font_box.itemData(index)
        if entry:
            self.editor.change_face(entry)

    def toggle_variant(self, key):
        style = self.editor.current_style()
        current = next((e for e in self.editor._catalog if e.get('name') == style.get('font_name')), None)
        if not current:
            self.editor.notice.emit('La variante original no está disponible en el catálogo. Elige una fuente exacta.'); return
        bold, italic = bool(current.get('bold')), bool(current.get('italic'))
        bold, italic = (not bold, italic) if key == 'bold' else (bold, not italic)
        match = next((e for e in self.editor._catalog if e.get('family') == current.get('family')
                      and bool(e.get('bold')) == bold and bool(e.get('italic')) == italic and e.get('editable') is not False), None)
        if not match:
            self.editor.notice.emit('Falta la variante ' + ('negrita cursiva' if bold and italic else 'negrita' if bold else 'cursiva' if italic else 'regular') + ' de ' + str(current.get('family')))
            self.sync_cursor(); return
        self.editor.change_face(match)

    def _color(self):
        value = QColorDialog.getColor(self.editor.textColor(), self, 'Color del tramo seleccionado')
        if value.isValid():
            self.editor.merge_style(color=(value.redF(), value.greenF(), value.blueF()))

    def _toggle_paragraph(self):
        self.paragraph_panel.setVisible(not self.paragraph_panel.isVisible())
        self.adjustSize()

    def _tabs_changed(self):
        try:
            values = [float(x.strip().replace(',', '.')) for x in self.tabs.text().split(';') if x.strip()]
            if values != sorted(set(values)) or any(x <= 0 for x in values):
                raise ValueError()
        except ValueError:
            self.editor.notice.emit('Tabulaciones: usa posiciones positivas crecientes en puntos, separadas por punto y coma.')
            return False
        current=dict(self.editor.textCursor().blockFormat().property(PARAGRAPH_PROPERTY) or {})
        if values!=list(current.get('tab_stops') or []):
            self.editor.merge_paragraph(tab_stops=values)
        return True
