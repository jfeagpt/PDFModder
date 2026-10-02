from io import BytesIO
import hashlib
import pytest
import pymupdf as fitz
from pypdf import PdfReader
from pdfmodder.model import EditRequest,EditError,union
from pdfmodder.engine import extract_page
from pdfmodder.textlayout import edit_with_layout
from pdfmodder.search_replace import find_matches,replace_matches
from pdfmodder.paragraphs import layout_lines
from pdfmodder.worker import Session


def fixture():
    with fitz.open() as doc:
        for _ in range(2):
            page=doc.new_page(width=420,height=420)
            page.draw_rect((35,55,385,185),fill=(.92,.96,.9),color=(.2,.4,.2))
            page.insert_text((45,80),'SOL',fontsize=12)
            page.insert_text((45,160),'SOL',fontsize=12)
            page.insert_text((45,240),'Vecino inalterado',fontsize=12)
        return doc.tobytes()


def choose(data,page=0):
    with fitz.open(stream=data,filetype='pdf') as doc:model=extract_page(doc,page,data)
    return model,model.glyphs[:3]


def test_auto_width_grows_then_shrinks_without_scaling_or_moving_other_words():
    data=fixture();model,chosen=choose(data)
    output,report=edit_with_layout(data,EditRequest(0,[g.id for g in chosen],text='ESTRELLA',auto_width=True,revision=model.revision))
    assert report['area_width']>union(g.bbox for g in chosen)[2]-45
    assert report['verified']
    assert all(page['max_channel_delta']==0 for page in report['pages'])
    hits=find_matches(output,'ESTRELLA')
    final,shrink=edit_with_layout(output,EditRequest(0,hits[0]['ids'],text='SOL',auto_width=True,revision=hits[0]['revision']))
    assert shrink['area_width']<report['area_width']
    assert len(find_matches(final,'SOL'))==4
    with fitz.open(stream=final,filetype='pdf') as doc:
        assert all(abs(g.size-12)<.001 for g in extract_page(doc,0,final).glyphs)


def test_auto_width_still_blocks_page_edge_and_neighbour_collision():
    data=fixture();model,chosen=choose(data)
    with pytest.raises(EditError,match='borde|supera'):
        edit_with_layout(data,EditRequest(0,[g.id for g in chosen],text='A'*150,auto_width=True))


def test_paragraph_controls_preserve_neighbours_and_detect_height_overflow():
    data=fixture();model,chosen=choose(data)
    request=EditRequest(0,[g.id for g in chosen],text='UNO DOS\nTRES\n\nCUATRO',width=120,height=75,
                        reflow=True,line_spacing=16,paragraph_spacing=7)
    output,report=edit_with_layout(data,request)
    with fitz.open(stream=output,filetype='pdf') as doc:
        m=extract_page(doc,0,output)
        ys=sorted(set(round(g.origin[1],3) for g in m.glyphs if g.origin[1]<155))
    assert ys==[80.,96.,135.]
    assert report['paragraph_layout']['paragraph_spacing']==7
    request.height=30
    with pytest.raises(EditError,match='altura'):edit_with_layout(data,request)


def test_wrapping_and_manual_breaks_do_not_move_outside_area():
    assert layout_lines('AA BB CC\nDD',len,5,True,10,4)==[('AA BB',0.),('CC',10.),('DD',20.)]
    with pytest.raises(EditError):layout_lines('ABCDEFGHI',len,5,True,10)


def test_review_specific_occurrences_across_pages_preserves_unchecked():
    data=fixture();matches=find_matches(data,'SOL')
    assert len(matches)==4
    output,report=replace_matches(data,[matches[0],matches[3]],'LUNA')
    assert report['match_count']==2 and report['verified']
    remaining=find_matches(output,'SOL');new=find_matches(output,'LUNA')
    assert [(m['page'],round(m['origins'][0][1])) for m in remaining]==[(0,160),(1,80)]
    assert len(new)==2
    text=''.join(p.extract_text() for p in PdfReader(BytesIO(output)).pages)
    assert text.count('LUNA')==2 and text.count('SOL')==2
    with pytest.raises(EditError,match='cambió'):replace_matches(output,matches[:1],'SOL')


def test_search_pages_selection_and_revision():
    data=fixture();matches=find_matches(data,'SOL',pages='2')
    assert len(matches)==2 and all(m['page']==1 for m in matches)
    one=matches[1]
    selected={'page':one['page'],'ids':one['ids'],'revision':one['revision']}
    assert len(find_matches(data,'SOL',selection=selected))==1
    assert find_matches(data,'sol')==[]
    assert len(find_matches(data,'sol',case_sensitive=False))==4
    selected['revision']='invalid'
    with pytest.raises(EditError,match='revisión'):find_matches(data,'SOL',selection=selected)


def test_search_batch_preview_is_one_history_unit_and_cancel_is_exact(tmp_path):
    source=tmp_path/'original.pdf';source.write_bytes(fixture())
    session=Session(source,config_path=tmp_path/'fonts.json',history_dir=tmp_path)
    try:
        original=session.history.current
        matches=session.find_replacements(query='SOL')['matches']
        session.preview_replacements([m['id'] for m in matches[:2]],'LUNA')
        assert session.history.current==original and session.state()['preview']
        session.cancel();assert session.history.current==original
        session.preview_replacements([m['id'] for m in matches[:2]],'LUNA');session.commit()
        assert session.history.index==1
        changed=session.history.current
        session.navigate_history();assert session.history.current==original
        session.navigate_history(True);assert session.history.current==changed
    finally:session.close()


def test_selection_scope_does_not_invent_word_boundaries_or_join_gaps():
    with fitz.open() as doc:
        doc.new_page().insert_text((40,70),'banana',fontsize=12)
        data=doc.tobytes()
    model,_=choose(data)
    scope={'page':0,'ids':[1,2,3],'revision':model.revision}
    assert find_matches(data,'ana',selection=scope,whole_word=True)==[]
    assert len(find_matches(data,'ana',selection=scope,whole_word=False))==1
    scope['ids']=[0,2,4]
    assert find_matches(data,'bnn',selection=scope)==[]


def test_auto_width_expands_justified_line_only_when_its_spaces_cannot_absorb_change():
    with fitz.open() as doc:
        page=doc.new_page(width=420,height=200)
        page.insert_text((40,70),'SOL FINAL',fontsize=12)
        page.insert_text((40,120),'Vecino fijo',fontsize=12)
        data=doc.tobytes()
    chosen=find_matches(data,'SOL')[0]
    output,report=edit_with_layout(data,EditRequest(0,chosen['ids'],text='ESTRELLA',auto_width=True,line_reflow=True))
    assert report['line_reflow'] and report['auto_width'] and report['verified']
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert after[0].search_for('FINAL')[0].x1>before[0].search_for('FINAL')[0].x1
        assert after[0].search_for('Vecino fijo')==before[0].search_for('Vecino fijo')
        assert not after[0].search_for('SOL') and after[0].search_for('ESTRELLA')
