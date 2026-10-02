"""New text is outside original graphics scopes; original operators stay intact."""
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.composition import AddTextRequest, insert_text_pdf
from pdfmodder.model import EditError


def clipped(rotation=0, unbalanced=False):
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=360)
        page.draw_rect((25, 40, 110, 100), color=(.2, .5, .7), fill=(.8, .9, .95))
        page.insert_text((25, 70), 'ORIGINAL', fontsize=11)
        # A persistent clip and CTM outside q/Q, valid but hazardous to append.
        original = b'1 0 0 1 12 0 cm\n0 0 150 360 re W n\n' + page.read_contents()
        if unbalanced:
            original += b'q\n'
        stream = page.get_contents()[0]
        doc.update_stream(stream, original)
        page.set_contents(stream)
        page.set_rotation(rotation)
        other = doc.new_page(width=300, height=360)
        other.insert_text((25, 70), 'PAGINA INTACTA')
        return doc.tobytes(), original


@pytest.mark.parametrize('rotation', [0, 90, 270])
def test_append_outside_original_clip_preserves_original_streams(rotation):
    data, original = clipped(rotation)
    request = AddTextRequest(0, 180, 220, 105, 30, 'Nuevo 2026', size=10)
    output, report = insert_text_pdf(data, request)
    assert report['verified'] and report['existing_clip_isolated']
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        assert after[0].rotation == rotation
        assert any(after.xref_stream(xref) == original for xref in after[0].get_contents())
        assert 'Nuevo 2026' in after[0].get_text()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        old_region = fitz.Rect(0, 0, 160, 180) * after[0].rotation_matrix
        assert before[0].get_pixmap(clip=old_region).samples == after[0].get_pixmap(clip=old_region).samples
        bounds = after[0].search_for('Nuevo 2026')[0]
        assert bounds.x0 == pytest.approx(180, abs=.035)
    assert 'Nuevo 2026' in PdfReader(BytesIO(output)).pages[0].extract_text()


def test_unbalanced_original_scopes_remain_blocked():
    data, _ = clipped(unbalanced=True)
    with pytest.raises(EditError, match='abierto|analizar los operadores'):
        insert_text_pdf(data, AddTextRequest(0, 180, 220, 105, 30, 'Nuevo', size=10))
