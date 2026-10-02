"""Lectura ligera, selección copiable y transición explícita a herramientas."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from .ui_icons_v170 import icon_v170


class ReadingUiV171Mixin:
    def _create_reading_ui_v171(self):
        self.application_mode = 'reading'
        self._mode_preparing_v171 = False
        self._wheel_scroll_edge_v171 = None
        self.reading_action = QAction('Lectura', self)
        self.reading_action.setObjectName('readingModeAction')
        self.reading_action.setIcon(icon_v170('pages'))
        self.reading_action.setToolTip('Volver a Lectura: seleccionar y copiar sin editar')
        self.reading_action.triggered.connect(lambda: self.tools_action.setChecked(False))
        self.toolbar.insertAction(self.sign_action, self.reading_action)
        self.mode_label_v171 = QLabel('Lectura')
        self.mode_label_v171.setObjectName('applicationModeLabel')
        self.toolbar.insertWidget(self.sign_action, self.mode_label_v171)
        self.tools_action.toggled.connect(self._tools_mode_v171)
        self.canvas.wheel_page_requested.connect(self._wheel_page_v171)
        self._set_mode_v171('reading')
        self._notice('Modo Lectura: selecciona y copia texto. Pulsa «Herramientas» para editar.')

    def _set_mode_v171(self, mode):
        self.application_mode = mode
        editing = mode == 'editing'
        blocked = self.tools_action.blockSignals(True)
        self.tools_action.setChecked(editing)
        self.tools_action.blockSignals(blocked)
        self.tools_scroll.setVisible(editing)
        self.canvas.reading_mode = not editing
        self.mode_label_v171.setText('Edición' if editing else 'Lectura')
        for action in self.mode_actions_v170.values():
            action.setVisible(editing)
        if hasattr(self, 'poller'):
            self._refresh_actions()

    def _tools_mode_v171(self, editing):
        writing = self.canvas.editor.isVisible() or getattr(self, '_rich_active', False) or getattr(self, '_rich_loading', False)
        if self.busy or writing or self.state.get('preview') or getattr(self, '_placement', None):
            self._set_mode_v171(self.application_mode)
            self._notice('Aplica o cancela el borrador antes de cambiar de modo.' if writing or self.state.get('preview') else 'Espera a que termine la operación antes de cambiar de modo.')
            return
        if not editing:
            self._set_mode_v171('reading')
            self._notice('Modo Lectura: clic para seleccionar una palabra; arrastra para seleccionar texto. Ctrl+C copia.')
            return
        if not self.state:
            self._set_mode_v171('editing')
            return
        # Even a previously prepared session may currently display a light
        # reading model: obtain a full page before enabling any editing route.
        self._restore_regions = [g.bbox for g in self.model.selected(self.canvas.ids)] if self.model else None
        self._mode_preparing_v171 = True
        def prepared(result):
            self._mode_preparing_v171 = False
            self._set_mode_v171('editing')
            self._loaded_page(result)
            if self.state.get('issues'):
                self._error('\n'.join(self.state['issues']))
            else:
                self._notice('Modo Edición: las herramientas están disponibles según la compatibilidad del documento.')
        if not self._submit('prepare_editing', {'number': self.page_number, 'zoom': self.zoom,
                                               'original': self.compare_action.isChecked()}, prepared):
            self._mode_preparing_v171 = False
            self._set_mode_v171('reading')

    def _reading_command_allowed_v171(self, command):
        if self.application_mode == 'editing':
            return True
        if command in ('open', 'close', 'page', 'prepare_editing', 'search', 'document_properties', 'clipboard_copy'):
            return True
        self._notice('Pulsa «Herramientas» para activar el modo Edición.')
        return False

    def _refresh_reading_actions_v171(self):
        if not hasattr(self, 'application_mode'):
            return
        reading = self.application_mode == 'reading'
        draft = self.canvas.editor.isVisible() or getattr(self, '_rich_active', False) or getattr(self, '_rich_loading', False)
        self.tools_action.setEnabled(not self.busy and not draft and not self.state.get('preview'))
        self.reading_action.setEnabled(not self.busy and not draft and not self.state.get('preview'))
        self.canvas.page_navigation_enabled = bool(self.state and not self.busy and not draft and not self.state.get('preview'))
        if not reading:
            return
        self.canvas.read_only = True
        self.canvas.allow_background_edit = False
        for name in ('save_action', 'sign_action', 'undo_action', 'redo_action', 'add_text_action',
                     'format_action', 'add_image_action', 'image_mode_action', 'delete_pages_action',
                     'extract_pages_action', 'merge_action', 'replace_action', 'organize_action',
                     'objects_action', 'copy_format_action', 'paste_format_action', 'edit_content_action',
                     'export_document_action', 'rotate_pages_action', 'insert_pages_action',
                     'replace_pages_action', 'crop_pages_action', 'split_document_action',
                     'add_text_properties_action', 'document_security_action', 'font_button'):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(False)
        for name in ('property_box', 'line_reflow_box', 'interaction_box', 'side_format_controls', 'image_box', 'image_quick_controls'):
            getattr(self, name).setEnabled(False)
        for action in self.mode_actions_v170.values():
            action.setEnabled(False)
        self.edit_steps.hide()
        self._refresh_clipboard_v170()

    def _clipboard_ready_v170(self, editing=False):
        if editing and getattr(self, 'application_mode', 'editing') == 'reading':
            return False
        return super()._clipboard_ready_v170(editing)

    def _refresh_clipboard_v170(self):
        super()._refresh_clipboard_v170()
        if getattr(self, 'application_mode', None) == 'reading' and self._native_clipboard_target_v170() is None:
            self.copy_action_v170.setEnabled(bool(self.model and self.canvas.ids and self.state.get('copy_allowed', True)))
            for action in (self.cut_action_v170, self.paste_action_v170, self.delete_action_v170):
                action.setEnabled(False)

    def clipboard_copy_v170(self):
        if self.application_mode != 'reading':
            return super().clipboard_copy_v170()
        if not self.state.get('copy_allowed', True):
            self._error('El documento no permite copiar texto con las credenciales aportadas.')
            return
        text = self.canvas.reading_text()
        if text:
            QApplication.clipboard().setText(text)
            self._notice('Texto copiado al portapapeles.')

    def _clipboard_context_v170(self, position, image=False):
        if self.application_mode != 'reading':
            return super()._clipboard_context_v170(position, image)
        if image or not self.canvas.ids:
            return
        self.canvas.setFocus()
        self._refresh_clipboard_v170()
        menu = QMenu(self)
        menu.setObjectName('readingTextContextMenu')
        menu.addAction(self.copy_action_v170)
        self._clipboard_menu_v170 = menu
        menu.popup(position)

    def _wheel_page_v171(self, direction):
        target = self.page_number + (1 if direction > 0 else -1)
        if not self.canvas.page_navigation_enabled or not 0 <= target < self.state.get('page_count', 0):
            return
        self._wheel_scroll_edge_v171 = 'top' if direction > 0 else 'bottom'
        self.go_page(target)

    def _after_reading_page_loaded_v171(self):
        edge, self._wheel_scroll_edge_v171 = self._wheel_scroll_edge_v171, None
        if edge:
            model = self.model
            def position():
                if self.model is model:
                    bar = self.canvas.verticalScrollBar()
                    bar.setValue(bar.minimum() if edge == 'top' else bar.maximum())
            QTimer.singleShot(0, position)
