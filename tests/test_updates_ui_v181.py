from pdfmodder import workspace_ui_v170 as workspace
from test_upgrade_v180 import SynchronousUpdater, UpdateWindow


def test_cooldown_disables_retry_without_query_and_reenables_when_due(qtbot, monkeypatch):
    window, updater = UpdateWindow(), SynchronousUpdater()
    qtbot.addWidget(window)
    updater.value.update(state='rate_limited', retryAt=1100,
                         message='GitHub ha limitado las consultas. Podrás reintentar a las 12:00:00.')
    monkeypatch.setattr(workspace.time, 'time', lambda: 1000)
    dialog = workspace.UpdatesDialog(window, updater)
    qtbot.addWidget(dialog)
    assert not dialog.check_button.isEnabled()
    assert '12:00:00' in dialog.message.text()
    dialog._check()
    dialog._refresh()
    assert updater.calls == [] and not window.closed
    monkeypatch.setattr(workspace.time, 'time', lambda: 1101)
    dialog._refresh()
    assert dialog.check_button.isEnabled() and updater.calls == []
    dialog.reject()
