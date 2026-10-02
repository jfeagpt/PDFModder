"""Exporter baseline jitter is kept, not mistaken for rows or normalized away."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.lineflow import expand_line, plan_line
from pdfmodder.model import EditError
from test_lineflow import request, setup


def jitter_fixture():
    text = 'Hoy llega nuestro pedido.'
    with fitz.open() as doc:
        page = doc.new_page(width=520, height=420)
        page.insert_text((40, 60), text, fontname='helv', fontsize=9)
        # One text painting operation, as in office exporters. All coordinates
        # use real font advances; only measured vertical positions differ.
        operators = ['BT /helv 9 Tf']
        x = 40.
        for i, char in enumerate(text):
            y = 60 + (.24 if i == 8 else .12 if 10 <= i < 17 else 0)
            operators.append(f'1 0 0 1 {x:.6f} {420-y:.6f} Tm <{ord(char):02x}> Tj')
            x += fitz.get_text_length(char, fontname='helv', fontsize=9)
        operators.append('ET')
        doc.update_stream(page.get_contents()[0], '\n'.join(operators).encode('ascii'))
        page.insert_text((330, 60), 'COLUMNA INTACTA', fontsize=9)
        page.insert_text((40, 80), 'FILA INTACTA', fontsize=9)
        return doc.tobytes()


def test_small_baseline_offsets_preserved_for_surviving_and_neighbour_characters():
    model, chosen, resolved = setup(jitter_fixture(), 'llega')
    line, planned, _ = plan_line(model, chosen, request(model, chosen, 'lega'), resolved)
    assert max(g.origin[1] for g in line)-min(g.origin[1] for g in line) == pytest.approx(.24, abs=.001)
    for old in line:
        if old.id not in {g.id for g in chosen}:
            new = next(g for g in planned if g.id == old.id)
            assert new.origin[1] == old.origin[1]
            assert new.bbox[1::2] == old.bbox[1::2]
    # The surviving 'a' in a length-changing replacement retains its own y.
    replacement = [g for g in planned if g.id == -1]
    assert replacement[-1].text == 'a'
    assert replacement[-1].origin[1] == chosen[-1].origin[1]
    assert 'COLUMNA' not in ''.join(g.text for g in line)


def test_same_length_replacement_keeps_each_baseline():
    model, chosen, resolved = setup(jitter_fixture(), 'llega')
    _, planned, _ = plan_line(model, chosen, request(model, chosen, 'silla'), resolved)
    replaced = [g for g in planned if g.id == -1]
    assert [g.origin[1] for g in replaced] == [g.origin[1] for g in chosen]


@pytest.mark.parametrize('ambiguity', ['large_offset', 'different_span', 'different_operation', 'nonoverlapping_envelopes'])
def test_baseline_exception_requires_narrow_geometry_and_one_original_span(ambiguity):
    model, chosen, _ = setup(jitter_fixture(), 'llega')
    g = chosen[-1]
    if ambiguity == 'large_offset':
        changed = replace(g, origin=(g.origin[0], g.origin[1]+1))
    elif ambiguity == 'different_span':
        changed = replace(g, span=g.span+1)
    elif ambiguity == 'different_operation':
        changed = replace(g, seqno=g.seqno+1)
    else:
        changed = replace(g, trace_bbox=(g.trace_bbox[0],g.trace_bbox[1]+3,g.trace_bbox[2],g.trace_bbox[3]+3))
    model.glyphs = [changed if old.id == g.id else old for old in model.glyphs]
    with pytest.raises(EditError, match='líneas base'):
        expand_line(model, model.selected([old.id for old in chosen]))


def test_baseline_jitter_roundtrip_keeps_other_rows_columns_and_neighbour_offsets():
    data = jitter_fixture()
    model, chosen, _ = setup(data, 'llega')
    original_line = expand_line(model, chosen)
    changed, report = edit_pdf(data, request(model, chosen, 'sale', line_reflow=True))
    assert all(p['pixels_above_8'] == 0 for p in report['pages'])
    assert 'Hoy sale nuestro pedido.' in PdfReader(BytesIO(changed)).pages[0].extract_text()
    with fitz.open(stream=data,filetype='pdf') as before, fitz.open(stream=changed,filetype='pdf') as after:
        for text in ('COLUMNA INTACTA', 'FILA INTACTA'):
            assert before[0].search_for(text) == after[0].search_for(text)
        reopened = extract_page(after, 0, changed)
        current = ''.join(g.text for g in reopened.glyphs)
        for text in ('nuestro', 'pedido.'):
            old_text = ''.join(g.text for g in original_line)
            old_start = old_text.index(text)
            new_start = current.index(text)
            for old, new in zip(original_line[old_start:old_start+len(text)], reopened.glyphs[new_start:new_start+len(text)]):
                assert new.origin[1] == pytest.approx(old.origin[1], abs=.001)
    # Reopening turns the preserved span into one painting operation per glyph.
    # A second edit must keep accepting that exact line without flattening it.
    reopened, chosen, _ = setup(changed, 'sale')
    again, second_report = edit_pdf(changed, request(reopened, chosen, 'va', line_reflow=True))
    assert all(p['pixels_above_8'] == 0 for p in second_report['pages'])
    assert 'Hoy va nuestro pedido.' in PdfReader(BytesIO(again)).pages[0].extract_text()
