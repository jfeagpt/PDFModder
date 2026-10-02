"""Recortes y texto invisible sintéticos; ningún PDF privado en este corpus."""
from io import BytesIO
from hashlib import sha256

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
import pytest

from pdfmodder.clipping import CLIP_ISSUE, operator_glyph_map
from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest


def fixture(*,overlay=False,shared=False,font='cour'):
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.draw_rect((30,55,250,100),color=(.2,.3,.4),fill=(.8,.93,.9))
        page.insert_text((40,80),'04/05/2026',fontname=font,fontsize=10)
        page.insert_text((40,140),'04/05/2026',fontname=font,fontsize=10)
        page.insert_text((180,80),'VECINO',fontname=font,fontsize=10)
        page.insert_text((40,200),'OCR INTACTO',fontname=font,fontsize=10,render_mode=3)
        if overlay:
            page.insert_text((40,80),'04/05/2026',fontname=font,fontsize=10,render_mode=3)
        doc.new_page(width=400,height=400).insert_text((40,80),'PAGINA INTACTA')
        data=doc.tobytes()
    writer=PdfWriter(clone_from=PdfReader(BytesIO(data)))
    page=writer.pages[0]
    stream=ContentStream(page['/Contents'][1],writer)
    operations=[]
    for args,op in stream.operations:
        if op==b'TJ':
            text=args[0][0].get_original_bytes()
            adjusted=ArrayObject()
            for i,code in enumerate(text):
                adjusted.extend([ByteStringObject(bytes([code])),FloatObject([31,-6.01074,15][i%3])])
            args=[adjusted]
        operations.append((args,op))
    n=lambda *values:[FloatObject(v) for v in values]
    prefix=[([],b'q'),(n(.1,0,0,.1,0,0),b'cm'),([],b'q'),
            (n(350,3100,2150,300),b're'),([],b'W'),([],b'n'),([],b'q'),(n(10,0,0,10,0,0),b'cm')]
    stream.operations=prefix+operations+[([],b'Q'),([],b'Q'),([],b'Q')]
    page['/Contents'][1]=writer._add_object(stream)
    if shared:
        writer.pages[1][NameObject('/Contents')]=page['/Contents']
        writer.pages[1][NameObject('/Resources')]=page['/Resources']
    buffer=BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def selection(data):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    chosen=[g for g in model.glyphs if g.mode==0 and abs(g.origin[1]-80)<.02 and g.origin[0]<150]
    assert ''.join(g.text for g in chosen)=='04/05/2026'
    return model,chosen


def request(model,chosen,**kwargs):
    return EditRequest(0,[g.id for g in chosen],revision=model.revision,**kwargs)


@pytest.mark.parametrize('shared',[False,True])
def test_native_resource_date_change_keeps_clips_cursor_ocr_and_other_page(shared):
    data=fixture(shared=shared)
    model,chosen=selection(data)
    assert CLIP_ISSUE in model.issues
    before=PdfReader(BytesIO(data))
    old_ops=ContentStream(before.pages[0].get_contents(),before).operations
    output,report=edit_pdf(data,request(model,chosen,text='05/05/2026',line_reflow=True))
    assert report['verified'] and report['changed_characters']==1
    assert len(report['source_regions'])==len(report['destination_regions'])==1
    assert all(page['max_channel_delta']==0 for page in report['pages'])
    after=PdfReader(BytesIO(output))
    new_ops=ContentStream(after.pages[0].get_contents(),after).operations
    assert len(old_ops)==len(new_ops)
    assert [op for _,op in old_ops]==[op for _,op in new_ops]
    for (a,op),(b,_) in zip(old_ops,new_ops):
        if op!=b'TJ':
            assert a==b
        else:
            assert [v for v in a[0] if isinstance(v,(int,float))]==[v for v in b[0] if isinstance(v,(int,float))]
    with fitz.open(stream=data,filetype='pdf') as old,fitz.open(stream=output,filetype='pdf') as new:
        assert old[1].get_pixmap().samples==new[1].get_pixmap().samples
        assert old[1].get_texttrace()==new[1].get_texttrace()
        assert len(new[0].search_for('04/05/2026'))==1
        assert len(new[0].search_for('05/05/2026'))==1
        old_hidden=[s for s in old[0].get_texttrace() if s['type']==3]
        new_hidden=[s for s in new[0].get_texttrace() if s['type']==3]
        assert old_hidden==new_hidden
        again=extract_page(new,0,output)
        target=[g for g in again.glyphs if g.mode==0 and abs(g.origin[1]-80)<.02 and g.origin[0]<150]
    restored,_=edit_pdf(output,request(again,target,text='04/05/2026'))
    with fitz.open(stream=data,filetype='pdf') as old,fitz.open(stream=restored,filetype='pdf') as new:
        assert old[0].get_pixmap().samples==new[0].get_pixmap().samples


def test_invisible_overlaid_ocr_is_removed_without_leaving_stale_hidden_text():
    data=fixture(overlay=True)
    fingerprint=sha256(data).hexdigest()
    model,chosen=selection(data)
    output,report=edit_pdf(data,request(model,chosen,text='05/05/2026'))
    assert report['ocr_cleanup']['removed_characters']==10
    assert report['ocr_cleanup']['appearance_unchanged']
    with fitz.open(stream=output,filetype='pdf') as doc:
        hidden=''.join(chr(c[0]) for span in doc[0].get_texttrace() if span['type']==3 for c in span['chars'])
        assert hidden=='OCR INTACTO'
        assert len(doc[0].search_for('04/05/2026'))==1
        assert len(doc[0].search_for('05/05/2026'))==1
    assert sha256(data).hexdigest()==fingerprint


@pytest.mark.parametrize('kwargs,message',[
    ({'text':'05/05/20260'},'espacio disponible'),
    ({'text':'05/05/2026','dx':2},'mover|Mover'),
    ({'text':'05/05/2026','reflow':True},'espacio disponible'),
    ({'text':'05/05/2026','size':0},'tamaño'),
    ({'text':'05/05/2026','width':150},'área'),
    ({'text':'漢3/05/2026'},'código único'),
])
def test_unsupported_clipped_changes_have_specific_blocks(kwargs,message):
    data=fixture()
    model,chosen=selection(data)
    with pytest.raises(EditError,match=message):
        edit_pdf(data,request(model,chosen,**kwargs))


@pytest.mark.parametrize('width',[None,150])
def test_changed_advance_preserves_later_cursor_when_character_exists_in_same_font(width):
    data=fixture(font='helv')
    model,chosen=selection(data)
    _,report=edit_pdf(data,request(model,chosen,text='0//05/2026',width=width))
    assert report['verified'] and report['operators_preserved']
    assert abs(report['cursor_residual'])<1e-10


def test_font_resource_probe_identifies_visible_and_invisible_glyphs_without_exporting_probe():
    data=fixture()
    model,_=selection(data)
    _,_,_,mapping=operator_glyph_map(data,0,model)
    assert all(g.font_xref is not None and g.font_resource.startswith('/') for g in model.glyphs)
    assert all(mapping[g.id]['font_xref']==g.font_xref for g in model.glyphs)
    assert any(g.mode==3 for g in model.glyphs)
    with fitz.open(stream=data,filetype='pdf') as doc:
        assert any(span['type']==3 for span in doc[0].get_texttrace())


def test_clipped_actualtext_cannot_be_left_stale_by_native_operator_route():
    from tagged_corpus import DATE_TEXT,make_tagged_pdf
    from test_engine import select
    writer=PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(actual_text=DATE_TEXT))))
    page=writer.pages[0]
    stream=ContentStream(page['/Contents'][0],writer)
    stream.operations=[([],b'q'),([NumberObject(0),NumberObject(0),NumberObject(420),NumberObject(420)],b're'),
                       ([],b'W'),([],b'n'),*stream.operations,([],b'Q')]
    page['/Contents'][0]=writer._add_object(stream)
    buffer=BytesIO()
    writer.write(buffer)
    data=buffer.getvalue()
    model,chosen=select(data,'10/09/2026',x=100,y=100)
    with pytest.raises(EditError,match='recortes y etiquetas'):
        edit_pdf(data,request(model,chosen,text='11/09/2026'))


def test_fill_and_clip_text_mode_four_is_blocked_even_if_trace_reports_visible_type_zero():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(fixture())))
    page=writer.pages[0]
    stream=ContentStream(page['/Contents'][1],writer)
    operations=[]
    for args,op in stream.operations:
        if op==b'TJ':
            operations.append(([NumberObject(4)],b'Tr'))
        operations.append((args,op))
    stream.operations=operations
    page['/Contents'][1]=writer._add_object(stream)
    buffer=BytesIO()
    writer.write(buffer)
    data=buffer.getvalue()
    fingerprint=sha256(data).hexdigest()
    model,chosen=selection(data)
    assert all(g.mode==0 for g in chosen), 'MuPDF presenta Tr4 como tipo de glifo visible 0'
    _,_,_,mapping=operator_glyph_map(data,0,model)
    assert all(mapping[g.id]['render_mode']==4 for g in chosen)
    with pytest.raises(EditError,match='recorte de texto Tr=4'):
        edit_pdf(data,request(model,chosen,text='05/05/2026'))
    assert sha256(data).hexdigest()==fingerprint


def test_direct_font_resources_do_not_borrow_codes_from_another_resource_with_none_xref():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(fixture())))
    page=writer.pages[0]
    stream=ContentStream(page.get_contents(),writer)
    operations=[]
    for args,op in stream.operations:
        if op==b'TJ':
            args=[ArrayObject([ByteStringObject(value.get_original_bytes().replace(b'5',b'4'))
                               if isinstance(value,TextStringObject) else
                               ByteStringObject(bytes(value).replace(b'5',b'4'))
                               if isinstance(value,bytes) else value for value in args[0]])]
        operations.append((args,op))
    fonts=page['/Resources']['/Font']
    fonts[NameObject('/cour')]=DictionaryObject(dict(fonts['/cour']))
    fonts['/cour'][NameObject('/Encoding')]=DictionaryObject({
        NameObject('/BaseEncoding'):NameObject('/WinAnsiEncoding'),
        NameObject('/Differences'):ArrayObject([NumberObject(53),NameObject('/.notdef')])})
    fonts[NameObject('/helv')]=DictionaryObject(dict(writer.pages[1]['/Resources']['/Font']['/helv']))
    operations.extend([([],b'BT'),([NameObject('/helv'),NumberObject(10)],b'Tf'),
                       ([NumberObject(1),NumberObject(0),NumberObject(0),NumberObject(1),NumberObject(250),NumberObject(200)],b'Tm'),
                       ([TextStringObject('5')],b'Tj'),([],b'ET')])
    stream.operations=operations
    page[NameObject('/Contents')]=writer._add_object(stream)
    buffer=BytesIO()
    writer.write(buffer)
    data=buffer.getvalue()
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    chosen=[g for g in model.glyphs if g.mode==0 and abs(g.origin[1]-80)<.02 and g.origin[0]<150]
    assert ''.join(g.text for g in chosen)=='04/04/2026'
    _,_,shows,_=operator_glyph_map(data,0,model)
    assert all(show['xref'] is None for show in shows)
    assert not any(g.text=='5' for show in shows if show['resource']=='/cour' for g in show['glyphs'])
    assert any(g.text=='5' for show in shows if show['resource']=='/helv' for g in show['glyphs'])
    fingerprint=sha256(data).hexdigest()
    with pytest.raises(EditError,match='mismo recurso de fuente'):
        edit_pdf(data,request(model,chosen,text='05/04/2026'))
    assert sha256(data).hexdigest()==fingerprint
