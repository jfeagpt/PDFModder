"""Explicit additions to a verified tagged PDF, with a planned structure snapshot.

Only new content streams are marked. Existing MCIDs, elements, attributes and
reading order survive; a new P/Figure is inserted at a chosen page boundary.
This preserves checked relationships, rather than certifying PDF/UA compliance.
"""
from io import BytesIO

from pypdf.generic import (ArrayObject, DictionaryObject, IndirectObject,
                          NameObject, NumberObject, TextStringObject)

from .tagged import Mark, analyze, fail, obj, ref, _number_tree


CONTAINERS = {'/Document', '/Part', '/Art', '/Sect', '/Div'}


def _dump(value):
    buffer = BytesIO()
    value.write_to_stream(buffer)
    return buffer.getvalue().decode('latin1')


def _children(value):
    value = obj(value)
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _parent_tree_copy(value):
    """Materialize tree dictionaries/arrays, retaining element references.

    A private replacement preserves the shape and all existing associations,
    including annotation keys, without changing a shared number-tree object.
    """
    source = obj(value)
    result = DictionaryObject(dict(source))
    if '/Kids' in source:
        result[NameObject('/Kids')] = ArrayObject(_parent_tree_copy(k) for k in obj(source['/Kids']))
    if '/Nums' in source:
        numbers = obj(source['/Nums'])
        copied = ArrayObject()
        for key, item in zip(numbers[::2], numbers[1::2]):
            resolved = obj(item)
            copied.extend([key, ArrayObject(resolved) if isinstance(resolved, (list, tuple)) else item])
        result[NameObject('/Nums')] = copied
    return result


def _set_parent_array(tree, key, value):
    numbers = tree.get('/Nums', [])
    for index in range(0, len(numbers), 2):
        if numbers[index] == key:
            numbers[index + 1] = value
            return True
    return any(_set_parent_array(child, key, value) for child in tree.get('/Kids', []))


def _append_parent_array(tree, key, value):
    if tree.get('/Kids'):
        _append_parent_array(tree['/Kids'][-1], key, value)
    else:
        tree.setdefault(NameObject('/Nums'), ArrayObject()).extend([NumberObject(key), value])
    if '/Limits' in tree:
        tree[NameObject('/Limits')] = ArrayObject([tree['/Limits'][0], NumberObject(key)])


class TaggedAddition:
    def __init__(self, data, page, role, order=None, *, alt_text=None, decorative=False, text=None):
        self.structure = analyze(data)
        self.page = page
        self.role = role
        self.order = order
        self.alt_text = alt_text
        self.decorative = decorative
        self.expected = None
        self.mcid = None
        if self.structure is None:
            return
        s = self.structure
        if not isinstance(page, int) or not 0 <= page < len(s.reader.pages):
            fail('la página seleccionada no existe.')
        if role not in ('/P', '/Figure'):
            fail('el tipo de contenido nuevo no está admitido.')
        if decorative and role != '/Figure':
            fail('sólo una imagen elegida explícitamente como decorativa puede ser artefacto.')
        if decorative:
            if alt_text and str(alt_text).strip():
                fail('una imagen decorativa no debe tener una descripción alternativa contradictoria.')
            self.expected = s.semantic()
            return
        if order not in ('page_start', 'page_end'):
            fail('elige si el contenido nuevo se leerá al inicio o al final de esta página.')
        if role == '/P' and (not isinstance(text, str) or not text.strip()):
            fail('escribe un párrafo para añadir al documento.')
        if role == '/P' and '\n' in text:
            fail('añade cada párrafo por separado para conservar su estructura de lectura. El ajuste automático de una línea sí está permitido.')
        if role == '/Figure':
            if not isinstance(alt_text, str) or not alt_text.strip():
                fail('describe la imagen con texto alternativo o elígela explícitamente como decorativa.')
            if len(alt_text) > 4000 or any(ord(c) < 32 for c in alt_text):
                fail('la descripción alternativa debe tener hasta 4000 caracteres y no contener controles.')
            self.alt_text = alt_text.strip()
        self.parent, self.index = self._boundary()

    def _boundary(self):
        """Find an exact reading-order page boundary inside a block container.

        Never insert paragraphs inside table rows/cells, spans or a paragraph
        that continues across pages merely because it is geometrically nearby.
        """
        s = self.structure
        # /OBJR-only nodes participate in order and may not be crossed.
        sequence = []
        def walk(value, inherited=None):
            value = obj(value)
            if isinstance(value, (list, tuple)):
                for child in value: walk(child, inherited)
            elif isinstance(value, int):
                if inherited in s.pages: sequence.append(s.pages[inherited])
            elif isinstance(value, dict):
                page = ref(value.get('/Pg')) or inherited
                if value.get('/Type') in ('/MCR', '/OBJR') or '/MCID' in value:
                    if page in s.pages: sequence.append(s.pages[page])
                else:
                    walk(value.get('/K', []), page)
        walk(s.tree.get('/K', []))
        if self.page not in sequence:
            # No existing reading content: place relative to the nearest page
            # only if a single document container gives an unambiguous order.
            fail('esta página no tiene una frontera de lectura verificable; no se asignan etiquetas automáticamente.')
        target = (sequence.index(self.page) if self.order == 'page_start'
                  else len(sequence) - list(reversed(sequence)).index(self.page))
        rolemap = obj(s.tree.get('/RoleMap', {}))
        candidates = []
        offset = 0
        def visit(value, inherited=None, depth=0):
            nonlocal offset
            value = obj(value)
            if isinstance(value, (list, tuple)):
                for child in value: visit(child, inherited, depth)
                return
            if isinstance(value, int):
                if inherited in s.pages: offset += 1
                return
            if not isinstance(value, dict): return
            page = ref(value.get('/Pg')) or inherited
            if value.get('/Type') in ('/MCR', '/OBJR') or '/MCID' in value:
                if page in s.pages: offset += 1
                return
            children = _children(value.get('/K', ArrayObject()))
            role = value.get('/S')
            seen = set()
            while role in rolemap and role not in seen:
                seen.add(role)
                role = rolemap[role]
            acceptable = role in CONTAINERS and not any(k in value for k in ('/ActualText', '/Alt', '/E', '/A', '/C'))
            for index, child in enumerate(children):
                if acceptable and offset == target: candidates.append((depth, value, index))
                visit(child, page, depth + 1)
            if acceptable and offset == target: candidates.append((depth, value, len(children)))
        visit(s.tree)
        if not candidates:
            fail('la frontera de lectura está dentro de un párrafo, una tabla o un grupo con significado propio; añade el contenido en otra página.')
        _, parent, index = max(candidates, key=lambda candidate: candidate[0])
        return parent, index

    def apply(self, doc, old_contents):
        """Mark only newly appended streams and update the planned logical tree."""
        s = self.structure
        if s is None:
            return None
        page = doc[self.page]
        contents = page.get_contents()
        if contents[:len(old_contents)] != list(old_contents) or len(contents) <= len(old_contents):
            fail('la inserción no conserva los flujos originales; operación cancelada.')
        prefix = b'/Artifact BMC\n'
        if not self.decorative:
            # Null slots are legitimate ParentTree entries. Leave them intact
            # and append after the full array, never reuse a historical slot.
            key = s.reader.pages[self.page].get('/StructParents')
            existing_owners = s.parents.get(key, [])
            mcid = max(max(s.marks[self.page], default=-1) + 1, len(existing_owners))
            self.mcid = mcid
            new_xref = doc.get_new_xref()
            node = DictionaryObject({NameObject('/Type'): NameObject('/StructElem'),
                NameObject('/S'): NameObject(self.role),
                NameObject('/P'): self.parent.indirect_reference,
                NameObject('/Pg'): s.reader.pages[self.page].indirect_reference,
                NameObject('/K'): NumberObject(mcid)})
            if self.role == '/Figure': node[NameObject('/Alt')] = TextStringObject(self.alt_text)
            # The reader is the original planning model. Registering the new
            # object here lets semantic() calculate shifted paths independently
            # of the full-write output and its rewritten xref numbers.
            s.reader.cache_indirect_object(0, new_xref, node)
            reference = IndirectObject(new_xref, 0, s.reader)
            doc.update_object(new_xref, _dump(node))
            kids = ArrayObject(_children(self.parent.get('/K', ArrayObject())))
            kids.insert(self.index, reference)
            self.parent[NameObject('/K')] = kids
            doc.xref_set_key(self.parent.indirect_reference.idnum, 'K', _dump(kids))
            parent_tree = _parent_tree_copy(s.tree['/ParentTree'])
            pdf_page = s.reader.pages[self.page]
            parent_key = pdf_page.get('/StructParents')
            if parent_key is None:
                parent_key = max(max(s.parents, default=-1) + 1, int(s.tree.get('/ParentTreeNextKey', 0)))
                pdf_page[NameObject('/StructParents')] = NumberObject(parent_key)
                doc.xref_set_key(page.xref, 'StructParents', str(parent_key))
                _append_parent_array(parent_tree, parent_key, ArrayObject([reference]))
                next_key = NumberObject(parent_key + 1)
                s.tree[NameObject('/ParentTreeNextKey')] = next_key
                doc.xref_set_key(ref(s.tree)[0], 'ParentTreeNextKey', str(next_key))
            else:
                owners = ArrayObject(s.parents.get(parent_key, []))
                if len(owners) != mcid:
                    fail('la matriz ParentTree no permite añadir un MCID consecutivo verificable.')
                owners.append(reference)
                if not _set_parent_array(parent_tree, parent_key, owners):
                    fail('la asociación ParentTree de esta página no existe.')
            s.tree[NameObject('/ParentTree')] = parent_tree
            doc.xref_set_key(ref(s.tree)[0], 'ParentTree', _dump(parent_tree))
            properties = DictionaryObject({NameObject('/MCID'): NumberObject(mcid)})
            s.marks[self.page][mcid] = Mark(mcid, NameObject(self.role), properties, properties, -1)
            s.parents = _number_tree(parent_tree)
            s.nodes, s.owners, s.object_owners = {}, {}, []
            s.node_refs = {ref(s.tree): ('tree',)}
            s._walk(s.tree.get('/K', []), (), ref(s.tree), None, 0)
            s.page_parent_keys[parent_key] = self.page
            s._validate_links()
            self.expected = s.semantic()
            prefix = (self.role + ' <</MCID ' + str(mcid) + '>> BDC\n').encode('ascii')
        opening, closing = doc.get_new_xref(), doc.get_new_xref()
        for xref, value in ((opening, prefix), (closing, b'EMC\n')):
            doc.update_object(xref, '<<>>')
            doc.update_stream(xref, value)
        result = [*old_contents, opening, *contents[len(old_contents):], closing]
        doc.xref_set_key(page.xref, 'Contents', '[' + ' '.join(f'{xref} 0 R' for xref in result) + ']')
        return self.expected

    def report(self):
        if self.structure is None: return None
        return {'verified': True, 'existing_structure_preserved': True,
                'reading_order': self.order if not self.decorative else None,
                'role': 'Artifact' if self.decorative else self.role[1:],
                'mcid': self.mcid, 'alt_text': self.alt_text,
                'scope': 'Relaciones y orden verificados; no certificación PDF/UA.'}
