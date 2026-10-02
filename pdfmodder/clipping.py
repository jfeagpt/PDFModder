"""Sustituciones conservadoras en contenido recortado, sin quitar recortes.

Se interpretan operadores con pypdf. Un sondeo RGB efímero relaciona cada glifo
con su operador y recurso real; nunca se exporta ese sondeo. La única mutación
admitida mantiene cantidad de códigos y avances PDF, usando códigos ya vistos
en el mismo recurso de fuente. No elimina OCR ni reconstruye contornos.
"""
from dataclasses import fields, replace
from io import BytesIO
import copy
import hashlib
import time

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ByteStringObject, ContentStream, DecodedStreamObject, FloatObject, NameObject, NumberObject

from .model import EditError, intersects, union

CLIP_ISSUE = 'Página con recortes gráficos explícitos: no se puede reconstruir el texto con seguridad.'
SHOW = {b'Tj', b'TJ', b"'", b'"'}


def _fail(message):
    raise EditError('Texto recortado: '+message)


def _serialize(operations):
    source = DecodedStreamObject()
    source.set_data(b'')
    stream = ContentStream(source,None)
    stream.operations = operations
    return stream.get_data()


def _raw(value):
    if isinstance(value,bytes):
        return bytes(value)
    if isinstance(value,str) and hasattr(value,'original_bytes'):
        # pypdf preserves the actual bytes here. get_original_bytes() may
        # reconstruct UTF-16 and add a BOM absent from a CID text operand.
        return value.original_bytes
    _fail('el operador contiene una cadena cuya codificación original no se puede recuperar.')


def _strings(args,op):
    if op == b'TJ':
        return [(index,value) for index,value in enumerate(args[0]) if isinstance(value,(str,bytes))]
    position = 2 if op == b'"' else 0
    return [(position,args[position])]


def _font_reference(resource):
    pointer = getattr(resource,'indirect_reference',resource)
    return getattr(pointer,'idnum',None)


def _signature(value,depth=0):
    """Identidad semántica de operandos y recursos, independiente del xref."""
    if depth>30:
        _fail('un recurso contiene una estructura recursiva no verificable.')
    value=value.get_object() if hasattr(value,'get_object') else value
    if isinstance(value,NameObject):
        return ('name',str(value))
    if isinstance(value,(str,bytes)):
        return ('string',_raw(value).hex())
    if isinstance(value,dict):
        stream=hasattr(value,'get_data')
        excluded={'/Length','/Filter','/DecodeParms'} if stream else set()
        properties=tuple(sorted((str(k),_signature(v,depth+1)) for k,v in value.items() if k not in excluded))
        return ('stream',hashlib.sha256(value.get_data()).hexdigest(),properties) if stream else properties
    if isinstance(value,(list,tuple)):
        return tuple(_signature(v,depth+1) for v in value)
    return value


def operator_glyph_map(data,number,model):
    """Relaciona glifos y Tf por color de cada SHOW, sin interpretar su texto."""
    reader = PdfReader(BytesIO(data),strict=True)
    page = reader.pages[number]
    operations = ContentStream(page.get_contents(),reader).operations
    fonts = page.get('/Resources',{}).get('/Font',{})
    fonts = fonts.get_object() if hasattr(fonts,'get_object') else fonts
    stack,resource,shows = [],None,{}
    render_mode = 0
    probing = []
    for index,(args,op) in enumerate(operations):
        if op == b'q':
            stack.append((resource,render_mode))
        elif op == b'Q':
            if not stack:
                _fail('el estado gráfico contiene un cierre Q sin apertura.')
            resource,render_mode = stack.pop()
        elif op == b'Tf':
            resource = args[0]
        elif op == b'Tr':
            render_mode = int(args[0])
        if op in SHOW:
            if resource not in fonts:
                _fail('no se puede identificar el recurso de una operación de texto.')
            marker = len(shows)+1
            if marker >= 0xffffff:
                _fail('la página contiene demasiadas operaciones de texto para verificarla.')
            rgb = [FloatObject(v/255) for v in ((marker>>16)&255,(marker>>8)&255,marker&255)]
            probing.extend([(rgb,b'rg'),(rgb,b'RG')])
            # MuPDF reports invisible text with a black color regardless of rg.
            # Reveal it only in this ephemeral probe, restoring Tr immediately;
            # original character count/text/positions still must match exactly.
            if render_mode==3:
                probing.append(([NumberObject(0)],b'Tr'))
            shows[marker] = {'operation':index,'resource':str(resource),
                             'xref':_font_reference(fonts[resource]),
                             'render_mode':render_mode,
                             'font':fonts[resource].get_object(),'glyphs':[]}
        probing.append((args,op))
        if op in SHOW and render_mode==3:
            probing.append(([NumberObject(3)],b'Tr'))
    if stack:
        _fail('el estado gráfico contiene una apertura q sin cierre.')
    with fitz.open(stream=data,filetype='pdf') as probe:
        xref = probe.get_new_xref()
        probe.update_object(xref,'<<>>')
        probe.update_stream(xref,_serialize(probing))
        probe[number].set_contents(xref)
        glyphs = [(chr(c[0]),c[2],span['color']) for span in probe[number].get_texttrace() for c in span['chars']]
    if len(glyphs) != len(model.glyphs):
        _fail('el sondeo de recursos no conserva el número de caracteres.')
    mapping = {}
    for glyph,(text,point,color) in zip(model.glyphs,glyphs):
        if text != glyph.text or any(abs(a-b)>.035 for a,b in zip(point,glyph.origin)) or len(color)!=3:
            _fail('el sondeo no conserva texto y posiciones; no se puede identificar la fuente exacta.')
        marker = (round(color[0]*255)<<16)|(round(color[1]*255)<<8)|round(color[2]*255)
        if marker not in shows:
            _fail('un carácter no pertenece a una operación de texto verificable.')
        show = shows[marker]
        mapping[glyph.id] = {'operation':show['operation'],'font_xref':show['xref'],
                             'font_resource':show['resource'],'render_mode':show['render_mode']}
        show['glyphs'].append(glyph)
    return reader,operations,list(shows.values()),mapping


def annotate_font_resources(data,number,model):
    """Identidad del recurso PDF para el inspector; un fallo deja datos ausentes."""
    if not model.glyphs or not {'font_xref','font_resource'} <= {f.name for f in fields(model.glyphs[0])}:
        return model
    try:
        _,_,_,mapping = operator_glyph_map(data,number,model)
    except Exception:
        return model
    return replace(model,glyphs=[replace(g,font_xref=mapping[g.id]['font_xref'],
                                           font_resource=mapping[g.id]['font_resource']) for g in model.glyphs])


def _advance(font,code,text):
    widths = font.get('/Widths')
    if widths is not None:
        widths = widths.get_object()
        first = int(font.get('/FirstChar',0))
        if first <= code < first+len(widths) and float(widths[code-first]) > 0:
            return float(widths[code-first])
        _fail('falta un avance explícito y válido para el código de fuente solicitado.')
    from .fonts import BASE14
    base = str(font.get('/BaseFont','')).lstrip('/')
    if base in BASE14:
        return fitz.get_text_length(text,fontname=BASE14[base],fontsize=1000)
    _fail('esta fuente no declara avances verificables de sus caracteres.')


def edit_clipped_text(data,request,model):
    """Copia y cambia sólo códigos de ancho idéntico en sus operadores originales."""
    from .engine import _safe_selection,full_write
    from .validation import validate_transition
    started = time.perf_counter()
    selected = model.selected(request.ids)
    if not selected or len(selected) != len(set(request.ids)):
        _fail('selecciona una palabra o fecha de la versión actual.')
    if request.text is None or ((request.dx or request.dy) and request.text==''.join(g.text for g in selected)):
        from .clipped_layout import move_clipped_text
        return move_clipped_text(data,request,model)
    if request.font_name or request.font_file or request.color is not None or (request.size is not None and any(abs(request.size-g.size)>.001 for g in selected)):
        from .native_layout import edit_native_layout
        return edit_native_layout(data,request,model)
    if request.text is not None and (len(request.text)!=len(selected) or '\n' in request.text or '\r' in request.text or request.reflow or request.line_spacing is not None or request.paragraph_spacing):
        from .clipped_layout import edit_clipped_layout
        return edit_clipped_layout(data,request,model)
    if request.text is None or len(request.text) != len(selected) or '\n' in request.text or request.reflow:
        _fail('en esta página sólo se pueden sustituir caracteres conservando su cantidad y avances. No se amplía ni redistribuye texto recortado.')
    if request.dx or request.dy or request.font_name or request.font_file or request.color is not None:
        _fail('mover o cambiar el formato requiere reconstruir el recorte y todavía no está habilitado.')
    if request.size is not None and any(abs(request.size-g.size)>.001 for g in selected):
        _fail('el tamaño debe conservarse exactamente dentro del recorte.')
    bounds = union(g.bbox for g in selected)
    area_changed=((not request.auto_width and request.width is not None and abs(request.width-(bounds[2]-bounds[0]))>.04) or
                  (request.height is not None and abs(request.height-(bounds[3]-bounds[1]))>.04))
    if len({g.line for g in selected})!=1 or any(b.id!=a.id+1 for a,b in zip(selected,selected[1:])):
        _fail('selecciona un fragmento contiguo de una sola línea.')
    with fitz.open(stream=data,filetype='pdf') as source:
        _safe_selection(source[request.page],replace(model,issues=[i for i in model.issues if i!=CLIP_ISSUE]),selected,preserve_paint_order=True)
    selected_ids = {g.id for g in selected}
    changed = {g.id:text for g,text in zip(selected,request.text) if g.text!=text}
    if any(g.mode!=0 or g.opacity<=0 for g in selected):
        _fail('la selección incluye texto invisible o una capa OCR.')
    if any(other.mode==3 and any(intersects(other.bbox,g.bbox,.12) for g in selected if g.id in changed)
           for other in model.glyphs if other.id not in selected_ids):
        _fail('hay texto OCR invisible superpuesto. Actualiza explícitamente esa capa antes de cambiar el texto visible; no se dejará una fecha antigua oculta.')
    reader,operations,shows,mapping = operator_glyph_map(data,request.page,model)
    if reader.trailer['/Root'].get('/StructTreeRoot'):
        _fail('la combinación de recortes y etiquetas accesibles necesita actualizar su semántica conjuntamente; esta ruta todavía no admite documentos etiquetados.')
    locations,codes = {},{}
    for show in shows:
        font = show['font']
        if font.get('/Subtype') not in ('/TrueType','/Type1'):
            continue
        args,op = operations[show['operation']]
        strings = _strings(args,op)
        raw = [(index,_raw(value)) for index,value in strings]
        if sum(len(value) for _,value in raw) != len(show['glyphs']):
            continue
        position = 0
        for index,value in raw:
            for offset,code in enumerate(value):
                glyph = show['glyphs'][position]
                locations[glyph.id] = (show,index,offset,code)
                codes.setdefault((show['resource'],show['xref'],glyph.text),set()).add(code)
                position += 1
    # Missing from this page does not mean missing from this same PDF font.
    # Resolve only declared and independently probed codes, never guesses.
    from .native_codes import verified_catalog
    for show in shows:
        key=(show['resource'],show['xref'])
        needed={changed[g.id] for g in selected if g.id in changed and g.id in locations
                and (locations[g.id][0]['resource'],locations[g.id][0]['xref'])==key}
        if not needed:continue
        observed={char:values for (resource,xref,char),values in codes.items() if (resource,xref)==key}
        for char,values in verified_catalog(data,request.page,show,observed,needed).items():
            codes[(*key,char)]=values
    result = copy.deepcopy(operations)
    replacements = {}
    resources = {}
    for glyph in selected:
        if glyph.id not in changed:
            continue
        if glyph.id not in locations:
            _fail('la fuente del carácter no usa códigos simples de un byte verificables.')
        show,index,offset,old_code = locations[glyph.id]
        if show['render_mode']!=0:
            _fail('el glifo usa un modo de pintura o recorte de texto Tr='+str(show['render_mode'])+'; sólo se sustituyen glifos con Tr=0.')
        candidates = codes.get((show['resource'],show['xref'],changed[glyph.id]),set())
        if len(candidates)!=1:
            from .native_layout import edit_native_layout
            return edit_native_layout(data,request,model)
        code = next(iter(candidates))
        if abs(_advance(show['font'],old_code,glyph.text)-_advance(show['font'],code,changed[glyph.id]))>.001:
            from .clipped_layout import edit_clipped_layout
            return edit_clipped_layout(data,request,model)
        key = (show['operation'],index)
        args,op = operations[show['operation']]
        old_string = args[0][index] if op==b'TJ' else args[index]
        replacements.setdefault(key,bytearray(_raw(old_string)))[offset] = code
        resources[show['resource']] = {'resource':show['resource'],'xref':show['xref'],
                                      'base_font':str(show['font'].get('/BaseFont','')),
                                      'subtype':str(show['font'].get('/Subtype',''))}
    if area_changed:
        _fail('no se puede cambiar el área de edición de un recorte existente cuando sus caracteres conservan los avances.')
    for (operation,index),value in replacements.items():
        args,op = result[operation]
        if op==b'TJ':
            args[0][index] = ByteStringObject(bytes(value))
        else:
            args[index] = ByteStringObject(bytes(value))
    with fitz.open(stream=data,filetype='pdf') as doc:
        page = doc[request.page]
        stream = doc.get_new_xref()
        doc.update_object(stream,'<<>>')
        doc.update_stream(stream,_serialize(result))
        page.set_contents(stream)  # New page-local stream, never mutate a shared stream.
        output = full_write(doc)
    independent=PdfReader(BytesIO(output),strict=True)
    actual_operations=ContentStream(independent.pages[request.page].get_contents(),independent).operations
    if (len(result)!=len(actual_operations) or
            any(op!=newop or _signature(args)!=_signature(newargs)
                for (args,op),(newargs,newop) in zip(result,actual_operations))):
        _fail('la escritura alteró operadores, matrices, ajustes o recortes ajenos a la sustitución.')
    before_fonts=reader.pages[request.page]['/Resources']['/Font']
    after_fonts=independent.pages[request.page]['/Resources']['/Font']
    for resource in resources:
        if resource not in after_fonts or _signature(before_fonts[resource])!=_signature(after_fonts[resource]):
            _fail('la escritura alteró la fuente original, sus avances o su codificación.')
    expected = [(changed.get(g.id,g.text),g.origin,g.font,g.size) for g in model.glyphs]
    regions = [g.bbox for g in selected if g.id in changed]
    report = validate_transition(data,output,request.page,expected,regions)
    # Content order, typography and invisible layers must remain identical;
    # only the explicitly requested visible character values may differ.
    with fitz.open(stream=output,filetype='pdf') as after:
        actual = [(chr(c[0]),tuple(c[2]),span) for span in after[request.page].get_texttrace() for c in span['chars']]
        if len(actual)!=len(model.glyphs):
            _fail('cambió la cantidad de glifos tras la escritura completa.')
        for original,(text,point,span) in zip(model.glyphs,actual):
            if (text!=changed.get(original.id,original.text) or span['font']!=original.font or
                    abs(span['size']-original.size)>.001 or span['type']!=original.mode or
                    tuple(span['color'])!=original.color or abs(span['opacity']-original.opacity)>.001 or
                    any(abs(a-b)>.035 for a,b in zip(point,original.origin))):
                _fail('la validación detectó cambios ajenos en tipografía, posición o capas de texto.')
    report.update({'page':request.page,'elapsed_seconds':round(time.perf_counter()-started,3),
                   'old_bounds':bounds,'new_bounds':bounds,
                   'source_regions':regions,
                   'destination_regions':regions,
                   'changed_regions':regions,'changed_characters':len(changed),
                   'font_resources_unchanged':True,'operators_preserved':True,
                   'clip_operators_preserved':sum(op in (b'W',b'W*') for _,op in operations),
                   'font_resources':list(resources.values()),
                   'fonts':{r['base_font']:'Recurso PDF original '+name+' sin reincrustar' for name,r in resources.items()},
                   'clipped_text_mode':'Códigos de igual avance; recursos, TJ, matrices y recortes originales conservados.',
                   'line_reflow':False,'manual_format':{'font':None,'size':None,'color':None}})
    return output,report
