"""Propiedades en ventana real, revisión, historial y atajos de entrada."""
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from pdfmodder.document_ui_v170 import DocumentPropertiesDialog, DocumentSecurityDialog
from test_ui import editor, settled


def test_document_properties_dialog_review_commit_undo(qtbot,editor):
    source=Path(__file__).resolve().parents[1]/'examples/digital.pdf'
    editor.open_document(source)
    settled(qtbot,editor)
    original_text=''.join(g.text for g in editor.model.glyphs)
    timer=QTimer(editor)
    timer.setInterval(20)
    def edit_properties():
        dialog=QApplication.activeModalWidget()
        if isinstance(dialog,DocumentPropertiesDialog):
            assert dialog.path.isReadOnly() and dialog.pages.isReadOnly()
            dialog.fields['title'].setText('Título revisado con ñ')
            dialog.fields['author'].setText('Corpus sintético')
            dialog.fields['creationDate'].setText('2026-10-01 12:30:00+02:00')
            dialog.accept()
            timer.stop()
    timer.timeout.connect(edit_properties)
    timer.start()
    try:
        editor.choose_document_properties_v170()
        qtbot.waitUntil(lambda:editor.state.get('preview',False),timeout=30000)
        settled(qtbot,editor)
        assert editor.state['history_index']==0
        assert ''.join(g.text for g in editor.model.glyphs)==original_text
        editor.commit()
        settled(qtbot,editor)
        assert editor.state['history_index']==1
        editor.history('undo')
        settled(qtbot,editor)
        assert editor.state['history_index']==0
        actions=editor.toolbar.actions()
        offset=actions.index(editor.redo_action)+1
        assert actions[offset:offset+4]==[editor.cut_action_v170,editor.copy_action_v170,
                                        editor.paste_action_v170,editor.delete_action_v170]
    finally:
        timer.stop()


def test_security_dialog_password_confirmation_and_read_only_signed_properties(qtbot):
    security=DocumentSecurityDialog()
    qtbot.addWidget(security)
    security.password.setText('prueba')
    security.confirm_password.setText('diferente')
    security.accept()
    assert not security.result()
    security.confirm_password.setText('prueba')
    security.accept()
    assert security.result()
    properties=DocumentPropertiesDialog({'editable':False,'edit_reason':'Documento firmado',
                                          'metadata':{'title':'Título'}})
    qtbot.addWidget(properties)
    assert properties.fields['title'].isReadOnly() and not properties.editable
