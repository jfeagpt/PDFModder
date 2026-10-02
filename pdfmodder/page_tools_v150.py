"""Additional whole-page tools. Inputs/outputs are immutable PDF bytes.

Crop changes only CropBox; it is NOT redaction. Margins are PDF points along
the displayed page edges, including its rotation. Replacement substitutes
complete pages (including annotations), not just their painted contents.

API reference: https://pymupdf.readthedocs.io/en/latest/page.html#Page.set_cropbox
"""
from __future__ import annotations

import hashlib
import io
import math
import time

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject

from . import page_catalog
from .model import EditError
from .pageops import (
    _annotation_details, _catalog_metadata, _font_programs, _indices, _metadata,
    _preflight, _raw_link_targets, _semantic, extract_pages_pdf,
    organize_pages_pdf, parse_pages,
)
from .tagged import assert_structure
from .validation import _canonical, assert_characters, assert_pixels, related, trace_chars


def _page_count(data):
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if not doc.is_pdf or doc.page_count < 1:
                raise ValueError("empty PDF")
            return doc.page_count
    except Exception as exc:
        raise EditError("Se necesita un PDF válido con al menos una página.") from exc


def replace_pages_pdf(data: bytes, pages: list[int], replacement: bytes,
                      replacement_pages: list[int] | None = None):
    """Replace specified 0-based positions, one complete page per position.

    Other page order/metadata are retained. Inbound links to removed pages,
    named destination collisions remain blocked by the existing organizer.
    Tagged inputs require compatible tagged replacement pages; their logical
    trees are projected and joined explicitly. Old annotations are removed.
    """
    count, source_count = _page_count(data), _page_count(replacement)
    targets = _indices(pages, count)
    sources = _indices(list(range(source_count)) if replacement_pages is None
                       else replacement_pages, source_count)
    if len(targets) != len(sources):
        raise EditError("Elige el mismo número de páginas originales y de sustitución.")
    mapping = dict(zip(targets, sources))
    plan = [{"source": "replacement", "page": mapping[number], "rotation": 0}
            if number in mapping else {"source": "current", "page": number, "rotation": 0}
            for number in range(count)]
    output, report = organize_pages_pdf(data, plan, {"replacement": replacement}, _tagged_replacement=True)
    report.update(operation="replace_pages", replaced_pages=targets,
                  replacement_pages=sources,
                  replacement_policy="Sustitución de páginas completas, incluidas sus anotaciones.")
    return output, report


def parse_split_groups(expression: str, page_count: int) -> list[list[int]]:
    """UI syntax ``1-3;4-6;7``; every source page must occur exactly once."""
    if not isinstance(expression, str) or not expression.strip():
        raise EditError("Indica los grupos separados por punto y coma, por ejemplo 1-3;4-6.")
    return _split_groups([parse_pages(part, page_count) for part in expression.split(";")], page_count)


def _split_groups(groups, count):
    if not isinstance(groups, (list, tuple)) or not groups:
        raise EditError("Indica al menos un grupo de páginas para dividir el documento.")
    checked = [_indices(group, count) for group in groups]
    flattened = [page for group in checked for page in group]
    if len(set(flattened)) != len(flattened):
        raise EditError("Los grupos de división no pueden compartir páginas.")
    if set(flattened) != set(range(count)):
        raise EditError("La división debe incluir todas las páginas. Usa Extraer para exportar sólo algunas.")
    return checked


def split_pdf(data: bytes, page_groups: list[list[int]] | None = None,
              pages_per_part: int | None = None):
    """Return ``(list[bytes], report)``; caller chooses paths and atomic save.

    Exactly one of page_groups or pages_per_part is required. No partial
    result is returned on validation failure. Cross-part links remain blocked.
    """
    started = time.perf_counter()
    count = _page_count(data)
    if (page_groups is None) == (pages_per_part is None):
        raise EditError("Elige grupos de páginas o un número de páginas por archivo.")
    if pages_per_part is not None:
        if type(pages_per_part) is not int or not 1 <= pages_per_part <= count:
            raise EditError(f"El tamaño de cada parte debe estar entre 1 y {count} páginas.")
        page_groups = [list(range(start, min(start + pages_per_part, count)))
                       for start in range(0, count, pages_per_part)]
    groups = _split_groups(page_groups, count)
    outputs, reports = [], []
    for group in groups:
        output, report = extract_pages_pdf(data, group)
        outputs.append(output)
        reports.append(report)
    return outputs, {"verified": True, "operation": "split_pdf", "parts": reports,
                     "page_groups": groups, "part_count": len(outputs),
                     "page_count": count, "source_sha256": hashlib.sha256(data).hexdigest(),
                     "elapsed_seconds": round(time.perf_counter() - started, 3)}


def _unrotated_margins(margins, rotation):
    left, top, right, bottom = margins
    return {0: (left, top, right, bottom), 90: (top, right, bottom, left),
            180: (right, bottom, left, top), 270: (bottom, left, top, right)}[rotation]


def _page_properties(reader, number):
    # Parent is a cyclic page-tree pointer. Content and annotations receive
    # dedicated exact checks; all other raw page properties must stay equal.
    refs = {(p.indirect_reference.idnum, p.indirect_reference.generation): n
            for n, p in enumerate(reader.pages)}
    return _semantic({k: v for k, v in reader.pages[number].items()
                      if k not in ("/Parent", "/CropBox", "/Contents", "/Annots")}, page_refs=refs)


def _write_crop_boxes(reader, pdf_boxes):
    # MuPDF garbage collection both invalidates cached xrefs and reserializes
    # unrelated real numbers (observed with MediaBox). Clone the original graph
    # through pypdf and replace only CropBox, preserving its other exact values.
    writer = PdfWriter(clone_from=reader)
    writer.pdf_header = reader.pdf_header
    for number, values in pdf_boxes:
        writer.pages[number][NameObject('/CropBox')] = ArrayObject([FloatObject(v) for v in values])
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def crop_pages_pdf(data: bytes, pages: list[int], margins: tuple[float, float, float, float]):
    """Crop by nonnegative displayed left/top/right/bottom margins in points.

    The visible box shrinks without removing text, images or vectors. Existing
    CropBox displacement and rotations are accounted for. Original bytes are
    never mutated. Undo must restore the original byte snapshot.
    """
    started = time.perf_counter()
    if (not isinstance(margins, (list, tuple)) or len(margins) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                   for value in margins)):
        raise EditError("Los cuatro márgenes deben ser medidas finitas, iguales o mayores que cero.")
    doc, reader = _preflight(data, "Documento actual")
    with doc:
        selected = _indices(pages, len(doc))
        boxes = []
        pdf_boxes = []
        for number in selected:
            page = doc[number]
            left, top, right, bottom = _unrotated_margins(margins, page.rotation)
            old = tuple(page.cropbox)
            new = fitz.Rect(old[0] + left, old[1] + top, old[2] - right, old[3] - bottom)
            if new.is_empty or new.width < 1 or new.height < 1:
                raise EditError(f"Página {number + 1}: los márgenes no dejan un área visible válida.")
            page.set_cropbox(new)
            # Read the four explicit numbers emitted by set_cropbox through
            # the object API: these are PDF-space coordinates, including a
            # displaced MediaBox, not extracted text or content operators.
            kind, literal = doc.xref_get_key(page.xref, 'CropBox')
            if kind != 'array':
                raise EditError('No se pudo obtener el área de recorte de la página.')
            values = literal.strip('[]').split()
            if len(values) != 4 or not all(math.isfinite(float(v)) for v in values):
                raise EditError('El área de recorte calculada no es válida.')
            pdf_boxes.append((number, values))
            doc.reload_page(page)
            boxes.append({"page": number, "before": old, "after": tuple(new)})
        output = _write_crop_boxes(reader, pdf_boxes)
        independent = PdfReader(io.BytesIO(output), strict=True)
        with fitz.open(stream=output, filetype="pdf") as result:
            if result.page_count != len(doc) or len(independent.pages) != len(reader.pages):
                raise EditError("El recorte alteró el número de páginas.")
            if (_metadata(reader) != _metadata(independent)
                    or _catalog_metadata(reader) != _catalog_metadata(independent)
                    or doc.get_xml_metadata() != result.get_xml_metadata()):
                raise EditError("El recorte alteró propiedades o metadatos del documento.")
            if _canonical(doc.get_toc(False)) != _canonical(result.get_toc(False)):
                raise EditError("El recorte alteró los marcadores.")
            page_catalog.validate([reader], independent, [{n: n for n in range(len(doc))}])
            assert_structure(data, output)
            stats = []
            for number in range(len(doc)):
                expected, copied = doc[number], result[number]
                if (tuple(expected.cropbox) != tuple(copied.cropbox)
                        or expected.rotation != copied.rotation
                        or _page_properties(reader, number) != _page_properties(independent, number)):
                    raise EditError(f"El recorte alteró propiedades ajenas de la página {number + 1}.")
                if (expected.read_contents() != copied.read_contents()
                        or _font_programs(expected) != _font_programs(copied)
                        or reader.pages[number].extract_text() != independent.pages[number].extract_text()):
                    raise EditError(f"El recorte alteró el contenido de la página {number + 1}.")
                if (_annotation_details(reader, number) != _annotation_details(independent, number)
                        or _raw_link_targets(reader, number) != _raw_link_targets(independent, number)
                        or related(expected) != related(copied)):
                    raise EditError(f"El recorte alteró imágenes, vectores, enlaces o anotaciones de la página {number + 1}.")
                assert_characters(trace_chars(expected), copied)
                stats.append({"page": number, **assert_pixels(expected, copied, excluded=())})
    return output, {"verified": True, "operation": "crop_pages", "page_count": len(reader.pages),
                    "writer": "pypdf", "independent_renderer": "MuPDF",
                    "page_map": list(range(len(reader.pages))), "crop_boxes": boxes, "pages": stats,
                    "margins": tuple(margins), "non_destructive": True,
                    "source_sha256": hashlib.sha256(data).hexdigest(),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "crop_policy": "Sólo cambia el área visible (CropBox). El contenido oculto sigue dentro del PDF."}
