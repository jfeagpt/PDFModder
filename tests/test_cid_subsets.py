"""Original synthetic CFF subsets; no proprietary font is bundled."""
from io import BytesIO

import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.cffLib import FDArrayIndex, FDSelect, FontDict
from fontTools.pens.t2CharStringPen import T2CharStringPen
from pypdf import PdfReader
import pytest

from pdfmodder.clipping import operator_glyph_map, _signature
from pdfmodder.engine import extract_page
from pdfmodder.model import EditError
from pdfmodder.native_codes import verified_catalog, verified_cid_fallbacks
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import _catalog, edit_rich_pdf, selection_payload


from cid_corpus import document


def test_donor_pdf_width_override_cannot_silently_change_typography():
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, NumberObject, NameObject
    writer=PdfWriter(clone_from=PdfReader(BytesIO(document())))
    font=writer.pages[0]['/Resources']['/Font']['/B']['/DescendantFonts'][0].get_object()
    font[NameObject('/W')]=ArrayObject([NumberObject(54),ArrayObject([NumberObject(400)])])
    target=BytesIO();writer.write(target);data=target.getvalue()
    model,ops,shows,source=context(data)
    assert verified_cid_fallbacks(data,0,source,shows,ops,'6')=={}


def test_complementary_glyph_keeps_selection_scale_when_donor_is_compressed():
    data=document()
    from pypdf import PdfWriter
    from pypdf.generic import ContentStream, NumberObject
    writer=PdfWriter(clone_from=PdfReader(BytesIO(data)))
    page=writer.pages[0];content=ContentStream(page.get_contents(),writer);ops=[]
    for args,op in content.operations:
        ops.append((args,op))
        if op==b'Tf' and args[0]=='/B':ops.append(([NumberObject(80)],b'Tz'))
    content.operations=ops;page.replace_contents(content)
    target=BytesIO();writer.write(target);data=target.getvalue()
    model,ops,shows,source=context(data);ids=[g.id for g in source['glyphs']]
    payload=selection_payload(data,0,ids)
    out,report=edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='2026')],rect=payload['rect']))
    assert report['verified']
    with fitz.open(stream=out,filetype='pdf') as result:
        model=extract_page(result,0,out)
    year=[g for g in model.glyphs if abs(g.origin[1]-source['glyphs'][0].origin[1])<.01]
    assert ''.join(g.text for g in year)=='2026'
    widths=[g.trace_bbox[2]-g.trace_bbox[0] for g in year]
    assert widths==pytest.approx([6.]*4,abs=.01)
    assert year[-1].origin[0]==pytest.approx(year[0].origin[0]+18,abs=.01)


def test_crlf_with_complementary_glyph_remains_one_paragraph_break():
    data=document();model,ops,shows,source=context(data);ids=[g.id for g in source['glyphs']]
    payload=selection_payload(data,0,ids)
    out,report=edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='2026\r\n2026')],
        rect=payload['rect'],auto_height=True,paragraphs=[dict(line_spacing=16)]))
    assert report['verified']
    baselines=sorted(set(round(g['origin'][1],3) for g in report['glyphs']))
    assert len(baselines)==2 and baselines[1]-baselines[0]==pytest.approx(16)


def context(data):
    with fitz.open(stream=data,filetype='pdf') as doc:model=extract_page(doc,0,data)
    _,ops,shows,_=operator_glyph_map(data,0,model)
    source=next(s for s in shows if s['resource']=='/A')
    return model,ops,shows,source


def test_complementary_subsets_reuse_original_program_and_declared_unused_cid():
    data=document();model,ops,shows,source=context(data)
    assert verified_cid_fallbacks(data,0,source,shows,ops,'6')=={'6':'/B'}
    donor=next(s for s in shows if s['resource']=='/B')
    assert '6' not in _catalog(shows,ops,'/B')
    assert verified_catalog(data,0,donor,_catalog(shows,ops,'/B'),'6')['6']=={54}
    glyphs=source['glyphs'];ids=[g.id for g in glyphs];payload=selection_payload(data,0,ids)
    output,report=edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='2026')],rect=payload['rect']))
    assert report['verified'] and all(p['pixels_above_8']==0 for p in report['pages'])
    assert report['fonts']['/B']['complementary_subset_of']=='/A'
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert len(after[0].search_for('2026'))==1 and not after[0].search_for('2025')
        assert 'VECINO INTACTO' in after[0].get_text()
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
    a,b=PdfReader(BytesIO(data)),PdfReader(BytesIO(output))
    for name in ('/A','/B'):
        assert _signature(a.pages[0]['/Resources']['/Font'][name])==_signature(b.pages[0]['/Resources']['/Font'][name])


@pytest.mark.parametrize('options',[{'changed':True},{'hints':True},{'matrix':True},{'absent':True}])
def test_similar_name_cannot_replace_program_hinting_transform_or_missing_glyph(options):
    data=document(**options);model,ops,shows,source=context(data)
    assert verified_cid_fallbacks(data,0,source,shows,ops,'6')=={}
    ids=[g.id for g in source['glyphs']];payload=selection_payload(data,0,ids)
    with pytest.raises(EditError,match='incrustación|fuente|glifo'):
        edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='2026')],rect=payload['rect']))
