"""v0.9 image frames: actual PDF matrices/clips, no pixel resampling."""
from io import BytesIO
import math

from PIL import Image
import pymupdf as fitz
import pytest

from pdfmodder.media import (edit_image_pdf,export_image_pdf,image_items,
                            transform_image_pdf,delete_image_pdf)
from pdfmodder.model import EditError
from test_image_tools import sample,image_bytes,rgba


@pytest.mark.parametrize('operation',[
    {'flip_horizontal':True},{'flip_vertical':True},
    {'rotation':33.25},{'rotation':-22.5,'flip_horizontal':True},
    {'crop':(.1,.2,.8,.9),'rotation':17,'fit_mode':'fill'},
    {'replacement_bytes':image_bytes(False),'rotation':71,'fit_mode':'fit'},
])
def test_frame_changes_one_shared_instance_without_resampling_and_reopens(tmp_path,operation):
    original=sample()
    options={'fit_mode':'fit',**operation}
    output,report=edit_image_pdf(original,0,'0',**options)
    assert report['verified'] and report['pixels_preserved'] and report['instance_only']
    result=tmp_path/'transformed.pdf'
    result.write_bytes(output)
    with fitz.open(stream=original,filetype='pdf') as before,fitz.open(result) as after:
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        assert before[0].get_text()==after[0].get_text()
        items=image_items(after,0)
        assert items[0]['editable'] and items[0]['framed']
        assert items[0]['rect']==pytest.approx((50,100,170,160),abs=.001)
        assert items[1]['rect']==pytest.approx((200,100,320,160),abs=.001)
        assert len(after[0].get_image_info())==2
        # The selected image is still an image; no page-sized render replaces it.
        assert after[0].get_image_info()[0]['width']==40
    expected=operation.get('replacement_bytes',image_bytes())
    assert rgba(export_image_pdf(output,0,'0')['image_bytes'])==rgba(expected)
    assert rgba(export_image_pdf(output,0,'1')['image_bytes'])==rgba(image_bytes())


def test_fit_vs_fill_have_equal_axis_scale_and_only_fill_clips():
    picture=BytesIO()
    Image.new('RGB',(40,40),'red').save(picture,'PNG')
    for mode,bbox in [('fit',(80,100,140,160)),('fill',(50,70,170,190))]:
        result,_=edit_image_pdf(sample(alpha=False),0,'0',replacement_bytes=picture.getvalue(),fit_mode=mode)
        with fitz.open(stream=result,filetype='pdf') as pdf:
            item=image_items(pdf,0)[0]
            assert item['asset_rect']==pytest.approx(bbox,abs=.001)
            matrix=item['matrix_pdf']
            assert abs(matrix[0])==pytest.approx(abs(matrix[3]))
            assert item['rect']==pytest.approx((50,100,170,160),abs=.001)
            pix=pdf[0].get_pixmap()
            assert pix.pixel(55,105)[:3]==((255,0,0) if mode=='fill' else (76,153,51))


def test_fill_free_rotation_covers_every_frame_corner():
    picture=BytesIO()
    Image.new('RGB',(80,40),'red').save(picture,'PNG')
    result,_=edit_image_pdf(sample(alpha=False),0,'0',replacement_bytes=picture.getvalue(),
                           rotation=31,fit_mode='fill')
    with fitz.open(stream=result,filetype='pdf') as pdf:
        pix=pdf[0].get_pixmap()
        for x,y in ((52,102),(167,102),(52,157),(167,157),(110,130)):
            assert pix.pixel(x,y)[:3]==(255,0,0)


def test_horizontal_and_vertical_flips_really_change_pixel_orientation():
    picture=Image.new('RGB',(40,20),'blue')
    for y in range(10):
        for x in range(20):
            picture.putpixel((x,y),(255,0,0))
    data=BytesIO();picture.save(data,'PNG')
    for options,location in [({},(55,105)),({'flip_horizontal':True},(165,105)),
                             ({'flip_vertical':True},(55,155))]:
        result,_=edit_image_pdf(sample(alpha=False),0,'0',replacement_bytes=data.getvalue(),fit_mode='fit',**options)
        with fitz.open(stream=result,filetype='pdf') as pdf:
            assert pdf[0].get_pixmap().pixel(*location)[:3]==(255,0,0)


def test_crop_keeps_source_pixels_and_can_be_restored_after_save():
    original=sample(alpha=False)
    result,_=edit_image_pdf(original,0,'0',crop=(.5,0,1,1),fit_mode='fill')
    with fitz.open(stream=result,filetype='pdf') as pdf:
        assert pdf[0].get_pixmap().pixel(55,110)[:3]==(0,0,255)
    assert rgba(export_image_pdf(result,0,'0')['image_bytes'])==rgba(image_bytes(False))
    restored,_=edit_image_pdf(result,0,'0',crop=(0,0,1,1),fit_mode='fit')
    with fitz.open(stream=original,filetype='pdf') as before,fitz.open(stream=restored,filetype='pdf') as after:
        assert before[0].get_pixmap().samples==after[0].get_pixmap().samples


@pytest.mark.parametrize('mode',['fit','fill','stretch'])
def test_reopen_editor_recovers_crop_and_equivalent_transform(mode):
    source,_=edit_image_pdf(sample(),0,'0',crop=(.2,.1,.9,.8),rotation=33.25,
                            flip_horizontal=True,fit_mode=mode)
    exported=export_image_pdf(source,0,'0')
    assert exported['image_operation'] is not None
    repeated,_=edit_image_pdf(source,0,'0',**exported['image_operation'])
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=repeated,filetype='pdf') as after:
        assert before[0].get_pixmap().samples==after[0].get_pixmap().samples


def test_move_resize_delete_preserve_free_rotation_flip_and_shared_asset():
    source,_=edit_image_pdf(sample(),0,'0',rotation=27,flip_horizontal=True,fit_mode='fit')
    with fitz.open(stream=source,filetype='pdf') as doc:
        before=image_items(doc,0)[0]['matrix_pdf']
    moved,_=transform_image_pdf(source,0,'0',(55,230,175,290))
    resized,_=transform_image_pdf(moved,0,'0',(55,230,115,260))
    with fitz.open(stream=resized,filetype='pdf') as doc:
        item=image_items(doc,0)[0]
        assert item['editable'] and item['rect']==pytest.approx((55,230,115,260))
        assert item['matrix_pdf'][:4]==pytest.approx([v*.5 for v in before[:4]])
    deleted,report=delete_image_pdf(resized,0,'0')
    assert report['verified']
    with fitz.open(stream=deleted,filetype='pdf') as doc:
        assert len(doc[0].get_image_info())==1
        assert len(doc[1].get_image_info())==2


@pytest.mark.parametrize('rotation',[90,180,270])
def test_shifted_cropbox_and_page_rotation_keep_frame_geometry(rotation):
    data,_=edit_image_pdf(sample(rotation=rotation,crop=True),0,'0',rotation=37,fit_mode='fit')
    with fitz.open(stream=data,filetype='pdf') as doc:
        assert doc[0].rotation==rotation
        assert image_items(doc,0)[0]['rect']==pytest.approx((30,70,150,130),abs=.001)
    data,_=transform_image_pdf(data,0,'0',(40,200,160,260))
    with fitz.open(stream=data,filetype='pdf') as doc:
        assert image_items(doc,0)[0]['rect']==pytest.approx((40,200,160,260),abs=.001)


@pytest.mark.parametrize('options',[{'rotation':float('nan')},{'rotation':float('inf')},
                                  {'crop':(0,0,0,1)},{'fit_mode':'automatic'}])
def test_invalid_geometry_is_rejected(options):
    with pytest.raises(EditError):
        edit_image_pdf(sample(),0,'0',**{'fit_mode':'fit',**options})


def test_dialog_free_angle_flip_fit_and_reset(qtbot):
    from pdfmodder.image_editor import ImageEditorDialog
    dialog=ImageEditorDialog(image_bytes(),frame_rect=(0,0,100,100))
    qtbot.addWidget(dialog)
    assert dialog.operation()['fit_mode']=='fit'
    dialog.rotation_spin.setValue(33.25)
    dialog.flip_horizontal.setChecked(True)
    dialog.fit_box.setCurrentIndex(dialog.fit_box.findData('fill'))
    dialog.crop_spins[2].setValue(75)
    operation=dialog.operation()
    assert operation['rotation']==33.25 and operation['flip_horizontal']
    assert operation['fit_mode']=='fill' and operation['crop']==(0,0,.75,1)
    result,report=edit_image_pdf(sample(),0,'0',**operation)
    assert report['verified']
    assert rgba(export_image_pdf(result,0,'0')['image_bytes'])==rgba(image_bytes())
    dialog.reset_button.click()
    assert dialog.operation()['rotation']==0 and not dialog.operation()['flip_horizontal']
    assert dialog.operation()['crop']==(0,0,1,1)
