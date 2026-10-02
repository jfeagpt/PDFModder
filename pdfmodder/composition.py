"""Añadir texto PDF real mediante elección tipográfica explícita y validación."""
from dataclasses import dataclass
import hashlib
import math
import time
import unicodedata

import pymupdf as fitz

from .engine import _insert, _stroke_hits, extract_page, full_write, validate_rgb
from .fonts import FontError, FontResolver
from .model import EditError, Glyph, intersects
from .validation import document_issues, validate_transition


@dataclass
class AddTextRequest:
    page: int
    x: float
    y: float
    width: float
    height: float
    text: str
    font_name: str = "Helvetica"
    font_file: str | None = None
    size: float = 12
    color: tuple = (0, 0, 0)
    align: str = "left"
    revision: str | None = None
    allow_overlap: bool = False
    reflow: bool = True
    accessibility_order: str | None = None


def _lines(text, face, size, width, reflow):
    result = []
    for paragraph in text.split('\n'):
        if not reflow:
            result.append(paragraph)
            continue
        # ASCII word separators become a line break at the wrap boundary.
        # Explicit NBSP is kept within its word and is never normalized.
        words = paragraph.split(' ')
        current = words[0]
        for word in words[1:]:
            proposed = current + ' ' + word
            if current and face.width(proposed, size) > width + .035:
                result.append(current)
                current = word
            else:
                current = proposed
        result.append(current)
    if any(face.width(line, size) > width + .035 for line in result):
        raise EditError("El texto supera el espacio disponible. Amplía el área o cambia el tamaño manualmente.")
    return result


def insert_text_pdf(data: bytes, request: AddTextRequest, resolver=None):
    """Return a full-write PDF and validation report, without modifying input.

    x/y are the top-left of the area in unrotated CropBox-local PDF points.
    Text is horizontal within the page; page rotation is retained. An explicit
    allow_overlap permits painting over existing text/images/strokes, but never
    links or annotations whose interaction regions could become misleading.
    """
    started = time.perf_counter()
    from .tagged_insert import TaggedAddition
    tagged = TaggedAddition(data, request.page, '/P', request.accessibility_order, text=request.text)
    if request.revision and request.revision != hashlib.sha256(data).hexdigest():
        raise EditError("El documento cambió desde la selección del área. Elige el área de nuevo.")
    values = (request.x, request.y, request.width, request.height, request.size)
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise EditError("Las posiciones, dimensiones y tamaño deben ser números finitos.")
    if request.width <= 0 or request.height <= 0 or not 1 <= request.size <= 300:
        raise EditError("El área debe tener dimensiones positivas y el tamaño estar entre 1 y 300 puntos.")
    if request.align not in ('left', 'center', 'right'):
        raise EditError("Selecciona alineación izquierda, centrada o derecha.")
    validate_rgb(request.color)
    if not isinstance(request.text, str) or not request.text.strip():
        raise EditError("Escribe texto para añadir al documento.")
    if any(unicodedata.category(c).startswith('C') and c != '\n' for c in request.text):
        raise EditError("No se admiten controles, tabuladores ni caracteres bidireccionales.")
    if any(unicodedata.combining(c) or unicodedata.bidirectional(c) in ('R', 'AL', 'AN') for c in request.text):
        raise EditError("La composición de marcas combinantes o texto de derecha a izquierda no está admitida; usa caracteres precompuestos.")
    resolver = resolver or FontResolver()
    try:
        face = resolver.resolve_explicit(request.font_name, request.text, request.font_file)
    except FontError as exc:
        raise EditError(str(exc)) from exc
    lines = _lines(request.text, face, request.size, request.width, request.reflow)
    ascent = face.font.ascender * request.size
    descent = -face.font.descender * request.size
    line_height = max(request.size * 1.2, ascent + descent)
    needed_height = ascent + descent + (len(lines) - 1) * line_height
    if not math.isfinite(needed_height) or ascent <= 0 or descent < 0:
        raise EditError("La fuente no proporciona métricas verticales válidas para componer el texto.")
    if needed_height > request.height + .035:
        raise EditError("El texto supera la altura disponible. Amplía el área de edición.")
    planned = []
    for line_index, text in enumerate(lines):
        width = face.width(text, request.size)
        x = request.x
        if request.align == 'center':
            x += (request.width - width) / 2
        elif request.align == 'right':
            x += request.width - width
        y = request.y + ascent + line_index * line_height
        for character in text:
            advance = face.width(character, request.size)
            bbox = (x, y - ascent, x + advance, y + descent)
            planned.append(Glyph(-1, character, (x, y), bbox, bbox, face.name, request.size,
                                 tuple(request.color), 1.0, 0, line_index, 0))
            x += advance
    with fitz.open(stream=data, filetype='pdf') as doc:
        issues = document_issues(data, doc)
        if issues:
            raise EditError('\n'.join(issues))
        if not isinstance(request.page, int) or not 0 <= request.page < doc.page_count:
            raise EditError("La página seleccionada ya no existe.")
        model = extract_page(doc, request.page, data)
        from .clipping import CLIP_ISSUE
        issues = [issue for issue in model.issues if issue != CLIP_ISSUE]
        if issues:
            raise EditError('\n'.join(issues))
        clipped = CLIP_ISSUE in model.issues
        if clipped or tagged.structure is not None:
            # Adding a new stream does not reconstruct or redact clipped text.
            # Verify balanced scopes before containing the complete old content
            # in q/Q; the new text must not inherit its clip or transformation.
            from .media import _graphics_scan, _isolate_existing_content
            _graphics_scan(doc, request.page, [])
        page = doc[request.page]
        visible = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        area = fitz.Rect(request.x, request.y, request.x + request.width, request.y + request.height)
        if not visible.contains(area):
            raise EditError("El área de texto queda fuera de la parte visible de la página.")
        links = page.get_links()
        annotations = list(page.annots() or [])
        images = page.get_image_info()
        strokes = [d for d in page.get_drawings() if d['type'] in ('s', 'fs')]
        for glyph in planned:
            if not visible.contains(fitz.Rect(glyph.bbox)):
                raise EditError("El texto queda fuera de la parte visible de la página.")
            if any(intersects(glyph.bbox, tuple(link['from'])) for link in links):
                raise EditError("El texto se solapa con un enlace existente.")
            if any(intersects(glyph.bbox, tuple(annot.rect)) for annot in annotations):
                raise EditError("El texto se solapa con una anotación existente.")
            if not request.allow_overlap:
                if any(intersects(glyph.bbox, old.bbox, .12) for old in model.glyphs):
                    raise EditError("El texto se solapa con caracteres existentes. Mueve el área o permite el solapamiento explícitamente.")
                if any(intersects(glyph.bbox, image['bbox']) for image in images):
                    raise EditError("El texto se solapa con una imagen. Mueve el área o permite el solapamiento explícitamente.")
                if any(_stroke_hits(drawing, glyph.bbox) for drawing in strokes):
                    raise EditError("El texto cruza una línea vectorial. Mueve el área o permite el solapamiento explícitamente.")
        expected = [(g.text, g.origin, g.font, g.size) for g in model.glyphs + planned]
        if clipped or tagged.structure is not None:
            _isolate_existing_content(doc, page)
            page = doc.reload_page(page)
        old_contents = page.get_contents()
        _insert(page, planned, {face.name: face})
        tagged_expected = tagged.apply(doc, old_contents)
        output = full_write(doc)
    regions = [g.bbox for g in planned]
    report = validate_transition(data, output, request.page, expected, regions, tagged_expected)
    report.update(page=request.page, source_regions=[], destination_regions=regions,
                  fonts={face.name: face.source}, operation='add_text',
                  elapsed_seconds=round(time.perf_counter() - started, 3),
                  manual_format={'font': face.name, 'size': request.size, 'color': request.color},
                  allowed_overlap=request.allow_overlap, existing_clip_isolated=clipped)
    if tagged.structure is not None:
        report['accessibility'] = tagged.report()
    return output, report
