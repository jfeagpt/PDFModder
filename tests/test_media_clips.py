"""Image placement with explicit clips and inherited matrices; no user files."""
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageDraw
import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream
import pytest

from pdfmodder.media import add_image_pdf, delete_image_pdf, image_items, transform_image_pdf
from pdfmodder.model import EditError
from pdfmodder.validation import related, trace_chars


def picture():
    bitmap=Image.new('RGBA',(24,16),(0,0,0,0))
    draw=ImageDraw.Draw(bitmap)
    draw.rectangle((0,0,11,15),fill=(210,30,60,128))
    draw.rectangle((12,0,23,15),fill=(20,50,210,255))
    output=BytesIO()
    bitmap.save(output,format='PNG')
    return output.getvalue()


def clipped_pdf(clip='rect',*,outer_restore=True,shared=False,gs=None,rotation=0,crop=False):
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_text((40,50),'VISIBLE',fontname='helv',fontsize=12)
        page.insert_image((60,120,140,160),stream=picture())
        image_name=page.get_images(full=True)[0][7]
        state=''
        if gs:
            xref=doc.get_new_xref()
            doc.update_object(xref,'<</ca .5>>' if gs=='alpha' else '<</BM/Multiply>>')
            resource_xref=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
            doc.xref_set_key(resource_xref,'ExtGState',f'<</Scope {xref} 0 R>>')
            state='/Scope gs\n'
        clipping={
            'none':'',
            'rect':'400 1800 2800 1800 re W n\n',
            'partial':'900 1800 1800 1800 re W n\n',
            'curve':'400 1800 m 400 3600 3200 3600 3200 1800 c h W n\n',
        }[clip]
        content=(('q\n' if outer_restore else '')+
                 '.1 0 0 .1 0 0 cm\n'
                 '.1 .6 .3 rg 200 200 3600 3600 re f\n'
                 '0 0 0 rg BT /helv 120 Tf 1 0 0 1 400 3500 Tm (VISIBLE) Tj ET\n'
                 'q\n'+clipping+state+
                 f'q 800 0 0 400 600 2400 cm /{image_name} Do Q\nQ\n'
                 'BT /helv 120 Tf 3 Tr 1 0 0 1 620 2460 Tm (OCR INVISIBLE) Tj ET\n'+
                 ('Q\n' if outer_restore else ''))
        content_xref=doc.get_new_xref()
        doc.update_object(content_xref,'<<>>')
        doc.update_stream(content_xref,content.encode('ascii'))
        page.set_contents(content_xref)
        resources=doc.xref_get_key(page.xref,'Resources')[1]
        if crop:
            page.set_cropbox(fitz.Rect(20,30,380,370))
        page.set_rotation(rotation)
        control=doc.new_page(width=400,height=400)
        if shared:
            doc.xref_set_key(control.xref,'Resources',resources)
            control.set_contents(content_xref)
        else:
            control.insert_text((40,50),'CONTROL INTACTO',fontname='helv',fontsize=12)
            control.draw_rect((40,80,360,320),color=(.2,.4,.7),fill=(.94,.96,.98))
        return doc.tobytes(garbage=3,deflate=True)


def selected(data,number=0,index=0):
    with fitz.open(stream=data,filetype='pdf') as doc:
        return image_items(doc,number)[index]


def clips(data):
    reader=PdfReader(BytesIO(data),strict=True)
    return [(str(args),op) for args,op in ContentStream(reader.pages[0].get_contents(),reader).operations
            if op in (b're',b'm',b'l',b'c',b'h',b'W',b'W*')]


def assert_retained(before,after):
    assert clips(before)==clips(after)
    with fitz.open(stream=before,filetype='pdf') as old,fitz.open(stream=after,filetype='pdf') as new:
        assert len(old)==len(new)==2
        for number in (0,1):
            assert trace_chars(old[number])==trace_chars(new[number])
        assert related(old[1])==related(new[1])
        assert old[1].get_pixmap(matrix=fitz.Matrix(2,2)).samples==new[1].get_pixmap(matrix=fitz.Matrix(2,2)).samples
        modes=[span['type'] for span in new[0].get_texttrace()]
        assert 3 in modes, 'El OCR invisible debe conservarse como contenido original'


@pytest.mark.parametrize('clip',['rect','curve'])
@pytest.mark.parametrize('outer_restore',[False,True])
def test_new_image_is_independent_of_old_clip_ctm_and_invisible_text(clip,outer_restore):
    source=clipped_pdf(clip,outer_restore=outer_restore)
    source_hash=sha256(source).hexdigest()
    # This rectangle is outside the original clipping scope and has an ordinary
    # PDF coordinate, despite the original page's inherited 0.1 scale.
    first,report=add_image_pdf(source,0,picture(),(260,280,356,344))
    assert report['verified']
    item=selected(first,index=1)
    assert item['editable'],item['reason']
    assert item['rect']==pytest.approx((260,280,356,344),abs=.035)
    assert item['clip_rect_pdf'] is None
    moved,_=transform_image_pdf(first,0,item['id'],(200,280,296,344))
    resized,_=transform_image_pdf(moved,0,item['id'],(200,280,272,328))
    assert selected(resized,index=1)['rect']==pytest.approx((200,280,272,328),abs=.035)
    removed,_=delete_image_pdf(resized,0,item['id'])
    assert_retained(source,removed)
    with fitz.open(stream=source,filetype='pdf') as old,fitz.open(stream=removed,filetype='pdf') as new:
        assert old[0].get_pixmap(matrix=fitz.Matrix(2,2)).samples==new[0].get_pixmap(matrix=fitz.Matrix(2,2)).samples
        assert len(new[0].get_image_info())==1
    assert sha256(source).hexdigest()==source_hash


def test_original_image_global_scale_can_move_resize_delete_without_shared_changes():
    source=clipped_pdf('rect',shared=True)
    original=selected(source)
    assert original['editable'],original['reason']
    assert original['parent_matrix']==pytest.approx((.1,0,0,.1,0,0))
    assert original['rect']==pytest.approx((60,120,140,160),abs=.035)
    moved,report=transform_image_pdf(source,0,'0',(160,120,240,160))
    assert report['verified']
    assert selected(moved)['rect']==pytest.approx((160,120,240,160),abs=.035)
    assert selected(moved,1)['rect']==pytest.approx(original['rect'],abs=.035)
    resized,_=transform_image_pdf(moved,0,'0',(160,120,280,180))
    assert selected(resized)['rect']==pytest.approx((160,120,280,180),abs=.035)
    deleted,_=delete_image_pdf(resized,0,'0')
    with fitz.open(stream=deleted,filetype='pdf') as pdf:
        assert not pdf[0].get_image_info()
        assert len(pdf[1].get_image_info())==1
    assert_retained(source,moved)
    assert_retained(source,resized)
    assert_retained(source,deleted)


def test_destination_must_fit_in_inherited_clip_without_revealing_hidden_pixels():
    source=clipped_pdf('rect')
    with pytest.raises(EditError,match='destino.*recorte heredado'):
        transform_image_pdf(source,0,'0',(325,120,395,160))
    with pytest.raises(EditError,match='destino.*recorte heredado'):
        transform_image_pdf(source,0,'0',(160,200,240,250))
    assert selected(source)['rect']==pytest.approx((60,120,140,160),abs=.035)


@pytest.mark.parametrize('clip,reason',[('partial','original está recortada'),('curve','recorte no rectangular')])
def test_clipped_original_instance_has_specific_reason_but_new_image_is_supported(clip,reason):
    source=clipped_pdf(clip)
    item=selected(source)
    assert not item['editable'] and reason in item['reason']
    with pytest.raises(EditError,match=reason):
        transform_image_pdf(source,0,'0',(160,120,240,160))
    output,_=add_image_pdf(source,0,picture(),(250,280,346,344))
    assert selected(output,index=1)['editable']
    assert_retained(source,output)


@pytest.mark.parametrize('rotation',[90,270])
def test_inherited_scale_clip_with_rotated_page_and_shifted_crop(rotation):
    source=clipped_pdf('rect',rotation=rotation,crop=True)
    assert selected(source)['rect']==pytest.approx((40,90,120,130),abs=.035)
    output,_=transform_image_pdf(source,0,'0',(130,100,230,150))
    assert selected(output)['rect']==pytest.approx((130,100,230,150),abs=.035)
    assert_retained(source,output)
    with fitz.open(stream=output,filetype='pdf') as pdf:
        assert pdf[0].rotation==rotation and tuple(pdf[0].cropbox)==(20,30,380,370)


def test_inherited_alpha_is_preserved_but_special_blend_gets_an_image_reason():
    source=clipped_pdf('rect',gs='alpha')
    assert selected(source)['editable']
    output,_=transform_image_pdf(source,0,'0',(160,120,240,160))
    assert_retained(source,output)
    reader=PdfReader(BytesIO(output))
    assert float(reader.pages[0]['/Resources']['/ExtGState']['/Scope']['/ca'])==.5
    special=clipped_pdf('rect',gs='multiply')
    item=selected(special)
    assert not item['editable'] and 'mezcla de color' in item['reason']
    with pytest.raises(EditError,match='mezcla de color'):
        transform_image_pdf(special,0,'0',(160,120,240,160))
    added,_=add_image_pdf(special,0,picture(),(250,280,346,344))
    assert selected(added,index=1)['editable']


def test_unbalanced_graphics_prevent_addition_instead_of_repairing_content():
    with fitz.open(stream=clipped_pdf('none'),filetype='pdf') as doc:
        xref=doc[0].get_contents()[0]
        doc.update_stream(xref,b'Q\n'+doc.xref_stream(xref))
        source=doc.tobytes()
    with pytest.raises(EditError,match='cierre Q sin apertura'):
        add_image_pdf(source,0,picture(),(250,280,346,344))
