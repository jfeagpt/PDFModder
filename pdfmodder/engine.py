"""Motor conservador: transacciones sobre copias y eliminación real de contenido.

Todas las llamadas MuPDF de la aplicación se ejecutan en UN proceso dedicado.
Los operadores se interpretan con un parser. Los documentos etiquetados conservan
sus relaciones mediante el módulo tagged; se bloquea la semántica ambigua.
"""
from dataclasses import replace
from pathlib import Path
import hashlib
import math
import os
import statistics
import tempfile
import time
import unicodedata
import pymupdf as fitz
from .model import Glyph, PageModel, EditRequest, EditError, union, intersects
from .fonts import FontResolver, FontError
from .validation import document_issues, page_issues, assert_characters, assert_pixels, validate_transition, trace_chars


def extract_page(doc, number, data=None):
    page = doc[number]
    # Selection uses the visible glyphs. ActualText is checked and updated
    # separately by tagged.py; it must not replace visual character geometry.
    raw = page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT|fitz.TEXT_IGNORE_ACTUALTEXT)
    raw_chars = []
    line_id = 0
    for block in raw['blocks']:
        if block['type'] != 0:
            continue
        lines = block['lines']
        # MuPDF sometimes groups different columns in one block: never accept
        # same-baseline lines as a paragraph; split ambiguous groups.
        coherent = all(abs(a['bbox'][1]-b['bbox'][1]) > 2 and
                       min(a['bbox'][2],b['bbox'][2])-max(a['bbox'][0],b['bbox'][0]) >
                       .5*min(a['bbox'][2]-a['bbox'][0],b['bbox'][2]-b['bbox'][0])
                       for a,b in zip(lines,lines[1:]))
        group = line_id
        for line in lines:
            for si, span in enumerate(line['spans']):
                for ch in span['chars']:
                    if not ch.get('synthetic'):
                        raw_chars.append((ch,group if coherent else line_id,line_id,si))
            line_id += 1
    raw_index={}
    for item in raw_chars:
        ch=item[0]
        key=(ch['c'],round(ch['origin'][0],1),round(ch['origin'][1],1))
        raw_index.setdefault(key,[]).append(item)
    glyphs = []
    for span_no,span in enumerate(page.get_texttrace()):
        for ch in span['chars']:
            text, origin, trace_bbox = chr(ch[0]), tuple(ch[2]), tuple(ch[3])
            nearby=raw_index.get((text,round(origin[0],1),round(origin[1],1)),[])
            found = next((x for x in nearby if x[0]['c']==text and
                          abs(x[0]['origin'][0]-origin[0])<.03 and abs(x[0]['origin'][1]-origin[1])<.03),None)
            bbox,bid,lid,si = (tuple(found[0]['bbox']),found[1],found[2],found[3]) if found else (trace_bbox,line_id+span_no,line_id+span_no,0)
            glyphs.append(Glyph(len(glyphs),text,origin,bbox,trace_bbox,span['font'],float(span['size']),
                                tuple(span['color']),float(span['opacity']),bid,lid,si,
                                tuple(span['dir']),int(span['type']),span.get('layer',''),span['seqno'],
                                bool(found) and not span.get('wmode') and not span.get('bidi_lvl')))
    issues = page_issues(data,number) if data else []
    if page.get_xobjects():
        issues.append("Página con Form XObjects: las instancias compartidas no se editan en esta versión.")
    if any(a.type[0]==fitz.PDF_ANNOT_REDACT for a in page.annots() or []):
        issues.append("La página contiene redacciones pendientes; se bloquea para no aplicarlas accidentalmente.")
    model=PageModel(number,page.rect.width,page.rect.height,page.rotation,tuple(page.rotation_matrix),
                    tuple(page.derotation_matrix),tuple(page.cropbox),glyphs,issues,
                    hashlib.sha256(data).hexdigest() if data else None)
    from .lineflow import normalize_rebuilt_lines
    model=normalize_rebuilt_lines(model)
    if data and model.glyphs:
        from .clipping import annotate_font_resources
        model=annotate_font_resources(data,number,model)
    return model


def full_write(doc):
    return doc.tobytes(garbage=4, deflate=True, incremental=False, no_new_id=True)


def _style(g):
    return g.font,round(g.size,4),g.color,g.opacity,g.direction,g.mode


def _stroke_hits(drawing, rect):
    """Exact conservative envelopes for horizontal/vertical lines and rectangles.

    Curves, diagonal segments and unusual joins retain their bounding envelope.
    """
    margin=(drawing.get('width') or 1)/2+.1
    def segment(a,b):
        if abs(a[0]-b[0])<1e-5 or abs(a[1]-b[1])<1e-5:
            bounds=(min(a[0],b[0])-margin,min(a[1],b[1])-margin,
                    max(a[0],b[0])+margin,max(a[1],b[1])+margin)
            return intersects(bounds,rect)
        return intersects(tuple(drawing['rect']),rect)
    for item in drawing['items']:
        if item[0]=='l':
            if segment(item[1],item[2]): return True
        elif item[0]=='re':
            r=item[1]
            corners=[(r.x0,r.y0),(r.x1,r.y0),(r.x1,r.y1),(r.x0,r.y1),(r.x0,r.y0)]
            if any(segment(a,b) for a,b in zip(corners,corners[1:])): return True
        elif intersects(tuple(drawing['rect']),rect):
            return True
    return False


def _safe_selection(page, model, selected, *, preserve_paint_order=False):
    if model.issues:
        raise EditError('\n'.join(model.issues))
    if not selected:
        raise EditError("Selecciona caracteres, una palabra o una línea.")
    paint_log=[] if preserve_paint_order else page.get_bboxlog()
    drawings={} if preserve_paint_order else {d['seqno']:d for d in page.get_drawings()}
    for g in selected:
        if not g.reliable or g.text=='\ufffd' or (unicodedata.category(g.text).startswith('C') and g.text!='\u00ad'):
            raise EditError("Codificación, ligadura o dirección del texto no reconstruible con garantías.")
        if abs(g.direction[0]-1)>1e-5 or abs(g.direction[1])>1e-5:
            raise EditError("Texto con orientación propia: sólo se edita texto horizontal; la rotación de página sí se admite.")
        if g.mode != 0 or g.layer:
            raise EditError("Texto invisible, trazado, recortado o en capas: propiedad no reproducible.")
        for index,item in enumerate(paint_log):
            # Painting after text may obscure it. Reinsertion on top would alter z order.
            if not preserve_paint_order and index>g.seqno and item[0] not in ('fill-text','ignore-text') and intersects(item[1],g.bbox):
                if item[0]=='stroke-path' and index in drawings and not _stroke_hits(drawings[index],g.bbox):
                    continue
                raise EditError("Hay un objeto dibujado encima del texto; no puede conservarse su orden visual.")
        if any(intersects(tuple(link['from']),g.bbox) for link in page.get_links()):
            raise EditError("La selección forma parte de un enlace. No se puede cambiar texto y área activa conjuntamente.")
        if any(intersects(tuple(a.rect),g.bbox) for a in page.annots() or []):
            raise EditError("La selección toca una anotación; edita un fragmento que pueda aislarse.")


def _safe_native_consolidation(page, selected, planned):
    """Composing at the first SHOW must not cross an intervening paint item.

    A native edit retains later/earlier artwork in its original order, unlike
    redaction followed by overlay insertion. Consolidating several SHOWs can
    still cross intervening objects, so verify that narrower condition.
    """
    first, last = min(g.seqno for g in selected), max(g.seqno for g in selected)
    chosen={g.id for g in selected}
    low,high=min(chosen),max(chosen)
    if high-low+1!=len(chosen):
        # Selected and unselected characters can share a SHOW, including the
        # first/last one. Consolidating may not cross those neighbours either.
        model=extract_page(page.parent,page.number)
        for glyph in model.glyphs:
            if low<glyph.id<high and glyph.id not in chosen and any(intersects(glyph.bbox,g.bbox) for g in selected+planned):
                raise EditError('La selección atraviesa texto vecino intercalado. Edita cada fragmento por separado para conservar el orden visual.')
    if first == last:
        return
    drawings = {d['seqno']: d for d in page.get_drawings()}
    for index, item in enumerate(page.get_bboxlog()):
        if not first < index < last or item[0] == 'ignore-text':
            continue
        if item[0] == 'fill-text' and any(g.seqno == index for g in selected):
            continue
        for glyph in selected + planned:
            if not intersects(item[1], glyph.bbox):
                continue
            if item[0] == 'stroke-path' and index in drawings and not _stroke_hits(drawings[index], glyph.bbox):
                continue
            raise EditError('La selección atraviesa un objeto intercalado entre sus fragmentos. Edita cada fragmento por separado para conservar el orden visual.')


def _redact(page, model, selected):
    ids = {g.id for g in selected}
    other = [g for g in model.glyphs if g.id not in ids]
    for g in selected:
        x0,y0,x1,y1 = g.bbox
        candidate = None
        for fx,fy in [(0.5,0.5),(.25,.5),(.75,.5),(.5,.25),(.5,.75)]:
            x,y=x0+(x1-x0)*fx,y0+(y1-y0)*fy
            tiny=(x-.04,y-.04,x+.04,y+.04)
            if not any(intersects(tiny,n.bbox) for n in other):
                candidate=tiny
                break
        if candidate is None:
            raise EditError("No se puede aislar el carácter sin eliminar un vecino superpuesto.")
        page.add_redact_annot(candidate,fill=False,cross_out=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)
    assert_characters([(g.text,g.origin,g.font,g.size) for g in other],page)


def _insert(page, glyphs, resolved):
    aliases = {}
    for g in glyphs:
        choice = resolved[g.font]
        # A Unicode font can map space/NBSP and hyphen/soft-hyphen to one GID;
        # MuPDF's generated ToUnicode then chooses one spelling. WinAnsi keeps
        # ordinary Spanish text unambiguous. Original NBSP/soft hyphen retain
        # the composite path, so we never silently normalize existing text.
        try:
            encoded=g.text.encode('cp1252').decode('latin1')
            simple=g.text not in ('\u00a0','\u00ad')
        except UnicodeEncodeError:
            encoded=g.text
            simple=False
        if choice.base14:
            if choice.base14 in ('symb','zadb'):
                encoded=g.text
            else:
                try:
                    encoded=g.text.encode('cp1252').decode('latin1')
                except UnicodeEncodeError as exc:
                    raise EditError("La codificación de este recurso Base14 no admite el carácter solicitado.") from exc
        key=(g.font,simple)
        if key not in aliases:
            if choice.base14:
                alias=choice.base14
                page.insert_font(fontname=alias)
            else:
                alias='PM'+hashlib.sha256(choice.buffer).hexdigest()[:14]+('W' if simple else 'U')
                page.insert_font(fontname=alias,fontbuffer=choice.buffer,set_simple=int(simple))
            aliases[key]=alias
        page.insert_text(g.origin,encoded if simple or choice.base14 else g.text,fontsize=g.size,fontname=aliases[key],
                         color=g.color,fill_opacity=g.opacity,overlay=True)


def _resolve(doc, page, selected, text, resolver):
    resolved = {}
    for name in dict.fromkeys(g.font for g in selected):
        existing=''.join(g.text for g in selected if g.font==name)
        try:
            resolved[name]=resolver.resolve(doc,page,name,existing+(text or '').replace('\n',''))
        except FontError as exc:
            raise EditError(str(exc)) from exc
    for g in selected:
        natural=resolved[g.font].width(g.text,g.size)
        original=g.trace_bbox[2]-g.trace_bbox[0]
        if abs(natural-original) > max(.035,g.size*.004):
            raise EditError("Escala horizontal o métricas de fuente diferentes: no se puede conservar la tipografía.")
    return resolved


def validate_rgb(color):
    if color is not None and (not isinstance(color, (tuple, list)) or len(color) != 3 or
                              any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in color)):
        raise EditError("El color debe contener tres componentes RGB entre 0 y 1.")


def _plan(selected, request, resolved, target=None):
    validate_rgb(request.color)
    if request.text is None and target is None and request.size is None:
        return [replace(g,origin=(g.origin[0]+request.dx,g.origin[1]+request.dy),
                        color=tuple(request.color) if request.color is not None else g.color,
                        bbox=tuple(v+(request.dx if i%2==0 else request.dy) for i,v in enumerate(g.bbox))) for g in selected]
    if request.text is None:
        content = []
        previous = None
        for glyph in selected:
            if previous is not None and glyph.line != previous.line:
                content.append('\n')
            content.append(glyph.text)
            previous = glyph
        request = replace(request, text=''.join(content))
    if len({_style(g) for g in selected})>1:
        raise EditError("La selección mezcla estilos. Selecciona un tramo de un solo estilo para escribir; el grupo completo sí se puede mover.")
    if len({g.line for g in selected})>1 and not request.reflow:
        raise EditError("Para sustituir varias líneas activa Redistribuir líneas explícitamente, o selecciona una línea.")
    # Arbitrary additions to selection are valid for moving, never concatenated for writing.
    for a,b in zip(selected,selected[1:]):
        if a.line==b.line and b.id!=a.id+1:
            raise EditError("La selección contiene fragmentos separados. Sustituye cada fragmento individualmente.")
    if any(unicodedata.category(c).startswith('C') and c!='\n' for c in request.text):
        raise EditError("No se admiten controles, tabuladores ni caracteres bidireccionales.")
    if any(unicodedata.combining(c) for c in request.text):
        raise EditError("Usa caracteres acentuados precompuestos; las marcas combinantes no están admitidas.")
    g=selected[0]
    original_choice=resolved[g.font]
    choice=target or original_choice
    size=request.size if request.size is not None else g.size
    if not 1<=size<=300:
        raise EditError("El tamaño manual debe estar entre 1 y 300 puntos.")
    bounds=union(x.bbox for x in selected)
    width=request.width if request.width is not None else bounds[2]-bounds[0]
    height=request.height if request.height is not None else bounds[3]-bounds[1]
    if width<=0 or height<=0:
        raise EditError("El área de edición debe tener anchura y altura positivas.")
    gaps=[b.origin[0]-a.origin[0]-original_choice.width(a.text,a.size) for a,b in zip(selected,selected[1:]) if a.line==b.line]
    spacing=statistics.median(gaps) if gaps else 0.
    if gaps and max(abs(v-spacing) for v in gaps)>.035:
        raise EditError("Espaciado irregular o ajuste por pares: se puede mover, pero no sustituir este tramo.")
    def measure(s):
        return choice.width(s,size)+max(0,len(s)-1)*spacing
    lines=request.text.split('\n')
    if len(lines)>1 and not request.reflow:
        raise EditError("Activa Redistribuir líneas para insertar saltos de línea.")
    asc=choice.font.ascender*size if target is not None else (g.origin[1]-g.bbox[1])*size/g.size
    desc=-choice.font.descender*size if target is not None else (g.bbox[3]-g.origin[1])*size/g.size
    lineheight=max(size*1.2, asc+desc) if target is not None else g.size*1.2
    if request.line_spacing is not None:lineheight=request.line_spacing
    from .paragraphs import layout_lines
    laid_out=layout_lines(request.text,measure,width,request.reflow,lineheight,request.paragraph_spacing)
    if laid_out and not request.auto_height and laid_out[-1][1]+(asc+desc)>height+.035:
        raise EditError("El texto supera la altura disponible. Amplía el área de edición.")
    result=[]
    for li,(line,line_offset) in enumerate(laid_out):
        line_width=measure(line)
        x=g.origin[0]+request.dx
        if request.anchor=='right':
            x=bounds[2]+request.dx-line_width
        elif request.anchor=='center':
            x=(bounds[0]+bounds[2])/2+request.dx-line_width/2
        elif request.anchor=='decimal':
            old=''.join(a.text for a in selected)
            sep=request.decimal_separator
            if len(lines)!=1 or len(sep)!=1 or old.count(sep)!=1 or line.count(sep)!=1:
                raise EditError("El anclaje decimal necesita un único separador explícito en cada texto.")
            decimal=selected[old.index(sep)].origin[0]
            x=decimal+request.dx-measure(line[:line.index(sep)])-(spacing if line.index(sep) else 0)
        y=g.origin[1]+request.dy+line_offset
        for char in line:
            cw=choice.width(char,size)
            result.append(replace(g,id=-1,text=char,origin=(x,y),size=size,
                                  font=choice.name if target is not None else g.font,
                                  color=tuple(request.color) if request.color is not None else g.color,
                                  bbox=(x,y-asc,x+cw,y+desc),line=li))
            x+=cw+spacing
    return result


def edit_pdf(data:bytes, request:EditRequest, resolver=None):
    if (request.text is None and request.size is None and not request.font_name and
            not request.font_file and request.color is None and not request.reflow):
        from .richtext import has_rich_metadata,move_rich_pdf
        if has_rich_metadata(data,request.page):
            return move_rich_pdf(data,request,resolver)
    started=time.perf_counter()
    resolver=resolver or FontResolver()
    validate_rgb(request.color)
    for value in (request.dx, request.dy, request.width, request.height, request.size):
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise EditError("Las posiciones y dimensiones deben ser números finitos.")
    if request.revision and request.revision!=hashlib.sha256(data).hexdigest():
        raise EditError("El documento cambió desde la selección. Selecciona el texto de nuevo.")
    with fitz.open(stream=data,filetype='pdf') as doc:
        issues=document_issues(data,doc)
        if issues:
            raise EditError('\n'.join(issues))
        model=extract_page(doc,request.page,data)
        selected=model.selected(request.ids)
        if len(selected)!=len(set(request.ids)):
            raise EditError("La selección pertenece a una versión anterior. Vuelve a seleccionarla.")
        ocr_mode=getattr(request,'ocr_mode','visible')
        if ocr_mode not in ('visible','searchable'):
            raise EditError("Modo OCR desconocido; selecciona edición visible o corrección buscable.")
        if ocr_mode=='searchable':
            from .ocr import edit_searchable
            return edit_searchable(data,request,model)
        if any(g.mode==3 for g in selected):
            raise EditError("Texto OCR invisible: activa explícitamente Corregir capa OCR buscable. La imagen escaneada conservará su apariencia.")
        if selected:
            from .ocr import clean_overlay
            cleaned,current,ocr_report=clean_overlay(data,request,model,selected)
            if ocr_report is not None:
                from .ocr import edit_visible_after_cleanup
                output,report=edit_visible_after_cleanup(cleaned,current,resolver)
                report['ocr_cleanup']=ocr_report
                report['warning']=ocr_report['warning']
                return output,report
        # CID subsets need their exact resource identity, not a family-name
        # lookup through the regional-redaction font resolver. Both UI paths
        # share the native compositor and its per-character validation.
        def partial_cid(glyph):
            if not glyph.font_xref or doc.xref_get_key(glyph.font_xref,'Subtype')[1]!='/Type0':
                return False
            base=doc.xref_get_key(glyph.font_xref,'BaseFont')[1].lstrip('/')
            return len(base)>7 and base[6]=='+' and base[:6].isalpha() and base[:6].isupper()
        if any(partial_cid(g) for g in selected):
            from .native_panel import edit_native_panel
            return edit_native_panel(data,request,model,resolver)
        from .clipping import CLIP_ISSUE,edit_clipped_text
        if CLIP_ISSUE in model.issues:
            return edit_clipped_text(data,request,model)
        if (request.allow_overlap and request.text is None and request.size is None
                and not request.font_name and not request.font_file and request.color is None):
            # Original text operators allow a later move to isolate the same
            # glyphs even after an exact overlap; regional redaction cannot.
            from .clipped_layout import move_clipped_text
            return move_clipped_text(data,request,model)
        page=doc[request.page]
        _safe_selection(page,model,selected)
        original_selection=selected[:]
        line_report={}
        manual_font=bool(request.font_name or request.font_file)
        # The original font proves reproduction before any requested typography
        # change. New characters only need to exist in the explicitly chosen face.
        resolved=_resolve(doc,request.page,selected,None if manual_font else request.text,resolver)
        target=None
        if manual_font:
            requested_text=request.text if request.text is not None else ''.join(g.text for g in selected)
            try:
                target=resolver.resolve_explicit(request.font_name or selected[0].font, requested_text, request.font_file)
            except FontError as exc:
                raise EditError(str(exc)) from exc
        if request.line_reflow:
            from .lineflow import expand_line,plan_line
            expanded=expand_line(model,selected)
            resolved.update(_resolve(doc,request.page,expanded,None,resolver))
            selected,planned,line_report=plan_line(model,selected,request,resolved,target)
        else:
            planned=_plan(selected,request,resolved,target)
        from .tagged import analyze,TaggedEdit
        structure=analyze(data)
        tagged_edit=None
        if structure is not None:
            tagged_edit=TaggedEdit(structure,request.page,model,selected,planned,original_selection,
                                   request.text is not None or manual_font or request.size is not None)
            selected=tagged_edit.selected
            resolved.update(_resolve(doc,request.page,selected,None,resolver))
            planned=[g for mcid in sorted(tagged_edit.affected) for g in tagged_edit.planned[mcid]]
        _safe_selection(page,model,selected)
        output_resolved=dict(resolved)
        if target is not None:
            output_resolved[target.name]=target
        others=[g for g in model.glyphs if g.id not in {item.id for item in selected}]
        allowed=fitz.Rect(0,0,page.cropbox.width,page.cropbox.height)
        images=page.get_image_info()
        strokes=[d for d in page.get_drawings() if d['type'] in ('s','fs')]
        overlaps=set()
        for g in planned:
            if not allowed.contains(fitz.Rect(g.bbox)):
                raise EditError("El destino queda fuera del área visible de la página.")
            collisions={n.id for n in others if intersects(g.bbox,n.bbox,.12)}
            overlaps.update(collisions)
            if collisions and not request.allow_overlap:
                raise EditError("El texto se solapa con caracteres no seleccionados. Mueve el área o activa «Permitir superponer texto» para conservar ambos contenidos en esa posición.")
            if any(intersects(g.bbox,tuple(x['from'])) for x in page.get_links()):
                raise EditError("El destino se solapa con un enlace existente.")
            if any(intersects(g.bbox,tuple(a.rect)) for a in page.annots() or []):
                raise EditError("El destino se solapa con una anotación existente.")
            for item in images:
                if intersects(item['bbox'],g.bbox) and not any(intersects(item['bbox'],old.bbox) for old in selected):
                    raise EditError("El destino se solapa con una imagen. Elige otra posición.")
            for drawing in strokes:
                if _stroke_hits(drawing,g.bbox) and not any(_stroke_hits(drawing,old.bbox) for old in selected):
                    raise EditError("El destino cruza una línea o borde vectorial. Ajusta la posición del texto.")
        # Idoneidad por operación: reproduce the original at its exact glyph origins.
        _redact(page,model,selected)
        erased=full_write(doc)
    # garbage=4 may renumber resources: never reuse a Page after serializing.
    if tagged_edit:
        reproduced=tagged_edit.insert(erased,resolved,reproduction=True)
    else:
        with fitz.open(stream=erased,filetype='pdf') as doc:
            _insert(doc[request.page],selected,resolved)
            reproduced=full_write(doc)
    with fitz.open(stream=data,filetype='pdf') as before, fitz.open(stream=reproduced,filetype='pdf') as copy:
        assert_pixels(before[request.page],copy[request.page],reproduction=True)
    if tagged_edit:
        output=tagged_edit.insert(erased,output_resolved)
    else:
        with fitz.open(stream=erased,filetype='pdf') as doc:
            _insert(doc[request.page],planned,output_resolved)
            output=full_write(doc)
    expected=[(g.text,g.origin,g.font,g.size) for g in others+planned]
    exclusions=[g.bbox for g in selected+planned]
    report=validate_transition(data,output,request.page,expected,exclusions,
                               tagged_expected=tagged_edit.expected if tagged_edit else None)
    if tagged_edit:
        report['accessibility']=tagged_edit.validate(output)
    report.update(line_report)
    report['elapsed_seconds']=round(time.perf_counter()-started,3)
    report['source_regions']=[g.bbox for g in selected]
    report['destination_regions']=[g.bbox for g in planned]
    report['fonts']={k:v.source for k,v in output_resolved.items()}
    report['page']=request.page
    report['manual_format']={'font':target.name if target is not None else None,'size':request.size,'color':request.color}
    if request.auto_height:
        bounds=union(g.bbox for g in planned)
        report.update(auto_height=True,area_height=max(.1,bounds[3]-bounds[1]))
    if overlaps:
        report.update(overlap_count=len(overlaps),warning=f'Superposición permitida sobre {len(overlaps)} caracteres vecinos; su contenido y posición se conservan.')
    return output,report


def atomic_save(data, destination, source=None):
    destination=Path(destination).resolve()
    if source and destination==Path(source).resolve():
        raise EditError("Guardar como no puede sobrescribir el original. Elige otra ruta.")
    if source and destination.exists() and os.path.samefile(destination,source):
        raise EditError("El destino apunta al archivo original mediante un enlace.")
    temporary=None
    try:
        with fitz.open(stream=data,filetype='pdf') as doc:
            issues=document_issues(data,doc)
            if issues:
                raise EditError('\n'.join(issues))
            output=full_write(doc)
        # The full-write route is the same as preview. Validate it before commit.
        validate_transition(data,output,-1,[],[])
        from pypdf import PdfReader
        import io
        PdfReader(io.BytesIO(output),strict=True)
        fd,temporary=tempfile.mkstemp(prefix='.pdfmodder-',suffix='.pdf',dir=destination.parent)
        with os.fdopen(fd,'wb') as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        with fitz.open(temporary) as check:
            if check.page_count!=len(PdfReader(io.BytesIO(output)).pages):
                raise EditError("Falló la verificación del archivo temporal.")
        os.replace(temporary,destination)
        temporary=None
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return str(destination)
