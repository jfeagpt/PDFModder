"""Fragmentos y líneas nativos: vecinos, recursos y avances se conservan."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, NumberObject

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.model import EditError, EditRequest
from test_clipped_layout import fixture, selected


def fragmented_fixture():
    data=fixture('SOL',neighbors=True)
    writer=PdfWriter(clone_from=PdfReader(BytesIO(data)))
    page=writer.pages[0]
    stream=ContentStream(page.get_contents(),writer)
    operations=[]
    replaced=False
    for args,op in stream.operations:
        if op==b'TJ' and not replaced:
            # Keep the first TJ's fine kerning, split its word across SHOWs.
            original=args[0]
            operations.append(([ArrayObject([original[0],original[1]])],b'TJ'))
            operations.append(([ArrayObject(original[2:])],b'TJ'))
            replaced=True
        else:operations.append((args,op))
    assert replaced
    stream.operations=operations
    page.replace_contents(stream)
    out=BytesIO();writer.write(out)
    return out.getvalue()


def run(data,new,**kwargs):
    model,chosen=selected(data,'SOL')
    return edit_pdf(data,EditRequest(0,[g.id for g in chosen],text=new,revision=model.revision,**kwargs))


def assert_neighbors(before,after,tolerance=.001):
    with fitz.open(stream=before,filetype='pdf') as old,fitz.open(stream=after,filetype='pdf') as new:
        for word in ('LUNA','FIN'):
            original=tuple(old[0].search_for(word)[0])
            assert any(original==pytest.approx(tuple(box),abs=tolerance) for box in new[0].search_for(word))
        assert old[0].get_drawings()==new[0].get_drawings()
        assert old[1].get_pixmap().samples==new[1].get_pixmap().samples
        assert old[1].get_texttrace()==new[1].get_texttrace()


@pytest.mark.parametrize('new',['ESTRELLA','A',''])
def test_fragmented_field_expansion_and_deletion_keep_neighbors(new):
    data=fragmented_fixture()
    output,report=run(data,new,auto_width=True)
    assert report['verified'] and report['source_operations']==2
    assert report['font_resources_unchanged'] and report['cursor_residual']==0
    assert_neighbors(data,output)
    text=PdfReader(BytesIO(output)).pages[0].extract_text()
    assert 'SOL' not in text
    if new:assert new in text


@pytest.mark.parametrize('fragmented',[False,True])
def test_explicit_newline_native_text_and_nearby_vectors(fragmented):
    data=fragmented_fixture() if fragmented else fixture('SOL')
    output,report=run(data,'SOL\nLUNA',width=48,height=25)
    assert report['verified'] and report['line_count']==2
    assert_neighbors(data,output)
    with fitz.open(stream=output,filetype='pdf') as doc:
        model=extract_page(doc,0,output)
        origins=[g.origin for g in model.glyphs if g.text=='L' and abs(g.origin[0]-40)<.01]
        assert any(abs(y-80-report['line_spacing'])<.02 for _,y in origins)
        assert 'SOL\nLUNA' in doc[0].get_text()
    independent=PdfReader(BytesIO(output)).pages[0].extract_text()
    assert independent.splitlines()[0].rstrip()=='SOL'
    assert independent.splitlines()[1].startswith('LUNA')


def test_newline_respects_explicit_height_and_clip():
    data=fragmented_fixture()
    with pytest.raises(EditError,match='altura'):
        run(data,'SOL\nLUNA',width=48,height=10)
    with pytest.raises(EditError,match='recorte'):
        run(data,'SOL\nLUNA\nSOL',width=48,height=50)


def test_fragmented_partial_change_retains_prefix_and_suffix():
    data=fragmented_fixture()
    model,chosen=selected(data,'SOL')
    output,report=edit_pdf(data,EditRequest(0,[g.id for g in chosen[:2]],text='EST',auto_width=True,allow_overlap=True))
    assert report['verified']
    assert_neighbors(data,output)
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        old=[(chr(c[0]),c[2]) for s in before[0].get_texttrace() for c in s['chars']]
        new=[(chr(c[0]),c[2]) for s in after[0].get_texttrace() for c in s['chars']]
        assert next(p for c,p in old if c=='L')==pytest.approx(next(p for c,p in new if c=='L'),abs=.001)


@pytest.mark.parametrize('font_name',[None,'Helvetica'])
@pytest.mark.parametrize('size',[8.375,12.25])
def test_explicit_size_rgb_and_optional_font_keep_baseline_and_neighbors(font_name,size):
    data=fragmented_fixture()
    output,report=run(data,'ESTRELLA',auto_width=True,auto_height=True,size=size,color=(.2,.5,.1),font_name=font_name)
    assert report['verified']
    assert_neighbors(data,output)
    with fitz.open(stream=output,filetype='pdf') as doc:
        spans=[s for s in doc[0].get_texttrace() if ''.join(chr(c[0]) for c in s['chars'])=='ESTRELLA']
        assert len(spans)==1
        assert spans[0]['size']==pytest.approx(size,abs=.001)
        assert spans[0]['color']==pytest.approx((.2,.5,.1),abs=.0001)
        assert spans[0]['chars'][0][2][1]==pytest.approx(80,abs=.001)
    if font_name:
        assert report['font_extension']['explicit'] and report['original_font_resources_unchanged']
        assert 'Fuente elegida' in report['warning']


def test_explicit_ttf_adds_new_accent_without_modifying_original_resources():
    from pathlib import Path
    font=Path('C:/Windows/Fonts/arial.ttf')
    if not font.exists():pytest.skip('Prueba adicional de fuente instalada en Windows')
    data=fragmented_fixture()
    output,report=run(data,'SANDÍA €',auto_width=True,auto_height=True,font_file=str(font))
    assert report['verified'] and report['font_extension']['explicit']
    assert_neighbors(data,output)
    assert 'SANDÍA €' in PdfReader(BytesIO(output)).pages[0].extract_text()
    with fitz.open(stream=output,filetype='pdf') as doc:model=extract_page(doc,0,output)
    joined=''.join(g.text for g in model.glyphs);offset=joined.index('SANDÍA €')
    chosen=model.glyphs[offset:offset+len('SANDÍA €')]
    second,report=edit_pdf(output,EditRequest(0,[g.id for g in chosen],text='SANDÍA Á €',auto_width=True,auto_height=True))
    assert report['verified'] and not report['font_extension']['explicit']
    assert report['font_extension']['source']=='programa incrustado exacto'
    assert 'SANDÍA Á €' in PdfReader(BytesIO(second)).pages[0].extract_text()
    assert_neighbors(data,second)


def test_native_reflow_autoheight_and_reedit_after_reopening():
    data=fragmented_fixture()
    first,report=run(data,'SOL LUNA',width=24,height=12.49,reflow=True,auto_height=True)
    assert report['line_count']==2 and report['auto_height'] and report['area_height']>12.49
    with fitz.open(stream=first,filetype='pdf') as doc:model=extract_page(doc,0,first)
    chosen=[g for g in model.glyphs if g.origin[0]<100 and 88<g.origin[1]<99]
    assert ''.join(g.text for g in chosen)=='LUNA'
    second,report=edit_pdf(first,EditRequest(0,[g.id for g in chosen],text='LUNAS',auto_width=True))
    assert report['verified']
    assert_neighbors(data,second)


def test_overlap_is_explicit_and_second_move_can_isolate_original_operator():
    data=fragmented_fixture()
    model,chosen=selected(data,'SOL')
    target=next(g for g in model.glyphs if g.text=='L' and g.origin[0]>100)
    dx=target.origin[0]-chosen[0].origin[0]
    with pytest.raises(EditError,match='solapa'):
        edit_pdf(data,EditRequest(0,[g.id for g in chosen],dx=dx))
    first,report=edit_pdf(data,EditRequest(0,[g.id for g in chosen],dx=dx,allow_overlap=True))
    assert report['verified'] and report['overlap_count']>0
    with fitz.open(stream=first,filetype='pdf') as doc:model=extract_page(doc,0,first)
    joined=''.join(g.text for g in model.glyphs);start=joined.index('SOL')
    ids=[g.id for g in model.glyphs[start:start+3]]
    second,report=edit_pdf(first,EditRequest(0,ids,dx=-dx,allow_overlap=True))
    assert report['verified']
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=second,filetype='pdf') as after:
        assert before[0].get_pixmap().samples==after[0].get_pixmap().samples
