"""Independent regression checks for fractional drags and native text state."""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, FloatObject

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditRequest
from test_clipped_layout import fixture, selected


@pytest.mark.parametrize('dx,dy', [(.1,.1), (1.234,2.345), (72/25.4,72/25.4)])
def test_fractional_drag_and_one_millimetre_step_survive_pdf_number_serialization(dx,dy):
    data = fixture(tc=.375,tw=1.1,tz=80,shared=True)
    model, chosen = selected(data,'SOL')
    changed, report = edit_pdf(data, EditRequest(0,[g.id for g in chosen],dx=dx,dy=dy,revision=model.revision))
    assert report['verified'] and report['operators_preserved']
    assert report['font_resources_unchanged']
    assert all(page['pixels_above_8'] == 0 for page in report['pages'])
    with fitz.open(stream=changed,filetype='pdf') as doc:
        reopened = extract_page(doc,0,changed)
    for original in model.glyphs:
        moved = original.id in {g.id for g in chosen}
        expected = (original.origin[0]+(dx if moved else 0),original.origin[1]+(dy if moved else 0))
        assert any(g.text == original.text and all(abs(a-b)<.001 for a,b in zip(g.origin,expected))
                   for g in reopened.glyphs)


def test_sheared_ctm_and_text_rise_keep_native_cursor_and_target_displacement():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(fixture(tc=.15,tz=80))))
    page = writer.pages[0]
    stream = ContentStream(page['/Contents'][1],writer)
    operations = []
    for args,op in stream.operations:
        if op == b'BT':
            operations.append(([FloatObject(v) for v in (1,0,.13,1,-35,0)],b'cm'))
        operations.append((args,op))
        if op == b'Tf':
            operations.append(([FloatObject(1.75)],b'Ts'))
    stream.operations = operations
    page['/Contents'][1] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    with fitz.open(stream=data,filetype='pdf') as doc:
        model = extract_page(doc,0,data)
    chosen = model.glyphs[:3]
    assert ''.join(g.text for g in chosen) == 'SOL'
    changed, report = edit_pdf(data,EditRequest(0,[g.id for g in chosen],dx=5,dy=4,revision=model.revision))
    assert report['verified'] and all(page['pixels_above_8'] == 0 for page in report['pages'])
    with fitz.open(stream=data,filetype='pdf') as before, fitz.open(stream=changed,filetype='pdf') as after:
        for word in ('LUNA','FIN'):
            assert tuple(after[0].search_for(word)[0]) == pytest.approx(tuple(before[0].search_for(word)[0]),abs=.001)


@pytest.mark.parametrize('word',['13/08/2026','PROVEEDOR DE EJEMPLO'])
def test_move_keeps_contiguous_searchable_text_in_independent_extractor(word):
    data = fixture(word=word,neighbors=False)
    model,chosen = selected(data,word)
    assert word in PdfReader(BytesIO(data)).pages[0].extract_text()
    changed,report = edit_pdf(data,EditRequest(0,[g.id for g in chosen],dx=4,dy=0,revision=model.revision))
    assert report['verified']
    assert word in PdfReader(BytesIO(changed)).pages[0].extract_text()


def test_native_movement_supports_embedded_identity_h_font_without_reencoding():
    with fitz.open() as doc:
        page = doc.new_page(width=450,height=400)
        page.insert_text((40,80),'ABC DEF',fontname='Vera',fontsize=10,
                         fontfile=str(Path(__file__).parents[1]/'assets/fonts/Vera.ttf'))
        old = doc.xref_stream(page.get_contents()[0])
        doc.update_stream(page.get_contents()[0],b'q 20 200 350 150 re W n\n'+old+b'\nQ')
        data = doc.tobytes()
        model = extract_page(doc,0,data)
    chosen = model.glyphs[1:2]
    assert chosen[0].text == 'B'
    changed, report = edit_pdf(data,EditRequest(0,[g.id for g in chosen],dx=.1,dy=12,revision=model.revision))
    assert report['verified'] and report['font_resources_unchanged']
    assert all(page['pixels_above_8'] == 0 for page in report['pages'])
    with fitz.open(stream=changed,filetype='pdf') as doc:
        reopened = extract_page(doc,0,changed)
        assert len(reopened.glyphs) == len(model.glyphs)
        for old,new in zip(model.glyphs,reopened.glyphs):
            offset = (.1,12) if old.id == chosen[0].id else (0,0)
            assert new.text == old.text and new.font == old.font and new.size == old.size
            assert new.origin == pytest.approx((old.origin[0]+offset[0],old.origin[1]+offset[1]),abs=.001)
