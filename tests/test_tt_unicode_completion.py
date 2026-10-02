from io import BytesIO
import pymupdf as fitz
import pytest
from pypdf import PdfReader

from cid_ttf_corpus import document
from pdfmodder.clipping import operator_glyph_map,_signature
from pdfmodder.engine import extract_page
from pdfmodder.fonts import FontError
from pdfmodder.native_codes import existing_tt_unicode,verified_cid_fallbacks
from pdfmodder.native_font_extension import prepare_native_font
from pdfmodder.richtext import edit_rich_pdf,selection_payload
from pdfmodder.richmodels import RichTextRequest


def source(data):
    with fitz.open(stream=data,filetype='pdf') as doc:model=extract_page(doc,0,data)
    _,ops,shows,_=operator_glyph_map(data,0,model)
    return model,ops,shows,next(s for s in shows if s['resource']=='/A')


def test_existing_glyph_unicode_completion_keeps_original_program_and_dictionary():
    data=document();model,ops,shows,show=source(data)
    assert verified_cid_fallbacks(data,0,show,shows,ops,'07')=={}
    catalog,evidence=existing_tt_unicode(data,0,show,'07')
    assert catalog=={'0':{2},'7':{9}}
    extension=prepare_native_font(data,0,show,'70,48')
    assert extension.unit==2 and extension.evidence['mapping_only'] and extension.evidence['program_unchanged']
    a,b=PdfReader(BytesIO(data)),PdfReader(BytesIO(extension.data))
    old=a.pages[0]['/Resources']['/Font']['/A'];new=b.pages[0]['/Resources']['/Font'][extension.resource]
    assert _signature(old)==_signature(b.pages[0]['/Resources']['/Font']['/A'])
    assert _signature(old['/DescendantFonts'])==_signature(new['/DescendantFonts'])
    assert old['/ToUnicode'].get_data()!=new['/ToUnicode'].get_data()


def test_rich_number_change_keeps_metrics_neighbours_control_and_saved_text():
    data=document();model,ops,shows,show=source(data)
    ids=[g.id for g in show['glyphs']];payload=selection_payload(data,0,ids)
    out,report=edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='70,48')],rect=payload['rect']))
    assert report['verified'] and all(p['pixels_above_8']==0 for p in report['pages'])
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=out,filetype='pdf') as after:
        assert len(after[0].search_for('70,48'))==1 and not after[0].search_for('68,48')
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        assert 'VECINO INTACTO' in after[0].get_text()
    assert '70,48' in PdfReader(BytesIO(out)).pages[0].extract_text()


@pytest.mark.parametrize('options',[{'missing':'0'},{'changed':'7'},{'indirect_map':True},{'ambiguous':True}])
def test_missing_different_ambiguous_or_unanalysed_mapping_stays_blocked(options):
    data=document(**options);model,ops,shows,show=source(data)
    with pytest.raises(FontError,match='Unicode|glifo|incrustación'):
        prepare_native_font(data,0,show,'70,48')


def test_same_version_complementary_truetype_subsets_can_borrow_declared_glyph():
    data=document(missing='07',same_revision=True);model,ops,shows,show=source(data)
    assert verified_cid_fallbacks(data,0,show,shows,ops,'07')=={'0':'/B','7':'/B'}
