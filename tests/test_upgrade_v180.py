"""Update handoff and one-click UI, without network or launching installers."""
import hashlib
import json

from PySide6.QtWidgets import QWidget

from pdfmodder import updates_v170 as updates
from pdfmodder import workspace_ui_v170 as workspace


def installed(directory, version='1.7.1'):
    directory.mkdir()
    (directory / 'PDFModder.exe').write_bytes(b'MZ installed fixture')
    (directory / 'Desinstalar.exe').write_bytes(b'MZ uninstaller fixture')
    (directory / '.pdfmodder-files.tsv').write_text('fixture', encoding='utf-8')
    (directory / '.pdfmodder-installation.json').write_text(json.dumps({
        'application_id': 'PDFModder.Windows.PerUser', 'version': version}), encoding='utf-8')
    return directory


def ready_updater(tmp_path):
    payload = b'MZ installer fixture'
    path = tmp_path / 'installer.exe'
    path.write_bytes(payload)
    updater = updates.AppUpdater('1.7.1', tmp_path)
    updater._release = {'version': '1.8.0', 'sha256': hashlib.sha256(payload).hexdigest(), 'size': len(payload)}
    updater._ready_path = path
    updater._set(state='ready')
    return updater


def test_installed_and_portable_copies_are_distinguished(tmp_path):
    directory = installed(tmp_path / 'Anterior')
    assert updates.detected_installation_directory(directory / 'PDFModder.exe', '1.7.1') == directory
    assert updates.detected_installation_directory(directory / 'PDFModder.exe', '1.7.0') is None
    (directory / '.pdfmodder-installation.json').unlink()
    assert updates.detected_installation_directory(directory / 'PDFModder.exe') is None


def test_handoff_targets_only_this_installation_and_verifies_installer_again(tmp_path, monkeypatch, qtbot):
    directory = installed(tmp_path / 'Anterior')
    updater = ready_updater(tmp_path)
    calls = []
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)))
    assert updater.install(directory, 12345)
    qtbot.waitUntil(lambda: not updater.status()['busy'])
    assert updater.status()['state'] == 'installing'
    command = calls[0][0][0]
    assert command[1:] == ['--update', '--previous-dir', str(directory), '--previous-pid', '12345']
    assert calls[0][1]['shell'] is False
    updater._set(state='ready')
    updater._ready_path.write_bytes(b'X' * updater._release['size'])
    assert updater.install(directory, 12345)
    qtbot.waitUntil(lambda: not updater.status()['busy'])
    assert updater.status()['state'] == 'error' and 'SHA-256' in updater.status()['message']
    assert len(calls) == 1


def test_portable_update_never_requests_removal_of_other_versions(tmp_path, monkeypatch, qtbot):
    updater = ready_updater(tmp_path)
    calls = []
    monkeypatch.setattr(updates.subprocess, 'Popen', lambda *args, **kwargs: calls.append(args[0]))
    updater.install()
    qtbot.waitUntil(lambda: not updater.status()['busy'])
    assert calls[0][1:] == ['--update']


class UpdateWindow(QWidget):
    busy = False
    _signature_placement_dialog = None

    def __init__(self, discard=True):
        super().__init__()
        self.discard, self.discard_checks, self.closed, self._allow_close = discard, 0, False, False

    def _confirm_discard(self):
        self.discard_checks += 1
        return self.discard

    def close(self):
        self.closed = True
        return True


class SynchronousUpdater:
    def __init__(self):
        self.value = {'state': 'idle', 'busy': False, 'installedVersion': '1.7.1',
                      'latestVersion': '', 'message': 'cuando quieras', 'progress': 0}
        self.calls = []

    def status(self):
        return dict(self.value)

    def check(self):
        self.calls.append('check')
        self.value.update(state='available', latestVersion='1.8.0')

    def download(self):
        self.calls.append('download')
        self.value.update(state='ready', progress=100)

    def install(self, **kwargs):
        self.calls.append(('install', kwargs))
        self.value['state'] = 'installing'

    def cancel(self):
        self.calls.append('cancel')


def test_one_click_updates_and_closes_only_after_unsaved_work_check(qtbot, monkeypatch):
    window, updater = UpdateWindow(), SynchronousUpdater()
    qtbot.addWidget(window)
    monkeypatch.setattr(workspace, 'detected_installation_directory', lambda **_: None)
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    dialog._check()
    assert updater.calls[:2] == ['check', 'download']
    assert updater.calls[2] == ('install', {'previous_directory': None, 'previous_pid': None})
    assert window.discard_checks == 1 and window._allow_close and window.closed
    assert dialog.check_button.text() == 'Actualizar ahora'
    assert dialog.download_button.isHidden() and dialog.install_button.isHidden()


def test_cancel_unsaved_work_keeps_app_and_ready_package(qtbot, monkeypatch):
    window, updater = UpdateWindow(discard=False), SynchronousUpdater()
    qtbot.addWidget(window)
    monkeypatch.setattr(workspace, 'detected_installation_directory', lambda **_: None)
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    dialog._check()
    assert updater.calls == ['check', 'download']
    assert window.discard_checks == 1 and not window._allow_close and not window.closed
    assert updater.status()['state'] == 'ready'
    dialog.reject()
