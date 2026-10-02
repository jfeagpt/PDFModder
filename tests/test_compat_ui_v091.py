"""Regressions for tagged page tools and neutral ExtGState, through the real GUI.

Only generated PDFs are used. MainWindow talks to its real worker process;
independent pypdf checks the saved text and the logical structure.
"""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, ContentStream, DictionaryObject, FloatObject,
    NameObject, NumberObject,
)
from PySide6.QtCore import Qt

from pdfmodder.app import MainWindow
from tagged_corpus import CONTROL_TEXT, DATE_TEXT, audit_tagged, make_tagged_pdf
from test_ui_line_edit import settled


def _select(window, text):
    glyphs = window.model.glyphs
    start = ''.join(g.text for g in glyphs).index(text)
    window.canvas.set_selection([g.id for g in glyphs[start:start + len(text)]])


def _wait_idle(qtbot, window):
    """Permit an expected error without swallowing a worker which is still busy."""
    qtbot.waitUntil(
        lambda: not window.busy and not window._rich_loading
        and not window._rich_accept_pending and window._rich_pending is None
        and not window._rich_timer.isActive(), timeout=30000,
    )


@pytest.fixture
def compatibility_window(qtbot, tmp_path):
    history = tmp_path / 'history'
    history.mkdir()
    window = MainWindow(config_path=tmp_path / 'fonts.json', history_dir=history)
    window.thumbnail_timer.stop()
    qtbot.addWidget(window, before_close_func=lambda widget: setattr(widget, '_allow_close', True))
    window.show()
    yield window
    window._allow_close = True
    window.close()


def _open(qtbot, window, tmp_path, data):
    source = tmp_path / 'original.pdf'
    source.write_bytes(data)
    window.open_document(source)
    settled(qtbot, window)
    assert window.model is not None
    return source


def _replace_date(qtbot, window, *, legacy):
    _select(window, '10/09/2026')
    window.start_edit()
    qtbot.waitUntil(lambda: window.canvas.editor.isVisible() or bool(window.last_error), timeout=30000)
    assert not window.last_error, window.last_error
    assert window._rich_active is not legacy
    editor = window.canvas.editor
    qtbot.keyClick(editor, Qt.Key_A, modifier=Qt.ControlModifier)
    qtbot.keyClicks(editor, '11/09/2026')
    qtbot.keyClick(editor, Qt.Key_Return, modifier=Qt.ControlModifier)
    settled(qtbot, window)
    if legacy:
        assert window.state['preview'] and window.state['history_index'] == 0
        assert window.commit_button.isEnabled()
        qtbot.mouseClick(window.commit_button, Qt.LeftButton)
        settled(qtbot, window)
    assert window.state['history_index'] == 1 and not window.state['preview']
    assert '11/09/2026' in ''.join(g.text for g in window.model.glyphs)


def test_tagged_gui_edit_extract_delete_undo_save_keeps_tags(qtbot, compatibility_window, tmp_path):
    window = compatibility_window
    original = make_tagged_pdf(named_properties=True, include_objr=True, actual_text=DATE_TEXT)
    before_audit = audit_tagged(original)
    source = _open(qtbot, window, tmp_path, original)
    assert window.state['tagged'] and not window.state['issues']
    capabilities = window.state['page_capabilities']
    assert all(capabilities[key] for key in ('supported', 'delete', 'extract', 'reorder', 'rotate', 'insert_blank'))
    assert not any(capabilities[key] for key in ('duplicate', 'insert_pdf'))
    assert window.delete_pages_action.isEnabled()
    assert window.extract_pages_action.isEnabled()
    assert window.organize_action.isEnabled()
    assert window.add_text_action.isEnabled()
    assert window.add_image_action.isEnabled()

    initial_revision = window.model.revision
    _replace_date(qtbot, window, legacy=True)
    changed_revision = window.model.revision
    assert changed_revision != initial_revision
    full = tmp_path / 'edited-two-pages.pdf'
    window.save_as(full)
    settled(qtbot, window)
    edited_bytes = full.read_bytes()
    edited_audit = audit_tagged(edited_bytes)
    assert edited_audit['reading_order'] == before_audit['reading_order'].replace('10/09/2026', '11/09/2026', 1)
    assert edited_audit['actual_text'][(0, 0)] == 'Fecha: 11/09/2026'
    assert edited_audit['objrs'] == before_audit['objrs']
    with fitz.open(stream=original, filetype='pdf') as before, fitz.open(full) as after:
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before[0].get_links()[0]['uri'] == after[0].get_links()[0]['uri']

    extracted = tmp_path / 'extracted-first-page.pdf'
    window.extract_pages('1', extracted)
    settled(qtbot, window)
    assert window.state['history_index'] == 1 and window.pages.count() == 2
    extracted_audit = audit_tagged(extracted.read_bytes())
    assert extracted_audit['content'][(0, 0)] == 'Fecha: 11/09/2026'
    assert extracted_audit['objrs']
    assert CONTROL_TEXT not in extracted_audit['reading_order']
    assert len(PdfReader(extracted).pages) == 1

    window.delete_pages('2')
    settled(qtbot, window)
    assert window.pages.count() == 1 and window.state['history_index'] == 2
    reduced = tmp_path / 'deleted-second-page.pdf'
    window.save_as(reduced)
    settled(qtbot, window)
    assert audit_tagged(reduced.read_bytes()) == extracted_audit
    with fitz.open(reduced) as after, fitz.open(full) as before:
        assert before[0].get_pixmap().samples == after[0].get_pixmap().samples

    window.undo_action.trigger()
    settled(qtbot, window)
    assert window.pages.count() == 2 and window.model.revision == changed_revision
    restored = tmp_path / 'restored-exact.pdf'
    window.save_as(restored)
    settled(qtbot, window)
    assert restored.read_bytes() == edited_bytes
    window.undo_action.trigger()
    settled(qtbot, window)
    assert window.model.revision == initial_revision
    window.redo_action.trigger()
    settled(qtbot, window)
    assert window.model.revision == changed_revision
    window.open_document(restored)
    settled(qtbot, window)
    assert window.state['tagged'] and window.delete_pages_action.isEnabled()
    assert '11/09/2026' in ''.join(g.text for g in window.model.glyphs)
    assert source.read_bytes() == original


def test_invalid_tag_structure_disables_page_tools_with_specific_reason(qtbot, compatibility_window, tmp_path):
    window = compatibility_window
    original = make_tagged_pdf(defect='broken_parenttree')
    source = _open(qtbot, window, tmp_path, original)
    capabilities = window.state['page_capabilities']
    assert not capabilities['supported'] and capabilities['reason']
    assert not any(capabilities[key] for key in ('delete', 'extract', 'reorder', 'rotate'))
    assert not window.delete_pages_action.isEnabled()
    assert not window.extract_pages_action.isEnabled()
    assert not window.organize_action.isEnabled()
    assert capabilities['reason'] in window.delete_pages_action.toolTip()
    assert window.state['history_index'] == 0 and not window.state['dirty']
    assert source.read_bytes() == original


def _clipped_tagged_pdf():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(
        make_tagged_pdf(named_properties=True, include_objr=True, actual_text=DATE_TEXT)
    )))
    page = writer.pages[0]
    contents = ContentStream(page.get_contents(), writer)
    contents.operations = [
        ([], b'q'),
        ([NumberObject(0), NumberObject(0), NumberObject(420), NumberObject(420)], b're'),
        ([], b'W'), ([], b'n'), *contents.operations, ([], b'Q'),
    ]
    page[NameObject('/Contents')] = writer._add_object(contents)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def test_tagged_rectangular_clip_uses_rich_edit_and_updates_actualtext(qtbot, compatibility_window, tmp_path):
    window = compatibility_window
    original = _clipped_tagged_pdf()
    source = _open(qtbot, window, tmp_path, original)
    assert window.state['tagged'] and window.delete_pages_action.isEnabled()
    _replace_date(qtbot, window, legacy=False)
    destination = tmp_path / 'tagged-clipped-edited.pdf'
    window.save_as(destination)
    settled(qtbot, window)
    audit = audit_tagged(destination.read_bytes())
    original_audit = audit_tagged(original)
    assert audit['actual_text'][(0, 0)] == 'Fecha: 11/09/2026'
    assert audit['reading_order'] == original_audit['reading_order'].replace('10/09/2026', '11/09/2026', 1)
    assert audit['objrs'] == original_audit['objrs']
    with fitz.open(stream=original, filetype='pdf') as before, fitz.open(destination) as after:
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before[0].get_pixmap(clip=(20, 120, 380, 350)).samples == after[0].get_pixmap(clip=(20, 120, 380, 350)).samples
    window.open_document(destination)
    settled(qtbot, window)
    assert window.state['tagged'] and '11/09/2026' in ''.join(g.text for g in window.model.glyphs)
    assert source.read_bytes() == original


def _function():
    return DictionaryObject({
        NameObject('/FunctionType'): NumberObject(2),
        NameObject('/Domain'): ArrayObject([NumberObject(0), NumberObject(1)]),
        NameObject('/C0'): ArrayObject([NumberObject(0)]),
        NameObject('/C1'): ArrayObject([NumberObject(1)]),
        NameObject('/N'): FloatObject(1.5),
    })


def _graphics_state_pdf(kind):
    with fitz.open() as document:
        page = document.new_page(width=360, height=240)
        page.insert_text((40, 60), '10/09/2026', fontsize=12)
        page.insert_text((40, 130), 'VECINO INTACTO', fontsize=12)
        page.draw_line((30, 150), (325, 150), color=(.1, .3, .5), width=1)
        page = document.new_page(width=360, height=240)
        page.insert_text((40, 60), 'PAGINA CONTROL', fontsize=12)
        plain = document.tobytes()
    writer = PdfWriter(clone_from=PdfReader(BytesIO(plain)))
    state = DictionaryObject({
        NameObject('/OP'): BooleanObject(kind == 'overprint'),
        NameObject('/op'): BooleanObject(False),
        NameObject('/OPM'): NumberObject(0),
        NameObject('/TR'): NameObject('/Identity'),
    })
    if kind == 'indirect_identity':
        state[NameObject('/OP')] = writer._add_object(BooleanObject(False))
        state[NameObject('/op')] = writer._add_object(BooleanObject(False))
        state[NameObject('/TR')] = writer._add_object(ArrayObject([NameObject('/Identity')] * 4))
    elif kind in ('transfer', 'default_overrides_transfer'):
        state[NameObject('/TR')] = writer._add_object(_function())
        if kind == 'default_overrides_transfer':
            state[NameObject('/TR2')] = NameObject('/Default')
    page = writer.pages[0]
    page['/Resources'][NameObject('/ExtGState')] = DictionaryObject({NameObject('/GS'): writer._add_object(state)})
    contents = ContentStream(page.get_contents(), writer)
    contents.operations.insert(0, ([NameObject('/GS')], b'gs'))
    page[NameObject('/Contents')] = writer._add_object(contents)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


@pytest.mark.parametrize('kind', ['identity', 'indirect_identity', 'default_overrides_transfer'])
def test_neutral_graphics_state_gui_edits_rich_text_and_preserves_neighbors(qtbot, compatibility_window, tmp_path, kind):
    window = compatibility_window
    original = _graphics_state_pdf(kind)
    source = _open(qtbot, window, tmp_path, original)
    assert not window.state['issues'] and not window.state['tagged']
    _replace_date(qtbot, window, legacy=False)
    destination = tmp_path / 'edited.pdf'
    window.save_as(destination)
    settled(qtbot, window)
    assert '11/09/2026' in PdfReader(destination).pages[0].extract_text()
    assert '10/09/2026' not in PdfReader(destination).pages[0].extract_text()
    with fitz.open(stream=original, filetype='pdf') as before, fitz.open(destination) as after:
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before[0].search_for('VECINO INTACTO') == after[0].search_for('VECINO INTACTO')
        neighbor = fitz.Rect(20, 100, 340, 180)
        assert before[0].get_pixmap(clip=neighbor).samples == after[0].get_pixmap(clip=neighbor).samples
    window.open_document(destination)
    settled(qtbot, window)
    assert '11/09/2026' in ''.join(g.text for g in window.model.glyphs)
    assert source.read_bytes() == original


@pytest.mark.parametrize('kind', ['overprint', 'transfer'])
def test_real_graphics_state_effect_remains_blocked_without_mutation(qtbot, compatibility_window, tmp_path, kind):
    window = compatibility_window
    original = _graphics_state_pdf(kind)
    source = _open(qtbot, window, tmp_path, original)
    revision = window.model.revision
    _select(window, '10/09/2026')
    window.start_edit()
    qtbot.waitUntil(lambda: window.canvas.editor.isVisible() or bool(window.last_error), timeout=30000)
    if window.canvas.editor.isVisible():
        editor = window.canvas.editor
        qtbot.keyClick(editor, Qt.Key_A, modifier=Qt.ControlModifier)
        qtbot.keyClicks(editor, '11/09/2026')
        qtbot.keyClick(editor, Qt.Key_Return, modifier=Qt.ControlModifier)
    _wait_idle(qtbot, window)
    assert 'sobreimpresión o transferencia de color' in window.last_error
    assert window.message.text() == window.last_error
    assert window.state['history_index'] == 0 and not window.state['preview'] and not window.state['dirty']
    assert window.model.revision == revision
    assert '10/09/2026' in ''.join(g.text for g in window.model.glyphs)
    window.cancel()
    _wait_idle(qtbot, window)
    assert not window.canvas.editor.isVisible()
    assert source.read_bytes() == original
