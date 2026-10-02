"""Glifos visibles e invisibles pueden compartir ID de línea de rawdict."""
from dataclasses import replace
from pathlib import Path

import pymupdf as fitz
import pytest

from pdfmodder.elements import zone_elements
from pdfmodder.engine import edit_pdf,extract_page
from pdfmodder.lineflow import expand_line,normalize_rebuilt_lines,_continuous_rebuilt_line
from pdfmodder.model import EditRequest,union
from pdfmodder.model import EditError
from pdfmodder.search_replace import find_matches,replace_matches
from pdfmodder.textlayout import edit_with_layout


EXAMPLES=Path(__file__).resolve().parents[1]/'examples'


def overlapping_date():
    data=(EXAMPLES/'herramientas-v08.pdf').read_bytes()
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    visible=next(g for g in model.glyphs if g.text=='F' and g.mode==0 and 70<g.origin[1]<140)
    hidden=next(g for g in model.glyphs if g.text=='F' and g.mode==3)
    assert visible.line==hidden.line
    return data,model,visible,hidden


@pytest.mark.parametrize('mode',[0,3])
@pytest.mark.parametrize('level',['character','word','line','block'])
def test_model_group_never_adds_opposite_paint_mode(level,mode):
    _,model,visible,hidden=overlapping_date()
    chosen=visible if mode==0 else hidden
    ids=model.group(chosen,level)
    assert ids and all(g.mode==mode for g in model.selected(ids))
    if level in ('line','block'):
        assert model.text(ids)=='Fecha: 10/09/2026'


@pytest.mark.parametrize('mode',[0,3])
def test_expand_line_keeps_mode_with_a_duplicate_in_same_raw_line(mode):
    _,model,visible,hidden=overlapping_date()
    chosen=visible if mode==0 else hidden
    line=expand_line(model,[chosen])
    assert all(g.mode==mode for g in line)
    assert ''.join(g.text for g in line)=='Fecha: 10/09/2026'


def test_click_and_zone_inventory_distinguish_the_two_overlaid_elements():
    _,model,visible,hidden=overlapping_date()
    point=((visible.bbox[0]+visible.bbox[2])/2,(visible.bbox[1]+visible.bbox[3])/2)
    assert model.hit(point).mode==0
    zone=union(g.bbox for g in model.glyphs if g.line==visible.line)
    elements=[e for e in zone_elements(model,[],zone,'line') if e['kind']=='text']
    assert len(elements)==2
    assert {e['ocr'] for e in elements}=={False,True}
    assert all(e['text']=='Fecha: 10/09/2026' for e in elements)
    assert not set(elements[0]['ids']) & set(elements[1]['ids'])


def test_search_scope_and_matches_keep_visible_and_ocr_separate():
    data,model,visible,hidden=overlapping_date()
    matches=find_matches(data,'10/09/2026',include_ocr=True)
    assert len(matches)==2 and {match['ocr'] for match in matches}=={False,True}
    selection={'page':0,'ids':model.group(visible,'line'),'revision':model.revision}
    scoped=find_matches(data,'10/09/2026',include_ocr=True,selection=selection)
    assert len(scoped)==1 and not scoped[0]['ocr']


def test_editing_selected_visible_line_cleans_ocr_and_keeps_searchable_result():
    data,model,visible,_=overlapping_date()
    ids=model.group(visible,'line')
    output,report=edit_pdf(data,EditRequest(0,ids,text='Fecha: 11/09/2026',revision=model.revision,line_reflow=True))
    assert report['verified'] and report['ocr_cleanup']['removed_characters']==len('Fecha: 10/09/2026')
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert len(doc[0].search_for('11/09/2026'))==1
        assert len(doc[0].search_for('10/09/2026'))==0


def adjacent_different_modes():
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=300)
        for index,text in enumerate('ABC DEF'):
            page.insert_text((30+6*index,80),text,fontname='cour',fontsize=10,render_mode=0 if index<4 else 3)
        data=doc.tobytes()
        model=extract_page(doc,0,data)
    # Model the extraction split between two otherwise adjacent raw lines.
    model.glyphs=[replace(g,line=0 if index<4 else 1,block=0 if index<4 else 1)
                  for index,g in enumerate(model.glyphs)]
    return model


def test_paint_continuity_does_not_join_visible_and_hidden_fragments():
    model=adjacent_different_modes()
    assert not _continuous_rebuilt_line(model.glyphs[:4],model.glyphs[4:])
    normalized=normalize_rebuilt_lines(model)
    assert {g.line for g in normalized.glyphs if g.mode==0}=={0}
    assert {g.line for g in normalized.glyphs if g.mode==3}=={1}


def zero_opacity_duplicate():
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=300)
        page.insert_text((30,80),'SOL',fontname='cour',fontsize=10)
        page.insert_text((30,80),'SOL',fontname='cour',fontsize=10,fill_opacity=0)
        data=doc.tobytes()
        model=extract_page(doc,0,data)
    visible=next(g for g in model.glyphs if g.opacity>0)
    hidden=next(g for g in model.glyphs if g.opacity==0)
    assert visible.line==hidden.line and visible.mode==hidden.mode==0
    return data,model,visible,hidden


@pytest.mark.parametrize('level',['word','line','block'])
def test_same_render_mode_with_zero_opacity_never_contaminates_visible_selection(level):
    _,model,visible,hidden=zero_opacity_duplicate()
    for glyph in (visible,hidden):
        selected=model.selected(model.group(glyph,level))
        assert ''.join(g.text for g in selected)=='SOL'
        assert all((g.opacity>0)==(glyph.opacity>0) for g in selected)
        expanded=expand_line(model,[glyph])
        assert ''.join(g.text for g in expanded)=='SOL'
        assert all((g.opacity>0)==(glyph.opacity>0) for g in expanded)


def test_zero_opacity_inventory_and_search_explain_unsupported_invisibility():
    data,model,visible,hidden=zero_opacity_duplicate()
    elements=zone_elements(model,[])
    assert len(elements)==2 and all(e['text']=='SOL' for e in elements)
    assert sum('opacidad 0' in e['label'] for e in elements)==1
    matches=find_matches(data,'SOL')
    assert len(matches)==1 and matches[0]['visible']
    all_matches=find_matches(data,'SOL',include_ocr=True)
    assert len(all_matches)==2
    unsupported=next(m for m in all_matches if not m['visible'])
    assert 'Tr=3' in unsupported['unsupported_reason'] and not unsupported['ocr']
    with pytest.raises(EditError,match='opacidad 0'):
        replace_matches(data,[unsupported],'LUNA')


@pytest.mark.parametrize('automatic',[False,True])
def test_zero_opacity_edit_has_specific_block_without_extending_ocr(automatic):
    data,model,visible,hidden=zero_opacity_duplicate()
    with pytest.raises(EditError,match='opacidad 0'):
        edit_with_layout(data,EditRequest(0,model.group(hidden,'word'),text='LUNA',revision=model.revision,auto_width=automatic))


def test_continuity_does_not_merge_same_mode_with_different_visibility():
    model=adjacent_different_modes()
    model.glyphs=[replace(g,mode=0,opacity=1. if i<4 else 0.) for i,g in enumerate(model.glyphs)]
    assert not _continuous_rebuilt_line(model.glyphs[:4],model.glyphs[4:])
    normalized=normalize_rebuilt_lines(model)
    assert {g.line for g in normalized.glyphs if g.opacity>0}=={0}
    assert {g.line for g in normalized.glyphs if g.opacity==0}=={1}
