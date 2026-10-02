from io import BytesIO
import pymupdf as fitz
from PIL import Image
import pytest
from pdfmodder.objects import object_info,group_pdf,transform_objects_pdf
from pdfmodder.model import EditError


def document():
    image=BytesIO();Image.new('RGB',(20,10),'blue').save(image,format='PNG')
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_text((40,60),'PRIMERO',fontsize=12)
        page.insert_text((80,110),'SEGUNDO',fontsize=12)
        page.insert_image((160,150,220,180),stream=image.getvalue())
        page=doc.new_page(width=400,height=400);page.insert_text((40,60),'CONTROL')
        return doc.tobytes()


def test_group_persists_move_and_ungroup():
    data=document();info=object_info(data,0)
    output,_=group_pdf(data,0,[info['items'][0],info['items'][2]],'Mi grupo',revision=info['revision'])
    grouped=object_info(output,0);group=grouped['groups'][0]
    assert group['valid'] and len(group['items'])==2
    moved,report=transform_objects_pdf(output,0,group['items'],'move',dx=5,dy=7)
    after=object_info(moved,0)
    assert after['groups'][0]['valid']
    assert after['groups'][0]['rect'][0]==pytest.approx(group['rect'][0]+5,abs=.035)
    with fitz.open(stream=moved,filetype='pdf') as doc:
        assert doc[0].get_text().count('PRIMERO')==1
        assert doc[1].get_text().strip()=='CONTROL'
    ungrouped,_=group_pdf(moved,0,group_id=group['id'])
    assert not object_info(ungrouped,0)['groups']


def test_align_mixed_without_changing_size():
    data=document();items=object_info(data,0)['items']
    out,_=transform_objects_pdf(data,0,items,'align_left')
    after=object_info(out,0)['items']
    assert all(i['rect'][0]==pytest.approx(40,abs=.035) for i in after)
    with fitz.open(stream=out,filetype='pdf') as doc:
        assert all(s['size']==12 for b in doc[0].get_text('dict')['blocks'] if b['type']==0 for l in b['lines'] for s in l['spans'])


def test_split_and_bad_batch_are_atomic():
    data=document();item=object_info(data,0)['items'][0]
    split,_=group_pdf(data,0,[item],name='Celda',split_at=3)
    info=object_info(split,0)
    assert [len(g['items'][0]['ids']) for g in info['groups']]==[3,4]
    with pytest.raises(EditError):transform_objects_pdf(data,0,[item],'move',dx=1000)
    assert object_info(data,0)['items'][0]['rect']==item['rect']


def test_order_text_and_image_keeps_searchable_content():
    data=document();info=object_info(data,0)
    out,_=transform_objects_pdf(data,0,[info['items'][0]],'front')
    with fitz.open(stream=out,filetype='pdf') as doc:
        assert doc[0].get_text().count('PRIMERO')==1
        assert len(doc[0].get_image_info())==1


def overlapping_images(*,shared_page=False):
    with fitz.open() as doc:
        page=doc.new_page(width=300,height=300)
        page.insert_text((20,25),'VECINO INTACTO',fontsize=10)
        for color,rect in [('red',(50,60,150,160)),('blue',(100,100,200,200))]:
            image=BytesIO();Image.new('RGB',(20,20),color).save(image,format='PNG')
            page.insert_image(rect,stream=image.getvalue())
        page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(20,220,100,230),'uri':'https://example.com/'})
        if shared_page:
            contents=page.get_contents();resources=doc.xref_get_key(page.xref,'Resources')[1]
            second=doc.new_page(width=300,height=300)
            doc.xref_set_key(second.xref,'Resources',resources)
            doc.xref_set_key(second.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in contents)+']')
        return doc.tobytes()


def test_image_front_and_back_change_overlap_without_moving_or_replacing_content():
    data=overlapping_images(shared_page=True)
    info=object_info(data,0)
    red=next(i for i in info['items'] if i.get('image_id')=='0')
    front,report=transform_objects_pdf(data,0,[red],'front')
    assert report['verified'] and report['operators_preserved']
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=front,filetype='pdf') as after:
        assert before[0].get_pixmap().pixel(125,125)==(0,0,255)
        assert after[0].get_pixmap().pixel(125,125)==(255,0,0)
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples
        assert before[0].get_text('words')==after[0].get_text('words')
        assert before[0].get_links()[0]['uri']==after[0].get_links()[0]['uri']
    # After reordering the selected red instance has a different extraction ID.
    red=next(i for i in object_info(front,0)['items'] if i['kind']=='image' and i['rect'][0]==50)
    back,_=transform_objects_pdf(front,0,[red],'back')
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=back,filetype='pdf') as after:
        assert before[0].get_pixmap().samples==after[0].get_pixmap().samples


def test_group_image_identity_survives_reorder_and_three_moves(tmp_path):
    data=overlapping_images()
    red=next(i for i in object_info(data,0)['items'] if i.get('image_id')=='0')
    data,_=group_pdf(data,0,[red],'Foto roja')
    data,_=transform_objects_pdf(data,0,[red],'front')
    for _ in range(3):
        group=object_info(data,0)['groups'][0]
        assert group['valid']
        data,_=transform_objects_pdf(data,0,group['items'],'move',dx=5,dy=3)
    saved=tmp_path/'grupo-reabierto.pdf';saved.write_bytes(data)
    group=object_info(saved.read_bytes(),0)['groups'][0]
    assert group['valid'] and group['rect']==pytest.approx((65,69,165,169),abs=.035)


def test_partial_member_move_updates_whole_saved_group_and_neighbors_stay_fixed():
    source=document();first=object_info(source,0)['items'][0]
    data,_=group_pdf(source,0,[first],'Palabra completa')
    fragment={'kind':'text','ids':first['ids'][:2]}
    data,_=transform_objects_pdf(data,0,[fragment],'move',dx=6,dy=4)
    assert object_info(data,0)['groups'][0]['valid']
    for _ in range(3):
        group=object_info(data,0)['groups'][0]
        data,_=transform_objects_pdf(data,0,group['items'],'move',dx=1,dy=2)
    group=object_info(data,0)['groups'][0]
    assert group['valid']
    from pdfmodder.engine import extract_page
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=data,filetype='pdf') as after:
        old=extract_page(before,0);new=extract_page(after,0)
        for a,b in zip(old.glyphs,new.glyphs):
            delta=(9,10) if a.id in fragment['ids'] else (3,6) if a.id in first['ids'] else (0,0)
            assert b.origin==pytest.approx((a.origin[0]+delta[0],a.origin[1]+delta[1]),abs=.035)
        assert before[1].get_pixmap().samples==after[1].get_pixmap().samples


def test_batch_occurrences_do_not_confuse_old_and_intermediate_positions():
    from pdfmodder.engine import extract_page
    image=BytesIO();Image.new('RGB',(10,10),'blue').save(image,format='PNG')
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=400)
        page.insert_text((40,50),'A');page.insert_text((90,50),'A')
        xref=page.insert_image((40,90,60,110),stream=image.getvalue())
        page.insert_image((90,90,110,110),xref=xref)
        source=doc.tobytes()
    items=[{'kind':'text','ids':[0]},{'kind':'text','ids':[1]},
           {'kind':'image','image_id':'0'},{'kind':'image','image_id':'1'}]
    result,_=transform_objects_pdf(source,0,items,'move',dx=50)
    with fitz.open(stream=result,filetype='pdf') as doc:
        assert [g.origin[0] for g in extract_page(doc,0).glyphs]==pytest.approx([90,140])
        assert [im['bbox'][0] for im in doc[0].get_image_info()]==pytest.approx([90,140])


def test_ordering_partial_text_cannot_move_neighbor_from_shared_scope():
    source=document();line=object_info(source,0)['items'][0]
    with pytest.raises(EditError,match='no seleccionados'):
        transform_objects_pdf(source,0,[{'kind':'text','ids':line['ids'][:3]}],'front')
    with fitz.open(stream=source,filetype='pdf') as doc:
        assert doc[0].get_text('words')[0][0]==40


def test_ordering_text_scope_with_vector_or_open_path_is_rejected():
    from pdfmodder.clipping import _serialize
    from pdfmodder.media import _ops
    from pypdf.generic import FloatObject
    for paint in (True,False):
        with fitz.open(stream=document(),filetype='pdf') as doc:
            page=doc[0];stream=page.get_contents()[0]
            ops=_ops(doc.xref_stream(stream)).operations
            path=[([FloatObject(v) for v in (10,10,10,10)],b're')]
            if paint:path.append(([],b'f'))
            ops[-1:-1]=path
            doc.update_stream(stream,_serialize(ops));source=doc.tobytes()
        line=object_info(source,0)['items'][0]
        with pytest.raises(EditError,match='vectores|trazado abierto'):
            transform_objects_pdf(source,0,[line],'front')


def test_failed_second_member_leaves_every_original_object_and_group_untouched():
    data=document();info=object_info(data,0)
    # First text would move successfully; image would leave page after that.
    data,_=group_pdf(data,0,[info['items'][0],info['items'][2]],'Transacción')
    before=object_info(data,0)
    with pytest.raises(EditError):
        transform_objects_pdf(data,0,before['groups'][0]['items'],'move',dx=190)
    assert object_info(data,0)==before


def test_duplicate_group_members_are_rejected():
    data=document();item=object_info(data,0)['items'][0]
    with pytest.raises(EditError,match='dos miembros'):
        group_pdf(data,0,[item,item])
