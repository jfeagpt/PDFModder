"""Composición de texto nativo fragmentado sin redacción ni pérdida del cursor.

Los glifos retirados se sustituyen por sus avances TJ. El texto nuevo se pinta
con el mismo recurso, dentro de q/cm/Q, y deshace únicamente su propio avance.
Los siguientes operadores ven exactamente el cursor y estado gráfico originales.
"""
from dataclasses import replace
from io import BytesIO
import copy
import hashlib
import math
import struct
import time
import unicodedata

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, FloatObject, NameObject

from .clipping import CLIP_ISSUE, _advance, _raw, _serialize, _signature, _strings, operator_glyph_map
from .model import EditError, intersects, union
from .paragraphs import layout_lines
from .validation import document_issues, validate_transition


def _number(value):
    # Use exactly the decimal precision that will subsequently reach the PDF.
    return FloatObject(FloatObject(value).myrepr())


def _compact_adjustments(array):
    """Combine consecutive cursor-only advances before decimal serialization.

    Re-editing an inserted string retires both its glyph advances and its
    balancing TJ. Their sum is zero; accumulating hundreds of separate float
    steps in the renderer would otherwise introduce a small recurrent drift.
    """
    result=ArrayObject()
    pending=[]
    def flush():
        if pending:
            total=math.fsum(pending)
            if abs(total)>1e-7:
                result.append(_number(total))
            pending.clear()
    for value in array:
        if isinstance(value,(str,bytes)):
            flush()
            result.append(value)
        else:
            pending.append(float(value))
    flush()
    return result


def edit_native_layout(data, request, model):
    """Edit a homogeneous selection across SHOWs, including explicit new lines."""
    from .clipped_layout import _assert_typography, _state_at
    from .engine import _safe_selection, _safe_native_consolidation, full_write
    from .native_codes import verified_catalog
    started = time.perf_counter()
    if request.page != model.number or (request.revision and request.revision != hashlib.sha256(data).hexdigest()):
        raise EditError('La selección está desactualizada. Selecciona el texto de nuevo.')
    selected = model.selected(request.ids)
    if not selected or len(selected) != len(set(request.ids)) or request.text is None:
        raise EditError('Selecciona el campo de texto que quieres modificar.')
    if request.dx or request.dy:
        raise EditError('Compón el texto y después mueve el campo en una operación independiente.')
    template = selected[0]
    if request.size is not None and (not isinstance(request.size,(int,float)) or not math.isfinite(request.size) or not 1 <= request.size <= 300):
        raise EditError('El tamaño elegido debe estar entre 1 y 300 puntos.')
    if request.color is not None and (len(request.color)!=3 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in request.color)):
        raise EditError('El color elegido debe contener tres componentes RGB entre 0 y 1.')
    if request.anchor not in ('left', 'center', 'right'):
        raise EditError('Selecciona anclaje izquierdo, centrado o derecho.')
    for glyph in selected:
        if (glyph.font != template.font or abs(glyph.size-template.size) > .001 or
                glyph.color != template.color or abs(glyph.opacity-template.opacity) > .001 or
                glyph.mode != 0 or not glyph.reliable or glyph.direction != template.direction):
            raise EditError('La selección mezcla estilos. Selecciona un fragmento con la misma fuente, tamaño y color.')
    text = request.text.replace('\r\n', '\n').replace('\r', '\n')
    if any((unicodedata.category(c).startswith('C') and c != '\n') or unicodedata.combining(c) for c in text):
        raise EditError('No se admiten controles ni marcas combinantes; usa acentos precompuestos.')
    chosen_ids = {g.id for g in selected}
    others = [g for g in model.glyphs if g.id not in chosen_ids]
    if any(g.mode == 3 and any(intersects(g.bbox, s.bbox) for s in selected) for g in others):
        raise EditError('Hay una capa OCR superpuesta. Selecciona explícitamente cómo editar esa capa.')
    clean = replace(model, issues=[issue for issue in model.issues if issue != CLIP_ISSUE])
    with fitz.open(stream=data, filetype='pdf') as doc:
        issues = document_issues(data, doc)
        if issues:
            raise EditError('\n'.join(issues))
        page = doc[request.page]
        _safe_selection(page, clean, selected, preserve_paint_order=True)
        rotation = page.rotation
        page.set_rotation(0)
        page_matrix = page.transformation_matrix
        page_bounds = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        page.set_rotation(rotation)
    reader, operations, shows, mapping = operator_glyph_map(data, request.page, model)
    if reader.trailer['/Root'].get('/StructTreeRoot'):
        raise EditError('La composición de texto recortado y etiquetado requiere actualizar sus relaciones semánticas.')
    targets = {mapping[g.id]['operation'] for g in selected}
    first_op = mapping[template.id]['operation']
    by_operation = {show['operation']: show for show in shows}
    first_show = by_operation[first_op]
    font = first_show['font']
    if font.get('/Subtype') not in ('/TrueType', '/Type1'):
        raise EditError('Esta fuente necesita una tabla de códigos verificable para componer el texto nuevo.')
    resources=reader.pages[request.page]['/Resources'].get_object()
    first_state = _state_at(operations, first_op, resources)
    matrix = first_state['matrix']
    if (first_state['size'] is None or first_state['size'] <= 0 or first_state['tz'] <= 0 or
            abs(matrix.b)+abs(matrix.c) > 1e-7 or matrix.a <= 0 or matrix.d <= 0 or first_state['unknown']):
        raise EditError('La selección utiliza una transformación o un recorte complejo no compatible.')
    tf, tc, tw, tz = [first_state[key] for key in ('size', 'tc', 'tw', 'tz')]
    original_tf = tf
    if not all(math.isfinite(v) for v in (tf, tc, tw, tz, *matrix)):
        raise EditError('El estado de texto contiene una transformación no finita.')
    linear = first_state['ctm'] * page_matrix
    xscale = matrix.a
    states = {}
    for operation in targets:
        show = by_operation[operation]
        args, op = operations[operation]
        state = _state_at(operations, operation, resources)
        states[operation] = state
        if (op not in (b'Tj', b'TJ') or show['render_mode'] != 0 or state['unknown'] or state['size'] is None or
                _signature(show['font']) != _signature(font) or
                any(abs(state[key]-first_state[key]) > 1e-7 for key in ('size', 'tc', 'tw', 'tz')) or
                any(abs(a-b) > 1e-7 for a, b in zip(tuple(state['matrix'])[:4], tuple(matrix)[:4]))):
            raise EditError('Los fragmentos usan estados de texto distintos. Selecciona un estilo uniforme.')
        raw = b''.join(_raw(value) for _, value in _strings(args, op))
        if len(raw) != len(show['glyphs']):
            raise EditError('No se puede comprobar la correspondencia de códigos y glifos de los fragmentos.')
        clip = state['clip'] * page_matrix if state['clip'] is not None else page_bounds
        if any(not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(g.bbox)) for g in show['glyphs'] if g.id in chosen_ids):
            raise EditError('El texto original está parcialmente oculto por su recorte.')
    catalog = {}
    for show in shows:
        if (show['resource'], show['xref']) != (first_show['resource'], first_show['xref']):
            continue
        args, op = operations[show['operation']]
        raw = b''.join(_raw(value) for _, value in _strings(args, op))
        if len(raw) == len(show['glyphs']):
            for code, glyph in zip(raw, show['glyphs']):
                catalog.setdefault(glyph.text, set()).add(code)
    catalog = verified_catalog(data, request.page, first_show, catalog, text.replace('\n',''))
    missing = sorted({c for c in text if c != '\n' and len(catalog.get(c, set())) != 1})
    extension = None
    working_data = data
    if (missing or request.font_name or request.font_file) and text.replace('\n',''):
        from .native_font_extension import prepare_native_font
        from .fonts import FontError
        try:
            extension = prepare_native_font(data,request.page,first_show,text,
                                            font_name=request.font_name,font_file=request.font_file)
        except FontError as exc:
            prefix=('Sin código único verificable en el mismo recurso de fuente para '+
                    ', '.join('«'+c+'»' for c in missing)+'. ') if missing else ''
            raise EditError(prefix+str(exc)) from exc
        working_data, font, catalog = extension.data, extension.font, extension.catalog
    desired_size=request.size if request.size is not None else template.size
    size_ratio=desired_size/template.size
    tf=original_tf*size_ratio
    codes = {char: next(iter(values)) for char, values in catalog.items() if len(values) == 1}
    def advance(char):
        code = codes[char]
        return _advance(font, code, char)+1000*tc/tf+(1000*tw/tf if code == 32 else 0)
    def measure(value):
        if not value:
            return 0.
        last = codes[value[-1]]
        return (sum(advance(c) for c in value)-1000*tc/tf-(1000*tw/tf if last == 32 else 0))*tf*tz*xscale/1000
    bounds = union(g.bbox for g in selected)
    width = request.width if request.width is not None else bounds[2]-bounds[0]
    if request.auto_width and not request.reflow:
        width = max([.1, *[measure(line) for line in text.split('\n')]])
    line_height = request.line_spacing if request.line_spacing is not None else max(desired_size*1.2, (bounds[3]-bounds[1])*size_ratio if len({g.line for g in selected}) == 1 else desired_size*1.2)
    if not isinstance(width, (int,float)) or not math.isfinite(width) or width <= 0:
        raise EditError('La anchura del área debe ser positiva y finita.')
    lines = layout_lines(text, measure, width, request.reflow, line_height, request.paragraph_spacing)
    top = (template.bbox[1]-template.origin[1])*size_ratio
    bottom = (template.bbox[3]-template.origin[1])*size_ratio
    rgb=tuple(struct.unpack('f',struct.pack('f',v))[0] for v in request.color) if request.color is not None else template.color
    template = replace(template,size=desired_size,color=rgb)
    if extension:
        template = replace(template,font=extension.rendered_name)
        top,bottom = (ratio*template.size for ratio in extension.bbox_ratios)
    required_height = max([bottom-top, *[dy+bottom-top for _, dy in lines]])
    height = request.height if request.height is not None else required_height
    if getattr(request,'auto_height',False):
        height = max(height, required_height)
    if not isinstance(height, (int,float)) or not math.isfinite(height) or height <= 0:
        raise EditError('La altura del área debe ser positiva y finita.')
    if required_height > height+.035:
        raise EditError('El texto supera la altura disponible. Amplía el área o reduce el interlineado manualmente.')
    area_left = bounds[2]-width if request.anchor == 'right' else ((bounds[0]+bounds[2]-width)/2 if request.anchor == 'center' else bounds[0])
    baseline = selected[0].origin[1]
    area = (area_left, baseline+top, area_left+width, baseline+top+height)
    insertion = []
    planned = []
    inverse = ~linear
    clip = first_state['clip']*page_matrix if first_state['clip'] is not None else page_bounds
    for line, dy in lines:
        actual_width = measure(line)
        start_x = area_left+width-actual_width if request.anchor == 'right' else (area_left+(width-actual_width)/2 if request.anchor == 'center' else area_left)
        start_y = baseline+dy
        delta = fitz.Point(start_x-template.origin[0], start_y-template.origin[1])*inverse-fitz.Point(0,0)*inverse
        line_codes = bytes(codes[c] for c in line)
        if line_codes:
            array = ArrayObject([ByteStringObject(b''), ByteStringObject(line_codes), _number(sum(advance(c) for c in line))])
            insertion.extend([([],b'q'),([_number(v) for v in (1,0,0,1,delta.x,delta.y)],b'cm')])
            if extension or size_ratio!=1:
                insertion.append(([NameObject(extension.resource if extension else first_show['resource']),_number(tf)],b'Tf'))
            if request.color is not None:
                insertion.append(([_number(v) for v in request.color],b'rg'))
            insertion.extend([([array],b'TJ'),([],b'Q')])
        cursor = 0.
        for char in line:
            x = start_x+cursor*tf*tz*xscale/1000
            char_width = _advance(font,codes[char],char)*tf*tz*xscale/1000
            bbox = (x,start_y+top,x+char_width,start_y+bottom)
            glyph = replace(template,id=-1,text=char,origin=(x,start_y),bbox=bbox,trace_bbox=bbox)
            if not page_bounds.contains(fitz.Rect(bbox)) or not (clip+(-.02,-.02,.02,.02)).contains(fitz.Rect(bbox)):
                raise EditError('La nueva línea queda fuera de la página o de su recorte. Amplía el área dentro de la zona visible.')
            if not getattr(request,'allow_overlap',False) and any(intersects(bbox,n.bbox,.12) for n in others):
                raise EditError('El texto nuevo se solapa con un vecino. Mueve el área o permite el solapamiento explícitamente.')
            planned.append(glyph)
            cursor += advance(char)
    replacements = {}
    for operation in targets:
        show = by_operation[operation]
        args, op = operations[operation]
        source_array = args[0] if op == b'TJ' else [args[0]]
        changed_array = ArrayObject()
        changed_ops = []
        position = 0
        def flush():
            nonlocal changed_array
            if changed_array:
                changed_ops.append(([_compact_adjustments(changed_array)],b'TJ'))
                changed_array = ArrayObject()
        for value in source_array:
            if isinstance(value,(str,bytes)):
                for code in _raw(value):
                    glyph = show['glyphs'][position]
                    if glyph.id == template.id:
                        flush()
                        changed_ops.extend(copy.deepcopy(insertion))
                    if glyph.id in chosen_ids:
                        step = _advance(show['font'],code,glyph.text)+1000*tc/original_tf+(1000*tw/original_tf if code == 32 else 0)
                        changed_array.append(FloatObject(-step))
                    elif changed_array and isinstance(changed_array[-1],bytes):
                        changed_array[-1] = ByteStringObject(bytes(changed_array[-1])+bytes([code]))
                    else:
                        changed_array.append(ByteStringObject(bytes([code])))
                    position += 1
            else:
                changed_array.append(copy.deepcopy(value))
        flush()
        replacements[operation] = changed_ops
    changed_ops = []
    for index, item in enumerate(operations):
        changed_ops.extend(replacements.get(index,[copy.deepcopy(item)]))
    with fitz.open(stream=working_data,filetype='pdf') as doc:
        if planned:
            _safe_selection(doc[request.page],clean,planned,preserve_paint_order=True)
            _safe_native_consolidation(doc[request.page],selected,planned)
        stream = doc.get_new_xref()
        doc.update_object(stream,'<<>>')
        doc.update_stream(stream,_serialize(changed_ops))
        doc[request.page].set_contents(stream)
        output = full_write(doc)
    after = PdfReader(BytesIO(output),strict=True)
    actual_ops = ContentStream(after.pages[request.page].get_contents(),after).operations
    if len(actual_ops) != len(changed_ops) or any(o != p or _signature(a) != _signature(b) for (a,o),(b,p) in zip(changed_ops,actual_ops)):
        raise EditError('La escritura alteró operadores ajenos al campo seleccionado.')
    original_resources=reader.pages[request.page]['/Resources']
    final_resources=after.pages[request.page]['/Resources']
    if extension:
        for key,value in original_resources.items():
            if key=='/Font':
                for name,original_font in value.get_object().items():
                    if _signature(original_font)!=_signature(final_resources['/Font'][name]):
                        raise EditError('La escritura alteró una fuente original compartida.')
            elif _signature(value)!=_signature(final_resources[key]):
                raise EditError('La escritura alteró recursos ajenos a la fuente elegida.')
        if _signature(final_resources['/Font'][extension.resource])!=_signature(extension.font):
            raise EditError('La nueva fuente no conserva el programa y códigos comprobados.')
    elif _signature(original_resources) != _signature(final_resources):
        raise EditError('La escritura alteró recursos compartidos.')
    _assert_typography(output,request.page,others+planned)
    report = validate_transition(data,output,request.page,[(g.text,g.origin,g.font,g.size) for g in others+planned],[g.bbox for g in selected+planned])
    report.update(page=request.page,elapsed_seconds=round(time.perf_counter()-started,3),
                  old_bounds=bounds,new_bounds=union(g.bbox for g in planned),
                  source_regions=[g.bbox for g in selected],destination_regions=[g.bbox for g in planned],
                  original=model.text(request.ids),replacement=text,selected_characters=len(selected),new_characters=len(planned),
                  untouched_characters=len(others),font_resources_unchanged=True,operators_preserved=True,
                  clip_operators_preserved=sum(op in (b'W',b'W*') for _,op in operations),
                  source_operations=len(targets),cursor_residual=0.,area_width=width,area_height=height,
                  auto_height=bool(getattr(request,'auto_height',False)),
                  line_count=len(lines),line_spacing=line_height,paragraph_spacing=request.paragraph_spacing,
                  font_resources=[{'resource':first_show['resource'],'xref':first_show['xref'],'base_font':str(first_show['font'].get('/BaseFont',''))}],
                  fonts={str(font.get('/BaseFont','')):'Recurso PDF original '+first_show['resource']+' sin reincrustar'},
                  clipped_text_mode='Composición nativa de fragmentos y líneas; recursos, recortes y cursores conservados.',
                  line_reflow=False,paragraph_layout=request.reflow,line_reflow_requested=request.line_reflow,
                  layout_scope='Campo seleccionado; vecinos fijos',
                  manual_format={'font':None,'size':request.size,'color':request.color})
    if extension:
        report.update(font_extension=extension.evidence,original_font_resources_unchanged=True,
                      font_resources_unchanged=False,
                      fonts={extension.rendered_name:extension.evidence['identity_basis']},
                      manual_format={'font':request.font_name or request.font_file,'size':request.size,'color':request.color})
        final_font=final_resources['/Font'][extension.resource]
        report['font_resources'].append({'resource':extension.resource,
            'xref':getattr(getattr(final_font,'indirect_reference',None),'idnum',None),
            'base_font':str(final_font.get('/BaseFont',''))})
        if extension.evidence['explicit']:
            report['warning']='Fuente elegida explícitamente: '+extension.rendered_name+'. La identidad con la fuente original no se presupone.'
    report['overlap_count']=len({n.id for g in planned for n in others if intersects(g.bbox,n.bbox,.12)})
    if report['overlap_count']:
        report.setdefault('warnings',[]).append('Solapamiento autorizado: el texto vecino conserva su contenido y posición.')
        report['warning']=' '.join(filter(None,[report.get('warning'),report['warnings'][-1]]))
    return output,report
