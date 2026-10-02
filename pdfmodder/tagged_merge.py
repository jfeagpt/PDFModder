"""Verified replacement of tagged pages, without inventing accessibility tags.

Contiguous portions retain their complete pruned logical trees. Their root
branches are joined in final page order; document wrappers are retained rather
than flattening paragraphs, lists or tables. A cross-page semantic alternative
that cannot be pruned, dangling relationships, and conflicting map/ID names
remain errors. MCIDs are page-local and stay unchanged; ParentTree keys are
document-global and are remapped explicitly.

Cloning API: https://pypdf.readthedocs.io/en/6.6.0/user/merging-pdfs.html
"""
from __future__ import annotations

from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from .engine import full_write
from .tagged import TaggedStructure, obj, ref, _number_tree
from .tagged_pages import _fail, _names, build_tagged_pages


def _array(value):
    resolved = obj(value)
    return list(resolved) if isinstance(resolved, (list, tuple)) else [value]


def _segments(entries):
    segments = []
    for entry in entries:
        if not segments or segments[-1][0] != entry['source']:
            segments.append((entry['source'], []))
        segments[-1][1].append(entry)
    return segments


def _merge_map(target, source, key, writer):
    from .pageops import _semantic
    incoming = obj(source.get(key, {}))
    if not isinstance(incoming, dict):
        _fail(f'{key} no es un diccionario verificable.')
    if not incoming:
        return
    result = target.setdefault(NameObject(key), DictionaryObject())
    for name, value in incoming.items():
        if name in result and _semantic(result.raw_get(name)) != _semantic(value):
            _fail(f'las fuentes asignan significados distintos a {key} {name}; no se pueden fusionar sin renombrar sus referencias.')
        result[name] = value.clone(writer)


def _check_identifiers(structure):
    """IDTree must describe exact unique /ID strings, not merely reachable nodes."""
    from .page_catalog import _key_bytes
    expected = {}
    for node in structure.nodes.values():
        if '/ID' not in node:
            continue
        value = node['/ID']
        if not isinstance(value, (TextStringObject, ByteStringObject)):
            _fail('un ID estructural no es una cadena PDF válida.')
        key = _key_bytes(value)
        if key in expected:
            _fail('hay IDs estructurales repetidos en un segmento.')
        expected[key] = ref(node)
    actual = {_key_bytes(key): ref(value) for key, value in
              (_names(structure.tree.raw_get('/IDTree')) if '/IDTree' in structure.tree else [])}
    if expected != actual:
        _fail('IDTree no coincide con los identificadores de los elementos; no se reemplazan páginas con IDs ambiguos.')


def build_tagged_replacement(readers, entries, source_indices, maps, toc_groups):
    """Only called by the explicit whole-page replacement transaction.

    Importing an untagged page is rejected: tagging text as generic paragraphs
    or pictures as artifacts would fabricate semantic information.
    """
    from . import page_catalog
    from .pageops import _organizer_toc, _retarget_page_annotations

    if any(not reader.trailer['/Root'].get('/StructTreeRoot') for reader in readers):
        _fail('reemplazar páginas requiere un PDF de sustitución también etiquetado. Etiqueta primero su texto, imágenes y orden de lectura; no se crean etiquetas ficticias.')
    if any(entry['source'] == 'blank' for entry in entries):
        _fail('la sustitución etiquetada no admite páginas de origen en blanco.')
    identities = [(entry['source'], entry['page']) for entry in entries]
    if len(set(identities)) != len(identities):
        _fail('la sustitución no puede duplicar una misma instancia de página.')
    for reader in readers:
        if '/Namespaces' in reader.trailer['/Root']['/StructTreeRoot']:
            _fail('la sustitución de páginas con namespaces de PDF 2.0 requiere soporte adicional.')

    # Each segment is an independently validated projection. This also rejects
    # /Ref links into excluded branches and partially removed ActualText/Alt.
    portions = []
    for source, segment in _segments(entries):
        selected = [dict(source='current', page=e['page'], rotation=e['rotation']) for e in segment]
        payload, _ = build_tagged_pages(readers[source_indices[source]], selected, [])
        _check_identifiers(TaggedStructure(payload))
        portions.append((source, segment, PdfReader(BytesIO(payload), strict=True)))

    writer = PdfWriter(clone_from=readers[0])
    writer.pdf_header = max(reader.pdf_header for reader in readers)
    root = writer.root_object
    root.pop(NameObject('/StructTreeRoot'), None)
    root.pop(NameObject('/Outlines'), None)
    root.pop(NameObject('/Names'), None)
    tree = DictionaryObject({NameObject('/Type'): NameObject('/StructTreeRoot')})
    tree_ref = writer._add_object(tree)
    root[NameObject('/StructTreeRoot')] = tree_ref
    kids, nums, ids, pages = ArrayObject(), ArrayObject(), [], []
    used_ids, next_key = set(), 0
    primary_language = root.get('/Lang')
    for source, segment, reader in portions:
        # clone(), unlike per-page add_page/reset_translation, gives pages,
        # annotations and /Pg references exactly one shared graph per portion.
        imported_pages = [page.clone(writer) for page in reader.pages]
        imported_tree = reader.trailer['/Root']['/StructTreeRoot'].clone(writer)
        source_tree = reader.trailer['/Root']['/StructTreeRoot']
        _merge_map(tree, source_tree, '/RoleMap', writer)
        _merge_map(tree, source_tree, '/ClassMap', writer)
        parents = _number_tree(imported_tree.get('/ParentTree', {}))
        remap = {key: next_key + n for n, key in enumerate(sorted(parents))}
        next_key += len(remap)
        for page in imported_pages:
            if '/StructParents' in page:
                if int(page['/StructParents']) not in remap:
                    _fail('una página declara StructParents sin asociación verificable.')
                page[NameObject('/StructParents')] = NumberObject(remap[int(page['/StructParents'])])
            for raw in obj(page.get('/Annots', [])):
                annotation = obj(raw)
                if '/StructParent' in annotation:
                    if int(annotation['/StructParent']) not in remap:
                        _fail('una anotación declara StructParent sin una relación OBJR verificable.')
                    annotation[NameObject('/StructParent')] = NumberObject(remap[int(annotation['/StructParent'])])
        for old in sorted(parents):
            value = parents[old]
            nums.extend([NumberObject(remap[old]), getattr(value, 'indirect_reference', None) or value])
        if '/IDTree' in imported_tree:
            for name, node in _names(imported_tree.raw_get('/IDTree')):
                # Keep exact PDF strings. Do not silently rename identifiers
                # which may also be referenced in attributes or external data.
                key = page_catalog._key_bytes(name)
                if key in used_ids:
                    _fail('los segmentos conservados contienen IDs estructurales repetidos; requiere resolver esos identificadores antes de reemplazar páginas.')
                used_ids.add(key)
                ids.append((name, node))
        language = reader.trailer['/Root'].get('/Lang')
        for branch in _array(imported_tree.raw_get('/K')):
            value = obj(branch)
            if not isinstance(value, dict) or ref(branch) is None or '/S' not in value:
                _fail('la raíz lógica de un segmento no contiene ramas estructurales independientes.')
            value[NameObject('/P')] = tree_ref
            if '/Lang' not in value and language != primary_language:
                if not language:
                    _fail('el PDF de sustitución no declara idioma y heredaría uno incorrecto del documento actual.')
                value[NameObject('/Lang')] = TextStringObject(str(language))
            kids.append(branch)
        pages.extend(imported_pages)
    tree[NameObject('/K')] = kids
    tree[NameObject('/ParentTree')] = DictionaryObject({NameObject('/Nums'): nums})
    tree[NameObject('/ParentTreeNextKey')] = NumberObject(next_key)
    if ids:
        pairs = ArrayObject()
        for name, node in sorted(ids, key=lambda pair: page_catalog._key_bytes(pair[0])):
            pairs.extend([name, node])
        tree[NameObject('/IDTree')] = DictionaryObject({NameObject('/Names'): pairs})
    page_root = root['/Pages']
    for page in pages:
        page[NameObject('/Parent')] = page_root.indirect_reference
    page_root[NameObject('/Kids')] = ArrayObject([page.indirect_reference for page in pages])
    page_root[NameObject('/Count')] = NumberObject(len(pages))
    writer.flattened_pages = pages
    # Links target the final identities, not the isolated segment numbering.
    for number, entry in enumerate(entries):
        source_number = source_indices[entry['source']]
        _retarget_page_annotations(readers[source_number], entry['page'], writer, number, maps[source_number])
    page_catalog.rebuild_many(writer, readers, maps)
    _organizer_toc(writer, readers, toc_groups)
    stream = BytesIO()
    writer.write(stream)
    expected = TaggedStructure(stream.getvalue())
    with fitz.open(stream=stream.getvalue(), filetype='pdf') as document:
        output = full_write(document)
    verified = TaggedStructure(output)
    if expected.semantic() != verified.semantic():
        _fail('el guardado alteró relaciones, orden de lectura o propiedades accesibles de las páginas sustituidas.')
    return output, dict(verified=True, operation='replace_tagged_pages',
                       retained_structural_elements=len(verified.nodes),
                       parent_tree_keys=sorted(verified.parents), segments=len(portions),
                       policy='Ramas conservadas en orden final; MCID locales intactos; claves ParentTree y referencias de página remapeadas; sin etiquetas sintetizadas.')
