"""Conservative catalog support for whole-page transactions.

Empty AcroForms keep their default resources. Named destinations are rebuilt
against the output page identities, retaining view parameters and existing null
targets; only destinations to explicitly excluded pages are removed.
"""
from pypdf.generic import (ArrayObject, DictionaryObject, IndirectObject,
                          NameObject, NullObject, TextStringObject, ByteStringObject)

from .model import EditError


def obj(value):
    return value.get_object() if isinstance(value, IndirectObject) else value


def _fail(message):
    raise EditError("Organizador de páginas: " + message)


def _key_bytes(key):
    if isinstance(key, ByteStringObject):
        return bytes(key)
    try:
        return key.original_bytes
    except Exception:
        return str(key).encode("utf-16-be")


def _tree(raw, seen=None):
    value = obj(raw)
    seen = set() if seen is None else seen
    if not isinstance(value, dict) or id(value) in seen:
        _fail("árbol de destinos con nombre no verificable.")
    if set(value) - {"/Names", "/Kids", "/Limits"} or "/Names" in value and "/Kids" in value:
        _fail("el árbol de destinos contiene propiedades no compatibles.")
    seen = seen | {id(value)}
    pairs = obj(value.get("/Names", []))
    if not isinstance(pairs, (list, tuple)) or len(pairs) % 2:
        _fail("el árbol de destinos contiene pares incompletos.")
    result = []
    for key, destination in zip(pairs[::2], pairs[1::2]):
        if not isinstance(key, (TextStringObject, ByteStringObject)):
            _fail("un identificador de destino no es una cadena PDF.")
        result.append((key, destination))
    kids = obj(value.get("/Kids", []))
    if not isinstance(kids, (list, tuple)):
        _fail("las ramas del árbol de destinos no son válidas.")
    for child in kids:
        result.extend(_tree(child, seen))
    if len({_key_bytes(key) for key, _ in result}) != len(result):
        _fail("hay identificadores de destino repetidos.")
    return result


def destinations(reader):
    """Return (name, page index or None, view array, dictionary wrapper)."""
    root = reader.trailer["/Root"]
    if "/Names" not in root:
        return []
    names = obj(root["/Names"])
    if not isinstance(names, dict) or set(names) != {"/Dests"}:
        _fail("/Names sólo admite destinos internos; adjuntos, scripts u otras colecciones siguen bloqueados.")
    refs = {(page.indirect_reference.idnum, page.indirect_reference.generation): number
            for number, page in enumerate(reader.pages)}
    shapes = {"/XYZ": 5, "/Fit": 2, "/FitH": 3, "/FitV": 3,
              "/FitR": 6, "/FitB": 2, "/FitBH": 3, "/FitBV": 3}
    result = []
    for key, raw in _tree(names["/Dests"]):
        value = obj(raw)
        wrapped = isinstance(value, dict)
        if wrapped:
            if set(value) != {"/D"}:
                _fail("un destino contiene propiedades adicionales no compatibles.")
            value = obj(value["/D"])
        if not isinstance(value, (list, tuple)) or len(value) < 2 or shapes.get(str(value[1])) != len(value):
            _fail("un destino tiene un ajuste de vista no verificable.")
        if any(not isinstance(obj(v), (int, float, NullObject)) for v in value[2:]):
            _fail("un destino contiene coordenadas no numéricas.")
        target = value[0]
        if isinstance(target, NullObject):
            page = None  # Existing unresolved destinations are preserved verbatim.
        elif isinstance(target, IndirectObject) and (target.idnum, target.generation) in refs:
            page = refs[target.idnum, target.generation]
        else:
            _fail("un destino apunta a un objeto que no es una página del documento.")
        result.append((key, page, list(value[1:]), wrapped))
    return result


def preflight(reader):
    root = reader.trailer["/Root"]
    if "/AcroForm" in root:
        form = obj(root["/AcroForm"])
        if (not isinstance(form, dict) or set(form) - {"/Fields", "/DA", "/DR", "/Q"}
                or not isinstance(obj(form.get("/Fields")), (list, tuple)) or obj(form["/Fields"])):
            _fail("el formulario contiene campos o funciones activas; sólo se admite un AcroForm vacío.")
    found = destinations(reader)
    if "/Names" in root and root.get("/StructTreeRoot"):
        _fail("la combinación de etiquetas y destinos con nombre necesita validación adicional.")
    return found


def require_unambiguous(readers, entries=None):
    if not any("/Names" in reader.trailer["/Root"] for reader in readers):
        return
    names = [_key_bytes(key) for reader in readers for key, *_ in destinations(reader)]
    if len(names) != len(set(names)):
        _fail("los PDFs contienen destinos con el mismo nombre; no se puede decidir a cuál debe apuntar cada enlace.")
    if entries is not None:
        pages = [(entry["source"], entry["page"]) for entry in entries if entry["source"] != "blank"]
        if len(pages) != len(set(pages)):
            _fail("duplicar páginas con destinos con nombre requiere elegir a qué copia apunta cada destino.")


def rebuild(writer, reader, mapping):
    rebuild_many(writer, [reader], [mapping])


def rebuild_many(writer, readers, mappings):
    """Merge disjoint name trees; retain exact keys, view values and null targets."""
    require_unambiguous(readers)
    if not any('/Names' in reader.trailer['/Root'] for reader in readers):
        return
    pairs = ArrayObject()
    rows = [(key, None if page is None else mapping[page], view, wrapped)
            for reader, mapping in zip(readers, mappings)
            for key, page, view, wrapped in destinations(reader)
            if page is None or page in mapping]
    for key, page, view, wrapped in sorted(rows, key=lambda item: _key_bytes(item[0])):
        target = NullObject() if page is None else writer.pages[page].indirect_reference
        value = ArrayObject([target, *[item.clone(writer) for item in view]])
        if wrapped:
            value = DictionaryObject({NameObject("/D"): value})
        pairs.extend([key.clone(writer), value])
    writer.root_object[NameObject("/Names")] = DictionaryObject({
        NameObject("/Dests"): DictionaryObject({NameObject("/Names"): pairs})})


def validate(readers, output_reader, mappings):
    from .pageops import _semantic
    def rows(reader, mapping=None):
        return sorted([(_key_bytes(key), page if mapping is None or page is None else mapping[page],
                        _semantic(view), wrapped)
                       for key, page, view, wrapped in destinations(reader)
                       if mapping is None or page is None or page in mapping], key=lambda row: row[0])
    expected = [row for reader, mapping in zip(readers, mappings) for row in rows(reader, mapping)]
    if sorted(expected, key=lambda row: row[0]) != rows(output_reader):
        _fail("el guardado alteró destinos con nombre o sus coordenadas.")


def report(reader, mapping):
    values = destinations(reader)
    return {"before": len(values), "retained": sum(page is None or page in mapping for _, page, _, _ in values),
            "removed_with_pages": sum(page is not None and page not in mapping for _, page, _, _ in values),
            "preexisting_null_targets_preserved": sum(page is None for _, page, _, _ in values)}
