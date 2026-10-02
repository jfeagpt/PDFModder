"""Actual rendering and content order, including disjoint vector envelopes."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader

from pdfmodder.engine import extract_page, _safe_selection
from pdfmodder.model import EditError, EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload, move_rich_pdf


def document(text='123', kind='fill', dx=0):
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=180)
        page.insert_text((40+dx,60),text,fontsize=12)
        page.insert_text((40,130),'VECINO',fontsize=10)
        if kind=='stroke':
            # The path envelope covers the text; its actual border does not.
            page.draw_rect((20,20,110,90),color=(.1,.4,.7),width=1)
        elif kind=='fill':
            # A small opaque stripe genuinely covers part of the text.
            page.draw_rect((49,45,51,70),color=None,fill=(.1,.4,.7))
        else:
            pix=fitz.Pixmap(fitz.csRGB,(0,0,2,2));pix.clear_with(160)
            page.insert_image((49,45,51,70),stream=pix.tobytes('png'))
        page=doc.new_page(width=300,height=180)
        page.insert_text((40,60),'CONTROL')
        return doc.tobytes(no_new_id=True)


def selection(data, text):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    full=''.join(g.text for g in model.glyphs);start=full.index(text)
    return model,[g.id for g in model.glyphs[start:start+len(text)]]


def compare(actual, expected):
    with fitz.open(stream=actual,filetype='pdf') as a, fitz.open(stream=expected,filetype='pdf') as b:
        for page in range(2):
            pa=a[page].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            pb=b[page].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            assert max(abs(x-y) for x,y in zip(pa.samples,pb.samples))<=8
        drawings=lambda p:[{k:v for k,v in d.items() if k!='seqno'} for d in p.get_drawings()]
        assert drawings(a[0])==drawings(b[0])


@pytest.mark.parametrize('kind',['stroke','fill','image'])
def test_native_edit_preserves_later_artwork_and_matches_reference(kind):
    data=document(kind=kind);model,ids=selection(data,'123')
    payload=selection_payload(data,0,ids)
    result,report=edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='143')],rect=payload['rect']))
    assert report['verified']
    compare(result,document('143',kind))
    assert '143' in PdfReader(BytesIO(result)).pages[0].extract_text()
    assert '123' not in PdfReader(BytesIO(result)).pages[0].extract_text()


def test_overlay_redaction_route_still_rejects_covering_object():
    data=document();model,ids=selection(data,'123')
    with fitz.open(stream=data,filetype='pdf') as doc:
        with pytest.raises(EditError,match='orden visual'):
            _safe_selection(doc[0],model,model.selected(ids))


def test_native_move_stays_below_original_image():
    data=document(kind='image');model,ids=selection(data,'123')
    result,report=move_rich_pdf(data,EditRequest(0,ids,dx=2))
    assert report['verified']
    compare(result,document(kind='image',dx=2))


def test_consolidation_cannot_cross_intervening_covering_object():
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=180)
        page.insert_text((40,60),'12',fontsize=12)
        page.draw_rect((49,45,51,70),color=None,fill=(.1,.4,.7))
        page.insert_text((54,60),'34',fontsize=12)
        data=doc.tobytes()
    model,ids=selection(data,'1234');payload=selection_payload(data,0,ids)
    with pytest.raises(EditError,match='intercalado'):
        edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='1434')],rect=payload['rect'],auto_width=True))


def test_new_underline_cannot_jump_above_later_image():
    data=document(kind='image');model,ids=selection(data,'123')
    payload=selection_payload(data,0,ids)
    with pytest.raises(EditError,match='subrayado'):
        edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],underline=True)],rect=payload['rect']))


@pytest.mark.parametrize('same_show',[True,False])
def test_selected_show_does_not_hide_unselected_interleaved_glyph(same_show):
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=180)
        if same_show:
            page.insert_text((40,60),'ABC',fontsize=12)
        else:
            page.insert_text((40,60),'A',fontsize=12)
            page.insert_text((48,60),'BC',fontsize=12)
        data=doc.tobytes()
    model,ids=selection(data,'ABC');ids=[ids[0],ids[2]]
    payload=selection_payload(data,0,ids)
    with pytest.raises(EditError,match='intercalado'):
        edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='ABCDEFG')],
                      rect=payload['rect'],auto_width=True,allow_overlap=True))
