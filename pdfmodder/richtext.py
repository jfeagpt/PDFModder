"""Edición rica mediante operadores PDF, sin tapar ni rasterizar el texto.

Cada glifo retirado se cambia por su avance TJ; el cursor de los operadores
vecinos se conserva. Los glifos nuevos usan recursos verificados y restauran
su avance. La maquetación devuelve las mismas posiciones que escribe al PDF.
"""
from dataclasses import asdict, replace
from io import BytesIO
import copy
import hashlib
import json
import math
import struct
import time
import unicodedata

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, NameObject, TextStringObject

from .clipping import CLIP_ISSUE, _advance, _raw, _serialize, _signature, _strings, operator_glyph_map
from .clipped_layout import _state_at, _assert_typography
from .engine import extract_page, full_write, _safe_selection, _safe_native_consolidation, validate_rgb
from .fonts import FontResolver, FontError, _font_metadata, normalized_name
from .model import EditError, Glyph, intersects, union
from .native_layout import _number, _compact_adjustments
from .richmodels import RichTextRequest

_BREAKS = '\n\u2028\t'
_META_KEY = 'PDFModderRichText'


def _read_metadata(doc, page):
    kind, value = doc.xref_get_key(doc[page].xref, _META_KEY)
    if kind != 'string':
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def _match(g, record):
    return (record.get('text') == g.text and
            all(abs(a-b) < .025 for a,b in zip(record.get('origin', (1e9,1e9)), g.origin)))


def has_rich_metadata(data, page):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return bool(_read_metadata(doc, page))


def _locate_underlines(operations, records):
    """A preceding native edit can shift indexes without changing our paths."""
    cache = {}
    for record in records:
        for item in record.get('underlines', []):
            start, length = item['start'], item['length']
            def digest(index):
                key = (index, length)
                if key not in cache:
                    cache[key] = hashlib.sha256(_serialize(operations[index:index+length])).hexdigest()
                return cache[key]
            if start >= 0 and start+length <= len(operations) and digest(start) == item['sha256']:
                continue
            candidates = [i for i in range(len(operations)-length+1) if digest(i) == item['sha256']]
            if len(candidates) != 1:
                raise EditError('El subrayado cambió fuera del editor o es ambiguo; no se puede aislar con garantías.')
            item['start'] = candidates[0]


def _surviving_records(record, removed):
    """Split logical metadata as well as glyphs; never retain replaced words."""
    glyphs = record.get('glyphs', [])
    groups = []
    for position, (glyph, deleted) in enumerate(zip(glyphs, removed)):
        if deleted:
            continue
        if groups and groups[-1][-1][0] == position-1:
            groups[-1].append((position, glyph))
        else:
            groups.append([(position, glyph)])
    result = []
    text = record.get('text', '')
    for group in groups:
        begin, end = group[0][0], group[-1][0]+1
        first = 0 if begin == 0 else group[0][1]['index']
        last = glyphs[end]['index'] if end < len(glyphs) else len(text)
        kept = [copy.deepcopy(g) for _, g in group]
        old_indices = {g['index'] for g in kept}
        underlines = [copy.deepcopy(item) for item in record.get('underlines', []) if item['index'] in old_indices]
        for item in kept+underlines:
            item['index'] -= first
        paragraph_start = text[:first].count('\n')
        paragraph_end = paragraph_start+text[first:last].count('\n')
        paragraphs = []
        for paragraph in record.get('paragraphs', []):
            if 'index' not in paragraph:
                paragraphs.append(copy.deepcopy(paragraph))
            elif paragraph_start <= paragraph['index'] <= paragraph_end:
                paragraphs.append(dict(paragraph, index=paragraph['index']-paragraph_start))
        result.append(dict(record, glyphs=kept, underlines=underlines,
                           text=text[first:last], paragraphs=paragraphs,
                           rect=union(g['bbox'] for g in kept)))
    return result


def _drop_affected_groups(doc, page, selected):
    """A group is an explicit user selection: do not guess its new membership."""
    from .objects import GROUP_KEY, _groups
    groups = _groups(doc, page)
    removed, kept = [], []
    for group in groups:
        affected = any(
            g.text == text and g.font == font and abs(g.size-size) < .002
            and all(abs(a-b) < .035 for a, b in zip(g.origin, origin))
            for member in group.get('members', []) if member.get('kind') == 'text'
            for text, origin, font, size in member.get('glyphs', [])
            for g in selected)
        (removed if affected else kept).append(group)
    if removed:
        doc.xref_set_key(doc[page].xref, GROUP_KEY, fitz.get_pdf_str(json.dumps(kept, ensure_ascii=True)))
    return [group.get('name', 'Grupo') for group in removed]


def _source_width(font, code, text):
    if font.get('/Subtype') != '/Type0':
        return _advance(font, code, text)
    if font.get('/Encoding') != '/Identity-H':
        raise EditError('Esta codificación compuesta no permite aislar los caracteres con seguridad.')
    descendant = font['/DescendantFonts'][0].get_object()
    widths = descendant.get('/W', [])
    widths=widths.get_object() if hasattr(widths,'get_object') else widths
    i = 0
    while i < len(widths):
        start = int(widths[i]); value = widths[i+1]; i += 2
        value=value.get_object() if hasattr(value,'get_object') else value
        if isinstance(value, (list, ArrayObject)):
            if start <= code < start+len(value):
                return float(value[code-start])
        else:
            end = int(value); width = float(widths[i]); i += 1
            if start <= code <= end:
                return width
    return float(descendant.get('/DW', 1000))


def _safe_rich_selection(page,model,selected,metadata,*,preserve_paint_order=True):
    """Allow only this editor's verified, owned underline paths above text."""
    if not any(r.get('underlines') for r in metadata):
        return _safe_selection(page,model,selected,preserve_paint_order=preserve_paint_order)
    # The original native operations stay intact; an isolated safety probe
    # removes only exactly matched owned underline sequences.
    data=page.parent.tobytes(garbage=0)
    reader=PdfReader(BytesIO(data),strict=True)
    ops=ContentStream(reader.pages[page.number].get_contents(),reader).operations
    _locate_underlines(ops, metadata)
    removed=set()
    for r in metadata:
        for item in r.get('underlines',[]):
            start,length=item['start'],item['length']
            if hashlib.sha256(_serialize(ops[start:start+length])).hexdigest()!=item['sha256']:
                raise EditError('El subrayado cambió fuera del editor; no se puede aislar con garantías.')
            removed.update(range(start,start+length))
    with fitz.open(stream=data,filetype='pdf') as probe:
        xref=probe.get_new_xref();probe.update_object(xref,'<<>>')
        probe.update_stream(xref,_serialize([o for i,o in enumerate(ops) if i not in removed]));probe[page.number].set_contents(xref)
        remapped=extract_page(probe,page.number)
        lookup={g.id:g for g in remapped.glyphs}
        targets=[replace(g,seqno=lookup[g.id].seqno) if g.id in lookup else g for g in selected]
        _safe_selection(probe[page.number],replace(remapped,issues=model.issues),targets,preserve_paint_order=preserve_paint_order)


def _unit(show):
    font = show['font']
    if font.get('/Subtype') in ('/TrueType', '/Type1'): return 1
    if font.get('/Subtype') == '/Type0' and font.get('/Encoding') == '/Identity-H': return 2
    raise EditError('La fuente usa una codificación variable no compatible con edición por fragmentos.')


def _catalog(shows, operations, resource):
    catalog = {}
    for show in shows:
        if show['resource'] != resource: continue
        unit = _unit(show)
        args, op = operations[show['operation']]
        raw = b''.join(_raw(v) for _,v in _strings(args,op))
        if len(raw) != unit*len(show['glyphs']):
            raise EditError('No hay correspondencia verificable entre los códigos y los glifos.')
        for i,glyph in enumerate(show['glyphs']):
            catalog.setdefault(glyph.text,set()).add(int.from_bytes(raw[i*unit:(i+1)*unit],'big'))
    return catalog


def selection_payload(data, page, ids, resolver=None):
    """Fuente real, estilos y cursores del PDF abierto; no modifica el documento."""
    resolver = resolver or FontResolver()
    with fitz.open(stream=data,filetype='pdf') as doc:
        model = extract_page(doc,page,data)
        selected = model.selected(ids)
        if not selected or len(selected) != len(set(ids)):
            raise EditError('Selecciona texto del documento actual.')
        records = _read_metadata(doc,page)
        stored = [c for r in records for c in r.get('glyphs',[])]
        matching=next((r for r in records if len(r.get('glyphs',[]))==len(selected) and
                       all(any(_match(g,c) for c in r['glyphs']) for g in selected)),None)
        _, operations, shows, mapping = operator_glyph_map(data,page,model)
        byop = {s['operation']:s for s in shows}
        runs, carets, previews = [],[],{}
        previous = None
        index = 0
        for position,glyph in enumerate(selected):
            existing = next((c for c in stored if _match(glyph,c)),None)
            logical_prefix=''
            if matching and 'text' in matching and existing:
                logical_prefix=matching['text'][index:existing['index']]
            elif previous and previous.line != glyph.line:
                # A stored explicit paragraph survives reopening; inferred lines
                # are soft breaks until the user joins them explicitly.
                sep = '\u2028'
                if existing and existing.get('break_before') in ('\n','\u2028'):
                    sep = existing['break_before']
                logical_prefix=sep
            leading_prefix = ''
            if logical_prefix:
                if runs: runs[-1]['text']+=logical_prefix
                else: leading_prefix = logical_prefix
                index+=len(logical_prefix)
            show = byop[mapping[glyph.id]['operation']]
            state = _state_at(operations,show['operation'])
            spacing = float(existing.get('char_spacing',0)) if existing else 0.
            following=selected[position+1] if position+1<len(selected) else None
            if not existing and following and following.line == glyph.line:
                gap = following.origin[0]-glyph.trace_bbox[2]
                if abs(gap) < glyph.size: spacing=gap
            style = dict(font_name=glyph.font,font_file=None,font_xref=glyph.font_xref,
                         font_resource=glyph.font_resource,size=glyph.size,color=glyph.color,
                         opacity=glyph.opacity,underline=bool(existing and existing.get('underline')),
                         char_spacing=spacing,source_ascent=(glyph.origin[1]-glyph.bbox[1])/glyph.size,
                         source_descent=(glyph.bbox[3]-glyph.origin[1])/glyph.size)
            if existing:
                style['char_spacing'] = existing.get('char_spacing',0.)
            # Keep each physical style separate. The UI may coalesce identical
            # styles; per-character spacing from native TJ remains expressible.
            if runs and {k:v for k,v in runs[-1].items() if k!='text'} == style:
                runs[-1]['text'] += glyph.text
            else:
                runs.append(dict(text=leading_prefix+glyph.text,**style))
            carets.append(dict(index=index,id=glyph.id,text=glyph.text,origin=glyph.origin,bbox=glyph.bbox,
                               end=(glyph.trace_bbox[2],glyph.origin[1])))
            index += len(glyph.text)
            key=(glyph.font,glyph.font_xref)
            if key not in previews:
                preview=dict(font_name=glyph.font,font_xref=glyph.font_xref,buffer=None,source='recurso PDF original',metadata={})
                try:
                    if glyph.font_xref:
                        name,ext,_,buffer=doc.extract_font(glyph.font_xref)
                        if buffer:
                            preview.update(buffer=buffer,metadata=_font_metadata(buffer,name))
                    if not preview['buffer']:
                        resolved=resolver.resolve(doc,page,glyph.font,glyph.text)
                        preview.update(buffer=resolved.buffer,source=resolved.source,metadata=resolved.metadata)
                        if resolved.base14:
                            preview['buffer']=bytes(resolved.font.buffer)
                except (FontError,RuntimeError,ValueError) as exc:
                    preview['warning']=str(exc)
                previews[key]=preview
            previous=glyph
        if matching and 'text' in matching and index<len(matching['text']) and runs:
            runs[-1]['text']+=matching['text'][index:]
            index=len(matching['text'])
        if carets:
            last=carets[-1]
            carets.append(dict(index=index,origin=last['end'],bbox=last['bbox'],text=''))
        rect=matching.get('rect') if matching else union(g.bbox for g in selected)
        return dict(page=page,ids=list(ids),runs=runs,rect=rect,revision=model.revision,
                    paragraphs=matching.get('paragraphs',[]) if matching else [],
                    font_previews=list(previews.values()),carets=carets,baseline=selected[0].origin[1],
                    text=''.join(r['text'] for r in runs))


def _finite(value,label,minimum=None,maximum=None):
    if not isinstance(value,(int,float)) or not math.isfinite(value) or (minimum is not None and value<minimum) or (maximum is not None and value>maximum):
        raise EditError(f'{label}: valor fuera del intervalo admitido.')
    return float(value)


def _paragraph(request,index):
    result=dict(alignment='left',left_indent=0.,right_indent=0.,first_indent=0.,
                line_spacing=0.,space_before=0.,space_after=0.,tab_stops=[],tab_interval=36.)
    for entry in request.paragraphs:
        if entry.get('index',index)==index:
            result.update(entry)
    for key in ('left_indent','right_indent','first_indent','space_before','space_after','line_spacing'):
        _finite(result[key],key,-500 if key=='first_indent' else 0,2000)
    _finite(result['tab_interval'],'Tabulación',.1,2000)
    result['tab_stops']=sorted(set(_finite(v,'Tabulación',0,2000) for v in result['tab_stops']))
    if result['alignment'] not in ('left','center','right','justify'):
        raise EditError('Alineación desconocida.')
    return result


def _layout(request,tokens,rect):
    """Deterministic word wrapping, paragraph/soft breaks and explicit tabs."""
    if not tokens:
        return [], [], rect
    x0,y0,x1,y1=rect
    width=x1-x0
    lines=[]; line=[]; para=0; first=True; settings=_paragraph(request,para)
    cursor=0.; y=y0+settings['space_before']; pending=''
    def available():
        return width-settings['left_indent']-settings['right_indent']-(settings['first_indent'] if first else 0.)
    def measure(items):
        pos=0.
        for t in items:
            if t.get('wrap_space'):
                t['advance']=0.
            elif t['char']=='\t':
                stops=[v for v in settings['tab_stops'] if v>pos+.001]
                target=stops[0] if stops else (math.floor(pos/settings['tab_interval'])+1)*settings['tab_interval']
                t['advance']=target-pos
            else:t['advance']=t['width']+t['spacing']
            pos+=t['advance']
        if items and items[-1]['char']!='\t' and not items[-1].get('wrap_space'):pos-=items[-1]['spacing']
        return pos
    def flush(break_kind='',last=False):
        nonlocal line,first,y,pending
        measured=measure(line)
        if measured>available()+.035:
            raise EditError('El texto supera la anchura disponible. Amplía el cuadro; el tamaño de letra se conserva.')
        asc=max([t['asc'] for t in line] or [12.9]);desc=max([t['desc'] for t in line] or [3.6])
        height=max([t['size']*1.2 for t in line] or [14.4])
        baseline=y+asc
        left=x0+settings['left_indent']+(settings['first_indent'] if first else 0.)
        if settings['alignment']=='right':left+=available()-measured
        elif settings['alignment']=='center':left+=(available()-measured)/2
        spaces=sum(t['char']==' ' for t in line)
        extra=(available()-measured)/spaces if settings['alignment']=='justify' and spaces and not last and not break_kind else 0.
        x=left
        for i,t in enumerate(line):
            # A separator at an automatic wrap has no painted ink and must not
            # become a line of its own. Keep its actual space code within the
            # line's frame, without moving or scaling any visible character.
            glyph_x=max(left,min(x,left+available()-t['width'])) if t.get('wrap_space') else x
            t.update(origin=(glyph_x,baseline),bbox=(glyph_x,baseline-t['asc'],glyph_x+t['width'],baseline+t['desc']),
                     line=len(lines),break_before=pending if i==0 else '')
            x+=t['advance']+(extra if t['char']==' ' else 0.)
        lines.append(dict(tokens=line,baseline=baseline,bottom=baseline+desc,paragraph=para))
        y=baseline-asc+(settings['line_spacing'] or height)
        line=[];first=False;pending=break_kind
    i=0
    while i<len(tokens):
        t=tokens[i]
        if t['char'] in ('\n','\u2028'):
            flush(t['char'],last=True)
            if t['char']=='\n':
                y+=settings['space_after'];para+=1;settings=_paragraph(request,para);y+=settings['space_before'];first=True
            i+=1;continue
        candidate=line+[t]
        if measure(candidate)>available()+.035:
            if t['char']==' ' and any(item['char'] not in (' ','\t') for item in line):
                t['wrap_space']=True
                line.append(t);i+=1;continue
            if not line:raise EditError('Una letra o tabulación supera la anchura disponible. Amplía el área.')
            # Break at the last whitespace; retain that actual character rather
            # than silently deleting it from the real PDF.
            split=next((j+1 for j in range(len(line)-1,-1,-1) if line[j]['char'] in (' ','\t')),len(line))
            tail=line[split:];line=line[:split];flush();line=tail
            if measure(line+[t])>available()+.035 and line:flush()
        line.append(t);i+=1
    flush(last=True)
    visible=[t for l in lines for t in l['tokens'] if t['char']!='\t']
    bottom=max([l['bottom'] for l in lines] or [y0])
    if bottom>y1+.035 and not request.auto_height:
        raise EditError('El texto supera la altura disponible. Amplía el cuadro o modifica el interlineado.')
    final_rect=(x0,y0,x1,max(y1,bottom) if request.auto_height else y1)
    return visible,lines,final_rect


def edit_rich_pdf(data, request, resolver=None):
    """Compose, validate and return a new PDF; callers own preview/history."""
    from .native_codes import verified_catalog
    from .native_font_extension import prepare_native_font
    from .validation import document_issues, assert_characters
    from .tagged import analyze, TaggedEdit
    if isinstance(request,dict): request=RichTextRequest(**request)
    resolver=resolver or FontResolver()
    started=time.perf_counter()
    if request.revision and request.revision!=hashlib.sha256(data).hexdigest():
        raise EditError('El documento cambió desde la selección. Selecciona el texto de nuevo.')
    if not request.ids:
        return _add_rich_pdf(data,request,resolver)
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc)
        if issues:raise EditError('\n'.join(issues))
        model=extract_page(doc,request.page,data)
        selected=model.selected(request.ids)
        if len(selected)!=len(set(request.ids)):
            raise EditError('La selección pertenece a una revisión anterior.')
        if not selected:
            raise EditError('Selecciona un texto para el editor por fragmentos.')
        clean=replace(model,issues=[v for v in model.issues if v!=CLIP_ISSUE])
        metadata=_read_metadata(doc,request.page)
        _safe_rich_selection(doc[request.page],clean,selected,metadata)
        rotation=doc[request.page].rotation
        doc[request.page].set_rotation(0)
        page_matrix=doc[request.page].transformation_matrix
        page_bounds=fitz.Rect(0,0,doc[request.page].cropbox.width,doc[request.page].cropbox.height)
        doc[request.page].set_rotation(rotation)
    chosen={g.id for g in selected}
    others=[g for g in model.glyphs if g.id not in chosen]
    if any(g.mode==3 and any(intersects(g.bbox,s.bbox) for s in selected) for g in others):
        raise EditError('La selección tiene OCR invisible superpuesto. Corrige esa capa por separado antes de usar formato por fragmentos.')
    if any(abs(g.opacity-selected[0].opacity)>.001 for g in selected):
        raise EditError('La selección mezcla opacidades. Edita cada opacidad en una sesión independiente.')
    reader,operations,shows,mapping=operator_glyph_map(data,request.page,model)
    byop={s['operation']:s for s in shows}
    first=selected[0]
    first_op=mapping[first.id]['operation']
    resources=reader.pages[request.page]['/Resources'].get_object()
    first_state=_state_at(operations,first_op,resources)
    states={}; source_clips=[]
    for op in {mapping[g.id]['operation'] for g in selected}:
        state=_state_at(operations,op,resources); states[op]=state
        show=byop[op];unit=_unit(show)
        if operations[op][1] not in (b'Tj',b'TJ') or show['render_mode']!=0:
            raise EditError('El operador de texto utiliza un salto o modo de pintura no compatible.')
        if (state['unknown'] or state['size'] is None or state['size']<=0 or state['tz']<=0 or
            abs(state['matrix'].b)+abs(state['matrix'].c)>1e-6 or state['matrix'].a<=0 or state['matrix'].d<=0):
            raise EditError('El campo usa una transformación o un recorte complejo no reproducible.')
        source_clips.append(state['clip']*page_matrix if state['clip'] is not None else page_bounds)
        raw=b''.join(_raw(v) for _,v in _strings(*operations[op]))
        if len(raw)!=unit*len(show['glyphs']):
            raise EditError('No se pueden aislar los códigos de los caracteres seleccionados.')
        for g in show['glyphs']:
            if g.id in chosen and not (source_clips[-1]+(-.03,-.03,.03,.03)).contains(fitz.Rect(g.bbox)):
                raise EditError('Un carácter original está parcialmente oculto por el recorte.')
    # A merged selection retains the intersection of its known clips. This
    # never expands a table cell or silently frees text from its original clip.
    clip=fitz.Rect(source_clips[0])
    for part in source_clips[1:]:clip &= part
    bounds=union(g.bbox for g in selected)
    rect=tuple(request.rect or bounds)
    if len(rect)!=4:raise EditError('El área de texto debe tener cuatro coordenadas.')
    rect=tuple(_finite(v,'Posición') for v in rect)
    width=_finite(request.width if request.width is not None else rect[2]-rect[0],'Anchura',.1,100000)
    height=_finite(request.height if request.height is not None else rect[3]-rect[1],'Altura',.1,100000)
    rect=(rect[0],rect[1],rect[0]+width,rect[1]+height)
    # Some generators split one CID font into complementary original subsets.
    # Reuse an already embedded glyph only after program-level identity checks.
    from .native_codes import verified_cid_fallbacks
    expanded_runs=[];subset_sources={}
    for run in request.runs:
        run={key:value for key,value in run.items() if key!='_complementary_source'}
        source=next((s for s in shows if s['resource']==run.get('font_resource')),None)
        text=str(run.get('text','')).replace('\r\n','\n').replace('\r','\n')
        if (source is not None and not run.get('font_file') and source['glyphs']
                and normalized_name(run.get('font_name') or first.font)==normalized_name(source['glyphs'][0].font)):
            catalog=verified_catalog(data,request.page,source,
                                     _catalog(shows,operations,source['resource']),text)
            missing={c for c in text if c not in _BREAKS+'\r' and len(catalog.get(c,set()))!=1}
            fallbacks=verified_cid_fallbacks(data,request.page,source,shows,operations,missing) if missing else {}
        else:
            fallbacks={}
        if fallbacks:
            for char in text:
                resource=fallbacks.get(char,run.get('font_resource'))
                expanded_runs.append(dict(run,text=char,font_resource=resource,
                    _complementary_source=source['resource'] if char in fallbacks else None))
                if char in fallbacks:subset_sources[resource]=source['resource']
        else:
            expanded_runs.append(run)
    request=replace(request,runs=expanded_runs)
    working=data; prepared={};tokens=[]; evidence={}; index=0
    for run_index,original_run in enumerate(request.runs):
        run=dict(original_run)
        text=str(run.get('text','')).replace('\r\n','\n').replace('\r','\n')
        if any((unicodedata.category(c).startswith('C') and c not in _BREAKS) or unicodedata.combining(c) for c in text):
            raise EditError('Usa acentos precompuestos; los controles y las marcas combinantes no están admitidos.')
        printable=''.join(c for c in text if c not in _BREAKS)
        size=_finite(run.get('size',first.size),'Tamaño de letra',1,300)
        color=tuple(run.get('color',first.color));validate_rgb(color)
        color=tuple(struct.unpack('f',struct.pack('f',v))[0] for v in color)
        spacing=_finite(run.get('char_spacing',0),'Espaciado entre caracteres',-100,300)
        opacity=_finite(run.get('opacity',first.opacity),'Opacidad',0,1)
        if abs(opacity-first.opacity)>.001:
            raise EditError('Cambiar la opacidad por fragmentos todavía no está admitido; conserva la original.')
        if run.get('underline') and abs(opacity-1.)>.001:
            raise EditError('El subrayado de texto semitransparente todavía no está admitido; conserva su formato sin subrayado.')
        resource=run.get('font_resource')
        font_name=run.get('font_name') or first.font
        source=next((s for s in shows if s['resource']==resource),None) if resource else None
        if source is None and not run.get('font_file'):
            candidates=[s for s in shows if any(normalized_name(g.font)==normalized_name(font_name) for g in s['glyphs'])]
            identities={(s['resource'],s['xref']) for s in candidates}
            if len(identities)==1:source=candidates[0]
        if source is None:source=byop[first_op]
        sample=source['glyphs'][0]
        explicit=bool(run.get('font_file')) or normalized_name(font_name)!=normalized_name(sample.font) or not resource and font_name!=first.font
        scale_source_resource=run.get('_complementary_source')
        key=(source['resource'],font_name,run.get('font_file'),explicit,scale_source_resource)
        # Collect all characters of this chosen face at once, avoiding a later
        # fragment accidentally reusing an incomplete freshly-created subset.
        same_text=''.join(str(r.get('text','')) for r in request.runs
                          if r.get('font_name',first.font)==font_name and r.get('font_file')==run.get('font_file') and r.get('font_resource')==resource)
        same_text=''.join(c for c in same_text if c not in _BREAKS and c!='\r')
        if key not in prepared:
            catalog=_catalog(shows,operations,source['resource'])
            if not explicit:
                catalog=verified_catalog(working,request.page,source,catalog,same_text)
            missing=[c for c in same_text if len(catalog.get(c,set()))!=1]
            if (explicit or missing) and same_text:
                try:
                    extension=prepare_native_font(working,request.page,source,same_text,
                        font_name=font_name if explicit else None,font_file=run.get('font_file'),resolver=resolver)
                except FontError as exc:raise EditError(str(exc)) from exc
                working=extension.data
                original_scale=1.
                if extension.evidence.get('mapping_only'):
                    source_state=_state_at(operations,source['operation'],resources)
                    if source_state['size'] is None or sample.size<=0:
                        raise EditError('No se puede verificar la escala de la fuente original.')
                    original_scale=source_state['size']*source_state['tz']*source_state['matrix'].a/sample.size
                prepared[key]=dict(font=extension.font,resource=extension.resource,catalog=extension.catalog,
                                   unit=extension.unit,font_name=extension.rendered_name,scale=original_scale,
                                   ascent=-extension.bbox_ratios[0],descent=extension.bbox_ratios[1])
                evidence[extension.resource]=extension.evidence
            else:
                scale_source=next((s for s in shows if s['resource']==scale_source_resource),source)
                scale_sample=scale_source['glyphs'][0]
                source_state=_state_at(operations,scale_source['operation'],resources)
                if source_state['size'] is None or scale_sample.size<=0:
                    raise EditError('No se puede verificar el tamaño del recurso de fuente seleccionado.')
                scale=source_state['size']*source_state['tz']*source_state['matrix'].a/scale_sample.size
                prepared[key]=dict(font=source['font'],resource=source['resource'],catalog=catalog,
                                   unit=_unit(source),font_name=sample.font,scale=scale,
                                   ascent=(scale_sample.origin[1]-scale_sample.bbox[1])/scale_sample.size,
                                   descent=(scale_sample.bbox[3]-scale_sample.origin[1])/scale_sample.size)
                evidence[source['resource']]=dict(source='recurso PDF original',identity_basis='Mismo recurso, códigos y programa del PDF')
                if source['resource'] in subset_sources:
                    evidence[source['resource']].update(complementary_subset_of=subset_sources[source['resource']],
                        identity_basis='Subconjuntos CID originales compatibles: metadatos, contornos, avances e instrucciones de ajuste coinciden en los glifos comunes verificados')
        choice=prepared[key]
        for char in text:
            advance=0. if char in _BREAKS else _source_width(choice['font'],next(iter(choice['catalog'][char])),char)*size*choice['scale']/1000
            if advance+spacing<0 and char not in _BREAKS:
                raise EditError('El espaciado solicitado invierte el avance del cursor.')
            tokens.append(dict(char=char,index=index,run=run_index,choice=choice,width=advance,size=size,
                               spacing=spacing,color=color,opacity=opacity,underline=bool(run.get('underline')),
                               asc=choice['ascent']*size,desc=choice['descent']*size))
            index+=1
    if request.auto_width:
        natural=[];w=0.; paragraph_index=0; first_line=True
        settings=_paragraph(request,paragraph_index)
        last_spacing=0.
        def natural_width():
            return w-last_spacing+settings['left_indent']+settings['right_indent']+(settings['first_indent'] if first_line else 0.)
        for t in tokens:
            if t['char'] in ('\n','\u2028'):
                natural.append(natural_width());w=0.;last_spacing=0.;first_line=False
                if t['char']=='\n':
                    paragraph_index+=1;settings=_paragraph(request,paragraph_index);first_line=True
            elif t['char']=='\t':
                stops=[v for v in settings['tab_stops'] if v>w+.001]
                w=stops[0] if stops else (math.floor(w/settings['tab_interval'])+1)*settings['tab_interval']
                last_spacing=0.
            else:w+=t['width']+t['spacing'];last_spacing=t['spacing']
        natural.append(natural_width())
        rect=(rect[0],rect[1],rect[0]+max(.1,*natural),rect[3])
    laid,lines,rect=_layout(request,tokens,rect)
    planned=[replace(first,id=-1,text=t['char'],origin=t['origin'],bbox=t['bbox'],trace_bbox=t['bbox'],
                     font=t['choice']['font_name'],size=t['size'],color=t['color'],line=t['line']) for t in laid]
    for g in planned:
        if not page_bounds.contains(fitz.Rect(g.bbox)) or not (clip+(-.035,-.035,.035,.035)).contains(fitz.Rect(g.bbox)):
            raise EditError('El texto nuevo queda fuera de la página o del recorte original.')
        if not request.allow_overlap and any(intersects(g.bbox,n.bbox,.12) for n in others):
            raise EditError('El texto se solapa con caracteres vecinos. Amplía o mueve el cuadro, o permite el solapamiento explícitamente.')
    with fitz.open(stream=data,filetype='pdf') as safety:
        if planned:_safe_rich_selection(safety[request.page],clean,planned,metadata)
        _safe_native_consolidation(safety[request.page],selected,planned)
    structure=analyze(data)
    tagged=TaggedEdit(structure,request.page,model,selected,planned,selected,True) if structure else None
    matrix=first_state['matrix'];linear=first_state['ctm']*page_matrix;inverse=~linear
    insertion=[];new_underlines=[];groups=[]
    for t in laid:
        key=(t['choice']['resource'],t['choice']['scale'],t['size'],t['color'],t['line'])
        if groups and groups[-1][0]==key:groups[-1][1].append(t)
        else:groups.append((key,[t]))
    for _,group in groups:
        t=group[0]
        choice=t['choice'];code=next(iter(choice['catalog'][t['char']]))
        delta=fitz.Point(t['origin'][0]-first.origin[0],t['origin'][1]-first.origin[1])*inverse-fitz.Point(0,0)*inverse
        tf=first_state['size']*t['size']/first.size
        tz=100*choice['scale']*t['size']/(tf*matrix.a)
        encoded=ArrayObject([ByteStringObject(b'')]);total_advance=0.
        for j,char in enumerate(group):
            code=next(iter(choice['catalog'][char['char']]))
            encoded.append(ByteStringObject(code.to_bytes(choice['unit'],'big')))
            natural=_source_width(choice['font'],code,char['char']);total_advance+=natural
            if j+1<len(group):
                gap=group[j+1]['origin'][0]-char['origin'][0]-char['width']
                adjustment=1000*gap/(tf*tz/100*matrix.a)
                if abs(adjustment)>1e-7:encoded.append(_number(-adjustment));total_advance+=adjustment
        encoded.append(_number(total_advance))
        insertion.extend([([],b'q'),([_number(v) for v in (1,0,0,1,delta.x,delta.y)],b'cm'),
                          ([NameObject(choice['resource']),_number(tf)],b'Tf'),([_number(0)],b'Tc'),
                          ([_number(0)],b'Tw'),([_number(tz)],b'Tz'),([_number(v) for v in t['color']],b'rg'),
                          ([encoded],b'TJ'),([],b'Q')])
    for t in laid:
        if t['underline']:
            thickness=max(.35,t['size']/18)
            box=(t['origin'][0],t['origin'][1]+t['size']*.12,t['origin'][0]+t['width'],t['origin'][1]+t['size']*.12+thickness)
            if box[2]>box[0]:new_underlines.append(dict(rect=box,color=t['color'],index=t['index']))
    if new_underlines:
        # Decorations are appended in page coordinates. Do not move a newly
        # requested underline above artwork that remains above its text.
        with fitz.open(stream=data,filetype='pdf') as safety:
            decorations=[replace(first,bbox=tuple(item['rect'])) for item in new_underlines]
            try:
                _safe_rich_selection(safety[request.page],clean,decorations,metadata,preserve_paint_order=False)
            except EditError as exc:
                raise EditError('No se puede conservar el orden visual del subrayado solicitado. '+str(exc)) from exc
    # Each underline belongs to a character, so editing a partial styled range
    # neither removes its neighbours' paths nor retains the replaced text.
    keep_records=[];remove_ops=set();old_underlines=[]
    for record in metadata:
        matches=[any(_match(g,c) for g in selected) for c in record.get('glyphs',[])]
        if any(matches):
            owned=record.get('underlines',[])
            for item in owned:
                owner=next((c for c in record['glyphs'] if c.get('index')==item['index']),None)
                if owner and any(_match(g,owner) for g in selected):
                    start,length=item['start'],item['length']
                    digest=hashlib.sha256(_serialize(operations[start:start+length])).hexdigest()
                    if digest!=item['sha256']:
                        raise EditError('Los operadores del subrayado cambiaron desde su creación. Vuelve a abrir una copia anterior para editarlo.')
                    remove_ops.update(range(start,start+length));old_underlines.append(item)
            keep_records.extend(_surviving_records(record,matches))
        else:keep_records.append(record)
    replacements={}
    for op,state in states.items():
        show=byop[op];unit=_unit(show);args,operator=operations[op]
        source_array=args[0] if operator==b'TJ' else [args[0]]
        changed=ArrayObject();chunks=[];position=0
        def flush():
            nonlocal changed
            if changed:chunks.append(([_compact_adjustments(changed)],b'TJ'));changed=ArrayObject()
        for value in source_array:
            if isinstance(value,(str,bytes)):
                raw=_raw(value)
                for offset in range(0,len(raw),unit):
                    glyph=show['glyphs'][position];code=int.from_bytes(raw[offset:offset+unit],'big')
                    if glyph.id==first.id:
                        flush();chunks.extend(copy.deepcopy(insertion))
                    if glyph.id in chosen:
                        step=_source_width(show['font'],code,glyph.text)+1000*state['tc']/state['size']+(1000*state['tw']/state['size'] if unit==1 and code==32 else 0)
                        changed.append(_number(-step))
                    else:changed.append(ByteStringObject(raw[offset:offset+unit]))
                    position+=1
            else:changed.append(copy.deepcopy(value))
        flush();replacements[op]=chunks
    changed_ops=[];index_map={}
    for op,item in enumerate(operations):
        index_map[op]=len(changed_ops)
        if op in remove_ops:continue
        if tagged and op in {structure.marks[request.page][mcid].start for mcid in tagged.marker_updates}:
            mcid=next(m for m in tagged.marker_updates if structure.marks[request.page][m].start==op)
            args,oper=item;props=copy.deepcopy(structure.marks[request.page][mcid].resolved)
            props[NameObject('/ActualText')]=TextStringObject(tagged.marker_updates[mcid]);item=([args[0],props],oper)
        changed_ops.extend(replacements.get(op,[copy.deepcopy(item)]))
    for record in keep_records:
        for item in record.get('underlines',[]):item['start']=index_map[item['start']]
    # New underlines are plain vector content in page coordinates; they carry
    # no annotations. A private metadata record allows precise later removal.
    # Wrap whole content, so any inherited CTM cannot affect these final paths.
    changed_ops=[([],b'q'),*changed_ops,([],b'Q')]
    for record in keep_records:
        for item in record.get('underlines',[]):item['start']+=1
    inverse_page=~page_matrix
    for item in new_underlines:
        r=fitz.Rect(item['rect'])*inverse_page
        ops=[([],b'q'),([_number(v) for v in item['color']],b'rg'),([_number(v) for v in (r.x0,r.y0,r.width,r.height)],b're'),([],b'f'),([],b'Q')]
        item.update(start=len(changed_ops),length=len(ops),sha256=hashlib.sha256(_serialize(ops)).hexdigest())
        changed_ops.extend(ops)
    stored_glyphs=[dict(index=t['index'],text=t['char'],origin=t['origin'],bbox=t['bbox'],char_spacing=t['spacing'],
                       underline=t['underline'],break_before=t.get('break_before','')) for t in laid]
    logical_text=''.join(t['char'] for t in tokens)
    keep_records.append(dict(glyphs=stored_glyphs,rect=rect,paragraphs=request.paragraphs,underlines=new_underlines,
                             text=logical_text))
    with fitz.open(stream=working,filetype='pdf') as output_doc:
        stream=output_doc.get_new_xref();output_doc.update_object(stream,'<<>>')
        output_doc.update_stream(stream,_serialize(changed_ops));output_doc[request.page].set_contents(stream)
        output_doc.xref_set_key(output_doc[request.page].xref,_META_KEY,fitz.get_pdf_str(json.dumps(keep_records,ensure_ascii=True)))
        removed_groups=_drop_affected_groups(output_doc,request.page,selected)
        if tagged:
            from .tagged import ref
            for path,text in tagged.actual_updates.items():
                output_doc.xref_set_key(ref(structure.nodes[path])[0],'ActualText',fitz.get_pdf_str(text))
        output=full_write(output_doc)
    _assert_typography(output,request.page,others+planned)
    report=_validate(data,output,request.page,others+planned,selected+planned,old_underlines,new_underlines,
                     tagged.expected if tagged else None)
    if tagged:report['accessibility']=tagged.validate(output)
    carets=[dict(index=t['index'],text=t['char'],origin=t['origin'],bbox=t['bbox'],
                 end=(t['origin'][0]+t['width']+t['spacing'],t['origin'][1])) for t in laid]
    if carets:
        last=carets[-1];carets.append(dict(index=index,origin=last['end'],bbox=last['bbox'],text=''))
    report.update(page=request.page,rect=rect,area_width=rect[2]-rect[0],area_height=rect[3]-rect[1],
                  auto_width=request.auto_width,auto_height=request.auto_height,
                  source_regions=[g.bbox for g in selected],destination_regions=[g.bbox for g in planned],
                  glyphs=[asdict(g) for g in planned],carets=carets,line_count=len(lines),fonts=evidence,
                  original=model.text(request.ids),replacement=logical_text,
                  elapsed_seconds=round(time.perf_counter()-started,3),rich_text=True)
    if removed_groups:
        report['removed_groups']=removed_groups
        report.setdefault('warnings',[]).append('Se han desagrupado los grupos afectados por el cambio de texto: '+', '.join(removed_groups)+'. Puedes agrupar su contenido de nuevo.')
        report['warning']=report['warnings'][-1]
    return output,report


def _add_rich_pdf(data,request,resolver):
    """Reuse the identical compositor through an ephemeral insertion anchor.

    The anchor exists only in worker memory and is removed as real content by
    the same native transaction. Final validation compares against the user's
    original bytes, so the temporary anchor cannot hide damage or remain saved.
    """
    from .tagged import require_untagged
    from .validation import document_issues
    require_untagged(data,'Añadir un párrafo nuevo')
    if not request.rect or len(request.rect)!=4:
        raise EditError('Define el cuadro donde quieres añadir el texto.')
    rect=tuple(_finite(v,'Posición') for v in request.rect)
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc)
        if issues:raise EditError('\n'.join(issues))
        original_model=extract_page(doc,request.page,data)
        # A unique font resource name is unnecessary: the standard PDF face is
        # only an internal positioning anchor and never a fallback font.
        doc[request.page].insert_text((rect[0],rect[1]+10),'|',fontsize=8,fontname='helv')
        anchored=doc.tobytes(garbage=0,deflate=True)
    with fitz.open(stream=anchored,filetype='pdf') as doc:
        anchor_model=extract_page(doc,request.page,anchored)
        ids=[g.id for g in anchor_model.glyphs[len(original_model.glyphs):]]
    if len(ids)!=1:raise EditError('No se pudo preparar el punto de inserción del texto nuevo.')
    output,report=edit_rich_pdf(anchored,replace(request,ids=ids,revision=None),resolver)
    expected=original_model.glyphs+[Glyph(**g) for g in report['glyphs']]
    with fitz.open(stream=output,filetype='pdf') as doc:
        records=_read_metadata(doc,request.page)
    underlines=records[-1].get('underlines',[]) if records else []
    checked=_validate(data,output,request.page,expected,[Glyph(**g) for g in report['glyphs']],[],underlines,None)
    report.update(checked);report.update(source_regions=[],original='',added_text=True)
    return output,report


def move_rich_pdf(data, request, resolver=None):
    """Move native glyphs and their owned decorations without recomposition."""
    from .clipped_layout import move_clipped_text
    from .objects import GROUP_KEY, _groups
    if request.revision and request.revision != hashlib.sha256(data).hexdigest():
        raise EditError('La selección está desactualizada. Selecciona el texto de nuevo.')
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, request.page, data)
        selected = model.selected(request.ids)
        if not selected or len(selected) != len(set(request.ids)):
            raise EditError('Selecciona los caracteres que quieres mover.')
        metadata = _read_metadata(doc, request.page)
        if not metadata:
            return move_clipped_text(data, request, model)
        _, operations, _, _ = operator_glyph_map(data, request.page, model)
        _locate_underlines(operations, metadata)
        old_underlines = [copy.deepcopy(item) for record in metadata for item in record.get('underlines', [])]
        removed = {index for item in old_underlines for index in range(item['start'], item['start']+item['length'])}
        stream = doc.get_new_xref(); doc.update_object(stream, '<<>>')
        doc.update_stream(stream, _serialize([op for index, op in enumerate(operations) if index not in removed]))
        doc[request.page].set_contents(stream)
        stripped = doc.tobytes(garbage=0)
        rotation = doc[request.page].rotation
        doc[request.page].set_rotation(0)
        inverse_page = ~doc[request.page].transformation_matrix
        doc[request.page].set_rotation(rotation)
    with fitz.open(stream=stripped, filetype='pdf') as doc:
        stripped_model = extract_page(doc, request.page, stripped)
    moved, report = move_clipped_text(stripped, replace(request, revision=None), stripped_model)
    dx, dy = request.dx, request.dy
    def shifted(rect):
        return tuple(v+(dx if i%2 == 0 else dy) for i, v in enumerate(rect))
    changed_old, changed_new = [], []
    for record in metadata:
        flags = [any(_match(g, item) for g in selected) for item in record.get('glyphs', [])]
        indices = {item['index'] for item, chosen in zip(record.get('glyphs', []), flags) if chosen}
        for item in record.get('underlines', []):
            if item['index'] in indices:
                changed_old.append(copy.deepcopy(item))
                item['rect'] = shifted(item['rect'])
                changed_new.append(item)
        for item, chosen in zip(record.get('glyphs', []), flags):
            if chosen:
                item['origin'] = shifted(item['origin'])
                item['bbox'] = shifted(item['bbox'])
        if flags and all(flags):
            record['rect'] = shifted(record['rect'])
        elif any(flags):
            record['rect'] = union(item['bbox'] for item in record['glyphs'])
    reader = PdfReader(BytesIO(moved), strict=True)
    ops = ContentStream(reader.pages[request.page].get_contents(), reader).operations
    ops = [([], b'q'), *ops, ([], b'Q')]
    new_underlines = []
    for record in metadata:
        for item in record.get('underlines', []):
            r = fitz.Rect(item['rect'])*inverse_page
            decoration = [([], b'q'), ([_number(v) for v in item['color']], b'rg'),
                          ([_number(v) for v in (r.x0, r.y0, r.width, r.height)], b're'), ([], b'f'), ([], b'Q')]
            item.update(start=len(ops), length=len(decoration), sha256=hashlib.sha256(_serialize(decoration)).hexdigest())
            ops.extend(decoration); new_underlines.append(item)
    with fitz.open(stream=moved, filetype='pdf') as doc:
        stream = doc.get_new_xref(); doc.update_object(stream, '<<>>')
        doc.update_stream(stream, _serialize(ops)); doc[request.page].set_contents(stream)
        doc.xref_set_key(doc[request.page].xref, _META_KEY, fitz.get_pdf_str(json.dumps(metadata, ensure_ascii=True)))
        groups = _groups(doc, request.page)
        for group in groups:
            for member in group.get('members', []):
                if member.get('kind') != 'text': continue
                for signature in member.get('glyphs', []):
                    text, origin, font, size = signature
                    if any(g.text == text and g.font == font and abs(g.size-size) < .002
                           and all(abs(a-b) < .035 for a, b in zip(g.origin, origin)) for g in selected):
                        signature[1] = list(shifted(origin))
        if groups:
            doc.xref_set_key(doc[request.page].xref, GROUP_KEY, fitz.get_pdf_str(json.dumps(groups, ensure_ascii=True)))
        output = full_write(doc)
    chosen = set(request.ids)
    planned = [replace(g, origin=shifted(g.origin), bbox=shifted(g.bbox), trace_bbox=shifted(g.trace_bbox)) for g in selected]
    expected = [g for g in model.glyphs if g.id not in chosen]+planned
    _assert_typography(output, request.page, expected)
    checked = _validate(data, output, request.page, expected, selected+planned, old_underlines, new_underlines,
                        None, pixel_underlines=changed_old+changed_new)
    report.update(checked); report.update(rich_text_move=True, underlines_moved=len(changed_new))
    return output, report


def _validate(before_data,after_data,page_number,expected,changed,old_underlines,new_underlines,tagged_expected,pixel_underlines=None):
    """Normal strict validator with an exact allowance for owned underlines."""
    from .validation import _canonical,related,assert_characters,trace_chars,assert_pixels,_ink_exclusions
    from .tagged import assert_structure
    def without_underlines(page,items):
        result=related(page)
        drawings=list(result['drawings'])
        for item in items:
            target=tuple(round(v,3) for v in item['rect'])
            index=next((i for i,d in enumerate(drawings) if d.get('type')=='f' and
                        all(abs(a-b)<.015 for a,b in zip(d['rect'],target)) and
                        d.get('fill') is not None and all(abs(a-b)<.001 for a,b in zip(d['fill'],item['color']))),None)
            if index is None:raise EditError('No se pudo verificar el subrayado vectorial solicitado.')
            drawings.pop(index)
        result['drawings']=drawings
        return result
    reports=[]
    with fitz.open(stream=before_data,filetype='pdf') as before,fitz.open(stream=after_data,filetype='pdf') as after:
        if before.page_count!=after.page_count or before.metadata!=after.metadata or before.get_xml_metadata()!=after.get_xml_metadata():
            raise EditError('La edición alteró páginas o metadatos ajenos.')
        if _canonical(before.get_toc(False))!=_canonical(after.get_toc(False)):
            raise EditError('La edición alteró los marcadores.')
        for i in range(before.page_count):
            a,b=before[i],after[i]
            if (tuple(a.mediabox),tuple(a.cropbox),a.rotation)!=(tuple(b.mediabox),tuple(b.cropbox),b.rotation):
                raise EditError('Cambió la geometría de una página.')
            if without_underlines(a,old_underlines if i==page_number else [])!=without_underlines(b,new_underlines if i==page_number else []):
                raise EditError('La edición alteró imágenes, vectores, enlaces, anotaciones o campos ajenos.')
            assert_characters([(g.text,g.origin,g.font,g.size) for g in expected] if i==page_number else trace_chars(a),b)
            decorated = old_underlines+new_underlines if pixel_underlines is None else pixel_underlines
            excluded=[g.bbox for g in changed]+[item['rect'] for item in decorated] if i==page_number else []
            pixels=assert_pixels(a,b,excluded)
            # Publish measured embedded outlines for independent renderers too:
            # their hinting may expose an accent overhang MuPDF did not paint.
            pixels['verified_ink_regions']=list(dict.fromkeys(_ink_exclusions(a,excluded)+_ink_exclusions(b,excluded)))
            reports.append(pixels)
    PdfReader(BytesIO(after_data),strict=True)
    assert_structure(before_data,after_data,tagged_expected)
    return dict(verified=True,pages=reports,independent_parser='pypdf')
