"""Imágenes reales: inserción y transformación de una instancia aislada.

Los streams q/cm/Do/Q se interpretan con pypdf. Nunca se reemplaza el objeto
imagen compartido ni se buscan cadenas dentro del binario PDF.
"""
from io import BytesIO
import hashlib
import math
import warnings
import pymupdf as fitz
from PIL import Image,ImageOps
from pypdf import PdfReader
from pypdf.generic import ContentStream,DecodedStreamObject,FloatObject,NameObject
from .model import EditError
from .validation import (document_issues,related,_canonical,
                         trace_chars,assert_characters,assert_pixels)
from .engine import full_write


def _ops(data):
    stream=DecodedStreamObject()
    stream.set_data(data)
    return ContentStream(stream,None)


def _rect(page,rect):
    if len(rect)!=4 or not all(math.isfinite(float(v)) for v in rect):
        raise EditError('La posición y las dimensiones de imagen deben ser finitas.')
    result=fitz.Rect(rect)
    bounds=fitz.Rect(0,0,page.cropbox.width,page.cropbox.height)
    if result.width<.1 or result.height<.1 or not bounds.contains(result):
        raise EditError('La imagen queda fuera de la página o su tamaño es demasiado pequeño.')
    return result


def _safe(data,page,revision,*,adding=False,transform_tagged=False):
    from .tagged import require_untagged
    if not adding and not transform_tagged:
        require_untagged(data,'Modificar imágenes')
    if revision and hashlib.sha256(data).hexdigest()!=revision:
        raise EditError('La selección está desactualizada. Selecciona la imagen de nuevo.')
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc)
        if issues:
            raise EditError('\n'.join(issues))
        if not 0<=page<doc.page_count:
            raise EditError('Página inexistente.')
        # Image placement does not reconstruct existing text. A clipping path
        # elsewhere is therefore not a document-wide incompatibility. Check
        # balanced graphics/text/marked scopes, then analyse the chosen instance.
        _graphics_scan(doc,page,[])


def _image_infos(page):
    return page.get_image_info(hashes=True,xrefs=True)


def _graphics_state(doc,page,name):
    # Read resource keys through MuPDF's object API. ContentStream's standalone
    # parser has no reader for indirect references inside resource dictionaries.
    owner=page.xref
    seen=set()
    while doc.xref_get_key(owner,'Resources')[0]=='null':
        kind,parent=doc.xref_get_key(owner,'Parent')
        if kind!='xref' or owner in seen:
            raise EditError('No se pueden resolver los recursos gráficos heredados de la página.')
        seen.add(owner)
        owner=int(parent.split()[0])
    prefix='Resources/ExtGState/'+str(name).lstrip('/')
    if doc.xref_get_key(owner,prefix)[0] not in ('dict','xref'):
        raise EditError('No se puede resolver un estado gráfico de la página para aislar imágenes.')
    result={}
    for key in ('BM','SMask','OP','op','TR','TR2','BG','BG2','UCR','UCR2'):
        kind,value=doc.xref_get_key(owner,prefix+'/'+key)
        if kind!='null':
            result['/'+key]=(value=='true') if kind=='bool' else value
    return result


def _gs_issue(values):
    truth=lambda value: bool(getattr(value,'value',value))
    if values.get('/BM','/Normal') not in ('/Normal','/Compatible') or values.get('/SMask','/None')!='/None':
        return 'La imagen hereda mezcla de color o una máscara externa que no se puede trasladar con garantías.'
    if truth(values.get('/OP',False)) or truth(values.get('/op',False)):
        return 'La imagen hereda sobreimpresión; no se admite transformar esta instancia.'
    if any(key in values and values[key] not in ('/Identity','/Default') for key in ('/TR','/TR2','/BG','/BG2','/UCR','/UCR2')):
        return 'La imagen hereda funciones especiales de color no admitidas para su transformación.'
    return ''


def _graphics_scan(doc,page_number,infos):
    """Track inherited CTM/clip/state while leaving every original operator intact.

    A transformable instance is an isolated q/cm/Do/Q sequence. Its ancestors may
    scale/translate it and apply a known rectangular clip, provided the complete
    source and requested destination stay inside that clip. Unknown clips are
    local incompatibilities, not a reason to reject independently added images.
    """
    page=doc[page_number]
    result=[{'id':str(i),'rect':tuple(info['bbox']),'xref':info.get('xref',0),
             'width_px':info['width'],'height_px':info['height'],'editable':False,
             'reason':'Esta instancia no tiene un ámbito aislado q/cm/Do/Q; puede estar dentro de un formulario o una transformación compleja.'}
            for i,info in enumerate(infos)]
    resources={row[7]:row[0] for row in page.get_images(full=True) if not row[9]}
    rotation=page.rotation
    try:
        page.set_rotation(0)
        page_matrix=page.transformation_matrix
    finally:
        page.set_rotation(rotation)
    used=set()
    stack=[]
    ctm=fitz.Matrix(1,0,0,1,0,0)
    clip=None
    clip_unknown=False
    graphics={}
    marked=0
    text_open=False
    render_mode=0
    text_clips=False
    path_kind=None
    path_rect=None
    pending_clip=False
    for position,xref in enumerate(page.get_contents()):
        ops=_ops(doc.xref_stream(xref)).operations
        for offset,(operands,operator) in enumerate(ops):
            simple=[op for _,op in ops[offset:offset+4]]==[b'q',b'cm',b'Do',b'Q']
            # v0.9 placements have an outer frame and an optional source crop.
            # Both are graphics clips: the underlying image pixels stay intact.
            framed=[op for _,op in ops[offset:offset+10]]==[b'q',b're',b'W',b'n',b'cm',b're',b'W',b'n',b'Do',b'Q']
            isolated=simple or framed
            if isolated:
                matrix_index=offset+(4 if framed else 1)
                do_index=offset+(8 if framed else 2)
                values=[float(value) for value in ops[matrix_index][0]]
                if len(values)!=6 or not all(math.isfinite(v) for v in values):
                    raise EditError('La matriz de colocación de una imagen no es válida.')
                name=str(ops[do_index][0][0]).lstrip('/')
                total=fitz.Matrix(*values)*ctm
                bounds=fitz.Rect(0,0,1,1)*total
                frame=None
                if framed:
                    x,y,w,h=map(float,ops[offset+1][0])
                    frame=fitz.Rect(x,y,x+w,y+h)*ctm
                bbox=tuple(bounds*page_matrix)
                target=next((i for i,info in enumerate(infos) if i not in used and info.get('xref')==resources.get(name)
                             and all(abs(a-b)<.035 for a,b in zip(info['bbox'],bbox))),None)
                if target is not None:
                    used.add(target)
                    reason=_gs_issue(graphics)
                    if clip_unknown:
                        reason='La imagen hereda un recorte no rectangular o de texto; esta instancia no puede aislarse con garantías.'
                    elif clip is not None and not (clip+(-.01,-.01,.01,.01)).contains(frame if framed else bounds):
                        reason='La imagen original está recortada; moverla o cambiar su tamaño podría revelar contenido oculto.'
                    elif abs(total.a*total.d-total.b*total.c)<1e-9:
                        reason='La imagen tiene una transformación no invertible.'
                    inverse=fitz.Matrix(ctm)
                    if inverse.invert():
                        reason='La imagen hereda una matriz no invertible.'
                    geometry_reason=reason
                    if marked:
                        reason='La imagen pertenece a contenido marcado o a una capa; no se transforma su semántica.'
                    result[target].update(editable=not reason,reason=reason,stream_position=position,
                                          stream_xref=xref,operator_index=offset,
                                          operator_count=10 if framed else 4,matrix_index=matrix_index,do_index=do_index,
                                          matrix_pdf=tuple(total),asset_rect=bbox,framed=framed,
                                          parent_matrix=tuple(ctm),clip_rect_pdf=tuple(clip) if clip is not None else None,
                                          marked=bool(marked),geometry_reason=geometry_reason)
                    if framed:
                        result[target]['rect']=tuple(frame*page_matrix)
                        x,y,w,h=map(float,ops[offset+5][0])
                        source_crop=(x,1-y-h,x+w,1-y)
                        width,height=infos[target]['width'],infos[target]['height']
                        reflected=total.a*total.d-total.b*total.c<0
                        angle=math.degrees(math.atan2(total.c/(height*(-1 if reflected else 1)),total.a/width))%360
                        for mode in ('fit','fill','stretch'):
                            candidate=_frame_matrix(frame,width,height,source_crop,angle,False,reflected,mode)
                            if max(abs(a-b) for a,b in zip(candidate,total))<.04:
                                result[target]['image_operation']={'crop':source_crop,'rotation':angle,
                                    'fit_mode':mode,'flip_horizontal':False,'flip_vertical':reflected}
                                break
            if operator==b'q':
                stack.append((ctm,clip,clip_unknown,dict(graphics),render_mode))
            elif operator==b'Q':
                if not stack:
                    raise EditError('La página tiene un cierre Q sin apertura; no se pueden aislar imágenes.')
                ctm,clip,clip_unknown,graphics,render_mode=stack.pop()
            elif operator==b'cm':
                values=[float(v) for v in operands]
                if len(values)!=6 or not all(math.isfinite(v) for v in values):
                    raise EditError('La página contiene una matriz gráfica no válida.')
                ctm=fitz.Matrix(*values)*ctm
            elif operator==b'gs':
                graphics.update(_graphics_state(doc,page,operands[0]))
            elif operator in (b'BDC',b'BMC'):
                marked+=1
            elif operator==b'EMC':
                marked-=1
                if marked<0:
                    raise EditError('El contenido marcado tiene un cierre sin apertura; no se añaden imágenes.')
            elif operator==b'BT':
                if text_open:
                    raise EditError('La página contiene objetos de texto anidados no válidos.')
                text_open=True
                text_clips=False
            elif operator==b'Tr':
                render_mode=int(operands[0])
            elif operator in (b'Tj',b'TJ',b"'",b'"') and render_mode>=4:
                text_clips=True
            elif operator==b'ET':
                if not text_open:
                    raise EditError('La página contiene un cierre de texto sin apertura.')
                text_open=False
                if text_clips:
                    clip_unknown=True
            elif operator==b're':
                x,y,w,h=map(float,operands)
                if path_kind is None and ctm.is_rectilinear:
                    path_kind='rectangle'
                    path_rect=fitz.Rect(min(x,x+w),min(y,y+h),max(x,x+w),max(y,y+h))*ctm
                else:
                    path_kind='other'
            elif operator==b'm':
                path_kind='point' if path_kind is None else 'other'
            elif operator in (b'l',b'c',b'v',b'y',b'h'):
                path_kind='other'
            elif operator in (b'W',b'W*'):
                pending_clip=True
            elif operator in (b'n',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*'):
                if pending_clip:
                    if path_kind in (None,'point'):
                        clip=fitz.Rect(0,0,0,0)
                    elif path_kind=='rectangle':
                        clip=fitz.Rect(path_rect) if clip is None else clip & path_rect
                    else:
                        clip_unknown=True
                path_kind=path_rect=None
                pending_clip=False
    if stack or marked or text_open or pending_clip:
        raise EditError('La página deja un estado gráfico, de texto o marcado abierto; no se pueden aislar imágenes.')
    return result


def image_items(doc,page_number):
    try:
        infos=_image_infos(doc[page_number])
    except Exception:
        return []
    try:
        items=_graphics_scan(doc,page_number,infos)
        candidates=[item for item in items if item.get('marked') and not item.get('geometry_reason')]
        if candidates and doc.xref_get_key(doc.pdf_catalog(),'StructTreeRoot')[0]!='null':
            from .tagged import analyze
            from .tagged_image_v160 import TaggedImageTransform
            data=doc.tobytes()
            structure=analyze(data)
            for item in candidates:
                try:
                    TaggedImageTransform(data,page_number,item,structure=structure)
                    item.update(editable=True,reason='',tagged_geometry=True)
                except EditError as exc:
                    item.update(editable=False,reason=str(exc))
        return items
    except Exception as exc:
        reason=str(exc) if isinstance(exc,EditError) else 'No se pudo interpretar de forma inequívoca el ámbito de esta imagen.'
        return [{'id':str(i),'rect':tuple(info['bbox']),'xref':info.get('xref',0),
                 'width_px':info['width'],'height_px':info['height'],'editable':False,'reason':reason}
                for i,info in enumerate(infos)]


def _isolate_existing_content(doc,page):
    """Protect old state with q/Q so an addition starts in default page space."""
    contents=page.get_contents()
    if not contents:
        return
    start=doc.get_new_xref()
    doc.update_object(start,'<<>>')
    doc.update_stream(start,b'q\n')
    end=doc.get_new_xref()
    doc.update_object(end,'<<>>')
    # Current paths are not part of graphics state. An unpainted trailing path
    # has no original visible effect; end it before restoring the saved state.
    doc.update_stream(end,b'n\nQ\n')
    doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{i} 0 R' for i in [start,*contents,end])+']')


def _normalized_image(data):
    if not data or len(data)>50*1024*1024:
        raise EditError('La imagen está vacía o supera el límite de 50 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if getattr(source,'n_frames',1)>1:
                    raise EditError('Elige una imagen de un solo fotograma.')
                if source.width*source.height>40_000_000:
                    raise EditError('La imagen supera el límite de 40 millones de píxeles.')
                source.load()
                image=ImageOps.exif_transpose(source)
                image=image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
                result=BytesIO()
                image.save(result,format='PNG')
                return result.getvalue()
    except EditError:
        raise
    except Exception as exc:
        raise EditError(f'No se pudo leer la imagen: {exc}') from exc


def _validate(before_data,after_data,page_number,old_index=None,new_rect=None,expected_asset=None,
              *,expected_bbox=None,old_rect=None):
    reports=[]
    with fitz.open(stream=before_data,filetype='pdf') as before,fitz.open(stream=after_data,filetype='pdf') as after:
        if before.page_count!=after.page_count or before.metadata!=after.metadata or before.get_xml_metadata()!=after.get_xml_metadata() or _canonical(before.get_toc(False))!=_canonical(after.get_toc(False)):
            raise EditError('La operación de imagen alteró la estructura del documento.')
        for n in range(before.page_count):
            a,b=before[n],after[n]
            if (tuple(a.mediabox),tuple(a.cropbox),a.rotation)!=(tuple(b.mediabox),tuple(b.cropbox),b.rotation):
                raise EditError('La operación de imagen alteró las dimensiones de una página.')
            ra,rb=related(a),related(b)
            ia,ib=_image_infos(a),_image_infos(b)
            if n!=page_number:
                if ra!=rb:
                    raise EditError('Se alteraron elementos de otra página.')
                if expected_asset is not None:
                    for first,second in zip(ia,ib):
                        if first.get('xref') and second.get('xref') and _asset_fingerprint(before,first['xref'])!=_asset_fingerprint(after,second['xref']):
                            raise EditError('Se alteraron píxeles o transparencia de una imagen en otra página.')
                excluded=[]
            else:
                ra.pop('images',None)
                rb.pop('images',None)
                if ra!=rb:
                    raise EditError('La operación alteró vectores, enlaces o anotaciones.')
                expected=ia[:]
                excluded=[]
                original=expected.pop(old_index) if old_index is not None else None
                if original:
                    excluded.append(old_rect if old_rect is not None else original['bbox'])
                actual=ib[:]
                if new_rect is not None:
                    index=old_index if old_index is not None else len(actual)-1
                    if not 0<=index<len(actual):
                        raise EditError('No se encuentra la imagen modificada en el resultado.')
                    inserted=actual.pop(index)
                    if not all(abs(a-b)<.035 for a,b in zip(inserted['bbox'],expected_bbox if expected_bbox is not None else new_rect)):
                        raise EditError('La imagen no aparece en la posición y tamaño pedidos.')
                    if expected_asset is not None:
                        if _asset_fingerprint(after,inserted['xref'])!=expected_asset:
                            raise EditError('Los píxeles o la transparencia de la imagen nueva no coinciden con la operación solicitada.')
                    elif original and any(inserted[k]!=original[k] for k in ('digest','width','height','bpc','colorspace')):
                        raise EditError('La transformación cambió los píxeles de la imagen.')
                    excluded.append(tuple(new_rect))
                semantic=lambda items:[{k:v for k,v in im.items() if k!='size'} for im in items]
                if _canonical(semantic(expected))!=_canonical(semantic(actual)):
                    raise EditError('Se alteró otra instancia de imagen o un recurso compartido.')
                if expected_asset is not None:
                    for first,second in zip(expected,actual):
                        if first.get('xref') and second.get('xref') and _asset_fingerprint(before,first['xref'])!=_asset_fingerprint(after,second['xref']):
                            raise EditError('Se alteraron píxeles o transparencia de otra instancia de imagen.')
            assert_characters(trace_chars(a),b)
            reports.append(assert_pixels(a,b,excluded))
    if len(PdfReader(BytesIO(after_data),strict=True).pages)!=len(reports):
        raise EditError('El lector independiente no confirma la estructura exportada.')
    return {'verified':True,'pages':reports,'independent_parser':'pypdf',
            'page':page_number,'source_regions':[tuple(old_rect if old_rect is not None else original['bbox'])] if old_index is not None else [],
            'destination_regions':[tuple(new_rect)] if new_rect is not None else []}


def add_image_pdf(data,page,image_bytes,rect,revision=None,*,accessibility_order=None,alt_text=None,decorative=False):
    _safe(data,page,revision,adding=True)
    from .tagged_insert import TaggedAddition
    tagged=TaggedAddition(data,page,'/Figure',accessibility_order,alt_text=alt_text,decorative=decorative)
    normalized=_normalized_image(image_bytes)
    with fitz.open(stream=data,filetype='pdf') as doc:
        target=doc[page]
        rect=_rect(target,rect)
        rotation=target.rotation
        target.set_rotation(0)
        try:
            _private_image_resources(doc,target)
            _isolate_existing_content(doc,target)
            target=doc.reload_page(target)
            old_contents=target.get_contents()
            target.insert_image(rect,stream=normalized,keep_proportion=False,overlay=True)
            tagged_expected=tagged.apply(doc,old_contents)
        finally:
            target.set_rotation(rotation)
        output=full_write(doc)
    report=_validate(data,output,page,new_rect=rect)
    from .tagged import assert_structure
    assert_structure(data,output,tagged_expected)
    if tagged.structure is not None:
        report['accessibility']=tagged.report()
    return output,report


def _change(data,page,image_id,rect,revision,remove=False):
    _safe(data,page,revision)
    with fitz.open(stream=data,filetype='pdf') as doc:
        target=doc[page]
        items=image_items(doc,page)
        item=next((item for item in items if item['id']==str(image_id)),None)
        if not item or not item['editable']:
            raise EditError(item['reason'] if item else 'La imagen seleccionada ya no existe.')
        contents=target.get_contents()
        stream=_ops(doc.xref_stream(item['stream_xref']))
        offset=item['operator_index']
        expected_bbox=None
        if remove:
            del stream.operations[offset:offset+item['operator_count']]
        else:
            rect=_rect(target,rect)
            rotation=target.rotation
            try:
                target.set_rotation(0)
                pdf_rect=rect*~target.transformation_matrix
                old_pdf_rect=fitz.Rect(item['rect'])*~target.transformation_matrix
                page_matrix=target.transformation_matrix
            finally:
                target.set_rotation(rotation)
            clip=item.get('clip_rect_pdf')
            if clip is not None and not (fitz.Rect(clip)+(-.01,-.01,.01,.01)).contains(pdf_rect):
                raise EditError('El destino de la imagen supera su recorte heredado. Elige una posición y tamaño dentro del área visible original.')
            # Map the existing frame, preserving the image's rotation and
            # reflection. Merely moving an edited image must not reset either.
            sx,sy=pdf_rect.width/old_pdf_rect.width,pdf_rect.height/old_pdf_rect.height
            mapping=fitz.Matrix(sx,0,0,sy,pdf_rect.x0-old_pdf_rect.x0*sx,pdf_rect.y0-old_pdf_rect.y0*sy)
            desired=fitz.Matrix(item['matrix_pdf'])*mapping
            parent=fitz.Matrix(item['parent_matrix'])
            inverse=fitz.Matrix(parent)
            if inverse.invert():
                raise EditError('La imagen hereda una matriz no invertible.')
            local=desired*inverse
            stream.operations[item['matrix_index']]=([FloatObject(v) for v in local],b'cm')
            if item.get('framed'):
                if not parent.is_rectilinear:
                    raise EditError('El marco de esta imagen hereda una inclinación que no permite redimensionarlo.')
                frame=pdf_rect*inverse
                stream.operations[offset+1]=([FloatObject(v) for v in (frame.x0,frame.y0,frame.width,frame.height)],b're')
            expected_bbox=tuple(fitz.Rect(0,0,1,1)*desired*page_matrix)
        # Clone only this stream reference, even if another page shares it.
        clone=doc.get_new_xref()
        doc.update_object(clone,'<<>>')
        doc.update_stream(clone,stream.get_data())
        contents[item['stream_position']]=clone
        doc.xref_set_key(target.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in contents)+']')
        output=full_write(doc)
    return output,_validate(data,output,page,int(image_id),None if remove else rect,
                            expected_bbox=expected_bbox,old_rect=item['rect'])


def transform_image_pdf(data,page,image_id,rect,revision=None):
    return _change(data,page,image_id,rect,revision)


def delete_image_pdf(data,page,image_id,revision=None):
    return _change(data,page,image_id,None,revision,remove=True)


def _private_image_resources(doc,page):
    """Materialize inherited Resources and clone XObject before adding names.

    Sharing the image object is safe; mutating a shared resource dictionary is
    not. All other entries still point to their original unmodified objects.
    """
    owner=page.xref
    seen=set()
    while doc.xref_get_key(owner,'Resources')[0]=='null':
        kind,parent=doc.xref_get_key(owner,'Parent')
        if kind!='xref' or owner in seen:
            raise EditError('No se pueden resolver los recursos heredados de esta página.')
        seen.add(owner)
        owner=int(parent.split()[0])
    kind,value=doc.xref_get_key(owner,'Resources')
    if kind=='xref':
        value=doc.xref_object(int(value.split()[0]))
    elif kind!='dict':
        raise EditError('Los recursos de esta página no forman un diccionario válido.')
    resources=doc.get_new_xref()
    doc.update_object(resources,value)
    kind,value=doc.xref_get_key(resources,'XObject')
    if kind=='xref':
        value=doc.xref_object(int(value.split()[0]))
    elif kind=='null':
        value='<<>>'
    elif kind!='dict':
        raise EditError('No se puede aislar el diccionario de imágenes de esta página.')
    objects=doc.get_new_xref()
    doc.update_object(objects,value)
    doc.xref_set_key(resources,'XObject',f'{objects} 0 R')
    doc.xref_set_key(page.xref,'Resources',f'{resources} 0 R')


def _image_selection(doc,page,image_id):
    if not 0<=page<doc.page_count:
        raise EditError('Página inexistente.')
    item=next((item for item in image_items(doc,page) if item['id']==str(image_id)),None)
    if item is None:
        raise EditError('La imagen seleccionada ya no existe.')
    if not item.get('xref'):
        raise EditError('La imagen es inline o su recurso es ambiguo; no se puede extraer de forma inequívoca.')
    return item


def _asset_png(doc,xref):
    """Decode one resource, retaining its own soft alpha, never a page render."""
    if doc.xref_get_key(xref,'ImageMask')==('bool','true'):
        raise EditError('Esta imagen es una máscara de estarcido: su color depende del contenido de la página.')
    if doc.xref_get_key(xref,'Mask')[0]!='null':
        raise EditError('Esta imagen utiliza una máscara dura o por clave de color que todavía no se puede exportar con garantías.')
    meta=doc.extract_image(xref)
    if not meta:
        raise EditError('No se pudo decodificar el recurso de imagen seleccionado.')
    if meta['width']*meta['height']>40_000_000:
        raise EditError('La imagen supera el límite de 40 millones de píxeles.')
    pix=fitz.Pixmap(doc,xref)
    if pix.colorspace is None:
        raise EditError('La imagen no tiene un espacio de color independiente.')
    if pix.colorspace.n!=3:
        pix=fitz.Pixmap(fitz.csRGB,pix)
    # Merge alpha with straight RGB samples, avoiding unnecessary rounding from
    # premultiplication / unpremultiplication of the original colour channels.
    if pix.alpha:
        png=pix.tobytes('png')
    else:
        bitmap=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        mask_xref=meta.get('smask',0)
        if mask_xref:
            if doc.xref_get_key(mask_xref,'Matte')[0]!='null':
                raise EditError('La máscara de esta imagen utiliza Matte; no se puede reproducir su transparencia con garantías.')
            mask=fitz.Pixmap(doc,mask_xref)
            if mask.colorspace is None or mask.colorspace.n!=1 or mask.alpha or (mask.width,mask.height)!=(pix.width,pix.height):
                raise EditError('La máscara de transparencia no coincide con las dimensiones de la imagen.')
            bitmap.putalpha(Image.frombytes('L',(mask.width,mask.height),mask.samples))
        target=BytesIO()
        bitmap.save(target,format='PNG')
        png=target.getvalue()
    return png,meta


def _asset_fingerprint(doc,xref):
    png,_=_asset_png(doc,xref)
    with Image.open(BytesIO(png)) as image:
        image=image.convert('RGBA')
        return (image.size,hashlib.sha256(image.tobytes()).hexdigest())


def export_image_pdf(data,page,image_id,revision=None):
    """Read an image resource; preserve JPEG bytes when no mask is involved.

    The export contains the entire resource, without page clipping, CTM or
    inherited opacity. preview_png is an RGB/RGBA decode for the image editor.
    This read-only operation also supports tagged / non-transformable instances.
    """
    if revision and hashlib.sha256(data).hexdigest()!=revision:
        raise EditError('La selección está desactualizada. Selecciona la imagen de nuevo.')
    with fitz.open(stream=data,filetype='pdf') as doc:
        if doc.needs_pass:
            raise EditError('El PDF necesita una contraseña válida antes de extraer imágenes.')
        if not doc.permissions & fitz.PDF_PERM_COPY:
            raise EditError('Los permisos del documento no autorizan extraer imágenes.')
        item=_image_selection(doc,page,image_id)
        png,meta=_asset_png(doc,item['xref'])
        alpha=bool(meta.get('smask'))
        native=meta.get('ext') in ('jpeg','jpg') and not alpha
        return {'image_bytes':meta['image'] if native else png,
                'ext':'jpg' if native else 'png','preview_png':png,
                'width_px':meta['width'],'height_px':meta['height'],'alpha':alpha,
                'rect':item['rect'],'editable':item['editable'],'reason':item['reason'],
                'image_operation':item.get('image_operation'),
                'notice':'Se exporta el recurso completo, sin los recortes, el giro ni la opacidad propios de la página.'}


def _edited_asset(image_bytes,crop,rotation):
    normalized=_normalized_image(image_bytes)
    if isinstance(rotation,bool) or rotation not in (0,90,180,270):
        raise EditError('El giro debe ser 0, 90, 180 o 270 grados en sentido horario.')
    if crop is None:
        crop=(0.,0.,1.,1.)
    try:
        valid=(len(crop)==4 and all(math.isfinite(float(value)) for value in crop)
               and 0<=crop[0]<crop[2]<=1 and 0<=crop[1]<crop[3]<=1)
    except (TypeError,ValueError):
        valid=False
    if not valid:
        raise EditError('El recorte debe ser un rectángulo válido dentro de la imagen (0 a 100 %).')
    with Image.open(BytesIO(normalized)) as source:
        pixel_box=(math.floor(crop[0]*source.width),math.floor(crop[1]*source.height),
                   math.ceil(crop[2]*source.width),math.ceil(crop[3]*source.height))
        image=source.crop(pixel_box)
        if rotation:
            method={90:Image.Transpose.ROTATE_270,180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_90}[rotation]
            image=image.transpose(method)
        target=BytesIO()
        image.save(target,format='PNG')
        return target.getvalue(),pixel_box,image.size


def _insert_asset(page,rect,png):
    # Supplying RGBA to MuPDF can premultiply / round / unpremultiply colour
    # channels. Independent RGB + grayscale SMask retain the exact 8-bit asset.
    with Image.open(BytesIO(png)) as bitmap:
        if bitmap.mode=='RGBA':
            rgb,alpha=BytesIO(),BytesIO()
            bitmap.convert('RGB').save(rgb,format='PNG')
            bitmap.getchannel('A').save(alpha,format='PNG')
            return page.insert_image(rect,stream=rgb.getvalue(),mask=alpha.getvalue(),keep_proportion=False,overlay=True)
    return page.insert_image(rect,stream=png,keep_proportion=False,overlay=True)


def edit_image_pdf(data,page,image_id,*,replacement_bytes=None,crop=None,rotation=0,revision=None,
                   flip_horizontal=False,flip_vertical=False,fit_mode=None):
    """Crop/rotate/replace exactly one isolated Do, keeping its existing box.

    Cropping removes pixels from a new asset and fits the result into the same
    box, as explicitly shown in the editor. No other placement of a shared image
    or stream changes. The original image object is never overwritten.
    """
    if fit_mode is not None or flip_horizontal or flip_vertical or rotation not in (0,90,180,270):
        return _edit_image_frame(data,page,image_id,replacement_bytes=replacement_bytes,crop=crop,
                                 rotation=rotation,revision=revision,flip_horizontal=flip_horizontal,
                                 flip_vertical=flip_vertical,fit_mode=fit_mode or 'fit')
    _safe(data,page,revision)
    with fitz.open(stream=data,filetype='pdf') as doc:
        target=doc[page]
        item=_image_selection(doc,page,image_id)
        if not item['editable']:
            raise EditError(item['reason'])
        source_png,_=_asset_png(doc,item['xref'])
        png,pixel_crop,pixel_size=_edited_asset(replacement_bytes if replacement_bytes is not None else source_png,crop,rotation)
        with Image.open(BytesIO(png)) as bitmap:
            expected_asset=(bitmap.size,hashlib.sha256(bitmap.convert('RGBA').tobytes()).hexdigest())
        contents=target.get_contents()[:]
        stream=_ops(doc.xref_stream(item['stream_xref']))
        offset=item['operator_index']
        original_names={row[7] for row in target.get_images(full=True) if not row[9]}
        _private_image_resources(doc,target)
        target=doc.reload_page(target)
        page_rotation=target.rotation
        try:
            target.set_rotation(0)
            inserted_xref=_insert_asset(target,fitz.Rect(item['rect']),png)
        finally:
            target.set_rotation(page_rotation)
        added_names=[row[7] for row in target.get_images(full=True) if not row[9] and row[0]==inserted_xref and row[7] not in original_names]
        if len(added_names)!=1:
            raise EditError('No se pudo aislar el recurso de la nueva imagen.')
        stream.operations[item['do_index']]=([NameObject('/'+added_names[0])],b'Do')
        clone=doc.get_new_xref()
        doc.update_object(clone,'<<>>')
        doc.update_stream(clone,stream.get_data())
        contents[item['stream_position']]=clone
        # Discard the temporary insertion placement; keep only the selected
        # original q/cm/Do/Q, including inherited alpha, clips and paint order.
        doc.xref_set_key(target.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in contents)+']')
        output=full_write(doc)
    report=_validate(data,output,page,int(image_id),item['rect'],expected_asset=expected_asset)
    report.update(image_operation='edit_asset',rotation_clockwise=rotation,crop_pixels=pixel_crop,
                  replacement=replacement_bytes is not None,image_size_px=pixel_size,
                  original_box_preserved=True,instance_only=True,
                  notice='La imagen nueva se ajusta a la caja original. Sus proporciones pueden cambiar; revisa la vista previa del PDF.')
    return output,report


def _frame_matrix(frame,width,height,crop,rotation,flip_horizontal,flip_vertical,fit_mode):
    """Unit-image → PDF coordinates. Rotate the geometry, never the pixels.

    fill uses inverse-rotated frame corners, rather than the rotated bounding
    box, so arbitrary angles fill all corners without transparent triangles.
    """
    radians=math.radians(rotation)
    cosine,sine=math.cos(radians),math.sin(radians)
    cw,ch=width*(crop[2]-crop[0]),height*(crop[3]-crop[1])
    bw,bh=abs(cosine)*cw+abs(sine)*ch,abs(sine)*cw+abs(cosine)*ch
    if fit_mode=='fill':
        sx=sy=max((abs(cosine)*frame.width+abs(sine)*frame.height)/cw,
                  (abs(sine)*frame.width+abs(cosine)*frame.height)/ch)
    elif fit_mode=='fit':
        sx=sy=min(frame.width/bw,frame.height/bh)
    else:
        sx,sy=frame.width/bw,frame.height/bh
    fx,fy=(-1 if flip_horizontal else 1),(-1 if flip_vertical else 1)
    a,b=width*fx*cosine*sx,-width*fx*sine*sy
    c,d=height*fy*sine*sx,height*fy*cosine*sy
    cx,cy=(crop[0]+crop[2])/2,1-(crop[1]+crop[3])/2
    return fitz.Matrix(a,b,c,d,(frame.x0+frame.x1)/2-a*cx-c*cy,
                       (frame.y0+frame.y1)/2-b*cx-d*cy)


def _edit_image_frame(data,page,image_id,*,replacement_bytes,crop,rotation,revision,
                      flip_horizontal,flip_vertical,fit_mode):
    _safe(data,page,revision)
    if isinstance(rotation,bool) or not isinstance(rotation,(int,float)) or not math.isfinite(rotation):
        raise EditError('El giro debe ser un número finito de grados.')
    if fit_mode not in ('fit','fill','stretch'):
        raise EditError('El modo debe ser Encajar, Rellenar recortando o Estirar explícitamente.')
    crop=(0.,0.,1.,1.) if crop is None else crop
    try:
        crop=tuple(float(v) for v in crop)
        valid=(len(crop)==4 and all(math.isfinite(v) for v in crop)
               and 0<=crop[0]<crop[2]<=1 and 0<=crop[1]<crop[3]<=1)
    except (TypeError,ValueError):
        valid=False
    if not valid:
        raise EditError('El recorte debe ser un rectángulo válido dentro de la imagen (0 a 100 %).')
    with fitz.open(stream=data,filetype='pdf') as doc:
        target=doc[page]
        item=_image_selection(doc,page,image_id)
        if not item['editable']:
            raise EditError(item['reason'])
        parent=fitz.Matrix(item['parent_matrix'])
        inverse=fitz.Matrix(parent)
        if inverse.invert() or not parent.is_rectilinear:
            raise EditError('La imagen hereda una inclinación que no permite aislar un marco rectangular.')
        frame=_rect(target,item['rect'])
        contents=target.get_contents()[:]
        stream=_ops(doc.xref_stream(item['stream_xref']))
        offset=item['operator_index']
        name=stream.operations[item['do_index']][0][0]
        if replacement_bytes is None:
            meta=doc.extract_image(item['xref'])
            width,height=meta['width'],meta['height']
            expected_asset=_asset_fingerprint(doc,item['xref'])
        else:
            normalized=_normalized_image(replacement_bytes)
            with Image.open(BytesIO(normalized)) as bitmap:
                width,height=bitmap.size
                expected_asset=(bitmap.size,hashlib.sha256(bitmap.convert('RGBA').tobytes()).hexdigest())
            names={row[7] for row in target.get_images(full=True) if not row[9]}
            _private_image_resources(doc,target)
            target=doc.reload_page(target)
            old_rotation=target.rotation
            try:
                target.set_rotation(0)
                inserted_xref=_insert_asset(target,frame,normalized)
            finally:
                target.set_rotation(old_rotation)
            added=[row[7] for row in target.get_images(full=True)
                   if not row[9] and row[0]==inserted_xref and row[7] not in names]
            if len(added)!=1:
                raise EditError('No se pudo aislar el recurso de la imagen reemplazada.')
            name=NameObject('/'+added[0])
        old_rotation=target.rotation
        try:
            target.set_rotation(0)
            page_matrix=target.transformation_matrix
        finally:
            target.set_rotation(old_rotation)
        pdf_frame=frame*~page_matrix
        clip=item.get('clip_rect_pdf')
        if clip is not None and not (fitz.Rect(clip)+(-.01,-.01,.01,.01)).contains(pdf_frame):
            raise EditError('El marco supera el recorte heredado de esta imagen.')
        total=_frame_matrix(pdf_frame,width,height,crop,rotation%360,flip_horizontal,flip_vertical,fit_mode)
        local=total*inverse
        local_frame=pdf_frame*inverse
        f=lambda values:[FloatObject(v) for v in values]
        placement=[([],b'q'),
                   (f((local_frame.x0,local_frame.y0,local_frame.width,local_frame.height)),b're'),
                   ([],b'W'),([],b'n'),(f(local),b'cm'),
                   (f((crop[0],1-crop[3],crop[2]-crop[0],crop[3]-crop[1])),b're'),
                   ([],b'W'),([],b'n'),([name],b'Do'),([],b'Q')]
        stream.operations[offset:offset+item['operator_count']]=placement
        clone=doc.get_new_xref()
        doc.update_object(clone,'<<>>')
        doc.update_stream(clone,stream.get_data())
        contents[item['stream_position']]=clone
        doc.xref_set_key(target.xref,'Contents','['+' '.join(f'{xref} 0 R' for xref in contents)+']')
        expected_bbox=tuple(fitz.Rect(0,0,1,1)*total*page_matrix)
        output=full_write(doc)
    report=_validate(data,output,page,int(image_id),frame,expected_asset=expected_asset,
                     expected_bbox=expected_bbox,old_rect=item['rect'])
    report.update(image_operation='frame_transform',rotation_clockwise=rotation%360,
                  flip_horizontal=bool(flip_horizontal),flip_vertical=bool(flip_vertical),fit_mode=fit_mode,
                  crop_normalized=crop,replacement=replacement_bytes is not None,image_size_px=(width,height),
                  original_box_preserved=True,instance_only=True,pixels_preserved=True,
                  notice='El encuadre conserva los píxeles originales. Puedes recuperar el recorte al volver a editar la imagen.'
                  if fit_mode!='stretch' else 'Estirar cambia las proporciones por elección explícita; revisa el resultado.')
    return output,report
