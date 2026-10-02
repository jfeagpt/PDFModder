"""Ajuste horizontal de una línea: cambia espacios, nunca escala los glifos.

La pertenencia inicial procede de la extracción, no de buscar texto cercano.
Una línea ya reconstruida puede quedar partida por el extractor si sus espacios
crecen. Sólo se recupera una continuidad explícita de caracteres y espacios en
la secuencia de pintura de un glifo por tramo; una fila cercana no basta.
Cada palabra conserva las posiciones relativas de sus glifos originales. Las
regiones con separaciones ambiguas se rechazan antes de tocar el documento.
"""
from dataclasses import replace
from difflib import SequenceMatcher
import math
import statistics
import unicodedata

from .model import EditError, LineWidthOverflow, union


MIN_SPACE_RATIO = .75
MAX_GAP_EM = 4.


def _coherent_baselines(line):
    """Accept exporter jitter within one measured span, never merge rows.

    Some exporters position individual letters 0.12 / 0.24 pt above their
    neighbours. The original y coordinates remain authoritative. This narrow
    exception requires one extraction line, span and font; either one paint
    operation or the consecutive one-glyph operations of a reconstructed line,
    strongly overlapping vertical envelopes and at most 4% of an em (0.3 pt).
    It does not relax the separate proof for joining reconstructed fragments.
    """
    spread = max(g.origin[1] for g in line) - min(g.origin[1] for g in line)
    if spread <= .08:
        return True
    if spread > min(.3, min(g.size for g in line) * .04):
        return False
    if len({(g.line, g.span, g.font, round(g.size, 4)) for g in line}) != 1:
        return False
    same_operation = len({g.seqno for g in line}) == 1
    rebuilt = all(b.id == a.id+1 and b.seqno == a.seqno+1 for a,b in zip(line,line[1:]))
    if not (same_operation or rebuilt):
        return False
    heights = [g.trace_bbox[3] - g.trace_bbox[1] for g in line]
    overlap = min(g.trace_bbox[3] for g in line) - max(g.trace_bbox[1] for g in line)
    return min(heights) > 0 and overlap >= .95 * max(heights)


def _replacement_baselines(selected, text):
    """Keep surviving letters' baselines; new runs inherit their source start.

    Equal-length replacements retain each replaced position's y coordinate.
    With an insertion/deletion, unchanged characters retain theirs and new
    characters use the first replaced character (or the insertion neighbour).
    No other word is flattened onto a common baseline.
    """
    if len(text) == len(selected):
        return [g.origin[1] for g in selected]
    origins = []
    matcher = SequenceMatcher(None, ''.join(g.text for g in selected), text, autojunk=False)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == 'equal' or (tag == 'replace' and a1-a0 == b1-b0):
            origins.extend(g.origin[1] for g in selected[a0:a1])
        elif b1 > b0:
            source = selected[min(a0, len(selected)-1)]
            origins.extend([source.origin[1]] * (b1-b0))
    return origins


def _continuous_rebuilt_line(left, right):
    """Prueba de continuidad, estricta, para fragmentos de nuestra reinserción.

    No utiliza la cercanía entre cajas como criterio de agrupación. Exige un
    espacio real que enlace ambos fragmentos y la secuencia consecutiva de
    operaciones de un glifo por tramo que emite el motor al reconstruir texto.
    Una línea de columna dibujada como un tramo ordinario no cumple la prueba.
    """
    if not left or not right:
        return False
    joined = left + right
    if len({(g.mode,g.opacity>0) for g in joined}) != 1:
        return False
    if left[-1].text not in (' ', '\u00a0') and right[0].text not in (' ', '\u00a0'):
        return False
    if any(b.id != a.id+1 or b.seqno != a.seqno+1 for a,b in zip(joined, joined[1:])):
        return False
    if any(not g.reliable or abs(g.direction[0]-1)>1e-5 or abs(g.direction[1])>1e-5 for g in joined):
        return False
    if max(g.origin[1] for g in joined)-min(g.origin[1] for g in joined) > .08:
        return False
    if any(b.origin[0] < a.origin[0]-.035 for a,b in zip(joined, joined[1:])):
        return False
    # Measure the complete intervening whitespace, including a space attached
    # to either rawdict fragment. More than two spaces remains a tabular cue.
    split = len(left)
    start, end = split, split
    while start > 0 and joined[start-1].text in (' ', '\u00a0'):
        start -= 1
    while end < len(joined) and joined[end].text in (' ', '\u00a0'):
        end += 1
    if start == 0 or end == len(joined) or not 1 <= end-start <= 2:
        return False
    before, after = joined[start-1], joined[end]
    natural_end = before.origin[0] + before.trace_bbox[2]-before.trace_bbox[0]
    gap = after.origin[0]-natural_end
    natural = sum(g.trace_bbox[2]-g.trace_bbox[0] for g in joined[start:end])
    maximum = MAX_GAP_EM * max(g.size for g in joined[start:end])
    return natural*MIN_SPACE_RATIO-.035 <= gap <= maximum+.035


def normalize_rebuilt_lines(model):
    """Unifica sólo líneas partidas con la misma prueba estricta de continuidad.

    Se ejecuta al extraer el modelo, para que selección, dimensiones y edición
    utilicen la misma línea. IDs, orden, geometría, fuentes y demás propiedades
    de los glifos se conservan. Los bloques sólo se unifican cuando cada bloque
    original contenía exclusivamente uno de los fragmentos recuperados.
    """
    groups, positions, block_lines = {}, {}, {}
    for index,g in enumerate(model.glyphs):
        groups.setdefault(g.line, []).append(g)
        positions.setdefault(g.line, []).append(index)
        block_lines.setdefault(g.block, set()).add(g.line)
    # Dict insertion order follows painting order. A raw line interleaved with
    # other text cannot participate: no geometric reordering is introduced.
    chains = []
    current = []
    low = high = None
    previous = None
    for number,group in groups.items():
        indexes = positions[number]
        contiguous = indexes[-1]-indexes[0]+1 == len(indexes)
        gl,gh = min(g.origin[1] for g in group),max(g.origin[1] for g in group)
        can_join = (contiguous and previous is not None and current and
                    positions[previous][-1]+1 == indexes[0] and
                    max(high,gh)-min(low,gl) <= .08 and
                    _continuous_rebuilt_line(groups[previous],group))
        if can_join:
            current.append(number)
            low,high = min(low,gl),max(high,gh)
        else:
            if current:
                chains.append(current)
            current = [number] if contiguous else []
            low,high = gl,gh
        previous = number if contiguous else None
    if current:
        chains.append(current)
    line_mapping,block_mapping = {},{}
    for chain in chains:
        if len(chain)<2:
            continue
        line_mapping.update({number:chain[0] for number in chain})
        blocks = {g.block for number in chain for g in groups[number]}
        if all(len(block_lines[block])==1 for block in blocks):
            block_mapping.update({number:groups[chain[0]][0].block for number in chain})
    if not line_mapping:
        return model
    return replace(model,glyphs=[replace(g,line=line_mapping.get(g.line,g.line),
                                          block=block_mapping.get(g.line,g.block))
                                 if g.line in line_mapping else g for g in model.glyphs])


def expand_line(model, selected):
    """Línea de extracción o fragmentos con continuidad de pintura demostrada."""
    if not selected:
        raise EditError("Selecciona una palabra o una línea para ajustar el texto.")
    line = [g for g in model.glyphs if g.line == selected[0].line and g.mode == selected[0].mode
            and (g.opacity>0)==(selected[0].opacity>0)]
    # Do not sort geometrically: only adjacent content in painting/extraction
    # order can extend the initial line. Whole raw lines are added or rejected.
    index_by_id = {g.id:i for i,g in enumerate(model.glyphs)}
    while True:
        offset = index_by_id[line[0].id]
        if offset == 0:
            break
        previous = model.glyphs[offset-1]
        fragment = [g for g in model.glyphs if g.line == previous.line and g.mode == previous.mode
                    and (g.opacity>0)==(previous.opacity>0)]
        if previous.line in {g.line for g in line} or not _continuous_rebuilt_line(fragment, line):
            break
        line = fragment + line
    while True:
        offset = index_by_id[line[-1].id]+1
        if offset >= len(model.glyphs):
            break
        following = model.glyphs[offset]
        fragment = [g for g in model.glyphs if g.line == following.line and g.mode == following.mode
                    and (g.opacity>0)==(following.opacity>0)]
        if following.line in {g.line for g in line} or not _continuous_rebuilt_line(line, fragment):
            break
        line += fragment
    if len({g.line for g in selected} - {g.line for g in line}):
        raise EditError("El ajuste justificado sólo modifica una línea cada vez.")
    indices = [i for i, g in enumerate(line) if g.id in {s.id for s in selected}]
    if len(indices) != len(selected) or indices != list(range(indices[0], indices[-1] + 1)):
        raise EditError("La selección contiene fragmentos separados de la línea.")
    if any(not g.reliable or abs(g.direction[0] - 1) > 1e-5 or abs(g.direction[1]) > 1e-5 for g in line):
        raise EditError("La línea contiene una dirección o codificación que no puede ajustarse con garantías.")
    if any(b.origin[0] < a.origin[0] - .035 for a, b in zip(line, line[1:])):
        raise EditError("El orden de los caracteres de la línea es ambiguo; no se puede justificar.")
    if not _coherent_baselines(line):
        raise EditError("La línea mezcla líneas base distintas; no se puede ajustar con garantías.")
    return line


def _shift(glyph, dx=0., dy=0.):
    def shifted(rect):
        return tuple(v + (dx if i % 2 == 0 else dy) for i, v in enumerate(rect))
    return replace(glyph, origin=(glyph.origin[0] + dx, glyph.origin[1] + dy),
                   bbox=shifted(glyph.bbox), trace_bbox=shifted(glyph.trace_bbox))


def _runs(glyphs):
    result = []
    for g in glyphs:
        space = g.text in (' ', '\u00a0')
        if not result or result[-1][0] != space:
            result.append((space, []))
        result[-1][1].append(g)
    return result


def plan_line(model, selected, request, resolved, target=None):
    """Planifica sustitución y justificación; no abre ni modifica un PDF.

    ``resolved`` debe contener las fuentes de ``expand_line(model, selected)``.
    Devuelve (línea original, glifos finales, medidas para el informe).
    """
    from .engine import _style, validate_rgb

    line = expand_line(model, selected)
    selected = [g for g in line if g.id in {s.id for s in selected}]
    validate_rgb(request.color)
    if request.text is None:
        raise EditError("El ajuste de línea necesita un texto de sustitución; para mover usa Mover.")
    if request.reflow or '\n' in request.text or '\r' in request.text:
        raise EditError("El ajuste justificado no inserta saltos de línea. Edita una sola línea.")
    if any(unicodedata.category(c).startswith('C') or unicodedata.combining(c) for c in request.text):
        raise EditError("No se admiten controles ni marcas combinantes; usa acentos precompuestos.")
    if any(g.text.isspace() and g.text not in (' ', '\u00a0') for g in line):
        raise EditError("La línea contiene espacios especiales o tabuladores que no se pueden redistribuir.")
    if len({_style(g) for g in selected}) > 1:
        raise EditError("El fragmento sustituido mezcla estilos. Selecciona una palabra de un solo estilo.")
    whole = len(selected) == len(line)
    if not whole and (request.width is not None or request.height is not None) and not request.auto_width:
        raise EditError("Selecciona la línea completa para cambiar su anchura o altura al justificar.")
    for value in (request.dx, request.dy, request.width, request.height, request.size):
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise EditError("Las posiciones y dimensiones deben ser números finitos.")
    missing = {g.font for g in line} - resolved.keys()
    if missing:
        raise EditError("Falta resolver una fuente vecina de la línea: " + ', '.join(sorted(missing)))
    if target is not None and target.name in resolved:
        original = resolved[target.name]
        if target.buffer != original.buffer or target.base14 != original.base14:
            raise EditError("La fuente elegida comparte nombre con una fuente distinta de la línea; no puede sustituirse sin afectar a los vecinos.")
    def width(g):
        font = target if target is not None and g.id == -1 else resolved[g.font]
        return font.width(g.text, g.size)

    # A PDF extraction line can still represent a tabulated row. Never infer
    # a coherent sentence across an unmarked gap or an excessively large space.
    for a, b in zip(line, line[1:]):
        gap = b.origin[0] - a.origin[0] - width(a)
        if gap < -max(.15, min(a.size, b.size) * .1):
            raise EditError("La línea contiene caracteres superpuestos; no se puede justificar.")
        if a.text not in (' ', '\u00a0') and b.text not in (' ', '\u00a0') and gap > max(a.size, b.size) * .5:
            raise EditError("Hay un hueco sin espacio explícito: podría separar columnas o celdas.")
    for is_space, group in _runs(line):
        if is_space:
            if len(group) > 2:
                raise EditError("La línea contiene varios espacios de alineación; podría pertenecer a una tabla.")
            start = line.index(group[0])
            end = start + len(group)
            if start > 0 and end < len(line):
                physical = line[end].origin[0] - (line[start-1].origin[0] + width(line[start-1]))
                if physical > max(g.size for g in group) * MAX_GAP_EM:
                    raise EditError("El hueco entre palabras es demasiado grande; podría separar columnas.")

    first = selected[0]
    choice = target or resolved[first.font]
    size = request.size if request.size is not None else first.size
    if not 1 <= size <= 300:
        raise EditError("El tamaño manual debe estar entre 1 y 300 puntos.")
    # Preserve regular tracking in the replacement. Existing variable pair
    # positioning is left intact in unaffected words, but cannot be guessed
    # for new character pairs.
    gaps = [b.origin[0] - a.origin[0] - width(a)
            for a, b in zip(selected, selected[1:])
            if a.text not in (' ', '\u00a0') and b.text not in (' ', '\u00a0')]
    spacing = statistics.median(gaps) if gaps else 0.
    if gaps and max(abs(v - spacing) for v in gaps) > .035:
        raise EditError("El fragmento sustituido tiene ajuste irregular por pares; selecciona otro tramo.")
    if target is not None:
        asc, desc = choice.font.ascender * size, -choice.font.descender * size
    else:
        asc = (first.origin[1] - first.bbox[1]) * size / first.size
        desc = (first.bbox[3] - first.origin[1]) * size / first.size
    start = line.index(first)
    end = start + len(selected)
    x, _ = first.origin
    baselines = _replacement_baselines(selected, request.text)
    replacement = []
    for index, char in enumerate(request.text):
        y = baselines[index]
        cw = choice.width(char, size)
        replacement.append(replace(first, id=-1, text=char, origin=(x, y),
                                   font=target.name if target is not None else first.font,
                                   size=size, color=tuple(request.color) if request.color is not None else first.color,
                                   bbox=(x, y-asc, x+cw, y+desc),
                                   trace_bbox=(x, y-asc, x+cw, y+desc)))
        x += cw + (spacing if index+1 < len(request.text) else 0.)
    old_end = selected[-1].origin[0] + width(selected[-1])
    delta = x - old_end
    combined = line[:start] + replacement + [_shift(g, delta) for g in line[end:]]
    bounds = union(g.bbox for g in line)
    left = line[0].origin[0] + request.dx
    area_width = request.width if request.width is not None else bounds[2] - line[0].origin[0]
    area_height = request.height if request.height is not None else bounds[3] - bounds[1]
    if area_width <= 0 or area_height <= 0:
        raise EditError("El área de edición debe tener anchura y altura positivas.")
    if combined and union(g.bbox for g in combined)[3] - union(g.bbox for g in combined)[1] > area_height + .035:
        raise EditError("El texto supera la altura disponible. Amplía el área de la línea.")
    runs = _runs(combined)
    interior_spaces = [group for i, (space, group) in enumerate(runs) if space and 0 < i < len(runs)-1]
    word_runs = [group for space, group in runs if not space]
    def run_width(group):
        return group[-1].origin[0] + width(group[-1]) - group[0].origin[0]
    fixed_width = sum(run_width(group) for space, group in runs if not space or group not in interior_spaces)
    natural_spaces = [sum(width(g) for g in group) for group in interior_spaces]
    minimum = sum(v * MIN_SPACE_RATIO for v in natural_spaces)
    required_width = (fixed_width + sum(natural_spaces) - len(natural_spaces)*min(natural_spaces)*(1-MIN_SPACE_RATIO)
                      if natural_spaces else fixed_width)
    if fixed_width + minimum > area_width + .035:
        raise LineWidthOverflow("El texto supera el espacio disponible en la línea. Amplía su anchura o cambia el formato manualmente.",required_width)
    available = area_width - fixed_width
    added = (available - sum(natural_spaces)) / len(interior_spaces) if interior_spaces else 0.
    space_widths = [v + added for v in natural_spaces]
    # Different font sizes may make a small space fail even when the sum fits.
    if any(v < natural * MIN_SPACE_RATIO - .035 for v, natural in zip(space_widths, natural_spaces)):
        raise LineWidthOverflow("El texto necesita comprimir demasiado los espacios. Amplía la anchura de la línea.",required_width)
    if any(v > MAX_GAP_EM * max(g.size for g in group) for v, group in zip(space_widths, interior_spaces)):
        raise EditError("La justificación separaría demasiado las palabras. Reduce la anchura de la línea.")
    planned = []
    cursor = left
    gap_index = 0
    for is_space, group in runs:
        if is_space and group in interior_spaces:
            allocated = space_widths[gap_index]
            natural = natural_spaces[gap_index]
            offset = 0.
            for g in group:
                planned.append(_shift(g, cursor + offset - g.origin[0], request.dy))
                offset += allocated * width(g) / natural
            cursor += allocated
            gap_index += 1
        else:
            planned.extend(_shift(g, cursor - group[0].origin[0], request.dy) for g in group)
            cursor += run_width(group)
    return line, planned, {
        'line_reflow': True, 'line_width': area_width,
        'line_source_ids': [g.id for g in line],
        'selected_source_ids': [g.id for g in selected],
        'spaces': len(interior_spaces), 'space_widths': space_widths,
        'minimum_space_ratio': MIN_SPACE_RATIO,
        'alignment': 'justified' if len(word_runs) > 1 else 'left',
    }
