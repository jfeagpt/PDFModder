"""Visible interaction modes, local recent files and a manual update dialog."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QSignalBlocker, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QProgressBar,
    QTabWidget, QToolButton, QVBoxLayout, QWidget)

from . import __version__
from .ui_icons_v170 import apply_action_icons_v170, icon_v170
from .updates_v170 import AppUpdater, RELEASES_URL, detected_installation_directory


class RecentFilesStore:
    """A local per-user list of paths; PDF content and passwords are never stored."""
    LIMIT = 25

    def __init__(self, path):
        self.path = Path(path)

    def entries(self):
        try:
            if self.path.stat().st_size > 128 * 1024:
                return []
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or value.get('schema') != 1:
                return []
            items = value.get('files')
            if not isinstance(items, list):
                return []
            valid, seen = [], set()
            for item in items[:self.LIMIT]:
                if (not isinstance(item, dict) or not isinstance(item.get('path'), str)
                        or not item['path'] or len(item['path']) > 32768
                        or not Path(item['path']).is_absolute()):
                    continue
                key = os.path.normcase(item['path'])
                if key not in seen:
                    valid.append({'path': item['path'], 'opened': str(item.get('opened', ''))[:40]})
                    seen.add(key)
            return valid
        except (OSError, ValueError, UnicodeError):
            return []

    def _write(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(prefix='recent-', suffix='.tmp', dir=self.path.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump({'schema': 1, 'files': items[:self.LIMIT]}, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def add(self, path):
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() != '.pdf':
            return False
        key = os.path.normcase(str(path))
        items = [item for item in self.entries() if os.path.normcase(item['path']) != key]
        items.insert(0, {'path': str(path), 'opened': datetime.now(timezone.utc).isoformat(timespec='seconds')})
        self._write(items)
        return True

    def clear(self):
        self._write([])


def local_data_directory(config_path=None):
    if config_path:
        return Path(config_path).resolve().parent
    base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    # QApplication applicationName can be unset when embedded in a UI test.
    directory = Path(base)
    return directory if directory.name.lower() == 'pdfmodder' else directory / 'PDFModder'


class UpdatesDialog(QDialog):
    def __init__(self, window, updater):
        super().__init__(window)
        self.window = window
        self.updater = updater
        self._automatic_update = False
        self._discard_confirmed = False
        self.setObjectName('updatesDialogV170')
        self.setWindowTitle('Actualizaciones de PDF Modder')
        self.setMinimumWidth(510)
        layout = QVBoxLayout(self)
        self.version_label = QLabel(f'Versión instalada: {__version__}')
        layout.addWidget(self.version_label)
        note = QLabel('«Actualizar ahora» busca, descarga y comprueba la nueva versión. Después se cierra la aplicación, se instala y se vuelve a abrir. La instalación anterior se retira sólo después de instalar correctamente; tus PDF y preferencias se conservan. Las copias portables se conservan.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.message = QLabel()
        self.message.setObjectName('updateStatusV170')
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.check_button = QPushButton('Actualizar ahora')
        self.check_button.setObjectName('checkUpdatesV170')
        self.check_button.setIcon(icon_v170('updates'))
        self.download_button = QPushButton('Descargar instalador')
        self.download_button.setObjectName('downloadUpdateV170')
        self.download_button.setIcon(icon_v170('download'))
        self.install_button = QPushButton('Instalar actualización…')
        self.install_button.setObjectName('installUpdateV170')
        self.install_button.setIcon(icon_v170('install'))
        self.check_button.clicked.connect(self._check)
        self.download_button.clicked.connect(self._download)
        self.install_button.clicked.connect(self._install)
        row.addWidget(self.check_button)
        # Preserve the old attributes for integrations, with one visible action.
        self.download_button.hide()
        self.install_button.hide()
        layout.addLayout(row)
        release_button = QPushButton('Ver versiones públicas en GitHub')
        release_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        layout.addWidget(release_button)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText('Cerrar')
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()
        self._refresh()

    def _check(self):
        self._automatic_update = True
        self._discard_confirmed = False
        state = self.updater.status()['state']
        if state == 'ready':
            self._install()
        elif state == 'available':
            self._download()
        else:
            self.updater.check()
        self._refresh()

    def _download(self):
        self.updater.download()
        self._refresh()

    def _install(self):
        if self.window.busy or getattr(self.window, '_signature_placement_dialog', None) is not None:
            self._automatic_update = False
            QMessageBox.information(self, 'Operación en curso', 'Espera a que termine la operación del PDF antes de instalar.')
            return
        if not self.window._confirm_discard():
            self._automatic_update = False
            return
        self._discard_confirmed = True
        self._automatic_update = False
        directory = detected_installation_directory(installed_version=self.updater.status()['installedVersion'])
        self.updater.install(previous_directory=directory,
                             previous_pid=os.getpid() if directory is not None else None)
        self._refresh()

    def _refresh(self):
        status = self.updater.status()
        state, busy = status['state'], status['busy']
        latest = status['latestVersion']
        self.version_label.setText(f"Versión instalada: {status['installedVersion']}" + (f' · Publicada: {latest}' if latest else ''))
        self.message.setText(status['message'])
        self.progress.setVisible(state in ('downloading', 'ready'))
        self.progress.setValue(status['progress'])
        self.check_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy and state == 'available')
        self.install_button.setEnabled(not busy and state == 'ready')
        if self._automatic_update and not busy:
            if state == 'available':
                self._download()
            elif state == 'ready':
                self._install()
            elif state in ('current', 'error', 'unavailable', 'cancelled'):
                self._automatic_update = False
        if state == 'installing' and self._discard_confirmed:
            self.timer.stop()
            self.accept()
            self.window._allow_close = True
            self.window.close()

    def reject(self):
        self._automatic_update = False
        self.timer.stop()
        if self.updater.status()['busy']:
            self.updater.cancel()
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.accept()


class WorkspaceUiV170Mixin:
    def _create_workspace_v170(self):
        self._local_data_v170 = local_data_directory(getattr(self, 'config_path', None))
        self._recent_store_v170 = RecentFilesStore(self._local_data_v170 / 'recent_files.json')
        self._updater_v170 = AppUpdater(__version__, self._local_data_v170 / 'updates')
        self.destroyed.connect(lambda _=None, updater=self._updater_v170: updater.cancel())

        self.workspace_tabs_v170 = QTabWidget()
        self.workspace_tabs_v170.setObjectName('workspaceTabsV170')
        self.workspace_tabs_v170.setMinimumWidth(220)
        self.workspace_tabs_v170.setMaximumWidth(235)
        index = self.document_splitter.indexOf(self.pages)
        self.document_splitter.replaceWidget(index, self.workspace_tabs_v170)
        self.workspace_tabs_v170.addTab(self.pages, icon_v170('pages'), 'Páginas')
        recent_panel = QWidget()
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(4, 6, 4, 6)
        hint = QLabel('Archivos abiertos en este equipo')
        hint.setWordWrap(True)
        recent_layout.addWidget(hint)
        self.recent_files_v170 = QListWidget()
        self.recent_files_v170.setObjectName('recentFilesV170')
        self.recent_files_v170.setWordWrap(True)
        self.recent_files_v170.setIconSize(QSize(24, 24))
        self.recent_files_v170.itemClicked.connect(self._open_recent_v170)
        self.recent_files_v170.itemActivated.connect(self._open_recent_v170)
        recent_layout.addWidget(self.recent_files_v170, 1)
        self.clear_recent_button_v170 = QPushButton('Vaciar lista')
        self.clear_recent_button_v170.setObjectName('clearRecentV170')
        self.clear_recent_button_v170.setIcon(icon_v170('delete'))
        self.clear_recent_button_v170.setToolTip('Borra esta lista local; los archivos PDF se conservan.')
        self.clear_recent_button_v170.clicked.connect(self._clear_recent_v170)
        recent_layout.addWidget(self.clear_recent_button_v170)
        self.workspace_tabs_v170.addTab(recent_panel, icon_v170('recent'), 'Recientes')
        self.thumbnail_action.triggered.connect(self.workspace_tabs_v170.setVisible)
        self._reload_recent_v170()

        self.mode_group_v170 = QActionGroup(self)
        self.mode_group_v170.setExclusive(True)
        self.mode_actions_v170 = {}
        combo_action = next((action for action in self.toolbar.actions()
                             if self.toolbar.widgetForAction(action) is self.interaction_box), None)
        for key, label in (('select', 'Seleccionar'), ('write', 'Escribir'), ('move', 'Mover')):
            action = QAction(icon_v170(key), label, self)
            action.setObjectName('interaction_' + key + '_v170')
            action.setCheckable(True)
            action.setToolTip(label + ' en la página')
            self.mode_group_v170.addAction(action)
            action.triggered.connect(lambda _=False, mode=key: self._set_mode_v170(mode))
            self.mode_actions_v170[key] = action
            if combo_action is not None:
                self.toolbar.insertAction(combo_action, action)
            else:
                self.toolbar.addAction(action)
            button = self.toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        if combo_action is not None:
            combo_action.setVisible(False)
        self.interaction_box.hide()
        self.interaction_box.currentIndexChanged.connect(self._sync_modes_v170)
        self._sync_modes_v170()

        self.update_action_v170 = QAction(icon_v170('updates'), 'Buscar actualizaciones…', self)
        self.update_action_v170.setObjectName('updateActionV170')
        self.update_action_v170.setToolTip('Buscar y descargar versiones públicas de PDF Modder; sólo al pulsar.')
        self.update_action_v170.triggered.connect(self.show_updates_v170)
        self.toolbar.addAction(self.update_action_v170)
        update_button = self.toolbar.widgetForAction(self.update_action_v170)
        if isinstance(update_button, QToolButton):
            update_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        apply_action_icons_v170(self)
        for section,kind in ((self.content_tools_section,'edit'),(self.format_tools_section,'format'),
                             (self.page_tools_section,'pages'),(self.advanced_tools_section,'document_properties')):
            section._section_icon_v170=icon_v170(kind)
            section.set_expanded(section.header.isChecked())
        self._refresh_v170()

    def _set_mode_v170(self, mode):
        index = self.interaction_box.findData(mode)
        if index >= 0:
            self.interaction_box.setCurrentIndex(index)
        self.canvas.setFocus()

    def _sync_modes_v170(self, *_):
        mode = self.interaction_box.currentData()
        for key, action in self.mode_actions_v170.items():
            with QSignalBlocker(action):
                action.setChecked(key == mode)

    def _reload_recent_v170(self):
        self.recent_files_v170.clear()
        entries = self._recent_store_v170.entries()
        for entry in entries:
            path = Path(entry['path'])
            exists = path.is_file()
            item = QListWidgetItem(icon_v170('document'), path.name + ('' if exists else '\nNo disponible'))
            item.setData(Qt.UserRole, entry['path'])
            item.setToolTip(str(path) + ('\nAbre este PDF local.' if exists else '\nEl archivo se ha movido o eliminado.'))
            self.recent_files_v170.addItem(item)
        if not entries:
            item = QListWidgetItem('Todavía no hay archivos recientes.')
            item.setFlags(Qt.NoItemFlags)
            self.recent_files_v170.addItem(item)
        self.clear_recent_button_v170.setEnabled(bool(entries))

    def recent_open(self, path):
        if not path or not hasattr(self, '_recent_store_v170'):
            return
        try:
            if self._recent_store_v170.add(path):
                self._reload_recent_v170()
        except OSError:
            self.statusBar().showMessage('El PDF está abierto; no se ha podido guardar la lista local de recientes.', 5000)

    def _open_recent_v170(self, item):
        path = item.data(Qt.UserRole)
        if not path or self.busy or not self.open_action.isEnabled():
            return
        if not Path(path).is_file():
            QMessageBox.information(self, 'Archivo no disponible', 'Este PDF se ha movido o eliminado. Usa «Abrir» para elegir su ubicación actual.')
            return
        if self._confirm_discard():
            self.open_document(path)

    def _clear_recent_v170(self):
        try:
            self._recent_store_v170.clear()
            self._reload_recent_v170()
        except OSError:
            QMessageBox.information(self, 'Lista de recientes', 'No se ha podido guardar la lista local de recientes.')

    def _refresh_v170(self):
        if not hasattr(self, 'mode_actions_v170'):
            return
        for action in self.mode_actions_v170.values():
            action.setEnabled(self.interaction_box.isEnabled())
        self._sync_modes_v170()
        self.recent_files_v170.setEnabled(self.open_action.isEnabled())
        self.update_action_v170.setEnabled(not self.busy and not getattr(self, '_closed', False))

    def show_updates_v170(self):
        if self._updater_v170._cancel.is_set():
            self._updater_v170 = AppUpdater(__version__, self._local_data_v170 / 'updates')
            self.destroyed.connect(lambda _=None, updater=self._updater_v170: updater.cancel())
        dialog = UpdatesDialog(self, self._updater_v170)
        dialog.exec()

    def _close_workspace_v170(self):
        if hasattr(self, '_updater_v170'):
            self._updater_v170.cancel()
