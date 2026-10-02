"""Integra el lector continuo con el proceso PDF serial y el historial existente."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap, QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from .ui_icons_v170 import icon_v170


class ContinuousUiV180Mixin:
    def _create_continuous_ui_v180(self):
        self._reader_generation_v180 = 0
        self._reader_key_v180 = None
        self._reader_queue_v180 = []
        self._reader_copy_v180 = None
        self._reader_tools_pending_v180 = False
        self.reader.pages_requested.connect(self._queue_reader_pages_v180)
        self.reader.current_page_changed.connect(self._reader_current_page_v180)
        self.reader.selection_changed.connect(self._reader_selection_v180)
        self.reader.copy_requested.connect(self.clipboard_copy_v170)
        self.reader.context_requested.connect(self._reader_context_v180)
        self.reader_timer_v180 = QTimer(self)
        self.reader_timer_v180.setInterval(45)
        self.reader_timer_v180.timeout.connect(self._pump_reader_v180)
        self.reader_timer_v180.start()
        self.remove_tags_action = QAction('Quitar etiquetas de accesibilidad…', self)
        self.remove_tags_action.setObjectName('removeTagsAction')
        self.remove_tags_action.setIcon(icon_v170('document_properties'))
        self.remove_tags_action.setToolTip('Crear una copia sin estructura accesible; conserva el PDF original')
        self.remove_tags_action.triggered.connect(self.remove_tags_v180)
        self._tool_button_v150(self.advanced_tools_section.body, self.remove_tags_action, 'toolRemoveTags')

    def _show_document_mode_v180(self, mode):
        self.document_views.setCurrentWidget(self.reader if mode == 'reading' else self.canvas)
        if mode != 'reading':
            self._reader_queue_v180.clear()
            self._reader_copy_v180 = None
        elif self.state:
            if self.reader.zoom != self.zoom:
                self.reader.set_zoom(self.zoom)
            self._ensure_reader_v180()

    def _ensure_reader_v180(self):
        if not self.state or self.busy:
            return
        key = (self.state.get('document_revision'), bool(self.compare_action.isChecked()))
        if self._reader_key_v180 == key:
            self.reader.go_page(self.page_number)
            return
        self._reader_generation_v180 += 1
        generation = self._reader_generation_v180
        self._reader_queue_v180.clear()
        def ready(result):
            if generation != self._reader_generation_v180 or self.application_mode != 'reading':
                return
            self._reader_key_v180 = key
            self.reader.reset_document(result['page_geometries'], zoom=self.zoom)
            self.reader.go_page(min(self.page_number, len(result['page_geometries'])-1))
            self._pump_reader_v180()
        self._submit('reading_info', {'original': self.compare_action.isChecked()}, ready)

    def _queue_reader_pages_v180(self, pages):
        if not self.state or self.application_mode != 'reading':
            return
        # Requests are replaced with the newest viewport: quickly scrolling to
        # page 80 must not wait for renders of pages which are no longer nearby.
        pages = list(dict.fromkeys(int(p) for p in pages if 0 <= int(p) < self.state['page_count']))
        self._reader_queue_v180 = pages

    def _pump_reader_v180(self):
        if self._closed or self.busy or not self.state or self.application_mode != 'reading' or QApplication.activeModalWidget() is not None:
            return
        if self._reader_tools_pending_v180:
            self._reader_tools_pending_v180 = False
            self._tools_mode_v171(True)
            return
        if self._reader_copy_v180 is not None:
            payload, self._reader_copy_v180 = self._reader_copy_v180, None
            def copied(result):
                QApplication.clipboard().setText(result['text'])
                self._notice('Texto seleccionado copiado, incluidos los párrafos y páginas intermedios.')
            self._submit('reading_copy_range', payload, copied)
            return
        key = (self.state.get('document_revision'), bool(self.compare_action.isChecked()))
        if self._reader_key_v180 != key:
            self._ensure_reader_v180()
            return
        while self._reader_queue_v180:
            number = self._reader_queue_v180.pop(0)
            if self.reader.has_page(number, self.zoom):
                continue
            generation = self._reader_generation_v180
            zoom = self.zoom
            def loaded(result):
                if generation != self._reader_generation_v180 or self.application_mode != 'reading' or zoom != self.zoom:
                    return
                self.reader.set_page(result['number'], result['png'], result['model'], result['zoom'])
                if result['number'] == self.page_number:
                    self.model = result['model']
                    self.fonts = []
                pixmap = QPixmap(); pixmap.loadFromData(result['png'])
                self._set_thumbnail(result['number'], pixmap)
                self._refresh_actions()
                self.page_ready.emit()
            self._submit('page', {'number': number, 'zoom': zoom, 'reading': True,
                                  'original': self.compare_action.isChecked()}, loaded)
            break

    def _reader_current_page_v180(self, number):
        if self.application_mode != 'reading' or not self.state:
            return
        self.page_number = number
        model = self.reader.model_for_page(number)
        if model is not None:
            self.model = model
        blocked = self.pages.blockSignals(True)
        self.pages.setCurrentRow(number)
        self.pages.blockSignals(blocked)
        self.statusBar().showMessage(f'Lectura · Página {number+1}/{self.state["page_count"]} · Zoom {self.zoom*100:.1f}%')

    def _reader_selection_v180(self, endpoints):
        if self.application_mode == 'reading':
            self._refresh_clipboard_v170()

    def _tools_mode_v171(self, editing):
        if editing and self.busy and self._command in ('page', 'reading_info') and self.application_mode == 'reading':
            self._reader_tools_pending_v180 = True
            self._reader_queue_v180.clear()
            self._notice('Preparando las herramientas al terminar la página en curso…')
            return
        if editing and self.state and self.application_mode == 'reading':
            self.page_number = self.reader.current_page()
            self.canvas.ids = []
            # A selection crossing pages is for copying. It cannot be silently
            # turned into one editable box on a different page.
            self._restore_regions = None
        return super()._tools_mode_v171(editing)

    def _refresh_reading_actions_v171(self):
        super()._refresh_reading_actions_v171()
        if not hasattr(self, 'remove_tags_action'):
            return
        reading = self.application_mode == 'reading'
        self.remove_tags_action.setEnabled(bool(self.state.get('tagged') and not self.busy
            and not self.state.get('issues') and not self.state.get('preview') and not reading
            and not self.canvas.editor.isVisible() and not getattr(self, '_rich_active', False)))
        if reading:
            self.pages.setEnabled(bool(self.state))
            if self._command in ('page', 'reading_info') and not self._mode_preparing_v171:
                self.tools_action.setEnabled(True)

    def _refresh_clipboard_v170(self):
        super()._refresh_clipboard_v170()
        if hasattr(self, 'reader') and getattr(self, 'application_mode', None) == 'reading' and self._native_clipboard_target_v170() is None:
            self.copy_action_v170.setEnabled(bool(self.reader.selection_endpoints() and self.state.get('copy_allowed', True)))

    def clipboard_copy_v170(self):
        if self.application_mode != 'reading':
            return super().clipboard_copy_v170()
        endpoints = self.reader.selection_endpoints()
        if not endpoints:
            return
        if not self.state.get('copy_allowed', True):
            self._error('El documento no permite copiar texto con las credenciales aportadas.')
            return
        model = self.reader.model_for_page(endpoints['start']['page'])
        if model is None:
            self._error('Espera a que termine de cargarse el texto seleccionado.')
            return
        self._reader_copy_v180 = {**endpoints, 'revision': model.revision,
                                  'original': self.compare_action.isChecked()}
        self._pump_reader_v180()

    def _reader_context_v180(self, position):
        self.reader.setFocus()
        self._refresh_clipboard_v170()
        menu = QMenu(self); menu.setObjectName('readingTextContextMenu')
        menu.addAction(self.copy_action_v170)
        self._clipboard_menu_v170 = menu
        menu.popup(position)

    def remove_tags_v180(self):
        if not self.remove_tags_action.isEnabled():
            return
        choice = QMessageBox.question(self, 'Quitar etiquetas de accesibilidad',
            'Las etiquetas identifican párrafos, títulos, tablas y el orden para los lectores de pantalla. '
            'Quitarlas pierde esta información de accesibilidad. Se conservarán el texto y la apariencia, '
            'y el original seguirá intacto. Esta operación no elimina otros límites de edición. '
            '¿Preparar la copia sin etiquetas?', QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if choice == QMessageBox.Yes:
            self._submit('remove_tags', callback=self._previewed)
