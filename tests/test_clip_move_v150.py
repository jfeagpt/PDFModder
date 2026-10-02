from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.engine import atomic_save, edit_pdf, extract_page
from pdfmodder.history import History
from pdfmodder.model import EditError, EditRequest


def fixture(*, parent_clip=False, extra_paint=False, tracking=False, shared=False):
    with fitz.open() as doc:
        page = doc.new_page(width=350, height=320)
        page.insert_font(fontname='cour')
        prefix = b'q 0 220 350 100 re W n\n' if parent_clip else b''
        suffix = b'Q\n' if parent_clip else b''
        paint = b'20 250 2 2 re f\n' if extra_paint else b''
        state = b'0.25 Tc 0.5 Tw 90 Tz\n' if tracking else b''
        raw = prefix + b'q 20 236 300 24 re W n\n'+paint+b'BT /cour 10 Tf\n'+state+b'1 0 0 1 30 243 Tm [(ANTES ) 15 (2026) -10 ( DESPUES)] TJ ET Q\n'+suffix
        raw += b'BT /cour 10 Tf 1 0 0 1 30 70 Tm (VECINO FIJO) Tj ET\n'
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        doc.update_stream(stream, raw)
        page.set_contents(stream)
        source_xref = page.xref
        second = doc.new_page(width=350, height=320)
        if shared:
            doc.xref_set_key(second.xref, 'Resources', doc.xref_get_key(source_xref, 'Resources')[1])
            second.set_contents(stream)
        else:
            second.insert_text((30, 60), 'OTRA PAGINA')
        return doc.tobytes()


def selection(data, text):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
    joined = ''.join(g.text for g in model.glyphs)
    index = joined.index(text)
    return model, model.glyphs[index:index+len(text)]


@pytest.mark.parametrize('text,tracking,shared', [('2026',False,False), ('ANTES 2026 DESPUES',False,True), ('2026',True,True)])
def test_move_fragment_or_line_carries_clip_preserving_neighbors_and_other_page(text, tracking, shared):
    data = fixture(tracking=tracking, shared=shared)
    model, chosen = selection(data, text)
    output, report = edit_pdf(data, EditRequest(0, [g.id for g in chosen], dx=12, dy=85))
    assert report['clip_translated'] and not report['clip_enlarged']
    assert all(page['pixels_above_8'] == 0 for page in report['pages'])
    ids = {g.id for g in chosen}
    with fitz.open(stream=data, filetype='pdf') as old, fitz.open(stream=output, filetype='pdf') as new:
        actual = extract_page(new, 0).glyphs
        assert len(actual) == len(model.glyphs)
        for glyph in model.glyphs:
            dx, dy = (12, 85) if glyph.id in ids else (0, 0)
            matches = [g for g in actual if g.text == glyph.text and
                       abs(g.origin[0]-glyph.origin[0]-dx)<.035 and abs(g.origin[1]-glyph.origin[1]-dy)<.035]
            assert len(matches) == 1
            if glyph.id in ids:
                assert not any(g.text == glyph.text and abs(g.origin[0]-glyph.origin[0])<.035
                               and abs(g.origin[1]-glyph.origin[1])<.035 for g in actual)
        assert old[1].get_pixmap().samples == new[1].get_pixmap().samples
        assert '2026' in new[0].get_text()
    assert '2026' in PdfReader(BytesIO(output)).pages[0].extract_text()


def test_move_clip_save_reopen_and_exact_undo(tmp_path):
    data = fixture()
    _, chosen = selection(data, '2026')
    output, report = edit_pdf(data, EditRequest(0, [g.id for g in chosen], dx=12, dy=85))
    history = History(data, directory=tmp_path)
    try:
        history.push(output, report)
        assert history.undo() == data
        assert history.redo() == output
        path = tmp_path/'moved.pdf'
        atomic_save(history.current, path)
        _, moved = selection(path.read_bytes(), '2026')
        assert moved[0].origin == pytest.approx((chosen[0].origin[0]+12, chosen[0].origin[1]+85), abs=.035)
    finally:
        history.close()


@pytest.mark.parametrize('kwargs,reason', [({'parent_clip':True}, 'recorte superior'),
                                          ({'extra_paint':True}, 'ámbito más complejo')])
def test_shared_ancestor_clip_or_other_paint_remains_blocked(kwargs, reason):
    data = fixture(**kwargs)
    _, chosen = selection(data, '2026')
    with pytest.raises(EditError, match=reason):
        edit_pdf(data, EditRequest(0, [g.id for g in chosen], dx=12, dy=85))


def test_move_fragment_into_neighbor_is_still_blocked():
    data = fixture()
    model, chosen = selection(data, '2026')
    neighbor = next(g for g in model.glyphs if g.text == 'V')
    with pytest.raises(EditError, match='vecino'):
        edit_pdf(data, EditRequest(0, [g.id for g in chosen],
                                 dx=neighbor.origin[0]-chosen[0].origin[0],
                                 dy=neighbor.origin[1]-chosen[0].origin[1]))
