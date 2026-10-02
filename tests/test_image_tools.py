"""v0.8 image tools, generated artwork only; exact selected-instance checks."""
from io import BytesIO
import hashlib

from PIL import Image,ImageDraw
import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream
import pytest

from pdfmodder.media import edit_image_pdf,export_image_pdf,image_items,transform_image_pdf
from pdfmodder.model import EditError
from pdfmodder.validation import trace_chars


def image_bytes(alpha=True):
    image=Image.new('RGBA' if alpha else 'RGB',(40,20),'white')
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,19,19),fill=(220,30,60,128) if alpha else 'red')
    draw.rectangle((20,0,39,19),fill=(20,60,230,255) if alpha else 'blue')
    output=BytesIO()
    image.save(output,format='PNG')
    return output.getvalue()


def sample(*,alpha=True,shared=True,rotation=0,crop=False):
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.draw_rect((20,20,380,380),fill=(.3,.6,.2),color=None)
        page.insert_text((35,60),'TEXTO VECINO')
        if alpha:
            rgb,mask=BytesIO(),BytesIO()
            with Image.open(BytesIO(image_bytes())) as bitmap:
                bitmap.convert('RGB').save(rgb,format='PNG')
                bitmap.getchannel('A').save(mask,format='PNG')
            xref=page.insert_image((50,100,170,160),stream=rgb.getvalue(),mask=mask.getvalue())
        else:
            xref=page.insert_image((50,100,170,160),stream=image_bytes(False))
        page.insert_image((200,100,320,160),xref=xref)
        page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(35,180,150,195),'uri':'https://example.com/'})
        page.add_text_annot((200,190),'Nota que se conserva')
        resources=doc.xref_get_key(page.xref,'Resources')[1]
        contents=page.get_contents()
        if crop:
            page.set_cropbox(fitz.Rect(20,30,380,370))
        page.set_rotation(rotation)
        second=doc.new_page(width=400,height=400)
        if shared:
            doc.xref_set_key(second.xref,'Resources',resources)
            doc.xref_set_key(second.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in contents)+']')
        else:
            second.insert_text((35,60),'PAGINA CONTROL')
        return doc.tobytes()


def rgba(data):
    with Image.open(BytesIO(data)) as image:
        image=image.convert('RGBA')
        return image.size,image.tobytes()


def operators(data,page=0):
    reader=PdfReader(BytesIO(data),strict=True)
    return [(str(args),op) for args,op in ContentStream(reader.pages[page].get_contents(),reader).operations]


def test_export_transparent_resource_preserves_pixels_alpha_and_source():
    source=sample()
    digest=hashlib.sha256(source).hexdigest()
    asset=export_image_pdf(source,0,'0',digest)
    assert asset['ext']=='png' and asset['alpha']
    assert rgba(asset['image_bytes'])==rgba(image_bytes())
    assert rgba(asset['preview_png'])==rgba(image_bytes())
    assert hashlib.sha256(source).hexdigest()==digest


def test_export_jpeg_keeps_encoded_original_bytes():
    buffer=BytesIO()
    Image.new('RGB',(16,16),'orange').save(buffer,format='JPEG',quality=93)
    with fitz.open() as doc:
        doc.new_page().insert_image((20,20,80,80),stream=buffer.getvalue())
        source=doc.tobytes()
    asset=export_image_pdf(source,0,'0')
    assert asset['ext']=='jpg' and asset['image_bytes']==buffer.getvalue()
    assert asset['preview_png'].startswith(b'\x89PNG')


@pytest.mark.parametrize('operation',[{'crop':(0,0,.5,1)},{'rotation':90},{'rotation':180},{'rotation':270},{'replacement_bytes':image_bytes(False)},{'replacement_bytes':image_bytes()}])
def test_each_edit_changes_only_selected_instance_preserving_shared_page_and_stream(operation):
    source=sample()
    before_asset=export_image_pdf(source,0,'1')['image_bytes']
    output,report=edit_image_pdf(source,0,'0',**operation)
    assert report['verified'] and report['instance_only'] and report['original_box_preserved']
    with fitz.open(stream=source,filetype='pdf') as old,fitz.open(stream=output,filetype='pdf') as new:
        assert old[1].get_pixmap().samples==new[1].get_pixmap().samples
        assert trace_chars(old[0])==trace_chars(new[0])
        assert image_items(new,0)[0]['rect']==pytest.approx((50,100,170,160))
        assert image_items(new,0)[0]['editable']
        assert len(new[0].get_image_info())==2
    assert rgba(export_image_pdf(output,0,'1')['image_bytes'])==rgba(before_asset)
    assert rgba(export_image_pdf(output,1,'0')['image_bytes'])==rgba(before_asset)
    old_ops,new_ops=operators(source),operators(output)
    assert len(old_ops)==len(new_ops)
    assert [entry for entry in old_ops if entry[1]!=b'Do']==[entry for entry in new_ops if entry[1]!=b'Do']
    old_do=[entry for entry in old_ops if entry[1]==b'Do']
    new_do=[entry for entry in new_ops if entry[1]==b'Do']
    assert old_do[0]!=new_do[0] and old_do[1]==new_do[1]


def test_crop_then_rotate_pixels_order_and_followup_move():
    source=sample()
    output,report=edit_image_pdf(source,0,'0',crop=(0,0,.5,1),rotation=90)
    with Image.open(BytesIO(image_bytes())) as original:
        expected=original.crop((0,0,20,20)).transpose(Image.Transpose.ROTATE_270)
        asset=export_image_pdf(output,0,'0')
        assert rgba(asset['image_bytes'])==(expected.size,expected.tobytes())
    assert report['crop_pixels']==(0,0,20,20)
    moved,_=transform_image_pdf(output,0,'0',(50,220,170,280))
    assert rgba(export_image_pdf(moved,0,'0')['image_bytes'])==rgba(asset['image_bytes'])


@pytest.mark.parametrize('rotation',[90,180,270])
def test_crop_rotation_and_replacement_preserve_shifted_cropbox_and_rotated_page(rotation):
    source=sample(rotation=rotation,crop=True)
    output,report=edit_image_pdf(source,0,'1',replacement_bytes=image_bytes(False),crop=(.25,0,1,1),rotation=90)
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert doc[0].rotation==rotation
        assert tuple(doc[0].cropbox)==(20,30,380,370)
        assert image_items(doc,0)[1]['rect']==pytest.approx((180,70,300,130))
    assert report['image_size_px']==(20,30)


@pytest.mark.parametrize('crop',[(0,0,0,1),(-.1,0,1,1),(0,0,1.1,1),(0,0,float('nan'),1),(1,2,3),None])
def test_invalid_crop_and_stale_revision_leave_source_untouched(crop):
    source=sample()
    if crop is None:
        with pytest.raises(EditError,match='desactualizada'):
            edit_image_pdf(source,0,'0',revision='stale')
    else:
        with pytest.raises(EditError,match='recorte'):
            edit_image_pdf(source,0,'0',crop=crop)


def test_export_readonly_not_limited_to_transformable_images_and_respects_copy_permissions():
    with fitz.open() as doc:
        doc.new_page().insert_image((20,20,100,100),stream=image_bytes(),rotate=90)
        source=doc.tobytes()
        restricted=doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,user_pw='',owner_pw='owner',permissions=fitz.PDF_PERM_PRINT)
    assert export_image_pdf(source,0,'0')['width_px']==40
    with pytest.raises(EditError,match='permisos'):
        export_image_pdf(restricted,0,'0')


def test_inherited_resources_are_materialized_only_on_selected_page():
    with fitz.open(stream=sample(),filetype='pdf') as doc:
        parent=int(doc.xref_get_key(doc[0].xref,'Parent')[1].split()[0])
        resources=doc.xref_get_key(doc[0].xref,'Resources')[1]
        doc.xref_set_key(parent,'Resources',resources)
        doc.xref_set_key(doc[0].xref,'Resources','null')
        source=doc.tobytes()
    output,_=edit_image_pdf(source,0,'0',rotation=90)
    with fitz.open(stream=source,filetype='pdf') as old,fitz.open(stream=output,filetype='pdf') as new:
        assert old[1].get_pixmap().samples==new[1].get_pixmap().samples


def test_visual_crop_dialog_drag_numbers_rotation_and_cancel(qtbot):
    from PySide6.QtCore import Qt,QPoint
    from pdfmodder.image_editor import ImageEditorDialog
    dialog=ImageEditorDialog(image_bytes())
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.operation()=={'replacement_bytes':None,'crop':(0,0,1,1),'rotation':0,
                               'fit_mode':'fit','flip_horizontal':False,'flip_vertical':False}
    r=dialog.canvas.image_rect()
    start=QPoint(round(r.left()+r.width()*.1),round(r.top()+r.height()*.1))
    end=QPoint(round(r.left()+r.width()*.6),round(r.top()+r.height()*.8))
    qtbot.mousePress(dialog.canvas,Qt.LeftButton,pos=start)
    qtbot.mouseMove(dialog.canvas,pos=end)
    qtbot.mouseRelease(dialog.canvas,Qt.LeftButton,pos=end)
    assert dialog.operation()['crop']==pytest.approx((.1,.1,.6,.8),abs=.01)
    dialog.crop_spins[0].setValue(0)
    dialog.crop_spins[1].setValue(0)
    dialog.crop_spins[2].setValue(50)
    dialog.crop_spins[3].setValue(100)
    dialog.rotation_box.setCurrentIndex(1)
    operation=dialog.operation()
    assert operation=={'replacement_bytes':None,'crop':(0,0,.5,1),'rotation':90,
                       'fit_mode':'fit','flip_horizontal':False,'flip_vertical':False}
    output,report=edit_image_pdf(sample(),0,'0',**operation)
    asset=export_image_pdf(output,0,'0')
    assert report['verified'] and report['pixels_preserved']
    assert (asset['width_px'],asset['height_px'])==(40,20)
    assert rgba(asset['image_bytes'])==rgba(image_bytes())
    qtbot.keyClick(dialog,Qt.Key_Escape)
    assert dialog.result()==0


def test_image_dialog_import_reset_invalid_dimensions_and_exif(qtbot):
    from pdfmodder.image_editor import ImageEditorDialog
    dialog=ImageEditorDialog(image_bytes())
    qtbot.addWidget(dialog)
    dialog.crop_spins[2].setValue(0)
    assert not dialog.preview_button.isEnabled()
    dialog.rotation_box.setCurrentIndex(1)
    assert not dialog.preview_button.isEnabled()
    dialog.reset_button.click()
    assert dialog.preview_button.isEnabled()
    picture=Image.new('RGB',(30,10),'orange')
    exif=Image.Exif()
    exif[274]=6
    output=BytesIO()
    picture.save(output,format='JPEG',exif=exif)
    dialog.set_replacement(output.getvalue())
    assert (dialog._image.width(),dialog._image.height())==(10,30)
    assert dialog.operation()['replacement_bytes']==output.getvalue()
    assert dialog.operation()['crop']==(0,0,1,1)
    previous=dialog.operation()
    with pytest.raises(ValueError,match='formato'):
        dialog.set_replacement(b'not an image')
    assert dialog.operation()==previous


def test_rectangular_clip_parent_alpha_and_crop_rotation_remain_intact():
    # Keep text and vector clipping operators, and another shared instance.
    with fitz.open(stream=sample(),filetype='pdf') as doc:
        page=doc[0]
        contents=page.get_contents()
        image_stream=contents[2]
        resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
        gs=doc.get_new_xref()
        doc.update_object(gs,'<</ca .5>>')
        doc.xref_set_key(resources,'ExtGState',f'<</Alpha {gs} 0 R>>')
        old=doc.xref_stream(image_stream)
        doc.update_stream(image_stream,b'q 40 220 140 90 re W n /Alpha gs\n'+old+b'Q\n')
        source=doc.tobytes()
    output,report=edit_image_pdf(source,0,'0',crop=(0,0,.5,1),rotation=270)
    assert report['verified']
    assert [op for op in operators(source) if op[1]!=b'Do']==[op for op in operators(output) if op[1]!=b'Do']
    reader=PdfReader(BytesIO(output),strict=True)
    assert float(reader.pages[0]['/Resources']['/ExtGState']['/Alpha']['/ca'])==.5
