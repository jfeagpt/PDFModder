"""Corrección de OCR existente; no reconocimiento, nube ni edición de píxeles.

Los SHOW se interpretan y los códigos retirados se sustituyen por avances TJ.
Así no quedan caracteres ocultos antiguos y el cursor de los vecinos se conserva.
Sólo se admiten códigos simples o CID Identity-H verificables uno a uno.
"""
from dataclasses import replace
from io import BytesIO
import copy
import hashlib
import math
import unicodedata

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, DecodedStreamObject, FloatObject

from .clipping import CLIP_ISSUE, operator_glyph_map, _advance, _raw, _serialize, _signature, _strings
from .model import EditError, intersects, union
from .validation import validate_transition


SEARCHABLE_WARNING = ('Sólo se modifica la capa OCR buscable. La fotografía o imagen escaneada '
                      'conservará su texto y apariencia originales; no es una edición visual.')


def _error(message):
    raise EditError('OCR: '+message)


def _code_size(font):
    if font.get('/Subtype') in ('/TrueType', '/Type1'):
        return 1
    if font.get('/Subtype') == '/Type0' and font.get('/Encoding') == '/Identity-H':
        return 2
    _error('la codificación de esta capa no permite aislar sus caracteres con seguridad.')


def _codes(font, raw):
    size = _code_size(font)
    if len(raw) % size:
        _error('la cadena contiene un código de fuente incompleto.')
    return [raw[i:i+size] for i in range(0, len(raw), size)]


def _width(font, raw, text):
    code = int.from_bytes(raw, 'big')
    if len(raw) == 1:
        return _advance(font, code, text)
    descendants = font.get('/DescendantFonts', [])
    if len(descendants) != 1:
        _error('no se puede verificar la fuente CID de la capa.')
    cid = descendants[0].get_object()
    if cid.get('/Subtype') not in ('/CIDFontType2', '/CIDFontType0'):
        _error('el tipo de fuente CID no está soportado.')
    widths = cid.get('/W', [])
    widths = widths.get_object() if hasattr(widths, 'get_object') else widths
    cursor = 0
    while cursor < len(widths):
        start = int(widths[cursor]); cursor += 1
        item = widths[cursor]; cursor += 1
        item = item.get_object() if hasattr(item, 'get_object') else item
        if isinstance(item, (list, tuple)):
            if start <= code < start+len(item):
                return float(item[code-start])
        else:
            end = int(item)
            value = float(widths[cursor]); cursor += 1
            if start <= code <= end:
                return value
    return float(cid.get('/DW', 1000))


def _state(operations, index):
    from .clipped_layout import _state_at
    state = _state_at(operations, index)
    if (state['size'] is None or state['size'] <= 0 or state['tr'] != 3 or
            any(not math.isfinite(v) for v in (state['size'], state['tc'], state['tw'], state['tz']))):
        _error('el estado de fuente o el modo invisible no se puede verificar.')
    return state


def _advance_units(font, code, text, state):
    value = (_width(font, code, text) + 1000*state['tc']/state['size'] +
             (1000*state['tw']/state['size'] if code == b' ' else 0))
    if not math.isfinite(value):
        _error('el avance de un carácter no es finito.')
    return value


def _prepare(data, number, model):
    from .validation import document_issues
    with fitz.open(stream=data,filetype='pdf') as doc:
        problems=document_issues(data,doc)
        if problems:
            _error('\n'.join(problems))
    reader, operations, shows, mapping = operator_glyph_map(data, number, model)
    if reader.trailer['/Root'].get('/StructTreeRoot'):
        _error('la capa está en un documento etiquetado; sus relaciones accesibles necesitan una actualización conjunta.')
    forbidden = [issue for issue in model.issues if issue != CLIP_ISSUE]
    if forbidden:
        _error('\n'.join(forbidden))
    return reader, operations, shows, mapping


def _write(data, number, operations, result, reader, altered):
    from .engine import full_write
    with fitz.open(stream=data, filetype='pdf') as doc:
        xref = doc.get_new_xref()
        doc.update_object(xref, '<<>>')
        doc.update_stream(xref, _serialize(result))
        doc[number].set_contents(xref)
        output = full_write(doc)
    after = PdfReader(BytesIO(output), strict=True)
    actual = ContentStream(after.pages[number].get_contents(), after).operations
    if len(actual) != len(operations):
        _error('la escritura alteró el número de operadores.')
    for index, ((args, op), (new_args, new_op)) in enumerate(zip(operations, actual)):
        if index not in altered and (op != new_op or _signature(args) != _signature(new_args)):
            _error('se alteró un operador ajeno a la capa seleccionada.')
        if index in altered:
            # Normalize only the decimal representation of newly computed TJ
            # numbers; compare string bytes, irrespective of hex/literal form.
            parsed=DecodedStreamObject()
            parsed.set_data(_serialize([result[index]]))
            expected_args,expected_op=ContentStream(parsed,None).operations[0]
            if expected_op!=new_op or _signature(expected_args)!=_signature(new_args):
                _error('la escritura no conserva los operadores previstos.')
    if _signature(reader.pages[number]['/Resources']) != _signature(after.pages[number]['/Resources']):
        _error('se modificaron recursos de fuente, imágenes u otros elementos de página.')
    return output


def remove_hidden(data, number, model, ids):
    """Retira sólo códigos seleccionados; los números TJ preservan los vecinos."""
    ids = set(ids)
    selected = model.selected(ids)
    if not selected or len(selected) != len(ids) or any(g.mode != 3 or g.layer for g in selected):
        _error('la retirada sólo admite caracteres invisibles identificados de la versión actual.')
    reader, operations, shows, mapping = _prepare(data, number, model)
    result = copy.deepcopy(operations)
    altered = set()
    removed = set()
    for show in shows:
        if not ids.intersection(g.id for g in show['glyphs']):
            continue
        index = show['operation']
        args, op = operations[index]
        if show['render_mode'] != 3 or op not in (b'Tj', b'TJ'):
            _error('la operación invisible usa un salto o modo de texto no aislable.')
        state = _state(operations, index)
        font = show['font']
        values = args[0] if op == b'TJ' else [args[0]]
        glyphs = show['glyphs']
        if sum(len(_codes(font, _raw(v))) for v in values if isinstance(v, (str, bytes))) != len(glyphs):
            _error('la cantidad de códigos no coincide con la de caracteres OCR.')
        array = ArrayObject()
        position = 0
        for value in values:
            if not isinstance(value, (str, bytes)):
                array.append(value)
                continue
            for code in _codes(font, _raw(value)):
                glyph = glyphs[position]; position += 1
                if glyph.id in ids:
                    array.append(FloatObject(-_advance_units(font, code, glyph.text, state)))
                    removed.add(glyph.id)
                else:
                    array.append(ByteStringObject(code))
        result[index] = ([array], b'TJ')
        altered.add(index)
    if removed != ids:
        _error('no se pudieron localizar todos los caracteres de la capa seleccionada.')
    output = _write(data, number, operations, result, reader, altered)
    remaining = [g for g in model.glyphs if g.id not in ids]
    report = validate_transition(data, output, number,
                                 [(g.text, g.origin, g.font, g.size) for g in remaining], [])
    from .clipped_layout import _assert_typography
    _assert_typography(output, number, remaining)
    report.update(removed_characters=len(ids), removed_ids=sorted(ids),
                  appearance_unchanged=True, font_resources_unchanged=True,
                  operators_preserved=True, source_regions=[g.bbox for g in selected])
    return output, report


def _words(glyphs):
    current = []
    for glyph in glyphs:
        if glyph.text.isspace():
            if current:
                yield current
            current = []
        else:
            current.append(glyph)
    if current:
        yield current


def overlapping_hidden_ids(model, selected):
    """Candidatos sólo; la prueba de cobertura completa se realiza más abajo."""
    return {g.id for g in model.glyphs if g.mode == 3 and
            any(intersects(g.bbox, old.bbox, .12) for old in selected)}


def clean_overlay(data, request, model, selected):
    """Retira palabras OCR cubiertas por texto digital real y remapea selección."""
    scope = selected
    if request.line_reflow:
        from .lineflow import expand_line
        scope = expand_line(replace(model,glyphs=[g for g in model.glyphs if g.mode==0 and g.opacity>0]), selected)
    candidates = overlapping_hidden_ids(model, scope)
    if not candidates:
        return data, request, None
    # A partial character edit still replaces the OCR duplicate of the whole
    # visible word. Its remaining characters remain searchable as real text.
    visible_ids = set()
    for glyph in scope:
        visible_ids.update(model.group(glyph, 'word'))
    visible = [g for g in model.selected(visible_ids) if g.mode == 0 and g.opacity > 0]
    lines = {}
    for glyph in visible:
        lines.setdefault(glyph.line, []).append(glyph)
    bounds = [union(g.bbox for g in word) for line in lines.values() for word in _words(line)]
    _, _, shows, _ = _prepare(data, request.page, model)
    remove = set()
    for show in shows:
        if show['render_mode'] != 3:
            continue
        for word in _words(show['glyphs']):
            if not candidates.intersection(g.id for g in word):
                continue
            rect = union(g.bbox for g in word)
            def covered(box):
                # Every OCR character must belong to the visible word. A
                # majority-overlap test could incorrectly swallow a neighbour.
                # Half a point in x and one point in y accommodate measured
                # OCR baseline/rounding differences without another character.
                return all(box[0]-.5 <= (g.bbox[0]+g.bbox[2])/2 <= box[2]+.5 and
                           box[1]-1 <= (g.bbox[1]+g.bbox[3])/2 <= box[3]+1 for g in word)
            if not any(covered(box) for box in bounds):
                _error('la palabra OCR superpuesta abarca otra región. Selecciona su palabra visible completa; no se borrará información vecina.')
            remove.update(g.id for g in word)
    # Whitespace can intersect wide glyph boxes; remove only whitespace within
    # the selected visible words, without expanding into neighbouring columns.
    remove.update(g.id for g in model.glyphs if g.id in candidates and g.text.isspace())
    if candidates-remove:
        _error('la capa superpuesta no puede separarse en palabras identificables.')
    cleaned, report = remove_hidden(data, request.page, model, remove)
    remap = {g.id: index for index, g in enumerate(g for g in model.glyphs if g.id not in remove)}
    current = replace(request, ids=[remap[g.id] for g in selected],
                      revision=hashlib.sha256(cleaned).hexdigest())
    report['warning'] = ('Se retira el duplicado OCR invisible de las palabras editadas. '
                         'El texto visible nuevo seguirá siendo seleccionable y buscable.')
    return cleaned, current, report


def edit_visible_after_cleanup(data, request, resolver):
    """Prefer native SHOW edits so a corrected character stays in word order."""
    from .engine import edit_pdf,extract_page
    from .clipping import edit_clipped_text
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,request.page,data)
    selected=model.selected(request.ids)
    compatible=(request.text is not None and not request.reflow and not request.dx and not request.dy and
                not request.font_name and not request.font_file and request.color is None and
                (request.size is None or all(abs(g.size-request.size)<.001 for g in selected)) and
                getattr(request,'line_spacing',None) is None and not getattr(request,'paragraph_spacing',0))
    if compatible:
        _,operations,shows,mapping=operator_glyph_map(data,request.page,model)
        selected_ops={mapping[g.id]['operation'] for g in selected}
        selected_shows=[s for s in shows if s['operation'] in selected_ops]
        compatible=all(s['font'].get('/Subtype') in ('/TrueType','/Type1') for s in selected_shows)
        if compatible:
            catalog={}
            for show in shows:
                if show['font'].get('/Subtype') not in ('/TrueType','/Type1'):
                    continue
                a,o=operations[show['operation']]
                codes=b''.join(_raw(v) for _,v in _strings(a,o))
                if len(codes)==len(show['glyphs']):
                    for code,glyph in zip(codes,show['glyphs']):
                        catalog.setdefault((show['resource'],show['xref'],glyph.text),set()).add(code)
            if len(request.text)==len(selected):
                compatible=all(len(catalog.get((g.font_resource,g.font_xref,c),set()))==1
                               for g,c in zip(selected,request.text))
            elif len(selected_shows)==1:
                show=selected_shows[0]
                compatible=all(len(catalog.get((show['resource'],show['xref'],c),set()))==1 for c in request.text)
            else:
                compatible=False
        if compatible:
            return edit_clipped_text(data,request,model)
    # Reinserting a middle character at the end of the content stream can break
    # search order even when it is visually exact. Whole-word reconstruction
    # remains supported; fragments require a verified native-code route.
    if request.text is not None:
        chosen={g.id for g in selected}
        for glyph in selected:
            if not glyph.text.isspace() and not set(model.group(glyph,'word')).issubset(chosen):
                _error('para conservar el orden de búsqueda selecciona la palabra visible completa; este fragmento no tiene una ruta nativa verificable.')
    return edit_pdf(data,request,resolver)


def edit_searchable(data, request, model):
    """Corrige una selección invisible de forma explícita; apariencia idéntica."""
    selected = model.selected(request.ids)
    if (not selected or any(g.mode != 3 or g.layer or not g.reliable for g in selected) or
            len(selected) != len(set(request.ids))):
        _error('selecciona exclusivamente texto OCR invisible en el panel de elementos.')
    if request.text is None or '\n' in request.text or '\r' in request.text:
        _error('la corrección buscable admite texto de una sola línea; no mueve ni recompone una imagen.')
    if (request.dx or request.dy or request.font_name or request.font_file or request.color is not None or
            request.reflow or request.line_reflow or request.size is not None or
            getattr(request, 'line_spacing', None) is not None or getattr(request, 'paragraph_spacing', 0)):
        _error('desactiva redistribución y cambios de formato o posición para corregir sólo la capa buscable.')
    if request.anchor != 'left':
        _error('la corrección buscable mantiene el origen izquierdo de la capa.')
    if any(v is not None and v<=0 for v in (request.width,request.height)):
        _error('la anchura y altura de la capa deben ser positivas.')
    if any(unicodedata.category(c).startswith('C') or unicodedata.combining(c) for c in request.text):
        _error('usa caracteres precompuestos; no se admiten controles ni marcas combinantes.')
    reader, operations, shows, mapping = _prepare(data, request.page, model)
    operations_selected = {mapping[g.id]['operation'] for g in selected}
    if len(operations_selected) != 1:
        _error('selecciona una palabra o tramo perteneciente a una única operación OCR.')
    operation = operations_selected.pop()
    show = next(s for s in shows if s['operation'] == operation)
    args, op = operations[operation]
    if op not in (b'Tj', b'TJ') or show['render_mode'] != 3:
        _error('este salto u operación OCR no admite sustitución aislada.')
    font = show['font']
    state = _state(operations, operation)
    matrix = state['matrix']
    if abs(matrix.b)+abs(matrix.c) > 1e-7 or matrix.a <= 0 or matrix.d <= 0 or state['tz'] <= 0:
        _error('la orientación propia de esta capa todavía no admite corrección buscable.')
    catalog = {}
    for candidate in shows:
        if (candidate['resource'], candidate['xref']) != (show['resource'], show['xref']):
            continue
        a, o = operations[candidate['operation']]
        codes = _codes(font, b''.join(_raw(v) for _, v in _strings(a, o)))
        if len(codes) == len(candidate['glyphs']):
            for code, glyph in zip(codes, candidate['glyphs']):
                catalog.setdefault(glyph.text, set()).add(code)
    missing = sorted({char for char in request.text if len(catalog.get(char, set())) != 1})
    if missing:
        _error('faltan códigos únicos en el recurso original para: '+', '.join(missing)+'.')
    ids = [g.id for g in show['glyphs']]
    first, last = ids.index(selected[0].id), ids.index(selected[-1].id)+1
    if ids[first:last] != [g.id for g in selected] or len({g.line for g in selected}) != 1:
        _error('selecciona un tramo contiguo de una sola línea OCR.')
    values = args[0] if op == b'TJ' else [args[0]]
    original_codes = _codes(font, b''.join(_raw(v) for v in values if isinstance(v, (str, bytes))))
    if len(original_codes) != len(show['glyphs']):
        _error('los códigos originales no corresponden uno a uno a los caracteres.')
    new_codes = [next(iter(catalog[c])) for c in request.text]
    position, internal = 0, 0.
    for value in values:
        if isinstance(value, (str, bytes)):
            position += len(_codes(font, _raw(value)))
        elif first < position < last:
            internal += float(value)
    old_advance = sum(_advance_units(font, c, g.text, state) for c, g in
                      zip(original_codes[first:last], selected))-internal
    new_advance = sum(_advance_units(font, c, t, state) for c, t in zip(new_codes, request.text))
    replacement = ArrayObject()
    position, inserted = 0, False
    for value in values:
        if isinstance(value, (str, bytes)):
            for code in _codes(font, _raw(value)):
                if position == first and not inserted:
                    if new_codes:
                        replacement.append(ByteStringObject(b''.join(new_codes)))
                    replacement.append(FloatObject(new_advance-old_advance))
                    inserted = True
                if not first <= position < last:
                    replacement.append(ByteStringObject(code))
                position += 1
        elif not first < position < last:
            replacement.append(value)
    with fitz.open(stream=data, filetype='pdf') as doc:
        doc[request.page].set_rotation(0)
        linear = fitz.Matrix(matrix)*doc[request.page].transformation_matrix
        page_bounds = fitz.Rect(0, 0, doc[request.page].cropbox.width, doc[request.page].cropbox.height)
    vector = fitz.Point(1, 0)*linear-fitz.Point(0, 0)*linear
    template = selected[0]
    planned = []
    cursor = 0.
    for text, code in zip(request.text, new_codes):
        x, y = template.origin[0]+cursor*vector.x, template.origin[1]+cursor*vector.y
        width = _width(font, code, text)/1000*state['size']*state['tz']*vector.x
        bounds = (x, y+template.bbox[1]-template.origin[1], x+width,
                  y+template.bbox[3]-template.origin[1])
        planned.append(replace(template, id=-1, text=text, origin=(x, y), bbox=bounds))
        cursor += _advance_units(font, code, text, state)/1000*state['size']*state['tz']
    area = union(g.bbox for g in selected)
    if request.width is not None:
        area = (area[0], area[1], area[0]+request.width, area[3])
    if request.height is not None:
        area = (area[0], area[1], area[2], area[1]+request.height)
    if getattr(request, 'auto_width', False) and planned:
        area = (area[0], area[1], union(g.bbox for g in planned)[2], area[3])
    others = [g for g in model.glyphs if g.id not in set(request.ids)]
    for glyph in planned:
        if not (fitz.Rect(area)+(-.04, -.04, .04, .04)).contains(fitz.Rect(glyph.bbox)) or not page_bounds.contains(fitz.Rect(glyph.bbox)):
            _error('el texto buscable supera el área disponible. Amplía su anchura dentro de la misma región.')
        if any(g.mode == 3 and intersects(glyph.bbox, g.bbox, .12) for g in others):
            _error('el texto buscable nuevo se solapa con otra palabra OCR no seleccionada.')
    result = copy.deepcopy(operations)
    result[operation] = ([replacement], b'TJ')
    output = _write(data, request.page, operations, result, reader, {operation})
    report = validate_transition(data, output, request.page,
                                 [(g.text, g.origin, g.font, g.size) for g in others+planned], [])
    from .clipped_layout import _assert_typography
    _assert_typography(output, request.page, others+planned)
    report.update(page=request.page, ocr_mode='searchable', appearance_unchanged=True,
                  warning=SEARCHABLE_WARNING, source_regions=[g.bbox for g in selected],
                  destination_regions=[g.bbox for g in planned], font_resources_unchanged=True,
                  fonts={template.font: 'Recurso OCR original '+show['resource']},
                  line_reflow=False, operators_preserved=True, changed_characters=len(selected))
    if getattr(request,'auto_width',False):
        final_bounds=union(g.bbox for g in planned)
        report.update(auto_width=True,area_width=max(.1,final_bounds[2]-final_bounds[0]))
    return output, report
