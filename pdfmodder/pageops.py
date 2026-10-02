"""Whole-page transactions; no text reconstruction and no mutation of inputs.

PyMuPDF 1.26.7 select/insert_pdf were tested and lose XMP / popup relationships
in some fixtures. pypdf clones complete page graphs; MuPDF validates and writes
the final PDF. Every copied page is checked with no excluded pixels.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
import io
import math
import re
import time

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, Fit, IndirectObject, NameObject, StreamObject

from .engine import full_write
from .model import EditError
from .validation import _canonical, assert_characters, assert_pixels, document_issues, related, trace_chars
from . import page_catalog


def parse_pages(expression: str, page_count: int) -> list[int]:
    """Parse UI numbers/ranges, preserving first occurrence order, into 0-based indices."""
    if type(page_count) is not int or page_count < 1:
        raise EditError("El documento no contiene páginas válidas.")
    if not isinstance(expression, str) or not expression.strip():
        raise EditError("Indica páginas, por ejemplo 1,3-5.")
    pages, seen = [], set()
    for piece in expression.split(","):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", piece)
        if not match:
            raise EditError(f"Rango de páginas no válido: {piece.strip()!r}. Usa 1,3-5.")
        first = int(match[1])
        last = int(match[2] or match[1])
        if first < 1 or last < 1 or first > page_count or last > page_count:
            raise EditError(f"Las páginas deben estar entre 1 y {page_count}.")
        if first > last:
            raise EditError("Los rangos deben ser ascendentes. Para otro orden escribe las páginas separadas por comas.")
        for number in range(first - 1, last):
            if number not in seen:
                pages.append(number)
                seen.add(number)
    return pages


def _indices(pages, count):
    if not isinstance(pages, (list, tuple)) or not pages:
        raise EditError("Selecciona al menos una página.")
    if any(type(number) is not int or number < 0 or number >= count for number in pages):
        raise EditError(f"Índice de página fuera del documento de {count} páginas.")
    if len(set(pages)) != len(pages):
        raise EditError("La operación no admite páginas repetidas.")
    return list(pages)


def _object(value):
    return value.get_object() if isinstance(value, IndirectObject) else value


def _semantic(value, *, page_refs=None, mapped=None, annotation_refs=None, seen=None):
    """Compare PDF values independently of xref numbers / stream compression."""
    page_refs, annotation_refs = page_refs or {}, annotation_refs or {}
    seen = set() if seen is None else seen
    if isinstance(value, IndirectObject):
        ref = (value.idnum, value.generation)
        if ref in page_refs:
            number = page_refs[ref]
            if mapped is not None and number not in mapped:
                raise EditError("Un objeto conservado hace referencia a una página excluida.")
            return ("page", mapped[number] if mapped is not None else number)
        if ref in annotation_refs:
            return ("annotation", annotation_refs[ref])
        if ref in seen:
            raise EditError("Una estructura de anotación cíclica no se puede verificar con garantías.")
        seen = seen | {ref}
        value = value.get_object()
    if isinstance(value, dict):
        result = {str(key): _semantic(item, page_refs=page_refs, mapped=mapped,
                                     annotation_refs=annotation_refs, seen=seen)
                  for key, item in value.items() if not isinstance(value, StreamObject) or key not in ("/Length", "/Filter", "/DecodeParms")}
        if isinstance(value, StreamObject):
            result["__decoded_stream_sha256__"] = hashlib.sha256(value.get_data()).hexdigest()
        return result
    if isinstance(value, (list, tuple)):
        return tuple(_semantic(item, page_refs=page_refs, mapped=mapped, annotation_refs=annotation_refs, seen=seen) for item in value)
    if isinstance(value, bytes):
        return ("bytes", value.hex())
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    # pypdf NullObject / BooleanObject are explicit scalar wrappers.
    if type(value).__name__ == "NullObject":
        return None
    if type(value).__name__ == "BooleanObject":
        return bool(value.value)
    return str(value)


def _check_destination(holder, *, context):
    """Only ordinary URI and explicit XYZ destinations can be reconstructed."""
    action = _object(holder.get("/A", {}))
    if action:
        if action.get("/Next") or action.get("/S") not in ("/GoTo", "/URI"):
            raise EditError(f"{context}: acción especial o encadenada no compatible con la reorganización.")
        if action.get("/S") == "/URI":
            if set(action) - {"/S", "/URI", "/IsMap"}:
                raise EditError(f"{context}: atributos adicionales de acción URI no compatibles.")
            if action.get("/IsMap"):
                raise EditError(f"{context}: enlace de mapa de imagen no compatible.")
            return
        if set(action) - {"/S", "/D"}:
            raise EditError(f"{context}: atributos adicionales de destino no compatibles.")
    destination = _object(holder.get("/Dest", action.get("/D")))
    if destination is not None:
        if not isinstance(destination, (list, tuple)) or len(destination) != 5 or str(destination[1]) != "/XYZ":
            raise EditError(f"{context}: destino con nombre o ajuste de vista distinto de XYZ no compatible.")


def _preflight(data, label):
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise EditError(f"{label}: no se puede abrir como PDF.") from exc
    try:
        if not doc.is_pdf or doc.page_count < 1:
            raise EditError(f"{label}: se necesita un PDF con al menos una página.")
        issues = document_issues(data, doc)
        if issues:
            raise EditError(f"{label}: " + "\n".join(issues))
        if doc.is_repaired:
            raise EditError(f"{label}: el PDF necesita reparación; no se reorganiza una estructura incierta.")
        reader = PdfReader(io.BytesIO(data), strict=True)
        root = reader.trailer["/Root"]
        allowed_catalog = {"/Type", "/Pages", "/Outlines", "/Metadata", "/PageLayout", "/PageMode", "/ViewerPreferences", "/Lang", "/Version", "/MarkInfo", "/StructTreeRoot", "/AcroForm", "/Names"}
        unsupported = sorted(str(key) for key in root if key not in allowed_catalog)
        if unsupported:
            raise EditError(f"{label}: estructura de documento no compatible al reorganizar páginas: {', '.join(unsupported)}. Puede contener destinos con nombre, capas, adjuntos, etiquetas o acciones.")
        page_catalog.preflight(reader)
        if root.get('/StructTreeRoot'):
            from .tagged_pages import preflight
            preflight(data)
        preferences = _object(root.get("/ViewerPreferences", {}))
        if preferences.get("/PrintPageRange"):
            raise EditError(f"{label}: intervalos de impresión predefinidos que requieren remapeo no compatible.")
        for number, page in enumerate(reader.pages):
            for key in ("/AA", "/B", "/PresSteps", "/Trans", "/Dur", "/SeparationInfo", "/AF", "/PieceInfo"):
                if key in page:
                    raise EditError(f"{label}, página {number+1}: estructura {key} no compatible al copiar páginas.")
            raw_links = 0
            for ref in _object(page.get("/Annots", [])):
                annotation = _object(ref)
                subtype = annotation.get("/Subtype")
                if subtype in ("/Widget", "/FileAttachment", "/Sound", "/Movie", "/Screen", "/RichMedia", "/3D"):
                    raise EditError(f"{label}, página {number+1}: anotación {subtype} no compatible al reorganizar.")
                if annotation.get("/AA") or annotation.get("/OC"):
                    raise EditError(f"{label}, página {number+1}: anotación con acciones o capas no compatibles.")
                if subtype == "/Link":
                    raw_links += 1
                    _check_destination(annotation, context=f"{label}, enlace de página {number+1}")
                elif annotation.get("/A") or annotation.get("/Dest"):
                    raise EditError(f"{label}, página {number+1}: acción en una anotación no compatible.")
            links = doc[number].get_links()
            if len(links) != raw_links:
                raise EditError(f"{label}, página {number+1}: hay enlaces que el motor no puede interpretar completamente.")
            for link in links:
                if link.get("kind") not in (fitz.LINK_GOTO, fitz.LINK_URI):
                    raise EditError(f"{label}, página {number+1}: enlace con destino no compatible.")
        for entry in doc.get_toc(False):
            destination = entry[3]
            if destination.get("kind") not in (fitz.LINK_NONE, fitz.LINK_GOTO, fitz.LINK_URI):
                raise EditError(f"{label}: marcador con destino especial no compatible.")
            if destination.get("xref"):
                obj = reader.get_object(destination["xref"])
                _check_destination(obj, context=f"{label}, marcador {entry[1]!r}")
                if set(obj) - {"/Title", "/Parent", "/Prev", "/Next", "/First", "/Last", "/Count", "/Dest", "/A", "/C", "/F"}:
                    raise EditError(f"{label}: marcador con atributos adicionales no compatibles.")
        return doc, reader
    except Exception:
        doc.close()
        raise


def _mapped_links(page, mapping):
    links = copy.deepcopy(page.get_links())
    for link in links:
        if link["kind"] == fitz.LINK_GOTO:
            original_target = link.get("page", -1)
            if original_target not in mapping:
                raise EditError(f"La página {page.number+1} contiene un enlace a la página {original_target+1}, que quedaría excluida. Conserva también la página de destino.")
            link["page"] = mapping[original_target]
    return _canonical(links)


def _mapped_toc(doc, mapping):
    result, ancestors, removed = [], [], []
    for entry in doc.get_toc(False):
        old_level, title, page, destination = copy.deepcopy(entry)
        while ancestors and ancestors[-1][0] >= old_level:
            ancestors.pop()
        kind = destination.get("kind")
        target = destination.get("page", page-1)
        if kind == fitz.LINK_GOTO and target not in mapping:
            removed.append(title)
            ancestors.append((old_level, None))
            continue
        kept_parent = next((level for _, level in reversed(ancestors) if level is not None), 0)
        level = kept_parent + 1
        # Keep source xref as build provenance; canonical comparison excludes it.
        if kind == fitz.LINK_GOTO:
            destination["page"] = mapping[target]
            page = mapping[target] + 1
        result.append([level, title, page, destination])
        ancestors.append((old_level, level))
    # Leaf entries cannot have a meaningful collapsed subtree after removal.
    for index, entry in enumerate(result):
        if index + 1 == len(result) or result[index+1][0] <= entry[0]:
            entry[3].pop("collapse", None)
    return result, removed


def _annotation_details(reader, page_number, mapping=None, *, ignore_struct_parent=False):
    refs = list(_object(reader.pages[page_number].get("/Annots", [])))
    page_refs = {(page.indirect_reference.idnum, page.indirect_reference.generation): number for number, page in enumerate(reader.pages)}
    annot_refs = {(ref.idnum, ref.generation): index for index, ref in enumerate(refs) if isinstance(ref, IndirectObject)}
    result = []
    for ref in refs:
        annotation = dict(_object(ref))
        # Ownership is checked by membership in this page's Annots array.
        # Link destinations are separately checked with the complete mapped list;
        # destination /A versus /Dest spelling may legitimately change.
        annotation.pop("/P", None)
        if ignore_struct_parent:
            # The tagged replacement validator checks this association against
            # the remapped ParentTree / OBJR rather than its source numeric key.
            annotation.pop('/StructParent', None)
        if annotation.get("/Subtype") == "/Link":
            annotation.pop("/A", None)
            annotation.pop("/Dest", None)
        result.append(_semantic(annotation, page_refs=page_refs, mapped=mapping, annotation_refs=annot_refs))
    return result


def _metadata(reader):
    return _semantic(reader.trailer.get("/Info", {}))


def _catalog_metadata(reader):
    root = reader.trailer["/Root"]
    return {key: _semantic(root[key]) for key in ("/PageLayout", "/PageMode", "/ViewerPreferences", "/Lang", "/MarkInfo", "/AcroForm") if key in root}


def _build_pdf(readers, selections, toc_groups):
    """Clone metadata, page/annotation graphs and exact PDF-space destinations.

    append() performs reference translation for full page graphs, including
    Popup/Parent annotation links. XYZ coordinates come from original objects,
    avoiding a rotated CropBox get_toc/set_toc coordinate round-trip.
    """
    writer = PdfWriter(clone_from=readers[0])
    writer.root_object.pop(NameObject("/Outlines"), None)
    writer.root_object.pop(NameObject("/Names"), None)
    for number in reversed(range(len(writer.pages))):
        writer.remove_page(number)
    writer.reset_translation(readers[0])
    for reader, pages in zip(readers, selections):
        writer.append(reader, pages=pages, import_outline=False)
    # Preflight permits only empty forms. append() can otherwise introduce an
    # empty external AcroForm into a document that never had one.
    if '/AcroForm' not in readers[0].trailer['/Root']:
        writer.root_object.pop(NameObject('/AcroForm'), None)
    destination_maps, offset = [], 0
    for selection in selections:
        destination_maps.append({old: offset + new for new, old in enumerate(selection)})
        offset += len(selection)
    page_catalog.rebuild_many(writer, readers, destination_maps)
    for reader, toc in zip(readers, toc_groups):
        parents = []
        for level, title, target_page, destination in toc:
            while len(parents) >= level:
                parents.pop()
            parent = parents[-1] if parents else None
            kind = destination.get("kind")
            source = reader.get_object(destination["xref"])
            action = _object(source.get("/A", {}))
            raw_destination = _object(source.get("/Dest", action.get("/D")))
            if kind == fitz.LINK_GOTO:
                values = [None if type(value).__name__ == "NullObject" else float(value) for value in raw_destination[2:5]]
                fit = Fit.xyz(*values)
            else:
                fit = Fit.xyz()
            item = writer.add_outline_item(title, target_page-1 if kind == fitz.LINK_GOTO else None,
                                           parent=parent, fit=fit, color=destination.get("color"),
                                           bold=destination.get("bold", False), italic=destination.get("italic", False),
                                           is_open=not destination.get("collapse", False))
            if kind == fitz.LINK_URI:
                item.get_object()[NameObject("/A")] = action.clone(writer)
                item.get_object().pop(NameObject("/Dest"), None)
            parents.append(item)
    buffer = io.BytesIO()
    writer.write(buffer)
    with fitz.open(stream=buffer.getvalue(), filetype="pdf") as final:
        return full_write(final)


def _validate(output, inputs, assignments, maps, expected_toc):
    """assignments[out] = (input_number, source_page); never compare wrong pages."""
    with ExitStack() as stack:
        sources = [stack.enter_context(fitz.open(stream=data, filetype="pdf")) for data in inputs]
        readers = [PdfReader(io.BytesIO(data), strict=True) for data in inputs]
        result = stack.enter_context(fitz.open(stream=output, filetype="pdf"))
        independent = PdfReader(io.BytesIO(output), strict=True)
        page_catalog.validate(readers, independent, maps)
        if result.page_count != len(assignments) or len(independent.pages) != len(assignments):
            raise EditError("Validación de páginas: número de páginas incorrecto.")
        if _metadata(readers[0]) != _metadata(independent) or sources[0].get_xml_metadata() != result.get_xml_metadata():
            raise EditError("La operación alteró los metadatos del documento actual.")
        if _catalog_metadata(readers[0]) != _catalog_metadata(independent):
            raise EditError("La operación alteró propiedades de visualización o idioma del documento actual.")
        if _canonical(expected_toc) != _canonical(result.get_toc(False)):
            raise EditError("La operación no conservó correctamente los marcadores y sus destinos.")
        stats = []
        for output_number, (source_number, input_page) in enumerate(assignments):
            original, copied = sources[source_number][input_page], result[output_number]
            boxes = lambda page: (tuple(page.mediabox), tuple(page.cropbox), tuple(page.bleedbox), tuple(page.trimbox), tuple(page.artbox), page.rotation, tuple(page.rect))
            if boxes(original) != boxes(copied):
                raise EditError(f"La página {output_number+1} cambió de dimensiones, recorte o rotación.")
            if original.read_contents() != copied.read_contents():
                raise EditError(f"La página {output_number+1} sufrió una modificación de sus operadores de contenido.")
            assert_characters(trace_chars(original), copied)
            if readers[source_number].pages[input_page].extract_text() != independent.pages[output_number].extract_text():
                raise EditError(f"El extractor independiente detectó cambios de texto en la página {output_number+1}.")
            expected_related = related(original)
            expected_related["links"] = _mapped_links(original, maps[source_number])
            if expected_related != related(copied):
                raise EditError(f"La página {output_number+1} no conserva imágenes, vectores, enlaces o anotaciones.")
            if _annotation_details(readers[source_number], input_page, maps[source_number]) != _annotation_details(independent, output_number):
                raise EditError(f"La página {output_number+1} no conserva todos los atributos y apariencias de sus anotaciones o enlaces.")
            pixels = assert_pixels(original, copied, excluded=())
            stats.append({"output_page": output_number, "source_document": source_number, "source_page": input_page, **pixels})
        return stats


def _select_pdf(data, pages, operation):
    started = time.perf_counter()
    doc, reader = _preflight(data, "Documento actual")
    with doc:
        checked = _indices(pages, len(doc))
        if operation == "delete_pages":
            excluded = set(checked)
            retained = [number for number in range(len(doc)) if number not in excluded]
            if not retained:
                raise EditError("No se pueden eliminar todas las páginas: el PDF debe conservar al menos una.")
        else:
            retained = checked
        mapping = {old: new for new, old in enumerate(retained)}
        for number in retained:
            _mapped_links(doc[number], mapping)
        toc, removed = _mapped_toc(doc, mapping)
        tagged_report = None
        if reader.trailer['/Root'].get('/StructTreeRoot'):
            from .tagged_pages import build_tagged_pages
            output, tagged_report = build_tagged_pages(reader, [{'source': 'current', 'page': page, 'rotation': 0} for page in retained], toc)
        else:
            output = _build_pdf([reader], [retained], [toc])
    assignments = [(0, page) for page in retained]
    stats = _validate(output, [data], assignments, [mapping], toc)
    return output, {"verified": True, "operation": operation, "page_count": len(retained),
                    "pages": stats, "page_map": retained, "removed_bookmarks": removed,
                    "named_destinations": page_catalog.report(reader, mapping),
                    "source_sha256": hashlib.sha256(data).hexdigest(), "elapsed_seconds": round(time.perf_counter()-started, 3),
                    "independent_parser": "pypdf", "tagged_structure": tagged_report,
                    "metadata_policy": "Se conservan metadatos y XMP del documento actual."}


def delete_pages_pdf(data: bytes, pages: list[int]):
    """Remove 0-based pages while retaining all other pages in their original order."""
    return _select_pdf(data, pages, "delete_pages")


def extract_pages_pdf(data: bytes, pages: list[int]):
    """Return a standalone PDF containing the requested 0-based pages in order."""
    return _select_pdf(data, pages, "extract_pages")


def merge_pdfs(data: bytes, additions: list[bytes]):
    """Append complete PDFs in order. Metadata belongs to the current document."""
    if not isinstance(additions, (list, tuple)) or not additions:
        raise EditError("Selecciona al menos un PDF para añadir.")
    started = time.perf_counter()
    inputs = [data, *additions]
    with ExitStack() as stack:
        docs, readers = [], []
        for index, payload in enumerate(inputs):
            doc, reader = _preflight(payload, "Documento actual" if index == 0 else f"PDF añadido {index}")
            docs.append(stack.enter_context(doc))
            readers.append(reader)
        if any(reader.trailer['/Root'].get('/StructTreeRoot') for reader in readers):
            raise EditError('PDF etiquetado: combinar PDFs requiere fusionar sus árboles de accesibilidad; esta operación todavía no está habilitada.')
        page_catalog.require_unambiguous(readers)
        assignments, maps, toc, source_metadata, toc_groups, selections = [], [], [], [], [], []
        for index, doc in enumerate(docs):
            offset = len(assignments)
            mapping = {page: offset+page for page in range(len(doc))}
            for page in doc:
                _mapped_links(page, mapping)
            mapped_toc, _ = _mapped_toc(doc, mapping)
            toc.extend(mapped_toc)
            toc_groups.append(mapped_toc)
            selections.append(list(range(len(doc))))
            assignments.extend((index, page) for page in range(len(doc)))
            maps.append(mapping)
            source_metadata.append({"document": index, "metadata": dict(doc.metadata), "xml_metadata": doc.get_xml_metadata()})
        output = _build_pdf(readers, selections, toc_groups)
    stats = _validate(output, inputs, assignments, maps, toc)
    return output, {"verified": True, "operation": "merge_pdfs", "page_count": len(assignments), "pages": stats,
                    "source_page_counts": [len(mapping) for mapping in maps], "source_metadata": source_metadata,
                    "source_sha256": [hashlib.sha256(payload).hexdigest() for payload in inputs],
                    "elapsed_seconds": round(time.perf_counter()-started, 3), "independent_parser": "pypdf",
                    "metadata_policy": "Se conservan Info/XMP del documento actual. Los metadatos de los PDFs añadidos se registran en este informe; no reemplazan los del documento actual."}


def _organizer_plan(plan, counts):
    if not isinstance(plan, (list, tuple)) or not plan:
        raise EditError("El orden final debe contener al menos una página.")
    checked = []
    for index, entry in enumerate(plan):
        if not isinstance(entry, dict):
            raise EditError(f"Página final {index+1}: entrada de plan no válida.")
        source = entry.get("source")
        rotation = entry.get("rotation", 0)
        if not isinstance(source, str) or not source:
            raise EditError(f"Página final {index+1}: falta el documento de origen.")
        if type(rotation) is not int or rotation not in (0, 90, 180, 270):
            raise EditError("Los giros deben ser 0, 90, 180 o 270 grados en sentido horario.")
        if source == "blank":
            if set(entry) - {"source", "width", "height", "rotation"}:
                raise EditError("Una página en blanco sólo admite anchura, altura y giro.")
            dimensions = [entry.get("width"), entry.get("height")]
            if any(type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 14400 for value in dimensions):
                raise EditError("Las dimensiones de una página en blanco deben estar entre 1 y 14400 puntos PDF.")
            checked.append({"source": source, "width": float(dimensions[0]), "height": float(dimensions[1]), "rotation": rotation})
        else:
            if set(entry) - {"source", "page", "rotation"}:
                raise EditError("El plan de una página PDF contiene opciones desconocidas.")
            page = entry.get("page")
            if source not in counts:
                raise EditError(f"No se ha cargado el PDF de origen «{source}».")
            if type(page) is not int or not 0 <= page < counts[source]:
                raise EditError(f"Página fuera del PDF «{source}», que contiene {counts[source]} páginas.")
            checked.append({"source": source, "page": page, "rotation": rotation})
    return checked


def _raw_link_targets(reader, page_number, mapping=None):
    page_refs = {(page.indirect_reference.idnum, page.indirect_reference.generation): number for number, page in enumerate(reader.pages)}
    result = []
    for ref in _object(reader.pages[page_number].get("/Annots", [])):
        annotation = _object(ref)
        if annotation.get("/Subtype") == "/Link":
            result.append(_semantic({key: annotation[key] for key in ("/A", "/Dest") if key in annotation}, page_refs=page_refs, mapped=mapping))
    return result


def _source_destination_page(reader, destination):
    target = destination[0]
    if isinstance(target, IndirectObject):
        for number, page in enumerate(reader.pages):
            ref = page.indirect_reference
            if ref.idnum == target.idnum and ref.generation == target.generation:
                return number
    raise EditError("Un enlace interno no referencia una página del PDF de origen.")


def _retarget_page_annotations(source_reader, source_page, result_reader, output_page, mapping):
    before = list(_object(source_reader.pages[source_page].get("/Annots", [])))
    after = list(_object(result_reader.pages[output_page].get("/Annots", [])))
    if len(before) != len(after):
        raise EditError("La clonación no conservó todas las anotaciones de una página.")
    annotation_refs = {(ref.idnum, ref.generation): index for index, ref in enumerate(before) if isinstance(ref, IndirectObject)}
    owner = result_reader.pages[output_page].indirect_reference
    for source_ref, copied_ref in zip(before, after):
        original, copied = _object(source_ref), _object(copied_ref)
        if "/P" in copied:
            copied[NameObject("/P")] = owner
        # add_page excludes /Parent while cloning the page graph; for a Popup
        # that key is an annotation relationship, not the page-tree parent.
        for key in ("/Parent", "/Popup", "/IRT"):
            if key not in original:
                continue
            ref = original.raw_get(key)
            index = annotation_refs.get((ref.idnum, ref.generation)) if isinstance(ref, IndirectObject) else None
            if index is None:
                raise EditError("Una relación entre anotaciones apunta fuera de la página; no se puede duplicar con garantías.")
            copied[NameObject(key)] = after[index]
        if original.get("/Subtype") != "/Link":
            continue
        action = _object(original.get("/A", {}))
        if action.get("/S") == "/URI":
            continue
        destination = _object(original.get("/Dest", action.get("/D")))
        if destination is None:
            continue
        target = _source_destination_page(source_reader, destination)
        if target not in mapping:
            raise EditError(f"La página {source_page+1} enlaza a la página {target+1}, que quedaría excluida.")
        exact = ArrayObject([result_reader.pages[mapping[target]].indirect_reference, *destination[1:]])
        if "/Dest" in original:
            copied[NameObject("/Dest")] = exact
        else:
            _object(copied["/A"])[NameObject("/D")] = exact


def _organizer_toc(writer, readers, groups):
    for reader, toc in zip(readers, groups):
        parents = []
        for level, title, target_page, destination in toc:
            while len(parents) >= level:
                parents.pop()
            parent = parents[-1] if parents else None
            kind = destination.get("kind")
            original = reader.get_object(destination["xref"])
            action = _object(original.get("/A", {}))
            raw = _object(original.get("/Dest", action.get("/D")))
            fit = Fit.xyz(*[None if type(value).__name__ == "NullObject" else float(value) for value in raw[2:5]]) if kind == fitz.LINK_GOTO else Fit.xyz()
            item = writer.add_outline_item(title, target_page-1 if kind == fitz.LINK_GOTO else None,
                                           parent=parent, fit=fit, color=destination.get("color"),
                                           bold=destination.get("bold", False), italic=destination.get("italic", False),
                                           is_open=not destination.get("collapse", False))
            if kind == fitz.LINK_URI:
                item.get_object()[NameObject("/A")] = action.clone(writer)
                item.get_object().pop(NameObject("/Dest"), None)
            parents.append(item)


def _build_organized(readers, entries, source_indices, maps, toc_groups):
    writer = PdfWriter(clone_from=readers[0])
    writer.root_object.pop(NameObject("/Outlines"), None)
    writer.root_object.pop(NameObject("/Names"), None)
    for index in reversed(range(len(writer.pages))):
        writer.remove_page(index)
    for entry in entries:
        if entry["source"] == "blank":
            page = writer.add_blank_page(entry["width"], entry["height"])
        else:
            reader = readers[source_indices[entry["source"]]]
            # Duplicate annotations, appearance graphs and page dictionaries
            # independently. A self-link in one copy must not mutate another.
            writer.reset_translation(reader)
            page = writer.add_page(reader.pages[entry["page"]])
        page.rotate(entry["rotation"])
    intermediate = io.BytesIO()
    writer.write(intermediate)
    copied = PdfReader(io.BytesIO(intermediate.getvalue()), strict=True)
    # pypdf remaps repeated-page links to its last clone while writing. Bind
    # the desired destinations in this independent graph BEFORE cloning it
    # for the final write, retaining the exact original XYZ coordinates.
    for output_number, entry in enumerate(entries):
        if entry["source"] == "blank":
            continue
        source_number = source_indices[entry["source"]]
        mapping = dict(maps[source_number])
        mapping[entry["page"]] = output_number
        _retarget_page_annotations(readers[source_number], entry["page"], copied, output_number, mapping)
    final_writer = PdfWriter(clone_from=copied)
    page_catalog.rebuild_many(final_writer, readers, maps)
    _organizer_toc(final_writer, readers, toc_groups)
    output = io.BytesIO()
    final_writer.write(output)
    with fitz.open(stream=output.getvalue(), filetype="pdf") as doc:
        return full_write(doc)


def _font_programs(page):
    result = []
    for xref, extension, kind, name, resource, encoding, *_ in page.get_fonts(full=True):
        try:
            data = page.parent.extract_font(xref)[3]
        except (ValueError, RuntimeError):
            data = b""
        result.append((extension, kind, name, resource, encoding, hashlib.sha256(data).hexdigest() if data else None))
    return sorted(result)


def _validate_organized(output, inputs, entries, source_indices, maps, expected_toc, primary_rotations, *, tagged_remap=False):
    with ExitStack() as stack:
        docs = [stack.enter_context(fitz.open(stream=data, filetype="pdf")) for data in inputs]
        readers = [PdfReader(io.BytesIO(data), strict=True) for data in inputs]
        result = stack.enter_context(fitz.open(stream=output, filetype="pdf"))
        independent = PdfReader(io.BytesIO(output), strict=True)
        page_catalog.validate(readers, independent, maps)
        if result.page_count != len(entries) or len(independent.pages) != len(entries):
            raise EditError("El organizador produjo un número de páginas incorrecto.")
        if _metadata(readers[0]) != _metadata(independent) or docs[0].get_xml_metadata() != result.get_xml_metadata():
            raise EditError("El organizador alteró metadatos del documento actual.")
        if _catalog_metadata(readers[0]) != _catalog_metadata(independent):
            raise EditError("El organizador alteró propiedades del catálogo.")
        if _canonical(expected_toc) != _canonical(result.get_toc(False)):
            raise EditError("No se conservaron los marcadores o sus destinos al organizar.")
        for (source_number, page_number), rotation in primary_rotations.items():
            page = docs[source_number][page_number]
            page.set_rotation(rotation)
            docs[source_number].reload_page(page)
        stats = []
        for output_number, entry in enumerate(entries):
            copied = result[output_number]
            if entry["source"] == "blank":
                with fitz.open() as expected:
                    original = expected.new_page(width=entry["width"], height=entry["height"])
                    original.set_rotation(entry["rotation"])
                    if copied.read_contents() or trace_chars(copied) or copied.get_links() or list(copied.annots() or []) or copied.get_images():
                        raise EditError("Una página solicitada en blanco contiene elementos inesperados.")
                    if tuple(copied.mediabox) != tuple(original.mediabox) or copied.rotation != original.rotation:
                        raise EditError("La página en blanco no tiene las dimensiones o giro solicitados.")
                    pixels = assert_pixels(original, copied, excluded=())
                stats.append({"output_page": output_number, "source": "blank", **pixels})
                continue
            source_number = source_indices[entry["source"]]
            input_page = entry["page"]
            original = docs[source_number][input_page]
            first_rotation = original.rotation
            target_rotation = (int(readers[source_number].pages[input_page].rotation) + entry["rotation"]) % 360
            original.set_rotation(target_rotation)
            original = docs[source_number].reload_page(original)
            mapping = dict(maps[source_number])
            mapping[input_page] = output_number  # Self-links belong to this copy.
            boxes = lambda p: (tuple(p.mediabox), tuple(p.cropbox), tuple(p.bleedbox), tuple(p.trimbox), tuple(p.artbox), p.rotation, tuple(p.rect))
            if boxes(original) != boxes(copied):
                raise EditError(f"La página final {output_number+1} cambió de cajas o giro fuera del plan.")
            if original.read_contents() != copied.read_contents() or _font_programs(original) != _font_programs(copied):
                raise EditError(f"La página final {output_number+1} cambió operadores o programas de fuente.")
            assert_characters(trace_chars(original), copied)
            if readers[source_number].pages[input_page].extract_text() != independent.pages[output_number].extract_text():
                raise EditError(f"El extractor independiente detectó cambios en la página final {output_number+1}.")
            expected_related = related(original)
            expected_related["links"] = _mapped_links(original, mapping)
            if expected_related != related(copied):
                raise EditError(f"La página final {output_number+1} no conserva imágenes, vectores, anotaciones o enlaces.")
            if _annotation_details(readers[source_number], input_page, mapping, ignore_struct_parent=tagged_remap) != _annotation_details(independent, output_number, ignore_struct_parent=tagged_remap):
                raise EditError(f"La página final {output_number+1} cambió atributos de anotaciones.")
            if _raw_link_targets(readers[source_number], input_page, mapping) != _raw_link_targets(independent, output_number):
                raise EditError(f"La página final {output_number+1} cambió coordenadas PDF o atributos de destino.")
            pixels = assert_pixels(original, copied, excluded=())
            original.set_rotation(first_rotation)
            docs[source_number].reload_page(original)
            stats.append({"output_page": output_number, "source": entry["source"], "source_page": input_page,
                          "rotation_delta": entry["rotation"], "font_programs_equal": True, **pixels})
        return stats


def organize_pages_pdf(data: bytes, plan: list[dict], additions: dict[str, bytes] | None = None, *, _tagged_replacement=False):
    """Execute an explicit final order; source indices and rotation deltas are 0-based.

    Entries are current/external PDF pages, or blank pages in PDF points.
    External identifiers refer only to caller-provided bytes, never filenames
    read by this function. Unsupported document features remain blocked.
    """
    started = time.perf_counter()
    additions = {} if additions is None else additions
    if not isinstance(additions, dict) or any(not isinstance(key, str) or key in ("current", "blank") for key in additions):
        raise EditError("Los PDFs añadidos necesitan identificadores distintos de current y blank.")
    if not isinstance(plan, (list, tuple)) or not plan:
        raise EditError("El orden final debe contener al menos una página.")
    used = list(dict.fromkeys(entry.get("source") for entry in plan if isinstance(entry, dict) and isinstance(entry.get("source"), str)))
    source_ids = ["current"] + [key for key in used if key not in ("current", "blank")]
    if any(key not in additions for key in source_ids[1:]):
        raise EditError("El plan contiene un PDF añadido que todavía no se ha cargado.")
    inputs = [data] + [additions[key] for key in source_ids[1:]]
    with ExitStack() as stack:
        docs, readers = [], []
        for key, payload in zip(source_ids, inputs):
            doc, reader = _preflight(payload, "Documento actual" if key == "current" else f"PDF añadido «{key}»")
            docs.append(stack.enter_context(doc))
            readers.append(reader)
        entries = _organizer_plan(plan, {key: len(doc) for key, doc in zip(source_ids, docs)})
        page_catalog.require_unambiguous(readers, entries)
        source_indices = {key: index for index, key in enumerate(source_ids)}
        maps = [{} for _ in docs]
        primary_rotations = {}
        for output_number, entry in enumerate(entries):
            if entry["source"] == "blank":
                continue
            number, page = source_indices[entry["source"]], entry["page"]
            if page not in maps[number]:
                maps[number][page] = output_number
                primary_rotations[number, page] = (docs[number][page].rotation + entry["rotation"]) % 360
        for (number, page), rotation in primary_rotations.items():
            changed = docs[number][page]
            changed.set_rotation(rotation)
            docs[number].reload_page(changed)
        expected_toc, toc_groups, removed = [], [], []
        for number, doc in enumerate(docs):
            for page in maps[number]:
                _mapped_links(doc[page], maps[number])
            toc, excluded = _mapped_toc(doc, maps[number])
            expected_toc.extend(toc)
            toc_groups.append(toc)
            removed.extend(excluded)
        tagged_report = None
        if any(reader.trailer['/Root'].get('/StructTreeRoot') for reader in readers):
            if _tagged_replacement and len(readers) == 2:
                from .tagged_merge import build_tagged_replacement
                output, tagged_report = build_tagged_replacement(readers, entries, source_indices, maps, toc_groups)
            elif len(readers) != 1 or not readers[0].trailer['/Root'].get('/StructTreeRoot'):
                raise EditError('PDF etiquetado: insertar otro PDF requiere fusionar sus árboles de accesibilidad; esta operación todavía no está habilitada.')
            else:
                from .tagged_pages import build_tagged_pages
                output, tagged_report = build_tagged_pages(readers[0], entries, toc_groups[0])
        else:
            output = _build_organized(readers, entries, source_indices, maps, toc_groups)
    stats = _validate_organized(output, inputs, entries, source_indices, maps, expected_toc, primary_rotations,
                                tagged_remap=bool(tagged_report and tagged_report.get('operation') == 'replace_tagged_pages'))
    return output, {"verified": True, "operation": "organize_pages", "page_count": len(entries),
                    "page_map": [entry["page"] if entry["source"] == "current" else None for entry in entries],
                    "assignments": entries, "pages": stats, "removed_bookmarks": removed, "tagged_structure": tagged_report,
                    "named_destinations": page_catalog.report(readers[0], maps[0]),
                    "destination_policy": "Primera aparición final del destino; los enlaces a la propia página apuntan a su copia.",
                    "source_sha256": {key: hashlib.sha256(payload).hexdigest() for key, payload in zip(source_ids, inputs)},
                    "metadata_policy": "Se conservan Info/XMP del documento actual y los marcadores compatibles de los documentos incorporados.",
                    "independent_parser": "pypdf", "elapsed_seconds": round(time.perf_counter()-started, 3)}
