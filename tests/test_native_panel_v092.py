"""CID panel alignment, dimensions and neighbour preservation."""
from pathlib import Path
import pymupdf as fitz
import pytest

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditRequest, EditError


def sample():
    with fitz.open() as doc:
        page=doc.new_page(width=500,height=200)
        font=page.insert_font(fontname='Embedded',fontfile=str(Path(__file__).parents[1]/'assets/fonts/LiberationSans-Regular.ttf'))
        doc.xref_set_key(font,'BaseFont','/ABCDEF+LiberationSans')
        page.insert_text((140,60),'123,45',fontname='Embedded',fontsize=12)
        page.insert_text((30,120),'VECINO',fontname='Embedded',fontsize=12)
        data=doc.tobytes()
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    return data,model,model.glyphs[:6]


@pytest.mark.parametrize('anchor',['right','center','decimal'])
def test_longer_number_preserves_requested_anchor_and_neighbours(anchor):
    data,model,selected=sample()
    result,report=edit_pdf(data,EditRequest(0,[g.id for g in selected],text='1239,250',anchor=anchor,auto_width=True))
    assert report['verified'] and report['native_panel']
    glyphs=report['glyphs']
    if anchor=='right':
        assert glyphs[-1]['bbox'][2]==pytest.approx(selected[-1].bbox[2],abs=.035)
    elif anchor=='center':
        assert (glyphs[0]['bbox'][0]+glyphs[-1]['bbox'][2])/2==pytest.approx((selected[0].bbox[0]+selected[-1].bbox[2])/2,abs=.035)
    else:
        assert next(g['origin'][0] for g in glyphs if g['text']==',')==pytest.approx(selected[3].origin[0],abs=.035)
    with fitz.open(stream=result,filetype='pdf') as doc:
        assert len(doc[0].search_for('1239,250'))==1
        edited=extract_page(doc,0,result)
    assert [(g.text,g.origin) for g in edited.glyphs if g.origin[1]>100]==[(g.text,g.origin) for g in model.glyphs if g.origin[1]>100]


def test_no_implicit_line_wrap_when_panel_reflow_is_disabled():
    data,model,selected=sample()
    with pytest.raises(EditError,match='anchura|Redistribuir'):
        edit_pdf(data,EditRequest(0,[g.id for g in selected],text='1239,250',width=10,height=100,auto_height=True))
