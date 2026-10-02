"""High-precision source matrices must not produce false movement failures."""
import pymupdf as fitz
import pytest

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditRequest, EditError
from test_clipped_layout import fixture


def sample():
    with fitz.open(stream=fixture(),filetype='pdf') as doc:
        page=doc[0]
        x=doc.get_new_xref();doc.update_object(x,'<<>>')
        doc.update_stream(x,b'q 1 0 0 1 0.123456789123 -0.3456789123 cm\n'+page.read_contents()+b'\nQ')
        page.set_contents(x)
        data=doc.tobytes()
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    return data,model,[g.id for g in model.glyphs[:3]]


def test_source_precision_is_compared_as_serialized_and_move_stays_exact():
    data,model,ids=sample()
    output,report=edit_pdf(data,EditRequest(0,ids,dx=3,dy=2))
    assert report['verified'] and report['operators_preserved']
    with fitz.open(stream=output,filetype='pdf') as doc:
        moved=extract_page(doc,0,output)
    for old,new in zip(model.glyphs[:3],moved.glyphs[:3]):
        assert new.origin==pytest.approx((old.origin[0]+3,old.origin[1]+2),abs=.035)


def test_real_writer_operator_change_is_still_rejected(monkeypatch):
    import pdfmodder.engine as engine
    original=engine.full_write
    def tamper(doc):
        output=original(doc)
        with fitz.open(stream=output,filetype='pdf') as result:
            page=result[0];x=result.get_new_xref();result.update_object(x,'<<>>')
            result.update_stream(x,b'1 0 0 1 1 0 cm\n'+page.read_contents());page.set_contents(x)
            return result.tobytes()
    data,model,ids=sample()
    monkeypatch.setattr(engine,'full_write',tamper)
    with pytest.raises(EditError,match='alteró operadores'):
        edit_pdf(data,EditRequest(0,ids,dx=3,dy=2))
