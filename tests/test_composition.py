"""Adding real text and deliberately changing typography in existing text."""
from io import BytesIO
from pathlib import Path
import hashlib

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.composition import AddTextRequest, insert_text_pdf
from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.fonts import FontError, FontResolver
from pdfmodder.model import EditError, EditRequest, union
from pdfmodder.validation import related, trace_chars

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / 'assets' / 'fonts'


def document():
    with fitz.open() as doc:
        page = doc.new_page(width=500, height=650)
        page.draw_rect((30, 100, 470, 290), fill=(.85, .94, .9), color=(.1, .4, .3), width=.7)
        page.insert_text((40, 60), 'ORIGINAL', fontname='helv', fontsize=12.375)
        page.insert_text((330, 60), 'VECINO', fontname='hebo', fontsize=10.5)
        page.insert_text((40, 350), 'ENLACE', fontname='helv', fontsize=10)
        page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(35, 335, 100, 360), 'uri': 'https://example.org'})
        page.add_text_annot((400, 400), 'Nota independiente')
        second = doc.new_page(width=500, height=650)
        second.insert_text((40, 60), 'PAGINA INTACTA', fontsize=12.375)
        doc.set_toc([[1, 'Control', 2]])
        return doc.tobytes()


def selection(data, text, page=0):
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, page, data)
    joined = ''.join(g.text for g in model.glyphs)
    offset = joined.index(text)
    chosen = model.glyphs[offset:offset+len(text)]
    assert ''.join(g.text for g in chosen) == text
    return model, chosen


def assert_originals_preserved(before, after, excluded=()):
    with fitz.open(stream=before, filetype='pdf') as old, fitz.open(stream=after, filetype='pdf') as new:
        for page in range(old.page_count):
            actual = trace_chars(new[page])
            for char, origin, font, size in trace_chars(old[page]):
                if page == 0 and any(char == g.text and abs(origin[0]-g.origin[0]) < .001 and abs(origin[1]-g.origin[1]) < .001 for g in excluded):
                    continue
                matches = [g for g in actual if g[0] == char and abs(g[1][0]-origin[0]) < .035 and abs(g[1][1]-origin[1]) < .035]
                assert len(matches) == 1 and matches[0][2] == font
                assert matches[0][3] == pytest.approx(size, abs=.001)
            assert related(old[page]) == related(new[page])
        assert old[1].get_pixmap(matrix=fitz.Matrix(2, 2)).samples == new[1].get_pixmap(matrix=fitz.Matrix(2, 2)).samples
        assert old.get_toc() == new.get_toc()


def test_insert_spanish_fractional_size_colour_is_real_and_reeditable():
    data = document()
    requested = 'Fecha: 12/09/2026 - niño áéíóú €'
    request = AddTextRequest(0, 45, 120, 400, 40, requested, size=12.375, color=(.7, .1, .2))
    changed, report = insert_text_pdf(data, request)
    assert report['verified'] and report['source_regions'] == [] and report['page'] == 0
    model, added = selection(changed, requested)
    assert all(g.size == pytest.approx(12.375, abs=.001) and g.color == pytest.approx((.7,.1,.2),abs=.001) for g in added)
    assert union(g.bbox for g in added)[0] == pytest.approx(45, abs=.035)
    assert union(g.bbox for g in added)[1] == pytest.approx(120, abs=.035)
    assert requested in PdfReader(BytesIO(changed), strict=True).pages[0].extract_text()
    model, date = selection(changed, '12/09/2026')
    edited, _ = edit_pdf(changed, EditRequest(0, [g.id for g in date], text='13/09/2026', revision=model.revision))
    assert '13/09/2026' in PdfReader(BytesIO(edited)).pages[0].extract_text()
    assert_originals_preserved(data, edited)


def test_add_wrap_height_overflow_alignment_and_actual_font_metrics():
    data = document()
    content = 'Uno dos tres cuatro cinco seis siete ocho'
    with pytest.raises(EditError, match='altura'):
        insert_text_pdf(data, AddTextRequest(0, 45, 120, 100, 15, content, size=11.375))
    changed, report = insert_text_pdf(data, AddTextRequest(0, 45, 120, 100, 130, content, size=11.375, align='right'))
    with fitz.open(stream=changed, filetype='pdf') as doc:
        model = extract_page(doc, 0, changed)
        body = [g for g in model.glyphs if 119 < g.bbox[1] < 260 and g.bbox[2] < 146]
        baselines = sorted({round(g.origin[1],3) for g in body})
        assert len(baselines) > 1
        joined = []
        for baseline in baselines:
            line = sorted([g for g in body if abs(g.origin[1]-baseline)<.001],key=lambda g:g.origin[0])
            assert union(g.bbox for g in line)[2] == pytest.approx(145, abs=.035)
            assert all(g.size == pytest.approx(11.375, abs=.001) for g in line)
            joined.append(''.join(g.text for g in line))
        assert ' '.join(joined) == content
    assert all(p['pixels_above_8'] == 0 for p in report['pages'])
    assert_originals_preserved(data, changed)


def test_explicit_font_and_colour_change_reproduces_original_before_changing():
    data = document()
    model, old = selection(data, 'ORIGINAL')
    changed, report = edit_pdf(data, EditRequest(0, [g.id for g in old], text='NIÑO €', width=200, height=35,
                                               font_name='Helvetica-BoldOblique', size=14.375, color=(.1,.3,.8), revision=model.revision))
    _, actual = selection(changed, 'NIÑO €')
    assert all(g.font == 'Helvetica-BoldOblique' for g in actual)
    assert all(g.size == pytest.approx(14.375, abs=.001) for g in actual)
    assert all(g.color == pytest.approx((.1,.3,.8),abs=.001) for g in actual)
    assert actual[0].origin == pytest.approx(old[0].origin, abs=.035)
    assert report['manual_format']['font'] == 'Helvetica-BoldOblique'
    assert_originals_preserved(data, changed, old)


def test_manual_file_real_bold_italic_is_embedded_without_faux_style():
    data = document()
    file = str(FONTS / 'LiberationSans-BoldItalic.ttf')
    changed, _ = insert_text_pdf(data, AddTextRequest(0, 45, 120, 400, 40, 'Negrita cursiva: ñ €', font_file=file, size=13.125))
    _, glyphs = selection(changed, 'Negrita cursiva: ñ €')
    assert {g.font for g in glyphs} == {'LiberationSans-BoldItalic'}
    with fitz.open(stream=changed, filetype='pdf') as doc:
        metadata = FontResolver(installed_dirs=[]).inspect(doc,0)
        chosen = next(info for info in metadata if info.get('postscript_name') == 'LiberationSans-BoldItalic')
        assert chosen['embedded'] and chosen['embedding_permission'] == 'instalable'
    model, original = selection(data, 'ORIGINAL')
    changed, _ = edit_pdf(data, EditRequest(0, [g.id for g in original], font_file=file, width=220, height=40))
    _, modified = selection(changed, 'ORIGINAL')
    assert {g.font for g in modified} == {'LiberationSans-BoldItalic'}


def test_missing_face_restricted_license_and_missing_glyph_refuse():
    data = document()
    resolver = FontResolver(installed_dirs=[])
    with pytest.raises(EditError, match='Falta la fuente'):
        insert_text_pdf(data, AddTextRequest(0,45,120,200,40,'Test',font_name='Missing-Face-Bold'),resolver)
    with pytest.raises(EditError, match='no permite incrustación editable'):
        insert_text_pdf(data, AddTextRequest(0,45,120,200,40,'Test',font_file=str(FONTS/'Vera.ttf')),resolver)
    with pytest.raises(EditError, match='Faltan caracteres'):
        insert_text_pdf(data, AddTextRequest(0,45,120,200,40,'中',font_name='Helvetica'),resolver)
    model, old = selection(data,'ORIGINAL')
    with pytest.raises(EditError, match='Falta la fuente'):
        edit_pdf(data,EditRequest(0,[g.id for g in old],font_name='Missing-Face-Bold'),resolver)


def test_target_font_can_add_glyph_absent_from_original_base14():
    data = document()
    model, old = selection(data,'ORIGINAL')
    file = str(FONTS/'LiberationSans-Regular.ttf')
    changed,_=edit_pdf(data,EditRequest(0,[g.id for g in old],text='Привет',font_file=file,width=150,height=35))
    assert 'Привет' in PdfReader(BytesIO(changed)).pages[0].extract_text()
    assert_originals_preserved(data,changed,old)


def test_rotated_crop_insertion_uses_unrotated_top_left_coordinates():
    with fitz.open() as doc:
        page=doc.new_page(width=600,height=800)
        page.set_cropbox(fitz.Rect(30,40,570,750))
        page.set_rotation(90)
        data=doc.tobytes()
    changed,_=insert_text_pdf(data,AddTextRequest(0,60,80,200,40,'Texto rotado: ñ €',size=11.375))
    model, inserted=selection(changed,'Texto rotado: ñ €')
    assert model.rotation==90 and model.cropbox==(30,40,570,750)
    assert union(g.bbox for g in inserted)[:2]==pytest.approx((60,80),abs=.035)
    moved,_=edit_pdf(changed,EditRequest(0,[g.id for g in inserted],dx=12.5,dy=8.25))
    _, final=selection(moved,'Texto rotado: ñ €')
    assert final[0].origin==(pytest.approx(inserted[0].origin[0]+12.5,abs=.035),pytest.approx(inserted[0].origin[1]+8.25,abs=.035))


def test_bounds_overlap_and_stale_area_are_explicitly_rejected():
    data=document()
    with pytest.raises(EditError,match='fuera'):
        insert_text_pdf(data,AddTextRequest(0,490,120,100,40,'Fuera'))
    with pytest.raises(EditError,match='caracteres existentes'):
        insert_text_pdf(data,AddTextRequest(0,40,48,200,40,'Encima'))
    with pytest.raises(EditError,match='enlace'):
        insert_text_pdf(data,AddTextRequest(0,40,335,200,40,'Encima',allow_overlap=True))
    with pytest.raises(EditError,match='cambió'):
        insert_text_pdf(data,AddTextRequest(0,45,120,200,40,'Test',revision='stale'))
    changed,_=insert_text_pdf(data,AddTextRequest(0,40,48,200,40,'Encima',allow_overlap=True))
    assert 'ORIGINAL' in PdfReader(BytesIO(changed)).pages[0].extract_text()


def test_catalog_has_real_variants_and_marks_restricted_files():
    resolver=FontResolver(installed_dirs=[FONTS])
    catalog=resolver.catalog()
    base=next(item for item in catalog if item['name']=='Helvetica-BoldOblique')
    assert base['bold'] and base['italic'] and base['path'] is None
    bold=next(item for item in catalog if item['name']=='LiberationSans-BoldItalic')
    assert bold['bold'] and bold['italic'] and bold['editable']
    assert Path(bold['path']).name=='LiberationSans-BoldItalic.ttf'
    vera=next(item for item in catalog if Path(item['path'] or '').name=='Vera.ttf')
    assert not vera['editable'] and 'incrustación editable' in vera['status']


def test_leading_spaces_and_explicit_nbsp_are_not_discarded_during_composition():
    data=document()
    requested='  A B\u00a0C'
    changed,_=insert_text_pdf(data,AddTextRequest(0,45,120,200,40,requested,font_file=str(FONTS/'LiberationSans-Regular.ttf')))
    _,body=selection(changed,requested)
    assert ''.join(g.text for g in body)==requested


def test_colour_only_operation_preserves_mixed_fonts_and_positions():
    with fitz.open() as doc:
        page=doc.new_page()
        page.insert_text((40,80),'Normal',fontname='helv',fontsize=12.375)
        page.insert_text((150,80),'Bold',fontname='hebo',fontsize=12.375)
        data=doc.tobytes()
    model=selection(data,'Normal')[0]
    changed,_=edit_pdf(data,EditRequest(0,[g.id for g in model.glyphs],color=(.8,.2,.1)))
    result=selection(changed,'Normal')[0]
    assert len(result.glyphs)==len(model.glyphs)
    for old,new in zip(model.glyphs,result.glyphs):
        assert old.text==new.text and old.font==new.font and old.origin==pytest.approx(new.origin,abs=.035)
        assert new.color==pytest.approx((.8,.2,.1),abs=.001)
