"""Directed UI checks without starting a PDF worker or a real update request."""
import hashlib

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from pdfmodder.ui_icons_v170 import ICON_DRAWINGS_V170, icon_v170
from pdfmodder.workspace_ui_v170 import RecentFilesStore, UpdatesDialog
from test_tools_ui_v150 import tools_window


def test_recent_files_are_local_persistent_deduplicated_and_clear_preserves_pdfs(tmp_path):
    first = tmp_path / 'Primero.pdf'
    second = tmp_path / 'Segundo.pdf'
    first.write_bytes(b'local one')
    second.write_bytes(b'local two')
    path = tmp_path / 'settings' / 'recent_files.json'
    store = RecentFilesStore(path)
    assert store.add(first) and store.add(second) and store.add(first)
    reopened = RecentFilesStore(path)
    assert [item['path'] for item in reopened.entries()] == [str(first), str(second)]
    reopened.clear()
    assert not store.entries() and first.exists() and second.exists()


def test_vector_icons_have_distinct_drawings_and_render_at_high_dpi(qtbot):
    assert len(set(ICON_DRAWINGS_V170.values())) == len(ICON_DRAWINGS_V170)
    fingerprints = []
    for kind in ('open', 'save', 'undo', 'redo', 'copy', 'cut', 'paste', 'delete',
                 'select', 'write', 'move', 'document_properties', 'security', 'recent', 'updates'):
        icon = icon_v170(kind)
        assert not icon.isNull()
        pixmap = icon.pixmap(QSize(24, 24), 2., QIcon.Normal, QIcon.Off)
        assert pixmap.width() == 48 and pixmap.devicePixelRatio() == 2.
        bits = pixmap.toImage().bits()
        fingerprints.append(hashlib.sha256(bytes(bits)).digest())
    assert len(set(fingerprints)) == len(fingerprints)


def test_workspace_modes_recent_tab_and_manual_update_startup(tools_window, monkeypatch, qtbot):
    window = tools_window
    assert window.workspace_tabs_v170.widget(0) is window.pages
    assert window.workspace_tabs_v170.tabText(1) == 'Recientes'
    assert window.workspace_tabs_v170.width()>=220
    for section in (window.content_tools_section,window.format_tools_section,
                    window.page_tools_section,window.advanced_tools_section):
        assert not section.header.icon().isNull() and not section.header.isChecked()
    assert not window.interaction_box.isVisible()
    assert window._updater_v170.status()['state'] == 'idle'
    assert window.update_action_v170.isEnabled()
    window.interaction_box.setEnabled(True)
    window._refresh_v170()
    window.mode_actions_v170['move'].trigger()
    assert window.canvas.interaction_mode == 'move'
    window.interaction_box.setCurrentIndex(window.interaction_box.findData('select'))
    assert window.mode_actions_v170['select'].isChecked()
    assert not window.mode_actions_v170['move'].isChecked()
    dialog = UpdatesDialog(window, window._updater_v170)
    qtbot.addWidget(dialog)
    assert dialog.check_button.isEnabled()
    assert not dialog.download_button.isEnabled() and not dialog.install_button.isEnabled()
    assert 'cuando quieras' in dialog.message.text()
    dialog.reject()
