"""Move a simple text fragment together with its isolated rectangular clip.

The original SHOW retains only neighbours and exact advances; a page-local
copy of its text-only graphics scope paints only the selected codes. Its clip
is translated, never enlarged. Other scopes, resources and pages stay intact.
"""
from dataclasses import replace
import copy
from io import BytesIO
import math
import time

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, DecodedStreamObject, FloatObject

from .clipping import CLIP_ISSUE, SHOW, _advance, _raw, _serialize, _signature
from .clipped_layout import _state_at, _assert_typography
from .model import EditError, intersects, union
from .validation import document_issues, validate_transition


ALLOWED = {b'q', b'Q', b're', b'W', b'W*', b'n', b'cm', b'rg', b'RG', b'g', b'G',
           b'k', b'K', b'gs', b'BT', b'ET', b'Tf', b'Tm', b'Tc', b'Tw', b'Tz', b'TL',
           b'Ts', b'Tr', b'Tj', b'TJ'}


def _scope(operations, target):
    stack, matches = [], {}
    for index, (_, op) in enumerate(operations):
        if op == b'q':
            stack.append(index)
        elif op == b'Q':
            if not stack:
                raise EditError('El ámbito gráfico contiene un cierre sin apertura.')
            begin = stack.pop()
            if begin < target < index:
                matches[begin] = index
    for begin in sorted(matches, reverse=True):
        end = matches[begin]
        scope = operations[begin:end+1]
        operators = [op for _, op in scope]
        if not any(op in (b'W', b'W*') for op in operators):
            continue
        if (any(op not in ALLOWED for op in operators)
                or sum(op in SHOW for op in operators) != 1
                or operators.count(b'BT') != 1 or operators.count(b'ET') != 1
                or operators.count(b'Tm') != 1 or operators.count(b're') != 1
                or sum(op in (b'W', b'W*') for op in operators) != 1):
            continue
        rectangle = operators.index(b're')
        if (operators[rectangle+1:rectangle+3] not in ([b'W', b'n'], [b'W*', b'n'])
                or not rectangle < operators.index(b'BT') < target-begin < operators.index(b'ET')):
            continue
        return begin, end
    raise EditError('Mover fuera del recorte necesita un ámbito aislado con un único tramo de texto y un recorte rectangular; este fragmento comparte un ámbito más complejo.')


def move_text_with_clip(data, request, model, mapped, tagged_move=None):
    from .engine import _safe_selection, full_write
    started = time.perf_counter()
    reader, operations, shows, mapping = mapped
    if reader.trailer['/Root'].get('/StructTreeRoot') and tagged_move is None:
        raise EditError('El traslado de recortes con etiquetas accesibles requiere conservar conjuntamente su estructura; no está habilitado para esta selección.')
    selected = model.selected(request.ids)
    ids = {g.id for g in selected}
    targets = {mapping[g.id]['operation'] for g in selected}
    if len(targets) != 1:
        raise EditError('Para trasladar el recorte selecciona un único tramo de texto aislado.')
    target = next(iter(targets))
    show = next(s for s in shows if s['operation'] == target)
    if show['font'].get('/Subtype') not in ('/TrueType', '/Type1') or show['render_mode'] != 0:
        raise EditError('Este traslado de recorte requiere texto visible con códigos simples y avances verificables.')
    selected_positions = [i for i, glyph in enumerate(show['glyphs']) if glyph.id in ids]
    if not selected_positions or selected_positions != list(range(min(selected_positions), max(selected_positions)+1)):
        raise EditError('Selecciona caracteres contiguos del mismo tramo para trasladar su recorte.')
    dx, dy = request.dx, request.dy
    planned = [replace(g, origin=(g.origin[0]+dx, g.origin[1]+dy),
                       bbox=tuple(v+(dx if i%2 == 0 else dy) for i, v in enumerate(g.bbox)),
                       trace_bbox=tuple(v+(dx if i%2 == 0 else dy) for i, v in enumerate(g.trace_bbox))) for g in selected]
    others = [g for g in model.glyphs if g.id not in ids]
    clean = replace(model, issues=[i for i in model.issues if i != CLIP_ISSUE])
    with fitz.open(stream=data, filetype='pdf') as doc:
        issues = document_issues(data, doc)
        if issues:
            raise EditError('\n'.join(issues))
        _safe_selection(doc[request.page], clean, selected, preserve_paint_order=True)
        _safe_selection(doc[request.page], clean, planned, preserve_paint_order=True)
        doc[request.page].set_rotation(0)
        page_matrix = doc[request.page].transformation_matrix
        page_bounds = fitz.Rect(0, 0, doc[request.page].cropbox.width, doc[request.page].cropbox.height)
    resources = reader.pages[request.page].get('/Resources')
    if tagged_move:
        from .tagged_clip_move import clip_scope
        begin, end = clip_scope(operations, target, planned, resources, page_matrix, page_bounds, ALLOWED)
    else:
        begin, end = _scope(operations, target)
    parent = _state_at(operations, begin, resources)
    state = _state_at(operations, target, resources)
    if (parent['unknown'] or state['unknown'] or state['clip'] is None
            or state['size'] is None or state['size'] <= 0
            or not all(math.isfinite(float(state[k])) for k in ('size', 'tc', 'tw', 'tz'))):
        raise EditError('El recorte o los avances del texto no se pueden trasladar con garantías.')
    inherited_clip = parent['clip']*page_matrix if parent['clip'] is not None else page_bounds
    original_clip = state['clip']*page_matrix
    for old, new in zip(selected, planned):
        if not (original_clip+(-.02, -.02, .02, .02)).contains(fitz.Rect(old.bbox)):
            raise EditError('El texto original está parcialmente oculto por el recorte; no se revelará contenido al moverlo.')
        if not page_bounds.contains(fitz.Rect(new.bbox)) or not inherited_clip.contains(fitz.Rect(new.bbox)):
            raise EditError('La posición queda fuera de la página o de otro recorte superior que no pertenece al texto.')
    if not request.allow_overlap and any(intersects(g.bbox, other.bbox, .12) for g in planned for other in others):
        raise EditError('El texto movido se solapa con un vecino. Elige otra posición.')
    linear = parent['ctm']*page_matrix
    if not all(math.isfinite(v) for v in linear) or abs(linear.a*linear.d-linear.b*linear.c) < 1e-10:
        raise EditError('La transformación superior del recorte no es invertible.')
    delta = fitz.Point(dx, dy)*(~linear)-fitz.Point(0, 0)*(~linear)
    def isolate(item, keep_selected):
        args, op = operations[item['operation']]
        item_state = _state_at(operations, item['operation'], resources)
        composite = (item['font'].get('/Subtype') == '/Type0'
                     and item['font'].get('/Encoding') == '/Identity-H')
        unit = 2 if composite else 1
        if (op not in (b'Tj', b'TJ') or item['render_mode'] != 0
                or not (item['font'].get('/Subtype') in ('/TrueType', '/Type1') or tagged_move and composite)
                or item_state['size'] is None or item_state['size'] <= 0):
            raise EditError('Un vecino del ámbito de recorte no tiene códigos simples y avances verificables.')
        array = args[0] if op == b'TJ' else [args[0]]
        raw_values = [_raw(value) for value in array if isinstance(value, (str, bytes))]
        if any(len(value) % unit for value in raw_values) or sum(len(value)//unit for value in raw_values) != len(item['glyphs']):
            raise EditError('No se puede relacionar cada código original con un carácter del tramo.')
        result = ArrayObject()
        position = 0
        for value in array:
            if not isinstance(value, (str, bytes)):
                result.append(copy.deepcopy(value))
                continue
            raw = _raw(value)
            for offset in range(0, len(raw), unit):
                code_bytes = raw[offset:offset+unit]
                code = int.from_bytes(code_bytes, 'big')
                glyph = item['glyphs'][position]
                if (glyph.id in ids) == keep_selected:
                    if result and isinstance(result[-1], bytes):
                        result[-1] = ByteStringObject(bytes(result[-1])+code_bytes)
                    else:
                        result.append(ByteStringObject(code_bytes))
                else:
                    from .richtext import _source_width
                    advance = (_source_width(item['font'], code, glyph.text)
                               + 1000*item_state['tc']/item_state['size']
                               + (1000*item_state['tw']/item_state['size'] if code_bytes == b' ' else 0))
                    if not math.isfinite(advance):
                        raise EditError('El avance de un carácter vecino no es finito.')
                    result.append(FloatObject(-advance))
                position += 1
        return result
    retained, moving = isolate(show, False), isolate(show, True)
    clone = copy.deepcopy(operations[begin:end+1])
    clone[target-begin] = ([moving], b'TJ')
    if tagged_move:
        # Retain every neighbouring show's exact advance but emit no glyphs.
        # The clone therefore paints only the selected codes, even when the
        # cell has repeated clips and several independent text objects.
        for item in shows:
            if begin < item['operation'] < end and item['operation'] != target:
                clone[item['operation']-begin] = ([isolate(item, True)], b'TJ')
    translation = [FloatObject(v) for v in (1, 0, 0, 1, delta.x, delta.y)]
    clone.insert(1, (translation, b'cm'))
    changed = []
    for index, item in enumerate(operations):
        changed.append(([retained], b'TJ') if index == target else copy.deepcopy(item))
        if index == end:
            changed.extend(clone)
    serialized = _serialize(changed)
    temporary = DecodedStreamObject()
    temporary.set_data(serialized)
    expected_ops = ContentStream(temporary, reader).operations
    with fitz.open(stream=data, filetype='pdf') as doc:
        stream = doc.get_new_xref()
        doc.update_object(stream, '<<>>')
        doc.update_stream(stream, serialized)
        doc[request.page].set_contents(stream)
        output = full_write(doc)
    after = PdfReader(BytesIO(output), strict=True)
    actual_ops = ContentStream(after.pages[request.page].get_contents(), after).operations
    if len(actual_ops) != len(expected_ops) or any(op != newop or _signature(args) != _signature(newargs)
            for (args, op), (newargs, newop) in zip(expected_ops, actual_ops)):
        raise EditError('El guardado alteró operadores ajenos al traslado del recorte.')
    if _signature(reader.pages[request.page]['/Resources']) != _signature(after.pages[request.page]['/Resources']):
        raise EditError('El guardado alteró recursos compartidos durante el traslado del recorte.')
    _assert_typography(output, request.page, others+planned)
    report = validate_transition(data, output, request.page,
                                 [(g.text, g.origin, g.font, g.size) for g in others+planned],
                                 [g.bbox for g in selected+planned])
    if tagged_move:
        report['accessibility'] = tagged_move.validate(output)
    report.update(page=request.page, operation='move_text_with_clip',
                  source_regions=[g.bbox for g in selected], destination_regions=[g.bbox for g in planned],
                  old_bounds=union(g.bbox for g in selected), new_bounds=union(g.bbox for g in planned),
                  moved_characters=len(selected), changed_characters=0, font_resources_unchanged=True,
                  operators_preserved=True, clip_translated=True, clip_enlarged=False,
                  clipped_text_mode='Tramo y recorte rectangular trasladados juntos; vecinos y recursos conservados.',
                  cursor_residual=0, elapsed_seconds=round(time.perf_counter()-started, 3))
    return output, report
