from io import BytesIO
import hashlib
from pathlib import Path
import pytest
import pymupdf as fitz
from PIL import Image,ImageDraw
from pdfmodder.media import add_image_pdf,transform_image_pdf,delete_image_pdf,image_items
from pdfmodder.validation import related,trace_chars,assert_pixels
from pdfmodder.model import EditError

ROOT=Path(__file__).resolve().parents[1]

def picture(alpha=True):
    image=Image.new('RGBA' if alpha else 'RGB',(80,40),(0,0,0,0) if alpha else 'white')
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,39,39),fill=(255,0,0,128) if alpha else 'red')
    draw.rectangle((40,0,79,39),fill=(0,0,255,255) if alpha else 'blue')
    output=BytesIO()
    image.save(output,format='PNG')
    return output.getvalue()

def simple():
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.draw_rect((20,20,380,380),fill=(.1,.6,.3),color=None)
        page.insert_text((40,80),'Texto real vecino 10/09/2026')
        doc.new_page(width=300,height=300).insert_text((30,40),'Pagina intacta')
        return doc.tobytes()

def test_add_transparent_image_keeps_real_text_background_and_unedited_page():
    data=simple()
    output,report=add_image_pdf(data,0,picture(),(40,120,200,200))
    assert report['verified']
    with fitz.open(stream=output,filetype='pdf') as doc,fitz.open(stream=data,filetype='pdf') as old:
        assert trace_chars(doc[0])==trace_chars(old[0])
        assert related(doc[1])==related(old[1])
        assert doc[0].get_text().strip()=='Texto real vecino 10/09/2026'
        info=image_items(doc,0)[0]
        assert info['editable'] and info['rect']==pytest.approx((40,120,200,200),abs=.035)
        pix=doc[0].get_pixmap(alpha=False)
        blend=pix.pixel(60,150)
        assert 125<blend[0]<150 and 65<blend[1]<90 and 30<blend[2]<50
        assert pix.pixel(170,150)==(0,0,255)

def test_move_resize_reopen_and_delete_own_image_without_duplicate():
    source=simple()
    first,_=add_image_pdf(source,0,picture(),(40,120,200,200))
    second,_=transform_image_pdf(first,0,'0',(170,230,330,310),hashlib.sha256(first).hexdigest())
    with fitz.open(stream=second,filetype='pdf') as doc:
        assert len(doc[0].get_image_info())==1
        assert image_items(doc,0)[0]['rect']==pytest.approx((170,230,330,310),abs=.035)
    third,_=transform_image_pdf(second,0,'0',(170,230,250,270))
    deleted,_=delete_image_pdf(third,0,'0')
    with fitz.open(stream=deleted,filetype='pdf') as doc,fitz.open(stream=source,filetype='pdf') as old:
        assert not doc[0].get_image_info()
        assert related(doc[0])==related(old[0])
        assert doc[0].get_pixmap().samples==old[0].get_pixmap().samples

def test_shared_image_resource_and_content_stream_remain_intact_on_other_page():
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_image((30,30,110,70),stream=picture())
        image_stream=page.get_contents()[0]
        resources=doc.xref_get_key(page.xref,'Resources')[1]
        page2=doc.new_page(width=400,height=400)
        doc.xref_set_key(page2.xref,'Resources',resources)
        page2.set_contents(image_stream)
        source=doc.tobytes()
    output,_=transform_image_pdf(source,0,'0',(160,180,320,260))
    with fitz.open(stream=output,filetype='pdf') as doc:
        assert image_items(doc,0)[0]['rect']==pytest.approx((160,180,320,260))
        assert image_items(doc,1)[0]['rect']==pytest.approx((30,30,110,70))
    deleted,_=delete_image_pdf(output,0,'0')
    with fitz.open(stream=deleted,filetype='pdf') as doc:
        assert not doc[0].get_image_info()
        assert len(doc[1].get_image_info())==1

@pytest.mark.parametrize('rotation',[90,180,270])
def test_image_coordinates_rotated_offset_cropbox(rotation):
    with fitz.open() as doc:
        page=doc.new_page(width=640,height=880)
        page.set_cropbox(fitz.Rect(30,40,610,840))
        page.set_rotation(rotation)
        source=doc.tobytes()
    first,_=add_image_pdf(source,0,picture(),(50,80,210,160))
    second,_=transform_image_pdf(first,0,'0',(180,240,260,280))
    with fitz.open(stream=second,filetype='pdf') as doc:
        assert doc[0].rotation==rotation
        assert tuple(doc[0].cropbox)==(30,40,610,840)
        assert image_items(doc,0)[0]['rect']==pytest.approx((180,240,260,280),abs=.035)

def test_rotated_instance_moves_without_resetting_rotation_or_shared_neighbour():
    with fitz.open() as doc:
        page=doc.new_page()
        page.insert_text((30,40),'Vecino')
        image_xref=page.insert_image((50,70,130,110),stream=picture(),rotate=90)
        page.insert_image((220,70,300,110),xref=image_xref)
        # Rotation within the image differs from rotation of the whole page.
        page.clean_contents()
        source=doc.tobytes()
        items=image_items(doc,0)
        assert len(items)==2 and items[0]['editable']
        old_rect=items[0]['rect']
    destination=tuple(value+(50 if index%2==0 else 80) for index,value in enumerate(old_rect))
    output,report=transform_image_pdf(source,0,'0',destination)
    assert report['verified']
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        original=before[0].get_image_info(hashes=True,xrefs=True)
        moved=after[0].get_image_info(hashes=True,xrefs=True)
        assert len(moved)==2
        assert original[0]['xref']==original[1]['xref']
        assert moved[0]['xref']==moved[1]['xref']
        # The linear matrix retains the actual 90-degree rotation and scale.
        assert original[0]['transform'][0]==original[0]['transform'][3]==0
        assert abs(original[0]['transform'][1])>0 and abs(original[0]['transform'][2])>0
        assert moved[0]['transform'][:4]==pytest.approx(original[0]['transform'][:4])
        assert moved[0]['transform'][4:]==pytest.approx((original[0]['transform'][4]+50,original[0]['transform'][5]+80))
        assert moved[0]['bbox']==pytest.approx(destination)
        for key in ('bbox','transform','digest','width','height'):
            assert moved[1][key]==original[1][key]
        assert moved[0]['digest']==original[0]['digest']
        assert trace_chars(after[0])==trace_chars(before[0])
        assert before[0].get_pixmap(clip=fitz.Rect(old_rect)).samples==after[0].get_pixmap(clip=fitz.Rect(destination)).samples
        assert assert_pixels(before[0],after[0],[old_rect,destination])['pixels_above_8']==0

def test_image_remains_editable_after_text_redaction_merges_streams():
    from pdfmodder.engine import edit_pdf,extract_page
    from pdfmodder.model import EditRequest
    first,_=add_image_pdf(simple(),0,picture(),(40,120,200,200))
    with fitz.open(stream=first,filetype='pdf') as doc:
        model=extract_page(doc,0,first)
        start=''.join(g.text for g in model.glyphs).index('10/09/2026')
        ids=[g.id for g in model.glyphs[start:start+10]]
    edited,_=edit_pdf(first,EditRequest(0,ids,text='11/09/2026'))
    moved,_=transform_image_pdf(edited,0,'0',(160,220,320,300))
    with fitz.open(stream=moved,filetype='pdf') as doc:
        assert '11/09/2026' in doc[0].get_text()
        assert len(doc[0].get_image_info())==1
        assert image_items(doc,0)[0]['rect']==pytest.approx((160,220,320,300))

def test_image_bounds_stale_revision_and_encryption_rejected():
    data=simple()
    with pytest.raises(EditError,match='fuera'):
        add_image_pdf(data,0,picture(),(350,20,450,70))
    with pytest.raises(EditError,match='desactualizada'):
        add_image_pdf(data,0,picture(),(40,120,200,200),'old')
    with pytest.raises(EditError):
        add_image_pdf((ROOT/'examples/restricted.pdf').read_bytes(),0,picture(),(40,120,200,200))

def test_exif_orientation_normalized_before_embedding():
    image=Image.new('RGB',(20,10),'red')
    exif=Image.Exif()
    exif[274]=6
    buffer=BytesIO()
    image.save(buffer,format='JPEG',exif=exif)
    output,_=add_image_pdf(simple(),0,buffer.getvalue(),(40,120,90,220))
    with fitz.open(stream=output,filetype='pdf') as doc:
        item=image_items(doc,0)[0]
        assert (item['width_px'],item['height_px'])==(10,20)
