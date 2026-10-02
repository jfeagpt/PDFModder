"""Tiny, generated outlines exercise ink outside declared font ascenders."""
from io import BytesIO
from functools import lru_cache

import numpy as np
import pymupdf as fitz
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from pdfmodder.model import EditError
from pdfmodder.validation import assert_pixels, pixel_diff, trace_chars, validate_transition


@lru_cache
def edge_font(accent_top=900):
    # Original geometric test font: deliberately inaccurate ascender like an
    # export whose Ñ outline is taller than its PDF extraction rectangle.
    builder=FontBuilder(1000,isTTF=True)
    builder.setupGlyphOrder(['.notdef','space','Ntilde','X'])
    builder.setupCharacterMap({32:'space',209:'Ntilde',88:'X'})
    glyphs={}
    for name in builder.font.getGlyphOrder():
        pen=TTGlyphPen(None)
        if name in {'Ntilde','X'}:
            pen.moveTo((80,0));pen.lineTo((570,0));pen.lineTo((570,680));pen.lineTo((80,680));pen.closePath()
        if name=='Ntilde':
            pen.moveTo((180,accent_top-80));pen.lineTo((410,accent_top-80));pen.lineTo((510,accent_top));pen.lineTo((280,accent_top));pen.closePath()
        glyphs[name]=pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name:(650,80 if name in {'Ntilde','X'} else 0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=700,descent=-200)
    builder.setupNameTable({'familyName':'Bounds Test','styleName':'Regular',
                          'uniqueFontIdentifier':'PDFModder Bounds Test 1',
                          'fullName':'Bounds Test Regular','psName':'BoundsTest-Regular'})
    builder.setupOS2(sTypoAscender=700,sTypoDescender=-200,usWinAscent=700,usWinDescent=200)
    builder.setupPost()
    buffer=BytesIO();builder.save(buffer)
    return buffer.getvalue()


def document(dx=0,dy=0,*,rotation=0,crop=False,bad_neighbour=False,accent_top=900):
    doc=fitz.open();page=doc.new_page(width=260,height=260)
    if crop:page.set_cropbox(fitz.Rect(15,20,245,240))
    page.insert_font(fontname='edge',fontbuffer=edge_font(accent_top))
    page.draw_rect((10,10,200,200),fill=(.8,.9,.7),color=None)
    page.insert_text((60.4+dx,85.2+dy),'Ñ',fontname='edge',fontsize=8.03)
    page.insert_text((100.4,85.2),'X' if not bad_neighbour else 'Ñ',fontname='edge',fontsize=8.03)
    page.set_rotation(rotation)
    return doc


def glyph_box(page,index=0):
    return [char['bbox'] for block in page.get_text('rawdict')['blocks']
            for line in block.get('lines',[]) for span in line['spans'] for char in span['chars']][index]


def legacy_bad_pixels(a,b,excluded):
    matrix=fitz.Matrix(2,2)
    pa=a.get_pixmap(matrix=matrix,alpha=False,colorspace=fitz.csRGB)
    pb=b.get_pixmap(matrix=matrix,alpha=False,colorspace=fitz.csRGB)
    aa=np.frombuffer(pa.samples,dtype=np.uint8).reshape(pa.height,pa.width,3)
    bb=np.frombuffer(pb.samples,dtype=np.uint8).reshape(pb.height,pb.width,3)
    changed=np.abs(aa.astype(np.int16)-bb.astype(np.int16)).max(axis=2)>8
    for rect in excluded:
        x0,y0,x1,y1=((fitz.Rect(rect)+(-.75,-.75,.75,.75))*a.rotation_matrix*matrix).irect
        changed[max(0,y0):max(0,y1),max(0,x0):max(0,x1)]=False
    return np.count_nonzero(changed)


@pytest.mark.parametrize('rotation,crop',[(0,False),(90,False),(180,True),(270,True)])
def test_verified_outline_covers_only_accent_ink_after_fractional_movement(rotation,crop):
    with document(rotation=rotation,crop=crop) as before,document(.37,.28,rotation=rotation,crop=crop) as after:
        excluded=[glyph_box(before[0]),glyph_box(after[0])]
        assert legacy_bad_pixels(before[0],after[0],excluded)>0
        stats=assert_pixels(before[0],after[0],excluded)
        assert stats['pixels_above_8']==0
        assert stats['ink_exclusion_regions']
        assert 0<stats['ink_extra_pixels']<150
        assert stats['checked_pixels']>before[0].rect.width*before[0].rect.height*4-450
        assert trace_chars(before[0])[1]==trace_chars(after[0])[1]


def test_neighbour_changed_outside_glyph_remains_a_visual_failure():
    with document() as before,document(.37,.28,bad_neighbour=True) as after:
        excluded=[glyph_box(before[0]),glyph_box(after[0])]
        with pytest.raises(EditError,match='cambios visuales'):
            assert_pixels(before[0],after[0],excluded)


def test_bad_character_inside_exclusion_still_fails_content_validation():
    with document() as before,document(.37,.28,bad_neighbour=True) as after:
        expected=trace_chars(before[0])
        expected[0]=(expected[0][0],(expected[0][1][0]+.37,expected[0][1][1]+.28),*expected[0][2:])
        excluded=[glyph_box(before[0]),glyph_box(after[0]),glyph_box(before[0],1),glyph_box(after[0],1)]
        with pytest.raises(EditError,match='carácter'):
            validate_transition(before.tobytes(),after.tobytes(),0,expected,excluded)


@pytest.mark.parametrize('excluded',[[(-40,30,-20,45)],[(30,-40,45,-20)],[(300,30,350,45)],[(30,300,45,350)]])
def test_completely_off_page_rectangles_never_hide_on_page_pixels(excluded):
    with fitz.open() as before,fitz.open() as after:
        a=before.new_page(width=100,height=100);b=after.new_page(width=100,height=100)
        b.draw_rect((10,32,12,34),fill=(0,0,0),color=None)
        stats=pixel_diff(a,b,excluded)
        assert stats['pixels_above_8']>0
        assert stats['checked_pixels']==40_000
        with pytest.raises(EditError,match='cambios visuales'):assert_pixels(a,b,excluded)


def test_no_selected_glyph_means_no_outline_relaxation():
    with document() as before,document(.37,.28) as after:
        stats=pixel_diff(before[0],after[0],[(10,10,12,12)])
        assert stats['pixels_above_8']>0 and stats['ink_extra_pixels']==0
        assert not stats['ink_exclusion_regions']


def test_ambiguous_font_resources_do_not_expand_the_mask():
    with document() as before,document(.37,.28) as after:
        for doc in (before,after):
            doc[0].insert_font(fontname='other',fontbuffer=edge_font(910))
        stats=pixel_diff(before[0],after[0],[glyph_box(before[0]),glyph_box(after[0])])
        assert stats['pixels_above_8']>0 and stats['ink_extra_pixels']==0


def test_large_untrusted_overhang_is_not_hidden_by_a_larger_exclusion():
    with document(accent_top=1200) as before,document(.37,.28,accent_top=1200) as after:
        stats=pixel_diff(before[0],after[0],[glyph_box(before[0]),glyph_box(after[0])])
        assert stats['pixels_above_8']>0 and stats['ink_extra_pixels']==0


def test_vector_damage_inside_accent_region_still_fails_related_objects():
    with document() as before,document(.37,.28) as after:
        after[0].draw_rect((62,77.5,62.1,77.6),fill=(1,0,0),color=None)
        expected=trace_chars(before[0])
        expected[0]=(expected[0][0],(expected[0][1][0]+.37,expected[0][1][1]+.28),*expected[0][2:])
        excluded=[glyph_box(before[0]),glyph_box(after[0])]
        with pytest.raises(EditError,match='vectores'):
            validate_transition(before.tobytes(),after.tobytes(),0,expected,excluded)


def test_mirrored_vertical_text_does_not_use_assumed_upright_outline():
    with document() as before,document(.37,.28) as after:
        for doc in (before,after):
            page=doc[0]
            stream=b'\n'.join(doc.xref_stream(xref) for xref in page.get_contents())
            xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
            doc.update_stream(xref,b'q 1 0 0 -1 0 260 cm\n'+stream+b'\nQ')
            page.set_contents(xref)
        stats=pixel_diff(before[0],after[0],[glyph_box(before[0]),glyph_box(after[0])])
        assert stats['pixels_above_8']>0 and stats['ink_extra_pixels']==0
