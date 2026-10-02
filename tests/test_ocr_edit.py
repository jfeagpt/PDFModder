"""Corpus OCR generado: capas reales invisibles, sin servicio de reconocimiento."""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, FloatObject, NameObject, NumberObject

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest
from pdfmodder.ocr import remove_hidden
from pdfmodder.validation import pixel_diff, trace_chars


def corpus(*, visible=True, cid=False, shared=False, clip=False, rotated=False, tracking=False):
    with fitz.open() as doc:
        page=doc.new_page(width=450,height=400)
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False)
        pix.clear_with(220)
        page.insert_image((25,40,400,110),pixmap=pix)
        page.draw_rect((20,35,410,115),color=(.2,.4,.8))
        if visible:
            page.insert_text((40,80),'SOL',fontname='cour',fontsize=10)
        name='cour'
        if cid:
            name='ocr'
            page.insert_font(fontname=name,fontbuffer=fitz.Font('cjk').buffer)
        page.insert_text((40,80),'SOL',fontname=name,fontsize=10,render_mode=3)
        page.insert_text((40,200),'ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789',fontname=name,fontsize=10,render_mode=3)
        page.insert_text((40,300),'VECINO VISIBLE',fontname='cour',fontsize=10)
        page.insert_text((220,80),'OTRO OCR',fontname=name,fontsize=10,render_mode=3)
        doc.new_page(width=450,height=400).insert_text((30,70),'SEGUNDA PAGINA')
        if rotated:
            page=doc[0]
            page.set_cropbox(fitz.Rect(10,10,440,390))
            page.set_rotation(90)
        data=doc.tobytes()
    writer=PdfWriter(clone_from=PdfReader(BytesIO(data)))
    page=writer.pages[0]
    original=ContentStream(page.get_contents(),writer)
    ops=[]
    mode=0
    for args,op in original.operations:
        if op==b'Tr':mode=int(args[0])
        if op==b'TJ' and mode==3 and tracking:
            ops.extend([([FloatObject(.2)],b'Tc'),([FloatObject(.7)],b'Tw'),([NumberObject(85)],b'Tz')])
        ops.append((args,op))
        if op==b'TJ' and mode==3 and tracking:
            ops.extend([([NumberObject(0)],b'Tc'),([NumberObject(0)],b'Tw'),([NumberObject(100)],b'Tz')])
    if clip:
        ops=[([],b'q'),([NumberObject(0),NumberObject(0),NumberObject(450),NumberObject(400)],b're'),
             ([],b'W'),([],b'n')]+ops+[([],b'Q')]
    original.operations=ops
    page[NameObject('/Contents')]=writer._add_object(original)
    if shared:
        writer.pages[1][NameObject('/Contents')]=page.raw_get('/Contents')
        writer.pages[1][NameObject('/Resources')]=page['/Resources']
    output=BytesIO(); writer.write(output)
    return output.getvalue()


def choose(data, hidden=False, word='SOL'):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    candidates=[g for g in model.glyphs if g.mode==(3 if hidden else 0)]
    text=''.join(g.text for g in candidates)
    offset=text.index(word)
    return model,candidates[offset:offset+len(word)]


def request(model,chosen,**kwargs):
    return EditRequest(0,[g.id for g in chosen],revision=model.revision,**kwargs)


@pytest.mark.parametrize('cid',[False,True])
@pytest.mark.parametrize('shared,clip,rotated',[(False,False,False),(True,True,False),(False,True,True)])
def test_visible_edit_removes_only_covered_duplicate_ocr(cid,shared,clip,rotated):
    data=corpus(cid=cid,shared=shared,clip=clip,rotated=rotated)
    original_sha=sha256(data).hexdigest()
    model,chosen=choose(data)
    # Equal-width codes from the same visible face are available in VECINO.
    output,report=edit_pdf(data,request(model,chosen,text='SOL' if cid else 'SOI'))
    assert report['ocr_cleanup']['removed_characters']==3
    assert report['ocr_cleanup']['appearance_unchanged']
    assert all(p['pixels_above_8']==0 for p in report['ocr_cleanup']['pages'])
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        hidden=''.join(chr(c[0]) for s in after[0].get_texttrace() if s['type']==3 for c in s['chars'])
        assert 'SOL' not in hidden
        assert 'OTRO OCR' in hidden
        assert trace_chars(before[1])==trace_chars(after[1])
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
    assert sha256(data).hexdigest()==original_sha


@pytest.mark.parametrize('cid',[False,True])
@pytest.mark.parametrize('tracking',[False,True])
def test_searchable_longer_shorter_and_reopen_preserve_entire_appearance(cid,tracking):
    data=corpus(visible=False,cid=cid,tracking=tracking)
    model,chosen=choose(data,True)
    output,report=edit_pdf(data,request(model,chosen,text='ESTRELLA',ocr_mode='searchable',width=100))
    assert report['ocr_mode']=='searchable' and report['appearance_unchanged']
    assert 'no es una edición visual' in report['warning']
    assert all(p['max_channel_delta']==0 for p in report['pages'])
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert len(after[0].search_for('ESTRELLA'))==1
        assert len(after[0].search_for('SOL'))==0
        assert before[0].get_pixmap().samples==after[0].get_pixmap().samples
    current,changed=choose(output,True,'ESTRELLA')
    restored,second=edit_pdf(output,request(current,changed,text='SOL',ocr_mode='searchable',width=100))
    assert second['appearance_unchanged']
    with fitz.open(stream=restored,filetype='pdf') as doc:
        assert len(doc[0].search_for('SOL'))==1
        assert len(doc[0].search_for('ESTRELLA'))==0


@pytest.mark.parametrize('cid',[False,True])
def test_remove_partial_hidden_word_keeps_same_show_cursor_and_neighbors(cid):
    data=corpus(visible=False,cid=cid,tracking=True)
    model,chosen=choose(data,True)
    output,report=remove_hidden(data,0,model,[chosen[1].id])
    assert report['removed_characters']==1
    expected=[g for g in model.glyphs if g.id!=chosen[1].id]
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert trace_chars(doc[0])==[(g.text,g.origin,g.font,g.size) for g in expected]
    assert all(p['max_channel_delta']==0 for p in report['pages'])


def test_searchable_requires_explicit_mode_and_hidden_selection():
    data=corpus()
    model,hidden=choose(data,True)
    with pytest.raises(EditError,match='activa explícitamente'):
        edit_pdf(data,request(model,hidden,text='SOL'))
    model,visible=choose(data)
    with pytest.raises(EditError,match='exclusivamente texto OCR'):
        edit_pdf(data,request(model,visible,text='SOL',ocr_mode='searchable'))


@pytest.mark.parametrize('kwargs,message',[
    ({'text':'NIÑO'},'códigos únicos'),
    ({'text':'ESTRELLA'},'supera el área'),
    ({'text':'SOL','dx':1},'formato o posición'),
    ({'text':'SOL','size':10},'formato o posición'),
    ({'text':'SOL','line_reflow':True},'formato o posición'),
    ({'text':'SOL','line_spacing':12},'formato o posición'),
    ({'text':'SOL','paragraph_spacing':2},'formato o posición'),
    ({'text':'SOL','anchor':'right'},'origen izquierdo'),
    ({'text':'SOL\nLUNA'},'una sola línea'),
])
def test_searchable_specific_limits_are_atomic(kwargs,message):
    data=corpus(visible=False)
    fingerprint=sha256(data).hexdigest()
    model,chosen=choose(data,True)
    with pytest.raises(EditError,match=message):
        edit_pdf(data,request(model,chosen,ocr_mode='searchable',**kwargs))
    assert sha256(data).hexdigest()==fingerprint


def test_searchable_can_delete_without_affecting_raster_or_other_ocr():
    data=corpus(visible=False,cid=True)
    model,chosen=choose(data,True)
    output,report=edit_pdf(data,request(model,chosen,text='',ocr_mode='searchable'))
    assert report['destination_regions']==[]
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert len(doc[0].search_for('SOL'))==0
        assert len(doc[0].search_for('OTRO OCR'))==1
    assert all(p['max_channel_delta']==0 for p in report['pages'])


def test_searchable_auto_width_retains_size_without_stretching_letters():
    data=corpus(visible=False)
    model,chosen=choose(data,True)
    output,report=edit_pdf(data,request(model,chosen,text='ESTRELLA',ocr_mode='searchable',auto_width=True))
    with fitz.open(stream=output,filetype='pdf') as doc:
        spans=[s for s in doc[0].get_texttrace() if ''.join(chr(c[0]) for c in s['chars'])=='ESTRELLA']
        assert len(spans)==1 and spans[0]['size']==chosen[0].size
    assert report['appearance_unchanged']


def test_visible_default_justification_does_not_include_duplicated_hidden_line():
    data=corpus()
    model,chosen=choose(data)
    output,report=edit_pdf(data,request(model,chosen,text='SOI',line_reflow=True))
    assert report['ocr_cleanup']['removed_characters']==3
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert len(doc[0].search_for('SOI'))==1


@pytest.mark.parametrize('cid',[False,True])
def test_searchable_rotated_cropbox_keeps_destination_and_all_pixels(cid):
    data=corpus(visible=False,cid=cid,rotated=True,clip=True)
    model,chosen=choose(data,True)
    output,report=edit_pdf(data,request(model,chosen,text='ESTRELLA',ocr_mode='searchable',auto_width=True))
    with fitz.open(stream=output,filetype='pdf') as doc:
        current=extract_page(doc,0,output)
        target=next(g for g in current.glyphs if g.mode==3)
        assert target.origin==chosen[0].origin
        assert doc[0].rotation==90 and tuple(doc[0].cropbox)==(10,10,440,390)
    assert all(p['max_channel_delta']==0 for p in report['pages'])


def test_partial_visible_letter_removes_whole_duplicate_but_retains_real_neighbors():
    data=corpus()
    model,chosen=choose(data)
    output,report=edit_pdf(data,request(model,[chosen[1]],text='I'))
    assert report['ocr_cleanup']['removed_characters']==3
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert len(doc[0].search_for('SIL'))==1
        assert len(doc[0].search_for('SOL'))==0


def test_hidden_text_covering_unselected_region_is_not_removed():
    data=corpus()
    with fitz.open(stream=data,filetype='pdf') as doc:
        # A giant unrelated OCR word overlaps the visible SOL only at its edge.
        doc[0].insert_text((50,80),'OTROCONTENIDO',fontname='cour',fontsize=10,render_mode=3)
        data=doc.tobytes()
    model,chosen=choose(data)
    with pytest.raises(EditError,match='abarca otra región'):
        edit_pdf(data,request(model,chosen,text='SOI'))


def test_clipped_paragraph_properties_do_not_silently_disappear():
    data=corpus(clip=True)
    model,chosen=choose(data)
    output,report=edit_pdf(data,request(model,chosen,text='SOI\nSOL',width=30,height=32,reflow=True,line_spacing=15))
    assert report['verified'] and report['line_spacing']==15
    assert report['ocr_cleanup']['removed_characters']==3
    with fitz.open(stream=output,filetype='pdf') as doc:
        result=extract_page(doc,0,output)
        visible=[g for g in result.glyphs if g.mode==0 and g.origin[0]<80 and g.origin[1]<120]
        assert sorted({round(g.origin[1],3) for g in visible})==[80.,95.]
        assert not any(g.mode==3 and g.origin[0]<80 and g.origin[1]<120 for g in result.glyphs)


def test_majority_overlap_is_insufficient_to_delete_a_different_ocr_region():
    data=corpus()
    with fitz.open(stream=data,filetype='pdf') as doc:
        # The whole box center is inside SOL and 60% of its width overlaps it;
        # first/last character centers extend outside and must block deletion.
        doc[0].insert_text((34,80),'RADIO',fontname='cour',fontsize=10,render_mode=3)
        data=doc.tobytes()
    model,chosen=choose(data)
    with pytest.raises(EditError,match='abarca otra región'):
        edit_pdf(data,request(model,chosen,text='SOI'))
