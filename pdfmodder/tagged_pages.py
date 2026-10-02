"""Page transactions for verified logical structure, without rebuilding content.

One cloned graph keeps page, annotation and structure references shared exactly
as in the source. Removing pages also removes their MCR / OBJR leaves and their
ParentTree entries. No text operator or accessibility property is synthesized.
Reordering is admitted only if complete sibling branches can follow the new
page order; an interleaved cross-page branch is not split implicitly.
"""
from __future__ import annotations

from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, NumberObject, NullObject

from .model import EditError
from .tagged import TaggedStructure, obj, ref, _number_tree


def is_tagged(reader):
    return bool(reader.trailer['/Root'].get('/StructTreeRoot'))


def _fail(message):
    raise EditError('PDF etiquetado: ' + message)


def _names(value, seen=None):
    value = obj(value)
    seen = set() if seen is None else seen
    if not isinstance(value, dict) or id(value) in seen:
        _fail('IDTree no es un árbol de nombres verificable.')
    seen = seen | {id(value)}
    values = obj(value.get('/Names', []))
    if len(values) % 2:
        _fail('IDTree contiene pares incompletos.')
    result = list(zip(values[::2], values[1::2]))
    for child in obj(value.get('/Kids', [])):
        result.extend(_names(child, seen))
    if len({str(key) for key, _ in result}) != len(result):
        _fail('IDTree contiene identificadores repetidos.')
    return result


def preflight(data):
    """Verify structural scope separately from any concrete text selection."""
    structure = TaggedStructure(data)
    allowed = {'/Type', '/K', '/ParentTree', '/ParentTreeNextKey', '/RoleMap', '/ClassMap', '/IDTree', '/Namespaces'}
    extra = set(structure.tree) - allowed
    if extra:
        _fail('la reorganización todavía no admite estas propiedades estructurales: ' + ', '.join(sorted(extra)) + '.')
    for node in structure.nodes.values():
        if '/Pg' in node and ref(node.raw_get('/Pg')) not in structure.pages:
            _fail('un elemento estructural referencia una página que no pertenece al documento.')
    if '/IDTree' in structure.tree:
        for _, node in _names(structure.tree.raw_get('/IDTree')):
            if ref(node) not in structure.node_refs:
                _fail('IDTree contiene un elemento ajeno al árbol de estructura.')
    return structure


def page_capabilities(data):
    """A cached caller may use this advisory result; every operation revalidates."""
    result = dict(supported=False, reason='', delete=False, extract=False, reorder=False,
                  rotate=False, duplicate=False, insert_blank=False, insert_pdf=False, replace_pdf=False)
    try:
        # The shared preflight also checks permissions, signatures, forms,
        # annotation actions and catalog features. Never advertise a bypass.
        from .pageops import _preflight
        doc, reader = _preflight(data, 'Documento actual')
        doc.close()
        if not is_tagged(reader):
            if '/Names' in reader.trailer['/Root']:
                result.update(supported=True, delete=True, extract=True, reorder=True, rotate=True, insert_blank=True, insert_pdf=True, replace_pdf=True,
                              reason='Se conservan los destinos internos. Se pueden incorporar PDFs sin nombres de destino repetidos; duplicar páginas con destinos sigue bloqueado.')
                return result
            return dict(supported=True, reason='', **{key: True for key in result if key not in ('supported', 'reason')})
        result.update(supported=True, delete=True, extract=True, reorder=True, rotate=True, insert_blank=True, replace_pdf=True,
                      reason='Se conservan las etiquetas al eliminar, extraer, girar y reordenar páginas compatibles. Reemplazar exige páginas también etiquetadas y árboles compatibles. Duplicar, insertar y combinar siguen bloqueados.')
    except Exception as exc:
        result['reason'] = str(exc)
    return result


def require_single_source(entries):
    if any(entry['source'] not in ('current', 'blank') for entry in entries):
        _fail('insertar o combinar otro PDF requiere fusionar sus árboles de accesibilidad; conserva los documentos separados.')
    pages = [entry['page'] for entry in entries if entry['source'] == 'current']
    if len(pages) != len(set(pages)):
        _fail('duplicar una página requiere nuevas claves ParentTree y relaciones de lectura; esta operación todavía no está habilitada.')


def _assert_reachable(root, forbidden):
    """Reject retained attributes (/Ref, IDs, custom attributes) to removed nodes."""
    seen = set()
    def visit(value):
        identity = ref(value)
        if isinstance(value, IndirectObject):
            if identity in forbidden:
                _fail('una relación accesible conservada apunta a una página o elemento excluido. Conserva también esa página.')
            if identity in seen:
                return
            seen.add(identity)
            value = obj(value)
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
    visit(root)


def _prune_tree(writer, original_pages, entries):
    root = writer.root_object['/StructTreeRoot']
    page_numbers = {ref(page): number for number, page in enumerate(original_pages)}
    mapping = {entry['page']: number for number, entry in enumerate(entries) if entry['source'] == 'current'}
    retained = set(mapping)
    annotations = {ref(a): number for number, page in enumerate(original_pages) for a in obj(page.get('/Annots', []))}
    removed_nodes, surviving_nodes = set(), set()
    reorder = list(mapping) != sorted(mapping)

    def reading_pages(raw, inherited_page):
        value = obj(raw)
        if isinstance(value, (list, tuple)):
            return [page for child in value for page in reading_pages(child, inherited_page)]
        if isinstance(value, int):
            return [page_numbers[inherited_page]]
        if not isinstance(value, dict):
            return []
        page = ref(value.get('/Pg')) or inherited_page
        if value.get('/Type') == '/OBJR':
            return [annotations[ref(value.get('/Obj'))]]
        if value.get('/Type') == '/MCR' or '/MCID' in value:
            return [page_numbers[page]]
        return reading_pages(value.get('/K', []), page)

    def sequence(values, inherited_page):
        records = [prune(value, inherited_page) for value in values]
        original = set().union(*(record[1] for record in records)) if records else set()
        kept = [(value, pages) for value, _, pages in records if value is not None]
        if reorder:
            # Empty structural elements stay at their original insertion slot.
            occupied = [(i, value, pages) for i, (value, pages) in enumerate(kept) if pages]
            ordered = sorted(occupied, key=lambda entry: min(mapping[p] for p in entry[2]))
            last = -1
            for _, _, pages in ordered:
                low, high = min(mapping[p] for p in pages), max(mapping[p] for p in pages)
                if low < last:
                    _fail('el orden solicitado intercala ramas de lectura que abarcan varias páginas. Extrae en el orden original o conserva juntas esas ramas.')
                last = high
            for (slot, _, _), (_, value, pages) in zip(occupied, ordered):
                kept[slot] = value, pages
        return ArrayObject([value for value, _ in kept]), original, set().union(*(pages for _, pages in kept)) if kept else set()

    def prune(raw, inherited_page):
        value = obj(raw)
        if isinstance(value, NullObject):
            return raw, set(), set()
        if isinstance(value, (list, tuple)):
            return sequence(value, inherited_page)
        if isinstance(value, int):
            if inherited_page not in page_numbers:
                _fail('un MCID no identifica una página válida.')
            number = page_numbers[inherited_page]
            return (raw if number in retained else None), {number}, ({number} if number in retained else set())
        if not isinstance(value, dict):
            _fail('un elemento de lectura no puede interpretarse.')
        page = ref(value.get('/Pg')) or inherited_page
        if value.get('/Type') == '/MCR' or '/MCID' in value:
            number = page_numbers.get(page)
            if number is None:
                _fail('una referencia MCR no identifica una página válida.')
            return (raw if number in retained else None), {number}, ({number} if number in retained else set())
        if value.get('/Type') == '/OBJR':
            number = annotations.get(ref(value.get('/Obj')))
            if number is None or page is not None and page_numbers.get(page) != number:
                _fail('una referencia OBJR no corresponde a su anotación y página.')
            return (raw if number in retained else None), {number}, ({number} if number in retained else set())
        kids = value.raw_get('/K') if '/K' in value else ArrayObject()
        semantic_text = any(key in value for key in ('/ActualText', '/Alt', '/E'))
        original_order = reading_pages(kids, page) if reorder and semantic_text else None
        result, before, after = prune(kids, page)
        if before and not after or not before and page in page_numbers and page_numbers[page] not in retained:
            removed_nodes.add(ref(raw))
            return None, before, set()
        if before != after and semantic_text:
            _fail('un bloque que abarca páginas excluidas tiene ActualText, Alt o expansión semántica. No se elimina parcialmente sin revisar ese texto accesible.')
        if original_order is not None and original_order != reading_pages(result, page):
            _fail('el nuevo orden afecta a un bloque con ActualText, Alt o expansión semántica. Revisa ese texto accesible antes de reordenarlo.')
        if '/K' in value:
            value[NameObject('/K')] = result if result is not None else ArrayObject()
        if '/Pg' in value and page_numbers.get(ref(value.raw_get('/Pg'))) not in retained:
            value.pop(NameObject('/Pg'))
        surviving_nodes.add(ref(raw))
        return raw, before, after

    new_kids, _, _ = prune(root.raw_get('/K') if '/K' in root else ArrayObject(), None)
    root[NameObject('/K')] = new_kids if new_kids is not None else ArrayObject()
    parents = _number_tree(root.get('/ParentTree', {}))
    used = set()
    for number in retained:
        page = original_pages[number]
        if '/StructParents' in page:
            used.add(int(page['/StructParents']))
        for annotation in obj(page.get('/Annots', [])):
            annotation = obj(annotation)
            if '/StructParent' in annotation:
                used.add(int(annotation['/StructParent']))
    nums = ArrayObject()
    for key in sorted(used):
        if key not in parents:
            _fail('falta una asociación ParentTree de una página conservada.')
        parent = parents[key]
        nums.extend([NumberObject(key), getattr(parent, 'indirect_reference', None) or parent])
    root[NameObject('/ParentTree')] = DictionaryObject({NameObject('/Nums'): nums})
    # Keys are deliberately retained, including gaps. NextKey may legitimately
    # exceed max(used)+1 and must not regress across future editing operations.
    if '/IDTree' in root:
        names = ArrayObject()
        for key, value in _names(root.raw_get('/IDTree')):
            if ref(value) in surviving_nodes:
                names.extend([key, value])
        root[NameObject('/IDTree')] = DictionaryObject({NameObject('/Names'): names})
    return (removed_nodes
            | {ref(page) for number, page in enumerate(original_pages) if number not in retained}
            | {annotation for annotation, number in annotations.items() if number not in retained})


def build_tagged_pages(reader, entries, toc):
    """Return fully rewritten bytes plus a structure verification report."""
    require_single_source(entries)
    from .pageops import _organizer_toc
    from .engine import full_write
    writer = PdfWriter(clone_from=reader)
    original_pages = list(writer.pages)
    forbidden = _prune_tree(writer, original_pages, entries)
    pages = []
    for entry in entries:
        if entry['source'] == 'blank':
            page = writer.add_blank_page(entry['width'], entry['height'])
        else:
            page = original_pages[entry['page']]
        page.rotate(entry.get('rotation', 0))
        pages.append(page)
    # Reuse the cloned page identities. append()/reset_translation() would
    # clone a second graph, detaching the original structure's /Pg and OBJR.
    pages_root = writer.root_object['/Pages']
    parent = pages_root.indirect_reference
    for page in pages:
        page[NameObject('/Parent')] = parent
    pages_root[NameObject('/Kids')] = ArrayObject([page.indirect_reference for page in pages])
    pages_root[NameObject('/Count')] = NumberObject(len(pages))
    writer.flattened_pages = pages
    writer.root_object.pop(NameObject('/Outlines'), None)
    _organizer_toc(writer, [reader], [toc])
    _assert_reachable(writer.root_object, forbidden)
    intermediate = BytesIO()
    writer.write(intermediate)
    expected = TaggedStructure(intermediate.getvalue())
    with fitz.open(stream=intermediate.getvalue(), filetype='pdf') as doc:
        output = full_write(doc)
    verified = TaggedStructure(output)
    if expected.semantic() != verified.semantic():
        _fail('el guardado cambió relaciones, orden o propiedades accesibles.')
    return output, {'verified': True, 'retained_structural_elements': len(verified.nodes),
                    'parent_tree_keys': sorted(verified.parents), 'removed_graph_objects': len(forbidden),
                    'policy': 'MCID y claves conservados; ramas, OBJR y asociaciones de páginas excluidas eliminados; orden de lectura verificado.'}
