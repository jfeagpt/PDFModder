"""Editing table cells and names through both public text-editing surfaces."""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
import pytest
from pypdf import PdfReader
from PySide6.QtCore import Qt

from test_compat_ui_v091 import compatibility_window, _select
from test_ui_line_edit import settled


@pytest.fixture
def table_document(tmp_path):
    source = tmp_path / 'table.pdf'
    with fitz.open() as document:
        page = document.new_page(width=520, height=300)
        page.insert_font(fontname='Fixture', fontfile=str(Path(__file__).resolve().parents[1] / 'assets/fonts/LiberationSans-Regular.ttf'))
        page.draw_rect((25, 25, 480, 200), color=None, fill=(.96, .98, .99))
        page.insert_text((40, 60), 'BARTOLOME PARRA', fontname='Fixture', fontsize=12)
        page.insert_text((40, 120), 'HECTAREAS', fontname='Fixture', fontsize=12)
        page.insert_text((270, 120), '123,45', fontname='Fixture', fontsize=12)
        page.insert_text((40, 180), 'VECINO INTACTO', fontname='Fixture', fontsize=12)
        # Later rectangle paint is a real table border, not an opaque overlay.
        # Its bbox contains the text, but its stroke does not touch any glyph.
        page.draw_rect((25, 25, 480, 85), color=(0, 0, 0), width=.4)
        page.draw_rect((25, 85, 245, 140), color=(0, 0, 0), width=.4)
        page.draw_rect((245, 85, 480, 140), color=(0, 0, 0), width=.4)
        page.draw_rect((25, 140, 480, 200), color=(0, 0, 0), width=.4)
        page = document.new_page(width=520, height=300)
        page.insert_text((40, 60), 'PAGINA CONTROL', fontsize=12)
        document.save(source)
    return source


@pytest.mark.parametrize('route', ['pagina', 'panel'])
@pytest.mark.parametrize('old,new', [
    ('123,45', '129,25'), ('123,45', '1239,250'),
    ('BARTOLOME PARRA', 'BARTOLOME PARRA ZURANO'), ('BARTOLOME PARRA', 'BARTOLOME'),
])
def test_table_text_is_editable_by_page_and_properties(qtbot, compatibility_window, table_document, tmp_path, route, old, new):
    window = compatibility_window
    original = table_document.read_bytes()
    window.open_document(table_document)
    settled(qtbot, window)
    revision = window.model.revision
    _select(window, old)
    original_glyphs = window.model.selected(window.canvas.ids)
    if route == 'pagina':
        window.start_edit()
        qtbot.waitUntil(lambda: window.canvas.editor.isVisible() or bool(window.last_error), timeout=30000)
        assert not window.last_error, window.last_error
        editor = window.canvas.editor
        qtbot.keyClick(editor, Qt.Key_A, modifier=Qt.ControlModifier)
        qtbot.keyClicks(editor, new)
        qtbot.keyClick(editor, Qt.Key_Return, modifier=Qt.ControlModifier)
        settled(qtbot, window)
    else:
        window.content.setPlainText(new)
        assert window.preview_button.isEnabled()
        qtbot.mouseClick(window.preview_button, Qt.LeftButton)
        settled(qtbot, window)
        assert window.state['preview'] and window.state['history_index'] == 0
        assert window.commit_button.isEnabled()
        qtbot.mouseClick(window.commit_button, Qt.LeftButton)
        settled(qtbot, window)
    assert window.state['history_index'] == 1 and not window.state['preview']
    assert window.last_report['verified']
    saved = tmp_path / f'edited-{route}.pdf'
    window.save_as(saved)
    settled(qtbot, window)
    text = PdfReader(saved).pages[0].extract_text()
    assert new in text
    # For a shorter/longer name the old string may legitimately be a substring.
    with fitz.open(stream=original, filetype='pdf') as before, fitz.open(saved) as after:
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        # A changed text SHOW may alter display-list sequence numbers; vector
        # geometry, opacity, strokes and the vector order must remain identical.
        drawings = lambda page: [{key: value for key, value in item.items() if key != 'seqno'} for item in page.get_drawings()]
        assert drawings(before[0]) == drawings(after[0])
        assert before[0].search_for('VECINO INTACTO') == after[0].search_for('VECINO INTACTO')
        area = fitz.Rect(25, 140, 480, 200)
        assert before[0].get_pixmap(clip=area).samples == after[0].get_pixmap(clip=area).samples
        replacement = after[0].search_for(new)
        assert len(replacement) == 1
        assert abs(replacement[0].x0 - original_glyphs[0].bbox[0]) < .04
    accepted_revision = window.model.revision
    window.history('undo')
    settled(qtbot, window)
    assert window.model.revision == revision
    window.history('redo')
    settled(qtbot, window)
    assert window.model.revision == accepted_revision
    window.open_document(saved)
    settled(qtbot, window)
    assert new in ''.join(g.text for g in window.model.glyphs)
    assert table_document.read_bytes() == original
