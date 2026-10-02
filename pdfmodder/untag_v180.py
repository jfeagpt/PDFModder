"""Explicit removal of accessibility structure from an immutable PDF snapshot.

Tags describe headings, paragraphs, alternative text and logical reading order.
Removing them intentionally loses that information. It does not convert the
pages to images or remove optional-content layers. Content streams, including
ActualText and marked-content wrappers, remain unchanged: they can carry useful
text extraction or visibility semantics even without a structure tree.
"""
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

from .document_ops_v170 import _assert_content, _open, _restriction
from .model import EditError


_STRUCTURE_ASSOCIATIONS = ('/StructParents', '/StructParent', '/ObjectStructParent')


def _remove_associations(root):
    """Handle both direct dictionaries and indirect objects, without cycles."""
    pending = [root]
    seen = set()
    removed = 0
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            value = value.get_object()
        if not isinstance(value, (DictionaryObject, ArrayObject)) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, DictionaryObject):
            for key in _STRUCTURE_ASSOCIATIONS:
                if key in value:
                    del value[NameObject(key)]
                    removed += 1
            pending.extend(value.values())
        else:
            pending.extend(value)
    return removed


def remove_tags(pdf_bytes, password=''):
    """Return (copy_bytes, report), or block an unsafe full rewrite.

    The caller must explain the accessibility loss before calling this function,
    keep the original, and commit the resulting snapshot through undo history.
    Signed and already encrypted PDFs are deliberately left intact. Ordinary
    AcroForms are retained, including their appearances, values and calculations.
    """
    try:
        with _open(pdf_bytes, password) as before:
            reason, _ = _restriction(pdf_bytes, before, password)
            if reason:
                raise EditError(reason)
            reader = PdfReader(BytesIO(pdf_bytes), strict=True)
            root = reader.trailer['/Root']
            marked = root.get('/MarkInfo')
            tagged = bool(root.get('/StructTreeRoot') or
                          (marked and marked.get_object().get('/Marked')))
            if not tagged:
                return pdf_bytes, {
                    'operation': 'remove_tags', 'pages': before.page_count,
                    'changed': False, 'verified': True, 'source_regions': [],
                    'destination_regions': [],
                }

            # Clone the complete document, rather than rebuilding its pages.
            # This preserves bookmarks, fields, attachments and custom metadata.
            writer = PdfWriter(clone_from=reader)
            writer.root_object.pop(NameObject('/StructTreeRoot'), None)
            writer.root_object.pop(NameObject('/MarkInfo'), None)
            removed = _remove_associations(writer.root_object)
            stream = BytesIO()
            writer.write(stream)
            with fitz.open(stream=stream.getvalue(), filetype='pdf') as copy:
                # Garbage collection removes the now-unreachable structure graph,
                # including cyclic parents. No cleaning or rewriting of operators.
                candidate = copy.tobytes(garbage=1, deflate=False,
                                         incremental=False, no_new_id=True)

            with _open(candidate) as after:
                _assert_content(before, after)
                if (before.metadata != after.metadata or
                        before.get_xml_metadata() != after.get_xml_metadata() or
                        before.get_toc() != after.get_toc()):
                    raise EditError('La copia sin etiquetas no conserva los metadatos o marcadores; operación cancelada.')
                for left, right in zip(before, after):
                    if left.read_contents() != right.read_contents():
                        raise EditError('La copia sin etiquetas alteró el contenido de una página; operación cancelada.')
            checked = PdfReader(BytesIO(candidate), strict=True)
            if checked.trailer['/Root'].get('/StructTreeRoot') or checked.trailer['/Root'].get('/MarkInfo'):
                raise EditError('No se ha podido retirar la estructura etiquetada; operación cancelada.')
            if any(left.extract_text() != right.extract_text()
                   for left, right in zip(reader.pages, checked.pages)):
                raise EditError('La copia sin etiquetas alteró el texto extraído; operación cancelada.')
            return candidate, {
                'operation': 'remove_tags', 'pages': before.page_count,
                'changed': True, 'verified': True, 'associations_removed': removed,
                'text_preserved': True, 'appearance_preserved': True,
                'accessibility_removed': True, 'marked_content_preserved': True,
                'source_regions': [], 'destination_regions': [],
            }
    except EditError:
        raise
    except Exception:
        raise EditError('No se puede quitar la estructura etiquetada con seguridad; se conserva el documento sin cambios.') from None
