"""Justificación horizontal con fuentes estándar y vecinos de estilos reales."""
from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.engine import _resolve, edit_pdf, extract_page
from pdfmodder.fonts import FontResolver
from pdfmodder.lineflow import expand_line, normalize_rebuilt_lines, plan_line
from pdfmodder.model import EditError, EditRequest, union


def fixture(text='Hoy llega nuestro pedido.', size=12.375):
    with fitz.open() as doc:
        p = doc.new_page(width=520, height=420)
        p.draw_rect((32, 38, 450, 78), fill=(.84, .94, .85), color=(.2, .5, .3))
        p.insert_text((40, 60), text, fontsize=size, fontname='helv')
        p.insert_text((40, 100), 'OTRA LINEA INTACTA', fontsize=10.75)
        p.insert_text((330, 60), 'OTRA COLUMNA', fontsize=9)
        doc.new_page(width=520, height=420).insert_text((40, 60), 'OTRA PAGINA INTACTA')
        return doc.tobytes()


def setup(data, text):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
        joined = ''.join(g.text for g in model.glyphs)
        start = joined.index(text)
        selected = model.glyphs[start:start+len(text)]
        line = expand_line(model, selected)
        resolved = _resolve(doc, 0, line, None, FontResolver())
    return model, selected, resolved


def request(model, selected, text, **kwargs):
    return EditRequest(0, [g.id for g in selected], text=text, revision=model.revision, **kwargs)


def test_word_replacement_changes_only_word_and_spaces_keeps_line_edges():
    model, selected, resolved = setup(fixture(), 'llega')
    line, result, report = plan_line(model, selected, request(model, selected, 'sale'), resolved)
    assert ''.join(g.text for g in result) == 'Hoy sale nuestro pedido.'
    assert union(g.bbox for g in result)[0] == pytest.approx(union(g.bbox for g in line)[0], abs=.001)
    assert union(g.bbox for g in result)[2] == pytest.approx(union(g.bbox for g in line)[2], abs=.001)
    assert report['spaces'] == 3 and report['alignment'] == 'justified'
    assert all(g.size == pytest.approx(12.375) for g in result)
    assert {g.id for g in line} == set(report['line_source_ids'])
    assert 'COLUMNA' not in ''.join(g.text for g in line)
    for word in ('Hoy', 'nuestro', 'pedido.'):
        old_text = ''.join(g.text for g in line)
        new_text = ''.join(g.text for g in result)
        old = line[old_text.index(word):old_text.index(word)+len(word)]
        new = result[new_text.index(word):new_text.index(word)+len(word)]
        dx = new[0].origin[0] - old[0].origin[0]
        for before, after in zip(old, new):
            assert after.id == before.id
            assert after.origin == pytest.approx((before.origin[0]+dx, before.origin[1]))
            assert after.font == before.font and after.size == before.size
            assert after.color == before.color and after.opacity == before.opacity
            assert after.trace_bbox[0] == pytest.approx(before.trace_bbox[0]+dx)


def test_neighbour_styles_and_internal_pair_position_are_preserved():
    model, selected, resolved = setup(fixture(), 'llega')
    line = expand_line(model, selected)
    # This unit fixture models a genuinely measured neighbour span, with its
    # distinct color/opacity and small pair offsets. No new text is synthesized
    # in that span, so those relative positions can be preserved exactly.
    modified = []
    word_start = ''.join(g.text for g in line).index('nuestro')
    for i, g in enumerate(model.glyphs):
        if word_start <= i < word_start+7:
            g = replace(g, color=(.1,.2,.6), opacity=.45,
                        origin=(g.origin[0]+(.06 if i % 2 else 0), g.origin[1]))
        modified.append(g)
    model.glyphs = modified
    line, result, _ = plan_line(model, selected, request(model, selected, 'sale'), resolved)
    old = [g for g in line if g.color == (.1,.2,.6)]
    new = [g for g in result if g.color == (.1,.2,.6)]
    assert len(old) == len(new) == 7
    for a,b in zip(old,new):
        assert b.origin[0]-new[0].origin[0] == pytest.approx(a.origin[0]-old[0].origin[0])
        assert b.opacity == .45


def test_real_mixed_font_neighbours_keep_font_size_baseline_colour_and_opacity():
    with fitz.open() as doc:
        page = doc.new_page(width=520, height=420)
        x = 40
        for text, font, size, color, opacity in (
                ('Hoy llega ', 'helv', 12.375, (0,0,0), 1.),
                ('nuestro ', 'hebo', 13.125, (.6,.1,.2), .65),
                ('pedido.', 'heit', 11.875, (.1,.2,.7), .8)):
            page.insert_text((x,60), text, fontname=font, fontsize=size,
                             color=color, fill_opacity=opacity)
            x += fitz.get_text_length(text, fontname=font, fontsize=size)
        data = doc.tobytes()
    model, selected, resolved = setup(data, 'llega')
    line, result, _ = plan_line(model, selected, request(model, selected, 'sale'), resolved)
    assert {g.font for g in result} == {'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'}
    for old in line:
        if old.id not in {g.id for g in selected}:
            new = next(g for g in result if g.id == old.id)
            assert (new.font, new.size, new.color, new.opacity, new.origin[1]) == (
                old.font, old.size, old.color, old.opacity, old.origin[1])
    assert union(g.bbox for g in result)[2] == pytest.approx(union(g.bbox for g in line)[2], abs=.001)


def test_manual_format_affects_only_replaced_word_and_reports_height_overflow():
    model, selected, resolved = setup(fixture(), 'llega')
    target = FontResolver().resolve_explicit('Helvetica-Bold', 'va')
    line, result, _ = plan_line(model, selected,
                                request(model, selected, 'va', font_name='Helvetica-Bold', size=11.375, color=(.1,.3,.6)),
                                resolved, target)
    replaced = [g for g in result if g.id == -1]
    assert replaced and all(g.font == 'Helvetica-Bold' and g.color == (.1,.3,.6) for g in replaced)
    assert all(g.font == 'Helvetica' and g.color == (0.,0.,0.) for g in result if g.id != -1)
    with pytest.raises(EditError, match='altura'):
        plan_line(model, selected, request(model, selected, 'va', size=40), resolved)


def test_same_font_name_does_not_replace_neighbour_resource_silently():
    model, selected, resolved = setup(fixture(), 'llega')
    different = FontResolver().resolve_explicit('Helvetica-Bold', 'sale')
    conflicting = replace(different, name='Helvetica')
    with pytest.raises(EditError, match='fuente distinta'):
        plan_line(model, selected, request(model, selected, 'sale'), resolved, conflicting)


def test_manual_whole_line_width_is_explicit_and_single_word_never_stretches():
    model, chosen, resolved = setup(fixture('Uno dos tres'), 'Uno dos tres')
    _, result, report = plan_line(model, chosen, request(model, chosen, 'Uno dos tres', width=140), resolved)
    assert union(g.bbox for g in result)[2] == pytest.approx(180, abs=.001)
    assert report['spaces'] == 2
    _, one, report = plan_line(model, chosen, request(model, chosen, 'Una', width=140), resolved)
    natural = resolved[chosen[0].font].width('Una', chosen[0].size)
    assert union(g.bbox for g in one)[2] - one[0].origin[0] == pytest.approx(natural, abs=.001)
    assert report['alignment'] == 'left'


@pytest.mark.parametrize('kwargs, message', [
    ({'text':'palabra demasiado larga que no cabe'}, 'espacio disponible'),
    ({'text':'sale\nahora'}, 'saltos'),
    ({'text':'sale', 'reflow':True}, 'saltos'),
    ({'text':'sale', 'width':200}, 'línea completa'),
    ({'text':'sale', 'height':40}, 'línea completa'),
    ({'text':'sal\te'}, 'controles'),
])
def test_unsupported_or_overflow_does_not_produce_plan(kwargs, message):
    model, selected, resolved = setup(fixture(), 'llega')
    with pytest.raises(EditError, match=message):
        plan_line(model, selected, request(model, selected, **kwargs), resolved)


def test_disconnected_selection_and_mixed_selected_style_blocked():
    model, selected, resolved = setup(fixture(), 'llega')
    with pytest.raises(EditError, match='separados'):
        expand_line(model, [selected[0], selected[-1]])
    model.glyphs = [replace(g, color=(1,0,0)) if g.id == selected[-1].id else g for g in model.glyphs]
    selected = model.selected([g.id for g in selected])
    with pytest.raises(EditError, match='mezcla estilos'):
        plan_line(model, selected, request(model, selected, 'sale'), resolved)


def test_explicit_space_gaps_support_repeated_justification_and_block_columns():
    model, selected, resolved = setup(fixture(), 'llega')
    line, result, _ = plan_line(model, selected, request(model, selected, 'sale'), resolved)
    # Simulate the next extraction IDs; the per-character origins are exactly
    # the prior plan, so the spaces now have nonuniform cursor advances.
    model.glyphs = [replace(g, id=i) for i,g in enumerate(result)]
    selected = model.glyphs[4:8]
    _, second, _ = plan_line(model, selected, request(model, selected, 'parte'), resolved)
    assert ''.join(g.text for g in second) == 'Hoy parte nuestro pedido.'
    assert union(g.bbox for g in second)[2] == pytest.approx(union(g.bbox for g in line)[2], abs=.001)
    model.glyphs = [replace(g, origin=(g.origin[0]+100, g.origin[1]),
                                  bbox=(g.bbox[0]+100,g.bbox[1],g.bbox[2]+100,g.bbox[3]))
                    if i >= 4 else g for i,g in enumerate(model.glyphs)]
    selected = model.glyphs[4:8]
    with pytest.raises(EditError, match='columnas'):
        plan_line(model, selected, request(model, selected, 'sale'), resolved)


def test_split_rawdict_line_requires_explicit_painting_continuity():
    model, selected, _ = setup(fixture(), 'llega')
    original = expand_line(model, selected)
    # Model the documented one-glyph-per-operation reinsertion with a split
    # after the real space. The exact IDs, paint sequence and baseline tie the
    # fragments together; their proximity alone is not the proof.
    model.glyphs = [replace(g, line=20 if i<4 else 21, block=20 if i<4 else 21, seqno=30+i)
                    for i,g in enumerate(original)]
    chosen = model.glyphs[4:9]
    recovered = expand_line(model, chosen)
    assert ''.join(g.text for g in recovered) == 'Hoy llega nuestro pedido.'
    assert expand_line(model, model.glyphs) == recovered
    normalized = normalize_rebuilt_lines(model)
    assert normalized.group(normalized.glyphs[4], 'line') == [g.id for g in original]
    assert {g.block for g in normalized.glyphs} == {20}
    for old,new in zip(model.glyphs,normalized.glyphs):
        assert replace(new,line=old.line,block=old.block) == old


@pytest.mark.parametrize('ambiguity', ['no_space', 'paint_gap', 'ordinary_span', 'id_gap', 'large_gap', 'baseline'])
def test_split_nearby_column_is_not_recovered_without_all_continuity_proofs(ambiguity):
    model, selected, _ = setup(fixture(), 'llega')
    original = expand_line(model, selected)
    glyphs = []
    for i,g in enumerate(original):
        g = replace(g, line=20 if i<4 else 21, block=20 if i<4 else 21, seqno=30+i)
        if ambiguity == 'no_space' and i==3:
            g = replace(g, text='X')
        if ambiguity == 'paint_gap' and i>=4:
            g = replace(g, seqno=g.seqno+2)
        if ambiguity == 'ordinary_span':
            g = replace(g, seqno=30 if i<4 else 31)
        if ambiguity == 'id_gap' and i>=4:
            g = replace(g, id=g.id+1)
        if ambiguity in ('large_gap', 'baseline') and i>=4:
            dx,dy = (60.,0.) if ambiguity=='large_gap' else (0.,.1)
            g = replace(g, origin=(g.origin[0]+dx,g.origin[1]+dy),
                        bbox=tuple(v+(dx if k%2==0 else dy) for k,v in enumerate(g.bbox)),
                        trace_bbox=tuple(v+(dx if k%2==0 else dy) for k,v in enumerate(g.trace_bbox)))
        glyphs.append(g)
    model.glyphs = glyphs
    chosen = model.glyphs[4:9]
    recovered = expand_line(model, chosen)
    assert {g.line for g in recovered} == {21}
    assert ''.join(g.text for g in recovered) == 'llega nuestro pedido.'
    normalized = normalize_rebuilt_lines(model)
    assert {g.line for g in normalized.glyphs} == {20,21}
    assert normalized.glyphs == model.glyphs


def test_line_normalization_preserves_blocks_that_contain_other_lines():
    model, selected, _ = setup(fixture(), 'llega')
    original = expand_line(model,selected)
    model.glyphs = [replace(g,line=20 if i<4 else 21,block=50 if i<4 else 51,seqno=30+i)
                    for i,g in enumerate(original)] + [replace(original[0],id=1000,line=40,block=50,
                                                               origin=(40,90),seqno=1000)]
    normalized = normalize_rebuilt_lines(model)
    assert len(normalized.group(normalized.glyphs[4],'line')) == len(original)
    assert [g.block for g in normalized.glyphs] == [g.block for g in model.glyphs]


def test_reopened_tagged_justified_line_is_one_ui_selection_and_width():
    from tagged_corpus import make_tagged_pdf
    data = make_tagged_pdf(mixed_styles=True,named_properties=True)
    model,chosen,_ = setup(data,'PALABRA')
    original_line = expand_line(model,chosen)
    changed,_ = edit_pdf(data,request(model,chosen,'VOZ',line_reflow=True))
    reopened,chosen,_ = setup(changed,'VOZ')
    ui_line = reopened.selected(reopened.group(chosen[0],'line'))
    assert ''.join(g.text for g in ui_line) == 'Mover VOZ fin.'
    assert len({g.line for g in ui_line}) == 1
    assert union(g.bbox for g in ui_line)[2] == pytest.approx(union(g.bbox for g in original_line)[2],abs=.035)
    assert len(chosen) < len(ui_line), 'La GUI debe reconocer VOZ como selección parcial de línea'


def test_character_insertion_and_deletion_preserve_neighbour_word_content():
    model, selected, resolved = setup(fixture(), 'llega')
    selected = selected[1:4]
    _, result, _ = plan_line(model, selected, request(model, selected, 'le'), resolved)
    assert ''.join(g.text for g in result) == 'Hoy llea nuestro pedido.'
    model, selected, resolved = setup(fixture(), 'llega')
    _, result, _ = plan_line(model, selected, request(model, selected, ''), resolved)
    assert ''.join(g.text for g in result) == 'Hoy  nuestro pedido.'


def test_actual_pdf_roundtrip_two_edits_and_untouched_column_page():
    data = fixture()
    original, chosen, _ = setup(data, 'llega')
    changed, report = edit_pdf(data, request(original, chosen, 'sale', line_reflow=True))
    model, chosen, _ = setup(changed, 'sale')
    again, second_report = edit_pdf(changed, request(model, chosen, 'parte', line_reflow=True))
    assert report['line_reflow'] and second_report['line_reflow']
    assert all(p['pixels_above_8'] == 0 for p in report['pages'] + second_report['pages'])
    assert 'Hoy parte nuestro pedido.' in PdfReader(BytesIO(again)).pages[0].extract_text()
    old_line = expand_line(original, original.selected(original.group(original.glyphs[0], 'line')))
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=again, filetype='pdf') as after:
        current = extract_page(after, 0, again)
        start = next(g for g in current.glyphs if g.text == 'H')
        new_line = current.selected(current.group(start, 'line'))
        assert union(g.bbox for g in old_line)[2] == pytest.approx(union(g.bbox for g in new_line)[2], abs=.035)
        for text in ('OTRA LINEA INTACTA', 'OTRA COLUMNA'):
            assert before[0].search_for(text) == after[0].search_for(text)
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert len(after[0].search_for('parte')) == 1 and after[0].search_for('llega') == []
