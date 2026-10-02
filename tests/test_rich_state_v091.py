"""PDF text state survives unrelated ExtGState operators (Word exports)."""
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, DictionaryObject, NameObject, FloatObject, ArrayObject
import pytest

from pdfmodder.clipped_layout import _state_at
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import selection_payload, edit_rich_pdf
from test_richtext_v09 import document, selection


def test_opacity_state_after_tf_retains_font_size_and_real_edit():
    reader=PdfReader(BytesIO(document()));writer=PdfWriter(clone_from=reader)
    page=writer.pages[0]
    page['/Resources'][NameObject('/ExtGState')]=DictionaryObject({
        NameObject('/GSNeutral'): DictionaryObject({NameObject('/ca'): FloatObject(1)})})
    content=ContentStream(page.get_contents(),writer);ops=[]
    for args,op in content.operations:
        ops.append((args,op))
        if op==b'Tf':ops.append(([NameObject('/GSNeutral')],b'gs'))
    content.operations=ops;page.replace_contents(content)
    target=BytesIO();writer.write(target);data=target.getvalue()
    ids=selection(data,'Hola mundo');payload=selection_payload(data,0,ids)
    out,report=edit_rich_pdf(data,RichTextRequest(0,ids,
        [dict(payload['runs'][0],text='Hola nuevo')],rect=payload['rect'],auto_width=True))
    assert report['verified']
    with fitz.open(stream=out,filetype='pdf') as doc:
        assert 'Hola nuevo' in doc[0].get_text()
        assert 'Hola mundo' not in doc[0].get_text()
        assert 'VECINO INTACTO' in doc[0].get_text()
        spans=[s for s in doc[0].get_texttrace() if s['bbox'][1]<80]
        assert all(s['size']==pytest.approx(12) for s in spans)


def test_gs_font_override_and_q_restore_are_not_guessed():
    state=DictionaryObject({NameObject('/Font'):ArrayObject([NameObject('/F1'),FloatObject(19.5)])})
    resources=DictionaryObject({NameObject('/ExtGState'):DictionaryObject({NameObject('/G'):state})})
    ops=[([NameObject('/F0'),FloatObject(12)],b'Tf'),([],b'q'),([NameObject('/G')],b'gs')]
    assert _state_at(ops,len(ops),resources)['size']==19.5
    ops.append(([],b'Q'))
    assert _state_at(ops,len(ops),resources)['size']==12
    assert _state_at(ops[:3],3,None)['size'] is None
