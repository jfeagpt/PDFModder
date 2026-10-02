"""Valores serializables; sin objetos del motor ni dependencias Qt."""
from dataclasses import dataclass, field
from math import hypot

PT_PER_MM = 72 / 25.4


def mm(pt):
    return pt / PT_PER_MM


def pt(mm_value):
    return mm_value * PT_PER_MM


def union(rects):
    rects = list(rects)
    if not rects:
        return (0., 0., 0., 0.)
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def intersects(a, b, epsilon=0):
    return (min(a[2], b[2]) - max(a[0], b[0]) > epsilon and
            min(a[3], b[3]) - max(a[1], b[1]) > epsilon)


def transform(point, matrix):
    x, y = point
    a, b, c, d, e, f = matrix
    return (a*x + c*y + e, b*x + d*y + f)


def transform_rect(rect, matrix):
    x0,y0,x1,y1 = rect
    points = [transform(p,matrix) for p in [(x0,y0),(x1,y0),(x0,y1),(x1,y1)]]
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


@dataclass(frozen=True)
class Glyph:
    id: int
    text: str
    origin: tuple
    bbox: tuple
    trace_bbox: tuple
    font: str
    size: float
    color: tuple
    opacity: float
    block: int
    line: int
    span: int
    direction: tuple = (1., 0.)
    mode: int = 0
    layer: str = ""
    seqno: int = 0
    reliable: bool = True
    font_xref: int | None = None
    font_resource: str | None = None


@dataclass
class PageModel:
    number: int
    width: float
    height: float
    rotation: int
    rotation_matrix: tuple
    derotation_matrix: tuple
    cropbox: tuple
    glyphs: list[Glyph]
    issues: list[str] = field(default_factory=list)
    revision: str | None = None

    def selected(self, ids):
        ids = set(ids)
        return [g for g in self.glyphs if g.id in ids]

    def text(self, ids):
        result, previous = [], None
        for g in self.selected(ids):
            if previous and g.line != previous.line:
                result.append("\n")
            result.append(g.text)
            previous = g
        return "".join(result)

    def hit(self, point):
        x,y = point
        # An OCR layer in rendering mode 3 is searchable metadata, not the
        # appearance that the user clicks. Retain it in the model for validation.
        hits = [g for g in self.glyphs if g.mode != 3 and g.opacity > 0
                and g.bbox[0] <= x <= g.bbox[2] and g.bbox[1] <= y <= g.bbox[3]]
        return min(hits, key=lambda g:hypot((g.bbox[0]+g.bbox[2])/2-x,(g.bbox[1]+g.bbox[3])/2-y)) if hits else None

    def group(self, glyph, mode):
        if mode == "character":
            return [glyph.id]
        line = [g for g in self.glyphs if g.line == glyph.line and g.mode==glyph.mode
                and (g.opacity>0)==(glyph.opacity>0)]
        if mode == "line":
            return [g.id for g in line]
        if mode == "block":
            # Blocks are extraction groups, never merged by spatial proximity.
            return [g.id for g in self.glyphs if g.block == glyph.block and g.mode==glyph.mode
                    and (g.opacity>0)==(glyph.opacity>0)]
        i = line.index(glyph)
        left, right = i, i
        while left > 0 and not line[left-1].text.isspace():
            if line[left].origin[0] - line[left-1].bbox[2] > glyph.size*.65:
                break
            left -= 1
        while right+1 < len(line) and not line[right+1].text.isspace():
            if line[right+1].origin[0] - line[right].bbox[2] > glyph.size*.65:
                break
            right += 1
        return [g.id for g in line[left:right+1]]


@dataclass
class EditRequest:
    page: int
    ids: list[int]
    text: str | None = None  # None moves exact glyphs, including mixed styles.
    dx: float = 0.
    dy: float = 0.
    anchor: str = "left"
    width: float | None = None
    height: float | None = None
    size: float | None = None
    reflow: bool = False
    decimal_separator: str = ","
    revision: str | None = None
    font_name: str | None = None  # Explicit typography choice; never inferred.
    font_file: str | None = None
    color: tuple | None = None
    line_reflow: bool = False  # Repartir espacios de la misma línea al sustituir.
    auto_width: bool = False
    auto_height: bool = False  # Extensión vertical explícita, conservando el tamaño.
    allow_overlap: bool = False  # El usuario permite superponer texto; no elimina vecinos.
    line_spacing: float | None = None  # Distancia entre líneas en puntos PDF.
    paragraph_spacing: float = 0.  # Espacio extra tras saltos de párrafo explícitos.
    ocr_mode: str = "visible"  # 'searchable' cambia sólo la capa OCR invisible.


class EditError(ValueError):
    """Operación sin garantías suficientes; el documento no se modifica."""


class LineWidthOverflow(EditError):
    """A planning failure with the exact minimum width; no PDF was modified."""
    def __init__(self,message,required_width):
        super().__init__(message)
        self.required_width=required_width
