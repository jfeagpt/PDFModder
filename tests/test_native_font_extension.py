"""Fonts created by the tests; no private invoice or licensed OS font bundled."""
from io import BytesIO
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen

import pymupdf as fitz
import pytest
from pypdf import PdfReader

from pdfmodder.clipping import _signature
from pdfmodder.fonts import FontError, FontResolver
from pdfmodder.native_font_extension import prepare_native_font
from test_fonts import make_font


def document(path):
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 50), 'SANDIA', fontname='Test', fontfile=str(path), fontsize=11.25)
        doc.fullcopy_page(0)
        data = doc.tobytes()
        xref = doc[0].get_fonts()[0][0]
    return data, {'xref': xref, 'resource': '/Test'}


def paint(extension, text):
    codes = bytes(next(iter(extension.catalog[c])) for c in text)
    with fitz.open(stream=extension.data, filetype='pdf') as doc:
        xref = doc.get_new_xref()
        doc.update_object(xref, '<<>>')
        stream = ('BT ' + extension.resource + ' 11.25 Tf 1 0 0 1 30 100 Tm <' + codes.hex() + '> Tj ET').encode('ascii')
        doc.update_stream(xref, stream)
        old_contents = doc[0].get_contents()
        doc.xref_set_key(doc[0].xref, 'Contents', '[' + ' '.join(f'{n} 0 R' for n in old_contents + [xref]) + ']')
        return doc.tobytes()


def test_embedded_unicode_glyph_without_original_pdf_code_is_reusable(tmp_path):
    path = make_font(tmp_path / 'test.ttf')
    data, show = document(path)
    extension = prepare_native_font(data, 0, show, 'SANDÍA Ñ €')
    assert not extension.evidence['explicit']
    assert extension.evidence['all_outlines_retained']
    assert extension.catalog[' '] == {32}
    changed = paint(extension, 'SANDÍA Ñ €')
    with fitz.open(stream=data, filetype='pdf') as before, fitz.open(stream=changed, filetype='pdf') as after:
        assert 'SANDÍA Ñ €' in after[0].get_text()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before[0].get_pixmap().samples == fitz.open(stream=extension.data, filetype='pdf')[0].get_pixmap().samples
    reader_before, reader_after = PdfReader(BytesIO(data)), PdfReader(BytesIO(changed))
    old_font = reader_before.pages[0]['/Resources']['/Font']['/Test']
    assert _signature(old_font) == _signature(reader_after.pages[0]['/Resources']['/Font']['/Test'])
    assert extension.resource not in reader_after.pages[1]['/Resources']['/Font']
    assert 'SANDÍA Ñ €' in reader_after.pages[0].extract_text()


def test_absent_embedded_glyph_requires_explicit_choice_even_when_installed(tmp_path):
    subset = make_font(tmp_path / 'partial.ttf', text=' SANDIA')
    full = make_font(tmp_path / 'full.ttf')
    data, show = document(subset)
    resolver = FontResolver(tmp_path / 'fonts.json', installed_dirs=[tmp_path])
    with pytest.raises(FontError, match='Elige explícitamente'):
        prepare_native_font(data, 0, show, 'SANDÍA', resolver=resolver)
    extension = prepare_native_font(data, 0, show, 'SANDÍA', font_file=full, resolver=resolver)
    assert extension.evidence['explicit']
    assert extension.font['/BaseFont'] == '/PDFModderTest-Regular'
    assert extension.font['/FontDescriptor']['/FontName'] == extension.font['/BaseFont']
    assert 'SANDÍA' in PdfReader(BytesIO(paint(extension, 'SANDÍA'))).pages[0].extract_text()


def test_restricted_font_cannot_be_silently_reembedded(tmp_path):
    path = make_font(tmp_path / 'restricted.ttf', flags=2)
    data, show = document(path)
    with pytest.raises(FontError, match='incrustación editable'):
        prepare_native_font(data, 0, show, 'SANDÍA')
    with pytest.raises(FontError, match='incrustación editable'):
        prepare_native_font(data, 0, show, 'SANDÍA', font_file=path)


@pytest.mark.parametrize('invalid', [{'resource':'/Missing'}, {'xref':99999}])
def test_minimal_font_record_requires_current_resource_identity(tmp_path, invalid):
    data, show = document(make_font(tmp_path / 'test.ttf'))
    with pytest.raises(FontError, match='identidad del recurso'):
        prepare_native_font(data, 0, {**show, **invalid}, 'SANDÍA')


@pytest.mark.parametrize('name', ['Helvetica', 'Courier-Bold'])
def test_explicit_standard_face_can_add_accents_euro_and_new_codes(tmp_path, name):
    data, show = document(make_font(tmp_path / 'test.ttf'))
    extension = prepare_native_font(data, 0, show, 'SANDÍA Ñ €', font_name=name)
    changed = paint(extension, 'SANDÍA Ñ €')
    assert extension.evidence['explicit']
    with fitz.open(stream=changed, filetype='pdf') as doc:
        assert 'SANDÍA Ñ €' in doc[0].get_text()
    assert 'SANDÍA Ñ €' in PdfReader(BytesIO(changed)).pages[0].extract_text()


def test_two_extensions_have_separate_resource_keys(tmp_path):
    data, show = document(make_font(tmp_path / 'test.ttf'))
    first = prepare_native_font(data, 0, show, 'SANDÍA')
    second = prepare_native_font(first.data, 0, show, 'SANDÍA', font_name='Helvetica')
    assert first.resource != second.resource
    reader = PdfReader(BytesIO(second.data))
    assert first.resource in reader.pages[0]['/Resources']['/Font']


def test_reopened_extension_reuses_other_original_unicode_glyphs(tmp_path):
    data, show = document(make_font(tmp_path / 'test.ttf'))
    first = prepare_native_font(data, 0, show, 'SANDÍA')
    first_saved = paint(first, 'SANDÍA')
    with fitz.open(stream=first_saved, filetype='pdf') as doc:
        xref = next(row[0] for row in doc[0].get_fonts() if row[4] == first.resource[1:])
    second = prepare_native_font(first_saved, 0, {'xref': xref, 'resource': first.resource}, 'SANDÍA Ñ €')
    assert not second.evidence['explicit']
    assert 'SANDÍA Ñ €' in PdfReader(BytesIO(paint(second, 'SANDÍA Ñ €'))).pages[0].extract_text()


def test_new_one_byte_codes_support_original_glyph_ids_above_255(tmp_path):
    text = ' SANDIA€' + ''.join(chr(0x1000 + n) for n in range(300))
    path = make_font(tmp_path / 'large.ttf', text=text)
    with TTFont(path) as font:
        assert font.getGlyphID(font.getBestCmap()[ord('€')]) > 255
    data, show = document(path)
    extension = prepare_native_font(data, 0, show, 'SANDIA €')
    assert 'SANDIA €' in PdfReader(BytesIO(paint(extension, 'SANDIA €'))).pages[0].extract_text()


def test_missing_base14_characters_and_no_implicit_family_substitution(tmp_path):
    data, show = document(make_font(tmp_path / 'test.ttf'))
    with pytest.raises(FontError):
        prepare_native_font(data, 0, show, '中', font_name='Helvetica')
    with pytest.raises(FontError, match='fuente o variante exacta'):
        prepare_native_font(data, 0, show, 'SANDÍA', font_name='Imaginary Arial')


def test_symbol_mapping_retains_composite_outlines_at_fractional_size(tmp_path):
    path = make_font(tmp_path / 'composite.ttf')
    with TTFont(path) as font:
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addComponent('uni0049', (1, 0, 0, 1, 0, 0))
        pen.addComponent('uni002F', (.2, 0, 0, .2, 200, 690))
        font['glyf']['uni00CD'] = pen.glyph()
        font.save(path)
    data, show = document(path)
    text = 'Í áñ €'
    extension = prepare_native_font(data, 0, show, text)
    # Render the two encodings at exactly the same baseline and size. The new
    # cmap must not change outlines, composites, hinting or horizontal metrics.
    with fitz.open() as reference:
        page = reference.new_page(width=300, height=200)
        page.insert_text((30, 100), text, fontname='Reference', fontfile=str(path), fontsize=11.375)
        reference_pixels = page.get_pixmap(matrix=fitz.Matrix(2, 2)).samples
    codes = bytes(next(iter(extension.catalog[c])) for c in text)
    with fitz.open(stream=extension.data, filetype='pdf') as edited:
        xref = edited.get_new_xref()
        edited.update_object(xref, '<<>>')
        edited.update_stream(xref, ('BT ' + extension.resource + ' 11.375 Tf 1 0 0 1 30 100 Tm <' + codes.hex() + '> Tj ET').encode('ascii'))
        edited[0].set_contents(xref)
        assert edited[0].get_pixmap(matrix=fitz.Matrix(2, 2)).samples == reference_pixels
