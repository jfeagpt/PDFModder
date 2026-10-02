"""Selecciones explícitas de objetos y operaciones atómicas sobre una página.

Los grupos son metadatos propios de edición, no etiquetas de accesibilidad.
Sus miembros se verifican por contenido y geometría antes de reutilizarlos.
"""
from collections import Counter, defaultdict
from io import BytesIO
import hashlib
import json
import math
import uuid

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream

from .engine import extract_page, full_write
from .model import EditError, EditRequest, union
from .validation import (document_issues, assert_pixels, related, assert_characters,
                         trace_chars, _canonical)

GROUP_KEY = 'PDFModderGroups'


def _signature(g):
    return [g.text, list(g.origin), g.font, g.size]


def _images(doc,page):
    from .media import image_items
    images=image_items(doc,page)
    raw=doc[page].get_image_info(hashes=True)
    for image in images:
        image['digest']=raw[int(image['id'])]['digest'].hex()
    return images


def _check(data, page, revision=None):
    if revision and revision != hashlib.sha256(data).hexdigest():
        raise EditError('La selección de objetos está desactualizada. Vuelve a abrir el panel.')
    with fitz.open(stream=data, filetype='pdf') as doc:
        issues = document_issues(data, doc)
        if issues:
            raise EditError('\n'.join(issues))
        if not isinstance(page, int) or not 0 <= page < len(doc):
            raise EditError('La página seleccionada no existe.')


def _groups(doc, page):
    kind, value = doc.xref_get_key(doc[page].xref, GROUP_KEY)
    if kind == 'null':
        return []
    try:
        groups = json.loads(value)
        if not isinstance(groups, list):
            raise ValueError()
        return groups
    except (ValueError, TypeError):
        raise EditError('Los grupos guardados no tienen un formato válido.')


def _resolve(spec, model, images):
    if spec['kind'] == 'text':
        found = []
        hints=spec.get('glyph_ids',[])
        for index,(text, origin, font, size) in enumerate(spec['glyphs']):
            candidates = [g for g in model.glyphs if g.id not in found and g.text == text
                          and g.font == font and abs(g.size-size) < .002
                          and all(abs(a-b) < .035 for a,b in zip(g.origin, origin))]
            hinted=next((g for g in candidates if index<len(hints) and g.id==hints[index]),None)
            if hinted is not None:
                candidates=[hinted]
            if len(candidates) != 1:
                raise EditError('Un miembro del grupo cambió o es ambiguo. Selecciónalo de nuevo.')
            found.append(candidates[0].id)
        return {'kind':'text', 'ids':found, 'rect':union(g.bbox for g in model.selected(found))}
    if spec['kind']!='image':
        raise EditError('El grupo incluye un tipo de objeto desconocido.')
    candidates = [im for im in images if all(abs(a-b)<.04 for a,b in zip(im['rect'],spec['rect']))
                  and im['width_px']==spec['width_px'] and im['height_px']==spec['height_px']
                  and (not spec.get('digest') or im.get('digest')==spec['digest'])]
    hinted=next((im for im in candidates if im['id']==spec.get('image_id')),None)
    if hinted is not None:candidates=[hinted]
    if len(candidates)!=1:
        raise EditError('La imagen del grupo cambió o se superpone con una instancia idéntica. Selecciónala de nuevo.')
    return {'kind':'image','image_id':candidates[0]['id'],'rect':candidates[0]['rect']}


def _spec(item, model, images):
    if item['kind']=='text':
        glyphs=model.selected(item['ids'])
        if not glyphs or len(glyphs)!=len(item['ids']):
            raise EditError('El fragmento de texto ya no existe.')
        return {'kind':'text','glyphs':[_signature(g) for g in glyphs],'glyph_ids':[g.id for g in glyphs]}
    if item['kind']!='image':
        raise EditError('Selecciona un objeto de texto o una imagen.')
    image=next((i for i in images if i['id']==str(item['image_id'])),None)
    if image is None:
        raise EditError('La imagen seleccionada ya no existe.')
    return {'kind':'image','rect':list(image['rect']),'width_px':image['width_px'],'height_px':image['height_px'],
            'image_id':image['id'],'digest':image.get('digest')}


def object_info(data, page):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,page,data)
        images=_images(doc,page)
        lines=defaultdict(list)
        for g in model.glyphs:
            if g.mode==0 and g.opacity>0:
                lines[(g.block,g.line)].append(g)
        items=[{'kind':'text','ids':[g.id for g in glyphs],
                'label':''.join(g.text for g in glyphs), 'rect':union(g.bbox for g in glyphs)}
               for glyphs in lines.values()]
        items += [{'kind':'image','image_id':im['id'],'rect':im['rect'],
                   'label':f"Imagen {int(im['id'])+1} · {im['width_px']}×{im['height_px']} px",
                   'editable':im['editable'],'reason':im.get('reason','')} for im in images]
        groups=[]
        for group in _groups(doc,page):
            try:
                members=[_resolve(s,model,images) for s in group['members']]
                groups.append({**group,'items':members,'valid':True,'rect':union(m['rect'] for m in members)})
            except (EditError,KeyError,TypeError) as exc:
                groups.append({**group,'valid':False,'reason':str(exc)})
        return {'items':items,'groups':groups,'revision':model.revision,'page':page}


def group_pdf(data,page,items=None,name='Grupo',group_id=None,revision=None,split_at=None):
    _check(data,page,revision)
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,page,data);images=_images(doc,page)
        groups=_groups(doc,page)
        if group_id:
            if not any(g['id']==group_id for g in groups):
                raise EditError('El grupo ya no existe.')
            groups=[g for g in groups if g['id']!=group_id]
        elif split_at is not None:
            ids=[i for item in items or [] if item['kind']=='text' for i in item['ids']]
            ids=list(dict.fromkeys(ids))
            if not 0 < split_at < len(ids):
                raise EditError('El punto de división debe quedar entre dos caracteres.')
            for index,part in enumerate((ids[:split_at],ids[split_at:]),1):
                groups.append({'id':uuid.uuid4().hex,'name':f'{name} {index}',
                               'members':[_spec({'kind':'text','ids':part},model,images)]})
        else:
            if not items:
                raise EditError('Selecciona los miembros del grupo.')
            seen=set()
            for item in items:
                keys=[('text',g) for g in item.get('ids',[])] if item['kind']=='text' else [('image',str(item['image_id']))]
                if any(key in seen for key in keys):
                    raise EditError('Un objeto aparece en dos miembros del grupo; elimina el duplicado.')
                seen.update(keys)
            groups.append({'id':uuid.uuid4().hex,'name':name.strip() or 'Grupo',
                           'members':[_spec(item,model,images) for item in items]})
        doc.xref_set_key(doc[page].xref,GROUP_KEY,fitz.get_pdf_str(json.dumps(groups,ensure_ascii=True)))
        output=full_write(doc)
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert_pixels(before[page],after[page],reproduction=True)
    return output,{'page':page,'operation':'object_groups','source_regions':[], 'destination_regions':[],
                   'group_count':len(groups)}


def _deltas(items,operation,dx,dy):
    bounds=union(i['rect'] for i in items)
    result=[(0.,0.) for _ in items]
    if operation=='move':
        return [(dx,dy) for _ in items]
    if operation.startswith('align_'):
        edge=operation[6:]
        for n,item in enumerate(items):
            r=item['rect']
            options={'left':(bounds[0]-r[0],0),'right':(bounds[2]-r[2],0),
                     'top':(0,bounds[1]-r[1]),'bottom':(0,bounds[3]-r[3]),
                     'center':((bounds[0]+bounds[2]-r[0]-r[2])/2,0),
                     'middle':(0,(bounds[1]+bounds[3]-r[1]-r[3])/2)}
            if edge not in options:raise EditError('Alineación desconocida.')
            result[n]=options[edge]
        return result
    if operation in ('distribute_x','distribute_y'):
        if len(items)<3:raise EditError('Selecciona al menos tres objetos para distribuirlos.')
        axis=0 if operation.endswith('x') else 1
        order=sorted(range(len(items)),key=lambda n:items[n]['rect'][axis])
        lengths=[items[n]['rect'][axis+2]-items[n]['rect'][axis] for n in order]
        gap=(bounds[axis+2]-bounds[axis]-sum(lengths))/(len(items)-1)
        if gap<-.035:raise EditError('No hay espacio para distribuir los objetos sin solaparlos.')
        cursor=bounds[axis]
        for n,length in zip(order,lengths):
            delta=cursor-items[n]['rect'][axis]
            result[n]=(delta,0) if axis==0 else (0,delta)
            cursor+=length+gap
        return result
    raise EditError('Operación conjunta desconocida.')


def transform_objects_pdf(data,page,items,operation,dx=0.,dy=0.,revision=None):
    _check(data,page,revision)
    if not items:raise EditError('Selecciona al menos un objeto.')
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (dx,dy)):
        raise EditError('El desplazamiento debe ser finito.')
    from .media import transform_image_pdf
    from .clipped_layout import move_clipped_text
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,page,data);images=_images(doc,page)
        specs=[_spec(item,model,images) for item in items]
        items=[_resolve(s,model,images) for s in specs]
        seen=set()
        for item in items:
            keys=[('text',g) for g in item.get('ids',[])] if item['kind']=='text' else [('image',item['image_id'])]
            if any(k in seen for k in keys):raise EditError('Un objeto aparece en dos selecciones; elimina el duplicado.')
            seen.update(keys)
        groups=_groups(doc,page)
        # Resolve valid stored members once, before any intermediate destination
        # can overlap another member's original location. Native moves preserve
        # occurrence order; geometry alone cannot distinguish such crossings.
        group_members=[]
        for group in groups:
            try:
                members=[(member,_resolve(member,model,images)) for member in group['members']]
                group_members.extend(members)
            except (EditError,KeyError,TypeError):
                pass  # Existing stale groups stay explicitly stale.
    if operation in ('front','back'):
        return reorder_objects_pdf(data,page,items,operation,revision)
    deltas=_deltas(items,operation,dx,dy)
    current=data;reports=[]
    # Every intermediate candidate is private. Failure returns no partial edit.
    for spec,(sx,sy) in zip(specs,deltas):
        if abs(sx)+abs(sy)<1e-9:continue
        with fitz.open(stream=current,filetype='pdf') as doc:
            now=extract_page(doc,page,current);images=_images(doc,page)
            item=_resolve(spec,now,images)
        if item['kind']=='text':
            from .richtext import has_rich_metadata,move_rich_pdf
            request=EditRequest(page,item['ids'],dx=sx,dy=sy,allow_overlap=True)
            if has_rich_metadata(current,page):current,report=move_rich_pdf(current,request)
            else:current,report=move_clipped_text(current,request,now)
        else:
            r=item['rect'];dest=[r[0]+sx,r[1]+sy,r[2]+sx,r[3]+sy]
            current,report=transform_image_pdf(current,page,item['image_id'],dest)
        reports.append(report)
    if groups:
        with fitz.open(stream=current,filetype='pdf') as doc:
            final_model=extract_page(doc,page,current);final_images=_images(doc,page)
            for member,resolved in group_members:
                updated=_spec(resolved,final_model,final_images)
                member.clear();member.update(updated)
            doc.xref_set_key(doc[page].xref,GROUP_KEY,fitz.get_pdf_str(json.dumps(groups,ensure_ascii=True)))
            current=full_write(doc)
    return current,{'operation':'objects_'+operation,'page':page,'edits':reports,
                    'source_regions':[r for t in reports for r in t.get('source_regions',[])],
                    'destination_regions':[r for t in reports for r in t.get('destination_regions',[])],
                    'object_count':len(items),'warning':'Alineación explícita: revisa posibles superposiciones antes de aplicar.'}


def reorder_objects_pdf(data,page,items,position,revision=None):
    """Reorder only complete self-contained q/Q painting scopes.

    No text-show is detached from its matrices/resources; nested shared forms
    and marked content remain unsupported instead of silently moving neighbors.
    """
    _check(data,page,revision)
    if position not in ('front','back'):
        raise EditError('El orden debe ser delante o detrás.')
    if not items:
        raise EditError('Selecciona al menos un objeto para ordenar.')
    from .clipping import operator_glyph_map,_serialize,_signature as operand_signature
    from .media import _ops
    from .tagged import require_untagged
    require_untagged(data,'Ordenar objetos')
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,page,data);images=_images(doc,page)
        reader,ops,shows,mapping=operator_glyph_map(data,page,model)
        wanted_text={g for item in items if item['kind']=='text' for g in item['ids']}
        wanted_images={item['image_id'] for item in items if item['kind']=='image'}
        image_ops={};offset=0
        for stream_position,stream in enumerate(doc[page].get_contents()):
            for im in images:
                if im.get('stream_position')==stream_position and 'operator_index' in im:
                    image_ops[offset+im['operator_index']]=im['id']
            offset+=len(_ops(doc.xref_stream(stream)).operations)
        chunks=[];depth=0;start=None;text_open=False;path_open=False
        for i,(_,op) in enumerate(ops):
            if op==b'BT':
                if text_open:raise EditError('Un objeto contiene texto anidado que no puede ordenarse.')
                text_open=True
            elif op==b'ET':
                if not text_open:raise EditError('El texto depende de un ámbito externo; no puede ordenarse.')
                text_open=False
            elif op in (b'm',b're'):
                path_open=True
            elif op in (b'n',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*'):
                path_open=False
            if op==b'q':
                if depth==0:start=i
                depth+=1
            elif op==b'Q':
                depth-=1
                if depth<0:raise EditError('La página contiene un cierre gráfico sin apertura.')
                if depth==0:
                    if text_open or path_open:
                        raise EditError('Un objeto deja texto o un trazado abierto; reordenarlo alteraría otros elementos.')
                    chunks.append((start,i+1))
            elif depth==0:
                # An external state change could make reordering dependent.
                if op not in (b'n',):raise EditError('El orden depende de un estado compartido fuera de los objetos; no se puede cambiar de forma aislada.')
        if depth or not chunks:raise EditError('No se encontraron objetos gráficos completos para ordenar.')
        chosen=[];covered_text=set();covered_images=set()
        for a,b in chunks:
            ids={g.id for show in shows if a<=show['operation']<b for g in show['glyphs']}
            ims={im for op,im in image_ops.items() if a<=op<b}
            if not (ids & wanted_text or ims & wanted_images):continue
            if ids-wanted_text or ims-wanted_images:
                raise EditError('El objeto comparte su ámbito con texto o imágenes no seleccionados. Selecciona el ámbito completo para ordenar.')
            if any(op in (b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'sh',b'BI',b'BDC',b'BMC') for _,op in ops[a:b]):
                raise EditError('El ámbito contiene vectores, contenido marcado u otra pintura; no se separa del objeto.')
            if sum(op==b'Do' for _,op in ops[a:b])!=len(ims):
                raise EditError('El objeto incluye un formulario o imagen que no se puede aislar.')
            chosen.append((a,b));covered_text|=ids;covered_images|=ims
        if covered_text!=wanted_text or covered_images!=wanted_images:
            raise EditError('La selección no corresponde a objetos completos y verificables.')
        rest=[c for c in chunks if c not in chosen]
        order=rest+chosen if position=='front' else chosen+rest
        updated=[op for a,b in order for op in ops[a:b]]
        stream=doc.get_new_xref();doc.update_object(stream,'<<>>');doc.update_stream(stream,_serialize(updated));doc[page].set_contents(stream)
        output=full_write(doc)
    regions=[r for item in items for r in ([g.bbox for g in model.selected(item['ids'])] if item['kind']=='text' else [item['rect']])]
    expected=[(g.text,g.origin,g.font,g.size) for g in model.glyphs]
    # A deliberate z-order change alters extraction order, never object content.
    # Confirm the exact planned operator permutation and resources independently,
    # then compare image identities as a multiset while keeping every other
    # related element and every untouched pixel under the original strict checks.
    independent=PdfReader(BytesIO(output),strict=True)
    actual_ops=ContentStream(independent.pages[page].get_contents(),independent).operations
    if len(actual_ops)!=len(updated) or any(op!=newop or operand_signature(args)!=operand_signature(newargs)
        for (args,op),(newargs,newop) in zip(updated,actual_ops)):
        raise EditError('El guardado alteró operadores ajenos al orden solicitado.')
    if operand_signature(reader.pages[page]['/Resources'])!=operand_signature(independent.pages[page]['/Resources']):
        raise EditError('El guardado alteró recursos compartidos al ordenar objetos.')
    report=_validate_order(data,output,page,expected,regions)
    report.update(page=page,operation='objects_'+position,source_regions=regions,destination_regions=regions,
                  reordered_scopes=len(chosen),warning='Cambió el orden de pintura; revisa la superposición en la vista previa.')
    return output,report


def _validate_order(data,output,page,expected,regions):
    reports=[]
    with fitz.open(stream=data,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        if (len(before)!=len(after) or before.metadata!=after.metadata
            or before.get_xml_metadata()!=after.get_xml_metadata()
            or _canonical(before.get_toc(False))!=_canonical(after.get_toc(False))):
            raise EditError('El cambio de orden alteró la estructura del documento.')
        for number in range(len(before)):
            a,b=before[number],after[number]
            if (tuple(a.mediabox),tuple(a.cropbox),a.rotation)!=(tuple(b.mediabox),tuple(b.cropbox),b.rotation):
                raise EditError('El cambio de orden alteró las dimensiones de página.')
            first,second=related(a),related(b)
            if number==page:
                original_images=first.pop('images')
                actual_images=second.pop('images')
                if Counter(repr(im) for im in original_images)!=Counter(repr(im) for im in actual_images):
                    raise EditError('Cambió una imagen, sus píxeles o su geometría al ordenar.')
            if first!=second:
                raise EditError('El cambio de orden alteró vectores, enlaces, anotaciones u otra página.')
            assert_characters(expected if number==page else trace_chars(a),b)
            reports.append(assert_pixels(a,b,regions if number==page else ()))
    return {'verified':True,'pages':reports,'independent_parser':'pypdf','operators_preserved':True}
