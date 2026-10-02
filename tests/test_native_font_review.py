"""Independent integration review of font cursor compensation and repeated edits."""
from io import BytesIO

from fontTools.ttLib import TTFont
import pymupdf as fitz
import pytest
from pypdf import PdfReader

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditRequest
from test_clipped_layout import fixture
from test_fonts import make_font


def choose(data, text):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
    sequence = ''.join(g.text for g in model.glyphs)
    first = sequence.index(text)
    return model, [g.id for g in model.glyphs[first:first+len(text)]]


@pytest.mark.parametrize('tc,tw,tz', [(0., 0., 100.), (.375, 1.1, 80.)])
def test_fractional_font_metrics_compensate_native_cursor_after_long_repeated_edits(tmp_path,tc,tw,tz):
    path = make_font(tmp_path / 'fractional-metrics.ttf')
    # A real-world unitsPerEm produces fractional widths in 1000-unit PDF
    # space. Glyph shapes remain the original CC0 fixture shapes.
    with TTFont(path) as font:
        font['head'].unitsPerEm = 2048
        font.save(path)
    original = fixture('SOL',tc=tc,tw=tw,tz=tz,shared=True)
    with fitz.open(stream=original, filetype='pdf') as doc:
        neighbour = tuple(doc[0].search_for('LUNA')[0])
        control = doc[1].get_pixmap().samples
    current, word = original, 'SOL'
    for index in range(10):
        model, ids = choose(current, word)
        replacement = ('A B ' if index%2 == 0 else 'C D ') * 20
        kwargs = {'font_file':str(path),'size':5.375} if index == 0 else {}
        current, report = edit_pdf(current, EditRequest(0,ids,text=replacement,auto_width=True,
            auto_height=True,allow_overlap=True,revision=model.revision,**kwargs))
        assert report['verified']
        assert replacement.strip() in PdfReader(BytesIO(current)).pages[0].extract_text()
        with fitz.open(stream=current, filetype='pdf') as doc:
            assert tuple(doc[0].search_for('LUNA')[0]) == pytest.approx(neighbour,abs=.001), f'iteration {index+1}'
            assert doc[1].get_pixmap().samples == control
        word = replacement
