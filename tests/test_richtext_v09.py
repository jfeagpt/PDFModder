"""Acceptance of native rich editing, not mocks of the planning algorithm."""
from dataclasses import replace
from io import BytesIO
import hashlib

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.engine import extract_page
from pdfmodder.model import EditError, EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf,selection_payload,move_rich_pdf


def document():
    with fitz.open() as doc:
        p=doc.new_page(width=400,height=300)
        p.draw_rect((20,20,380,120),fill=(.93,.96,.98),color=None)
        p.insert_text((35,50),'Hola mundo',fontsize=12)
        p.insert_text((35,150),'VECINO INTACTO',fontsize=10)
        p.draw_line((20,130),(380,130),color=(.2,.4,.8))
        p2=doc.new_page(width=400,height=300)
        p2.insert_text((35,50),'SEGUNDA PAGINA',fontsize=12)
        return doc.tobytes()


def selection(data,text):
    with fitz.open(stream=data,filetype='pdf') as d:
        model=extract_page(d,0,data)
    full=''.join(g.text for g in model.glyphs)
    start=full.index(text)
    return [g.id for g in model.glyphs[start:start+len(text)]]


def request(data,text='Hola mundo'):
    ids=selection(data,text)
    payload=selection_payload(data,0,ids)
    return RichTextRequest(0,ids,payload['runs'],rect=(35,payload['rect'][1],360,115),revision=payload['revision'])


def test_mixed_style_spacing_underline_and_roundtrip():
    data=document(); req=request(data);style=req.runs[0]
    req.runs=[dict(style,text='Hola '),dict(style,text='mundo nuevo',font_name='Helvetica-Bold',font_resource=None,font_xref=None,size=14,color=(.8,0,0),underline=True,char_spacing=.5)]
    output,report=edit_rich_pdf(data,req)
    assert report['verified'] and report['pages'][0]['pixels_above_8']==0
    with fitz.open(stream=output,filetype='pdf') as d:
        spans=d[0].get_texttrace()
        assert any(s['font']=='Helvetica-Bold' and s['size']==14 for s in spans)
        assert 'Hola mundo nuevo' in d[0].get_text()
        assert 'VECINO INTACTO' in d[0].get_text()
        assert d.page_count==2
        assert sum(x['type']=='f' for x in d[0].get_drawings())==1+len('mundo nuevo')
    assert 'mundo nuevo' in PdfReader(BytesIO(output)).pages[0].extract_text()
    ids=selection(output,'Hola mundo nuevo');payload=selection_payload(output,0,ids)
    assert any(r['underline'] for r in payload['runs'])
    second,_=edit_rich_pdf(output,RichTextRequest(0,ids,[dict(r,underline=False) for r in payload['runs']],rect=payload['rect']))
    with fitz.open(stream=second,filetype='pdf') as d:
        assert sum(x['type']=='f' for x in d[0].get_drawings())==1
        assert d[0].get_text().count('mundo nuevo')==1


def test_paragraph_soft_break_tabs_indent_and_reopen():
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='A\tB\u2028C\nD')]
    req.paragraphs=[dict(line_spacing=16,space_after=8,left_indent=5,first_indent=7,tab_stops=[40])]
    out,report=edit_rich_pdf(data,req)
    glyphs=report['glyphs'];bychar={g['text']:g for g in glyphs}
    assert bychar['A']['origin'][0]==pytest.approx(47)
    assert bychar['B']['origin'][0]==pytest.approx(87)
    assert bychar['C']['origin'][0]==pytest.approx(40)
    assert bychar['C']['origin'][1]-bychar['A']['origin'][1]==pytest.approx(16)
    assert bychar['D']['origin'][1]-bychar['C']['origin'][1]==pytest.approx(24)
    payload=selection_payload(out,0,selection(out,'ABCD'))
    assert payload['text']=='A\tB\u2028C\nD'
    assert payload['paragraphs']==req.paragraphs


def test_overflow_cancel_and_stale_revision_leave_input_unchanged():
    data=document();digest=hashlib.sha256(data).hexdigest();req=request(data)
    req.runs=[dict(req.runs[0],text='Una palabra y muchas palabras que no caben')]
    req.width=20;req.height=10
    with pytest.raises(EditError,match='altura|anchura'):edit_rich_pdf(data,req)
    assert hashlib.sha256(data).hexdigest()==digest
    with pytest.raises(EditError,match='cambió'):edit_rich_pdf(data,replace(req,revision='stale'))


def test_copy_source_format_addition_and_range_isolation():
    data=document();req=request(data);style=req.runs[0]
    out,report=edit_rich_pdf(data,RichTextRequest(0,[],[dict(style,text='Texto añadido')],rect=(35,180,350,220)))
    assert report['added_text'] and report['source_regions']==[]
    with fitz.open(stream=out,filetype='pdf') as d:
        assert 'Hola mundo' in d[0].get_text()
        assert 'Texto añadido' in d[0].get_text()
    middle=selection(data,'mundo')
    payload=selection_payload(data,0,middle)
    out,report=edit_rich_pdf(data,RichTextRequest(0,middle,[dict(payload['runs'][0],text='MUNDO',color=(0,0,.8))],rect=payload['rect'],auto_width=True))
    with fitz.open(stream=out,filetype='pdf') as d:
        assert 'Hola MUNDO' in d[0].get_text()


def test_wrap_keeps_letter_size_and_logical_text():
    data=document();req=request(data)
    content='uno dos tres cuatro'
    req.runs=[dict(req.runs[0],text=content)];req.width=65;req.auto_height=True
    out,report=edit_rich_pdf(data,req)
    assert report['line_count']>1
    assert {g['size'] for g in report['glyphs']}=={12}
    ids=selection(out,content)
    assert selection_payload(out,0,ids)['text']==content


def test_missing_character_never_silently_substitutes():
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='Hola 漢',font_name='Helvetica',font_resource=None,font_xref=None)]
    with pytest.raises(EditError):edit_rich_pdf(data,req)


def test_partial_underlined_edit_preserves_remaining_style_without_old_metadata():
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='Hola mundo',underline=True)]
    data,_=edit_rich_pdf(data,req)
    ids=selection(data,'mundo');payload=selection_payload(data,0,ids)
    output,_=edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='nuevo')],
                                             rect=payload['rect'],auto_width=True))
    assert selection_payload(output,0,selection(output,'H'))['text']=='H'
    remaining=selection_payload(output,0,selection(output,'Hola '))
    assert remaining['text']=='Hola '
    assert all(run['underline'] for run in remaining['runs'])
    # A later edit of the untouched range must not resurrect the deleted word.
    second,_=edit_rich_pdf(output,RichTextRequest(0,remaining['ids'],
                           [dict(r,underline=False) for r in remaining['runs']],rect=remaining['rect']))
    with fitz.open(stream=second,filetype='pdf') as doc:
        assert 'Hola nuevo' in doc[0].get_text()
        kind,value=doc.xref_get_key(doc[0].xref,'PDFModderRichText')
        assert 'mundo' not in value
        assert sum(item['type']=='f' for item in doc[0].get_drawings())==1+len('nuevo')


def test_replace_removes_only_affected_group_signatures():
    from pdfmodder.objects import group_pdf,object_info
    data=document()
    data,_=group_pdf(data,0,[dict(kind='text',ids=selection(data,'Hola mundo'))],name='Editado')
    data,_=group_pdf(data,0,[dict(kind='text',ids=selection(data,'VECINO INTACTO'))],name='Conservado')
    req=request(data);req.runs=[dict(req.runs[0],text='Adios nuevo')]
    output,report=edit_rich_pdf(data,req)
    assert report['removed_groups']==['Editado']
    groups=object_info(output,0)['groups']
    assert len(groups)==1 and groups[0]['name']=='Conservado' and groups[0]['valid']
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert 'Hola' not in doc.xref_get_key(doc[0].xref,'PDFModderGroups')[1]


def test_move_underlined_range_keeps_spacing_font_groups_and_reediting():
    from pdfmodder.objects import group_pdf,object_info
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='Hola mundo',underline=True,char_spacing=.7)]
    data,_=edit_rich_pdf(data,req)
    ids=selection(data,'mundo')
    data,_=group_pdf(data,0,[dict(kind='text',ids=ids)],name='Palabra')
    before=selection_payload(data,0,ids)
    moved,report=move_rich_pdf(data,EditRequest(0,ids,dx=12,dy=25))
    assert report['underlines_moved']==len('mundo')
    after=selection_payload(moved,0,selection(moved,'mundo'))
    for original,current in zip(before['carets'],after['carets']):
        assert current['origin'][0]==pytest.approx(original['origin'][0]+12,abs=.001)
        assert current['origin'][1]==pytest.approx(original['origin'][1]+25,abs=.001)
    assert all(r['underline'] and r['char_spacing']==.7 for r in after['runs'])
    assert object_info(moved,0)['groups'][0]['valid']
    second,_=edit_rich_pdf(moved,RichTextRequest(0,after['ids'],[dict(r,underline=False) for r in after['runs']],rect=after['rect']))
    with fitz.open(stream=second,filetype='pdf') as doc:
        assert sum(item['type']=='f' for item in doc[0].get_drawings())==1+len('Hola ')


def test_underline_reedit_after_unrelated_native_move_shifted_operators():
    from pdfmodder.clipped_layout import move_clipped_text
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='Hola mundo',underline=True)]
    data,_=edit_rich_pdf(data,req)
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    # Simulates an unrelated operation in an older caller, leaving stale indexes.
    data,_=move_clipped_text(data,EditRequest(0,selection(data,'VECINO INTACTO'),dx=3,dy=0),model)
    payload=selection_payload(data,0,selection(data,'Hola mundo'))
    out,_=edit_rich_pdf(data,RichTextRequest(0,payload['ids'],[dict(r,underline=False) for r in payload['runs']],rect=payload['rect']))
    with fitz.open(stream=out,filetype='pdf') as doc:
        assert sum(item['type']=='f' for item in doc[0].get_drawings())==1


def test_leading_tabs_soft_breaks_and_paragraphs_survive_reopen():
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='\tA\u2028B\r\nC\t')]
    req.paragraphs=[dict(tab_stops=[44],left_indent=5,right_indent=8,first_indent=3)]
    req.auto_width=True;req.auto_height=True
    output,report=edit_rich_pdf(data,req)
    payload=selection_payload(output,0,selection(output,'ABC'))
    assert payload['text']=='\tA\u2028B\nC\t'
    assert payload['carets'][0]['index']==1
    assert report['line_count']==3
    assert report['glyphs'][0]['origin'][0]==pytest.approx(35+5+3+44)
    assert report['area_width']>=60


def test_translucent_underlining_is_rejected_before_changing_pdf():
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=300)
        page.insert_text((35,50),'Hola mundo',fontsize=12,fill_opacity=.5)
        data=doc.tobytes()
    req=request(data);req.runs=[dict(req.runs[0],text='Hola mundo',underline=True)]
    with pytest.raises(EditError,match='semitransparente'):
        edit_rich_pdf(data,req)


def test_word_wrap_never_makes_an_extra_line_for_overflowing_separator():
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='DOS UNO')]
    req.width=27;req.height=32
    output,report=edit_rich_pdf(data,req)
    assert report['line_count']==2
    assert {g['size'] for g in report['glyphs']}=={12}
    assert ''.join(g['text'] for g in report['glyphs'] if g['line']==0)=='DOS '
    assert ''.join(g['text'] for g in report['glyphs'] if g['line']==1)=='UNO'
    assert selection_payload(output,0,selection(output,'DOS UNO'))['text']=='DOS UNO'
    assert report['pages'][0]['pixels_above_8']==0
    with fitz.open(stream=output,filetype='pdf') as doc:
        lines=[line.strip() for line in doc[0].get_text().splitlines()]
        assert lines[:2]==['DOS','UNO']
        assert 'VECINO INTACTO' in lines


@pytest.mark.parametrize('runs',[[],[dict(text='')]])
def test_delete_all_text_has_no_phantom_line_height_or_remaining_underline(runs):
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='Hola mundo',underline=True)]
    data,_=edit_rich_pdf(data,req)
    ids=selection(data,'Hola mundo')
    payload=selection_payload(data,0,ids)
    output,report=edit_rich_pdf(data,RichTextRequest(0,ids,runs,rect=payload['rect'],height=.1))
    assert report['line_count']==0 and report['glyphs']==[]
    assert report['replacement']==''
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert 'Hola' not in doc[0].get_text() and 'mundo' not in doc[0].get_text()
        assert 'VECINO INTACTO' in doc[0].get_text()
        assert sum(item['type']=='f' for item in doc[0].get_drawings())==1


def test_report_automatic_area_flags_and_measured_growth():
    data=document();req=request(data)
    req.runs=[dict(req.runs[0],text='Hola mundo\nSegunda linea')]
    req.width=2;req.height=.1;req.auto_width=True;req.auto_height=True
    _,report=edit_rich_pdf(data,req)
    assert report['auto_width'] is True and report['auto_height'] is True
    assert report['area_width']>2 and report['area_height']>.1
    assert report['line_count']==2
