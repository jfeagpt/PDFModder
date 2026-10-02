"""Edición nativa de campos recortados con compensación del cursor PDF.

Preserva Tf/Tc/Tw/Tz, la fuente y los recortes. Cambia un único Tj/TJ usando
códigos verificados del mismo recurso. No reconstruye texto con otra fuente
ni mueve los vecinos. Sólo admite matrices horizontales y recortes conocidos.
"""
from dataclasses import replace
from io import BytesIO
import copy
import hashlib
import math
import time
import unicodedata

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ArrayObject,ByteStringObject,ContentStream,FloatObject
from .clipping import CLIP_ISSUE,operator_glyph_map,_advance,_raw,_serialize,_signature,_strings
from .model import EditError,intersects,union
from .validation import document_issues,validate_transition

def _state_at(operations,index,resources=None):
    state={'size':None,'tc':0.,'tw':0.,'tz':1.,'tr':0,'ctm':fitz.Matrix(1,0,0,1,0,0),
           'clip':None,'unknown':False}
    stack=[]
    text_matrix=fitz.Matrix(1,0,0,1,0,0)
    path,pending=None,False
    text_clips=False
    for args,op in operations[:index]:
        if op==b'q':stack.append(dict(state))
        elif op==b'Q':state=stack.pop()
        elif op==b'cm':state['ctm']=fitz.Matrix(*[float(v) for v in args])*state['ctm']
        elif op==b'BT':
            text_matrix=fitz.Matrix(1,0,0,1,0,0)
            text_clips=False
        elif op in (b'Tj',b'TJ',b"'",b'"') and state['tr']>=4:text_clips=True
        elif op==b'ET' and text_clips:state['unknown']=True
        elif op==b'Tm':text_matrix=fitz.Matrix(*[float(v) for v in args])
        elif op==b'Tf':state['size']=float(args[1])
        elif op==b'Tc':state['tc']=float(args[0])
        elif op==b'Tw':state['tw']=float(args[0])
        elif op==b'Tz':state['tz']=float(args[0])/100
        elif op==b'Tr':state['tr']=int(args[0])
        elif op==b're':
            x,y,w,h=map(float,args)
            path=fitz.Rect(min(x,x+w),min(y,y+h),max(x,x+w),max(y,y+h))*state['ctm'] if path is None and state['ctm'].is_rectilinear else False
        elif op in (b'm',b'l',b'c',b'v',b'y',b'h'):path=False
        elif op in (b'W',b'W*'):pending=True
        elif op in (b'n',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*'):
            if pending:
                if path is None or path is False:state['unknown']=True
                else:state['clip']=path if state['clip'] is None else state['clip']&path
            path,pending=None,False
        elif op==b'gs':
            # Only /Font changes the text font size. An opacity-only gs must
            # retain Tf. With no resources supplied keep the conservative
            # legacy behaviour; an unresolved state never invents a size.
            try:
                ext=resources.get('/ExtGState',{}).get_object()
                item=ext[args[0]].get_object()
                if '/Font' in item:
                    state['size']=float(item['/Font'].get_object()[1])
            except (AttributeError,KeyError,TypeError,ValueError,IndexError):
                state['size']=None
    state['matrix']=text_matrix*state['ctm']
    return state


def edit_clipped_layout(data,request,model):
    from .engine import _safe_selection,full_write
    started=time.perf_counter()
    if request.page!=model.number or (request.revision and request.revision!=hashlib.sha256(data).hexdigest()):
        raise EditError('La selección está desactualizada. Selecciona el texto de nuevo.')
    selected=model.selected(request.ids)
    if not selected or len(selected)!=len(set(request.ids)):
        raise EditError('Selecciona un fragmento contiguo del documento actual.')
    if request.text is not None and (request.reflow or '\n' in request.text or '\r' in request.text or request.line_spacing is not None or request.paragraph_spacing):
        from .native_layout import edit_native_layout
        return edit_native_layout(data,request,model)
    if request.text is None:
        raise EditError('Selecciona el texto que quieres sustituir.')
    if request.dx or request.dy or request.font_name or request.font_file or request.color is not None:
        raise EditError('Texto recortado: mover o cambiar la fuente o el color necesita otro tratamiento; conserva el formato original.')
    if request.size is not None and any(abs(request.size-g.size)>.001 for g in selected):
        raise EditError('Texto recortado: conserva el tamaño original; no se comprime ni reduce el texto automáticamente.')
    if request.anchor not in ('left','right','center'):
        raise EditError('Texto recortado: utiliza anclaje izquierdo, centrado o derecho para este cambio.')
    text=''.join(g.text for g in selected)
    new_text=request.text
    if any(unicodedata.category(c).startswith('C') or unicodedata.combining(c) for c in new_text):
        raise EditError('No se admiten controles ni marcas combinantes; usa acentos precompuestos.')
    bounds=union(g.bbox for g in selected)
    width=request.width if request.width is not None else bounds[2]-bounds[0]
    height=request.height if request.height is not None else bounds[3]-bounds[1]
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (width,height)):
        raise EditError('El área de edición debe tener dimensiones positivas y finitas.')
    if request.anchor=='right':area_left=bounds[2]-width
    elif request.anchor=='center':area_left=(bounds[0]+bounds[2]-width)/2
    else:area_left=bounds[0]
    area=(area_left,bounds[1],area_left+width,bounds[1]+height)
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc)
        if issues:raise EditError('\n'.join(issues))
        _safe_selection(doc[request.page],replace(model,issues=[i for i in model.issues if i!=CLIP_ISSUE]),selected,preserve_paint_order=True)
        rotation=doc[request.page].rotation
        doc[request.page].set_rotation(0)
        page_matrix=doc[request.page].transformation_matrix
        page_bounds=fitz.Rect(0,0,doc[request.page].cropbox.width,doc[request.page].cropbox.height)
        doc[request.page].set_rotation(rotation)
    if any(g.mode!=0 or not g.reliable for g in selected):raise EditError('Texto no visible o codificación ambigua.')
    if any(g.mode==3 and any(intersects(g.bbox,s.bbox) for s in selected) for g in model.glyphs):
        raise EditError('Capa OCR superpuesta: operación bloqueada.')
    reader,operations,shows,mapping=operator_glyph_map(data,request.page,model)
    if reader.trailer['/Root'].get('/StructTreeRoot'):raise EditError('Texto recortado: esta combinación con etiquetas accesibles necesita actualizar su semántica conjuntamente.')
    operation_ids={mapping[g.id]['operation'] for g in selected}
    if len(operation_ids)!=1:
        from .native_layout import edit_native_layout
        return edit_native_layout(data,request,model)
    operation=operation_ids.pop()
    show=next(s for s in shows if s['operation']==operation)
    args,op=operations[operation]
    if op not in (b'Tj',b'TJ') or show['render_mode']!=0:raise EditError('El texto usa un modo de pintura, recorte o salto no compatible; esta operación requiere texto visible normal.')
    font=show['font']
    if font.get('/Subtype') not in ('/TrueType','/Type1'):raise EditError('La fuente no usa códigos simples verificables en esta ruta de edición.')
    state=_state_at(operations,operation)
    matrix=state['matrix']
    if (state['size'] is None or not all(math.isfinite(v) for v in (state['size'],state['tc'],state['tw'],state['tz'],*matrix)) or
            state['size']<=0 or state['tz']<=0 or
            abs(matrix.b)+abs(matrix.c)>1e-7 or matrix.a<=0 or matrix.d<=0 or state['unknown']):
        raise EditError('El campo hereda un recorte de texto, un recorte complejo o una transformación no compatible; no se modificará su contenido.')
    catalog={}
    for candidate in shows:
        if (candidate['resource'],candidate['xref'])!=(show['resource'],show['xref']):continue
        a,o=operations[candidate['operation']]
        raw=b''.join(_raw(v) for _,v in _strings(a,o))
        if len(raw)!=len(candidate['glyphs']):continue
        for code,glyph in zip(raw,candidate['glyphs']):catalog.setdefault(glyph.text,set()).add(code)
    from .native_codes import verified_catalog
    catalog=verified_catalog(data,request.page,show,catalog,new_text)
    missing=sorted({c for c in new_text if len(catalog.get(c,set()))!=1})
    if missing:
        from .native_layout import edit_native_layout
        return edit_native_layout(data,request,model)
    new_codes=bytes(next(iter(catalog[c])) for c in new_text)
    original_codes=b''.join(_raw(v) for _,v in _strings(args,op))
    if len(original_codes)!=len(show['glyphs']):raise EditError('No es correspondencia uno a uno código/glifo.')
    ids=[g.id for g in show['glyphs']]
    first,last=ids.index(selected[0].id),ids.index(selected[-1].id)+1
    if ids[first:last]!=[g.id for g in selected] or len({g.line for g in selected})!=1:raise EditError('Selecciona un fragmento contiguo de una sola línea.')
    whole=first==0 and last==len(show['glyphs'])
    if request.line_reflow and not whole:
        raise EditError('Para ajustar un campo recortado selecciona su texto completo. Para editar sólo este fragmento desactiva Ajustar el resto de la línea; los vecinos conservarán su posición.')
    array=args[0] if op==b'TJ' else [args[0]]
    position=0
    internal=0.
    for value in array:
        if isinstance(value,(str,bytes)):position+=len(_raw(value))
        elif first<position<last:internal+=float(value)
    tf,tc,tw,tz=state['size'],state['tc'],state['tw'],state['tz']
    def advance(codes,chars):
        return sum(_advance(font,code,char)+1000*tc/tf+(1000*tw/tf if code==32 else 0) for code,char in zip(codes,chars))
    old_advance=advance(original_codes[first:last],text)-internal
    new_advance=advance(new_codes,new_text)
    ink_width=0.
    if new_codes:
        ink_width=(new_advance-1000*tc/tf-(1000*tw/tf if new_codes[-1]==32 else 0))*tf*tz/1000*matrix.a
    if request.anchor=='right':shift=bounds[2]-selected[0].origin[0]-ink_width
    elif request.anchor=='center':shift=(bounds[0]+bounds[2]-ink_width)/2-selected[0].origin[0]
    else:shift=0.
    pre_adjust=-shift/(tf*tz*matrix.a)*1000
    compensation=new_advance-old_advance-pre_adjust
    changed_array=ArrayObject()
    position=0
    inserted=False
    def emit_bytes(value):
        if value:changed_array.append(ByteStringObject(value))
    for value in array:
        if isinstance(value,(str,bytes)):
            for code in _raw(value):
                if position==first and not inserted:
                    if abs(pre_adjust)>1e-10:changed_array.append(FloatObject(pre_adjust))
                    emit_bytes(new_codes)
                    changed_array.append(FloatObject(compensation))
                    inserted=True
                if not first<=position<last:emit_bytes(bytes([code]))
                position+=1
        elif not first<position<last:changed_array.append(value)
    linear=fitz.Matrix(matrix)*page_matrix
    xvector=fitz.Point(1,0)*linear-fitz.Point(0,0)*linear
    cursor=0.
    template=selected[0]
    planned=[]
    for char,code in zip(new_text,new_codes):
        x,y0=template.origin[0]+shift+cursor*xvector.x,template.origin[1]+cursor*xvector.y
        width=_advance(font,code,char)/1000*tf*tz*xvector.x
        top,bottom=template.bbox[1]-template.origin[1],template.bbox[3]-template.origin[1]
        planned.append(replace(template,id=-1,text=char,origin=(x,y0),bbox=(x,y0+top,x+width,y0+bottom)))
        cursor+=(_advance(font,code,char)/1000*tf+tc+(tw if code==32 else 0))*tz
    if request.auto_width:
        actual=union(g.bbox for g in planned) if planned else (bounds[0],bounds[1],bounds[0]+.1,bounds[3])
        area=(actual[0],bounds[1],actual[2]+.025,bounds[1]+height)
    requested_area=fitz.Rect(area)
    clip=state['clip']*page_matrix if state['clip'] is not None else page_bounds
    selected_ids={g.id for g in selected}
    others=[g for g in model.glyphs if g.id not in selected_ids]
    for old in selected:
        if not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(old.bbox)):
            raise EditError('El texto original está parcialmente recortado; no se puede reconstruir su campo con garantías.')
    for g in planned:
        if not (requested_area+(-.035,-.035,.035,.035)).contains(fitz.Rect(g.bbox)) or not page_bounds.contains(fitz.Rect(g.bbox)) or not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(g.bbox)):
            raise EditError('El texto supera el espacio disponible o su recorte. Amplía la anchura del campo dentro de su columna.')
        if not getattr(request,'allow_overlap',False) and any(intersects(g.bbox,n.bbox,.12) for n in others):raise EditError('El texto nuevo se solapa con un vecino.')
    changed_ops=copy.deepcopy(operations)
    changed_ops[operation]=([changed_array],b'TJ')
    with fitz.open(stream=data,filetype='pdf') as doc:
        if planned:
            _safe_selection(doc[request.page],replace(model,issues=[i for i in model.issues if i!=CLIP_ISSUE]),planned,preserve_paint_order=True)
        xref=doc.get_new_xref();doc.update_object(xref,'<<>>');doc.update_stream(xref,_serialize(changed_ops));doc[request.page].set_contents(xref)
        output=full_write(doc)
    after=PdfReader(BytesIO(output),strict=True)
    new_ops=ContentStream(after.pages[request.page].get_contents(),after).operations
    if len(new_ops)!=len(operations):raise EditError('Cambió el número de operadores.')
    for i,((a,o),(b,p)) in enumerate(zip(operations,new_ops)):
        if i!=operation and (o!=p or _signature(a)!=_signature(b)):raise EditError('Cambió un operador ajeno al SHOW.')
    if _signature(reader.pages[request.page]['/Resources']['/Font'][show['resource']])!=_signature(after.pages[request.page]['/Resources']['/Font'][show['resource']]):
        raise EditError('Cambió la fuente.')
    expected=[(g.text,g.origin,g.font,g.size) for g in others+planned]
    report=validate_transition(data,output,request.page,expected,[g.bbox for g in selected+planned])
    report.update(original=text,replacement=new_text,selected_characters=len(selected),new_characters=len(planned),
                  untouched_characters=len(others),operator=operation,resource=show['resource'],xref=show['xref'],
                  tf=tf,tc=tc,tw=tw,tz=tz,compensation_tj=compensation,internal_tj_removed=internal,
                  matrix=list(matrix),clip_pdf=list(state['clip']) if state['clip'] is not None else None,
                  old_bounds=union(g.bbox for g in selected),new_bounds=union(g.bbox for g in planned),
                  cursor_residual=(new_advance-compensation-pre_adjust-old_advance)*tf*tz/1000,
                  source_sha256=hashlib.sha256(data).hexdigest(),font_unchanged=True)
    _assert_typography(output,request.page,others+planned)
    report.update(page=request.page,elapsed_seconds=round(time.perf_counter()-started,3),
                  source_regions=[g.bbox for g in selected],destination_regions=[g.bbox for g in planned],
                  font_resources=[{'resource':show['resource'],'xref':show['xref'],'base_font':str(font.get('/BaseFont',''))}],
                  fonts={str(font.get('/BaseFont','')):'Recurso PDF original '+show['resource']+' sin reincrustar'},
                  font_resources_unchanged=True,operators_preserved=True,
                  clipped_text_mode='Campo de longitud variable; fuente, recorte y cursor posterior conservados.',
                  line_reflow=False,line_reflow_requested=request.line_reflow,
                  layout_scope='Campo completo' if whole else 'Fragmento; vecinos fijos',
                  manual_format={'font':None,'size':None,'color':None})
    report['overlap_count']=len({n.id for g in planned for n in others if intersects(g.bbox,n.bbox,.12)})
    if report['overlap_count']:
        report.setdefault('warnings',[]).append('Solapamiento autorizado: el texto vecino conserva su contenido y posición.')
        report['warning']=report['warnings'][-1]
    return output,report


def move_clipped_text(data,request,model):
    """Traslada sólo SHOW seleccionados sin alterar códigos, TJ ni cursor.

    q/Q restauran el estado gráfico, pero no las matrices de posición textual.
    Por ello cm desplaza la pintura seleccionada mientras sus avances nativos
    siguen ejecutándose una sola vez; el siguiente carácter conserva su origen.
    El recorte ya establecido permanece fijo en coordenadas de página.
    """
    from .engine import _safe_selection,full_write
    started=time.perf_counter()
    if request.page!=model.number or (request.revision and request.revision!=hashlib.sha256(data).hexdigest()):
        raise EditError('La selección está desactualizada. Selecciona el texto de nuevo.')
    selected=model.selected(request.ids)
    if not selected or len(selected)!=len(set(request.ids)):
        raise EditError('Selecciona los caracteres que quieres mover.')
    if (request.font_name or request.font_file or request.color is not None or
            request.size is not None and any(abs(request.size-g.size)>.001 for g in selected) or request.reflow):
        raise EditError('Mover texto recortado conserva su formato. Cambia el formato en una operación independiente compatible.')
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (request.dx,request.dy)):
        raise EditError('El desplazamiento debe contener coordenadas finitas.')
    clean=replace(model,issues=[i for i in model.issues if i!=CLIP_ISSUE])
    dx,dy=request.dx,request.dy
    planned=[replace(g,origin=(g.origin[0]+dx,g.origin[1]+dy),
                     bbox=tuple(v+(dx if i%2==0 else dy) for i,v in enumerate(g.bbox)),
                     trace_bbox=tuple(v+(dx if i%2==0 else dy) for i,v in enumerate(g.trace_bbox))) for g in selected]
    selected_ids={g.id for g in selected}
    others=[g for g in model.glyphs if g.id not in selected_ids]
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc)
        if issues:raise EditError('\n'.join(issues))
        _safe_selection(doc[request.page],clean,selected,preserve_paint_order=True)
        _safe_selection(doc[request.page],clean,planned,preserve_paint_order=True)
        rotation=doc[request.page].rotation
        doc[request.page].set_rotation(0)
        page_matrix=doc[request.page].transformation_matrix
        page_bounds=fitz.Rect(0,0,doc[request.page].cropbox.width,doc[request.page].cropbox.height)
        doc[request.page].set_rotation(rotation)
    if not getattr(request,'allow_overlap',False) and any(intersects(g.bbox,n.bbox,.12) for g in planned for n in others):
        raise EditError('El texto movido se solapa con un vecino. Elige otra posición.')
    reader,operations,shows,mapping=operator_glyph_map(data,request.page,model)
    tagged_move=None
    if reader.trailer['/Root'].get('/StructTreeRoot'):
        from .tagged_clip_move import TaggedNativeMove
        tagged_move=TaggedNativeMove(data,request.page,model,selected)
    target_ops={mapping[g.id]['operation'] for g in selected}
    replacements={}
    resources={}
    for show in shows:
        operation=show['operation']
        if operation not in target_ops:continue
        args,op=operations[operation]
        if op not in (b'Tj',b'TJ') or show['render_mode']!=0:
            raise EditError('No se puede mover este operador: usa un salto o un modo de pintura/recorte de texto no compatible.')
        font=show['font']
        if font.get('/Subtype') in ('/TrueType','/Type1'):unit=1
        elif font.get('/Subtype')=='/Type0' and font.get('/Encoding')=='/Identity-H':unit=2
        else:raise EditError('El recurso usa una codificación variable que no permite aislar sus caracteres para moverlos.')
        array=args[0] if op==b'TJ' else [args[0]]
        raw=[_raw(value) for value in array if isinstance(value,(str,bytes))]
        if any(len(value)%unit for value in raw) or sum(len(value)//unit for value in raw)!=len(show['glyphs']):
            raise EditError('No se puede verificar la correspondencia entre códigos y caracteres del texto seleccionado.')
        state=_state_at(operations,operation)
        linear=state['ctm']*page_matrix
        if state['unknown'] or not all(math.isfinite(v) for v in linear) or abs(linear.a*linear.d-linear.b*linear.c)<1e-10:
            raise EditError('El texto hereda un recorte complejo o una transformación no verificable; no se puede mover con garantías.')
        clip=state['clip']*page_matrix if state['clip'] is not None else page_bounds
        originals=[g for g in show['glyphs'] if g.id in selected_ids]
        destinations=[g for g in planned if g.id in {s.id for s in originals}]
        for g in originals:
            if not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(g.bbox)):
                raise EditError('El texto original está parcialmente recortado; no se puede mover con garantías.')
        for g in destinations:
            if not page_bounds.contains(fitz.Rect(g.bbox)):
                raise EditError('La posición de destino queda fuera de la página.')
            if not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(g.bbox)):
                from .clip_move_v150 import move_text_with_clip
                return move_text_with_clip(data,request,model,(reader,operations,shows,mapping),tagged_move=tagged_move)
        inverse=~linear
        delta=fitz.Point(dx,dy)*inverse-fitz.Point(0,0)*inverse
        chunks=[]
        current=ArrayObject()
        moving=None
        position=0
        def flush():
            nonlocal current
            if current:chunks.append((moving,current));current=ArrayObject()
        for value in array:
            if isinstance(value,(str,bytes)):
                value=_raw(value)
                for offset in range(0,len(value),unit):
                    chosen=show['glyphs'][position].id in selected_ids
                    if moving is not None and chosen!=moving:flush()
                    moving=chosen
                    code=value[offset:offset+unit]
                    if current and isinstance(current[-1],bytes):current[-1]=ByteStringObject(bytes(current[-1])+code)
                    else:current.append(ByteStringObject(code))
                    position+=1
            else:current.append(copy.deepcopy(value))
        flush()
        changed=[]
        for chosen,chunk in chunks:
            if chosen:
                # Canonicalise only newly introduced numbers to the exact
                # precision written by pypdf. FitZ vectors use float32; their
                # in-memory value can differ from its PDF decimal spelling.
                # Original operands still undergo exact comparison below.
                translation=[FloatObject(FloatObject(v).myrepr()) for v in (1,0,0,1,delta.x,delta.y)]
                # An empty string has no glyphs, width, or cursor advance. It
                # also lets extractors observe the new CTM before the first
                # real substring, avoiding an invented space after its first
                # letter when the original TJ contains fine kerning entries.
                moving_chunk=ArrayObject([ByteStringObject(b''),*chunk])
                changed.extend([([],b'q'),(translation,b'cm'),
                                ([moving_chunk],b'TJ'),([],b'Q')])
            else:changed.append(([chunk],b'TJ'))
        replacements[operation]=changed
        resources[show['resource']]={'resource':show['resource'],'xref':show['xref'],
                                     'base_font':str(font.get('/BaseFont',''))}
    changed_ops=[]
    for index,item in enumerate(operations):changed_ops.extend(replacements.get(index,[copy.deepcopy(item)]))
    # Compare against the exact decimal spelling written by the PDF serializer.
    # FloatObject keeps more binary precision than its PDF representation:
    # comparing those in-memory doubles falsely rejects unchanged matrices.
    serialized=_serialize(changed_ops)
    from pypdf.generic import DecodedStreamObject
    expected_stream=DecodedStreamObject();expected_stream.set_data(serialized)
    expected_ops=ContentStream(expected_stream,reader).operations
    with fitz.open(stream=data,filetype='pdf') as doc:
        stream=doc.get_new_xref();doc.update_object(stream,'<<>>')
        doc.update_stream(stream,serialized);doc[request.page].set_contents(stream)
        output=full_write(doc)
    after=PdfReader(BytesIO(output),strict=True)
    actual_ops=ContentStream(after.pages[request.page].get_contents(),after).operations
    if len(actual_ops)!=len(expected_ops) or any(o!=p or _signature(a)!=_signature(b) for (a,o),(b,p) in zip(expected_ops,actual_ops)):
        raise EditError('La escritura alteró operadores ajenos al movimiento; operación cancelada.')
    if _signature(reader.pages[request.page]['/Resources'])!=_signature(after.pages[request.page]['/Resources']):
        raise EditError('La escritura alteró recursos compartidos; operación cancelada.')
    _assert_typography(output,request.page,others+planned)
    report=validate_transition(data,output,request.page,[(g.text,g.origin,g.font,g.size) for g in others+planned],
                               [g.bbox for g in selected+planned])
    if tagged_move:
        report['accessibility']=tagged_move.validate(output)
    report.update(page=request.page,elapsed_seconds=round(time.perf_counter()-started,3),
                  old_bounds=union(g.bbox for g in selected),new_bounds=union(g.bbox for g in planned),
                  source_regions=[g.bbox for g in selected],destination_regions=[g.bbox for g in planned],
                  changed_characters=0,moved_characters=len(selected),font_resources=list(resources.values()),
                  fonts={r['base_font']:'Recurso PDF original '+name+' sin reincrustar' for name,r in resources.items()},
                  font_resources_unchanged=True,operators_preserved=True,cursor_residual=0.,
                  clipped_text_mode='Movimiento nativo; códigos, ajustes TJ, recortes y cursor posterior conservados.',
                  clip_operators_preserved=sum(op in (b'W',b'W*') for _,op in operations),line_reflow=False,
                  manual_format={'font':None,'size':None,'color':None})
    report['overlap_count']=len({n.id for g in planned for n in others if intersects(g.bbox,n.bbox,.12)})
    if report['overlap_count']:
        report.setdefault('warnings',[]).append('Solapamiento autorizado: el texto vecino conserva su contenido y posición.')
        report['warning']=report['warnings'][-1]
    return output,report


def _assert_typography(data,page,glyphs):
    """Además de texto y píxeles, exige propiedades idénticas de cada glifo."""
    with fitz.open(stream=data,filetype='pdf') as doc:
        actual=[(chr(c[0]),c[2],s) for s in doc[page].get_texttrace() for c in s['chars']]
    groups={}
    for item in actual:groups.setdefault(item[0],[]).append(item)
    for glyph in glyphs:
        matches=groups.get(glyph.text,[])
        index=next((i for i,(_,origin,s) in enumerate(matches)
                    if all(abs(a-b)<.035 for a,b in zip(origin,glyph.origin)) and
                    s['font']==glyph.font and abs(s['size']-glyph.size)<.001 and
                    s['type']==glyph.mode and tuple(s['color'])==glyph.color and
                    abs(s['opacity']-glyph.opacity)<.001 and
                    all(abs(a-b)<1e-5 for a,b in zip(s['dir'],glyph.direction))),None)
        if index is None:raise EditError('La validación detectó cambios en tipografía, posición o modo de pintura.')
        matches.pop(index)
    if any(groups.values()):raise EditError('La validación detectó glifos añadidos inesperadamente.')
