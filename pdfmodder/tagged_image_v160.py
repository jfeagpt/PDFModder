"""Preserve semantics when transforming one independently tagged image instance."""
from pypdf.generic import ContentStream

from .tagged import PAINT, SHOW, analyze, assert_structure, fail, obj, _has_string


class TaggedImageTransform:
    def __init__(self, data, page, item, *, structure=None):
        self.data = data
        self.structure = structure if structure is not None else analyze(data)
        self.page = page
        self.mcid = None
        if self.structure is None:
            return
        s = self.structure
        contents = obj(s.reader.pages[page].get('/Contents', []))
        contents = contents if isinstance(contents, (list, tuple)) else [contents]
        offset = sum(len(ContentStream(content, s.reader).operations)
                     for content in contents[:item['stream_position']]) + item['do_index']
        ops = s.operations[page]
        if offset >= len(ops) or ops[offset][1] != b'Do':
            fail('no se puede asociar la imagen seleccionada con su etiqueta.')
        stack = []
        resources = obj(s.reader.pages[page].get('/Resources', {}))
        properties = obj(resources.get('/Properties', {}))
        for args, operator in ops[:offset+1]:
            if operator in (b'BMC', b'BDC'):
                prop = args[1] if operator == b'BDC' else {}
                prop = obj(properties.get(prop)) if isinstance(prop, str) else obj(prop)
                stack.append((str(args[0]), prop or {}))
            elif operator == b'EMC':
                stack.pop()
        if any('/BBox' in prop for _, prop in stack):
            fail('la imagen tiene una caja semántica que requiere actualizar su geometría.')
        self.mcid = s.contexts[page][offset]
        if self.mcid is None:
            if not any(tag == '/Artifact' for tag, _ in stack):
                fail('la imagen no tiene una etiqueta de figura ni una marca decorativa.')
            return
        mark = s.marks[page][self.mcid]
        selected_ops = ops[mark.start:mark.end+1]
        if (sum(operator in PAINT for _, operator in selected_ops) != 1
                or any(operator in SHOW and _has_string(args) for args, operator in selected_ops)):
            fail('la etiqueta reúne la imagen con otros contenidos; no se modifica su distribución.')
        owner = s.owners[(page, self.mcid)]
        ancestors = [node for path, node in s.nodes.items() if owner[:len(path)] == path]
        if any(node.get('/A') or node.get('/C') for node in ancestors):
            fail('la imagen tiene atributos de disposición o clases que necesitan actualizar su geometría.')
        rolemap = obj(s.tree.get('/RoleMap', {}))
        figure = False
        for node in ancestors:
            role, seen = node.get('/S'), set()
            while role in rolemap and role not in seen:
                seen.add(role); role = rolemap[role]
            if role == '/Figure' and str(node.get('/Alt', '')).strip():
                figure = True
        if not figure:
            fail('la imagen necesita una etiqueta Figure con descripción alternativa verificable.')

    def validate(self, output):
        current = assert_structure(self.data, output)
        if self.structure is None:
            return None
        def associations(structure):
            return [[(context, str(args[0])) for (args, operator), context in zip(ops, contexts)
                     if operator == b'Do']
                    for ops, contexts in zip(structure.operations, structure.contexts)]
        if associations(self.structure) != associations(current):
            fail('se alteró la asociación de una imagen con su etiqueta u orden de lectura.')
        return {'verified': True, 'structure_preserved': True, 'reading_order_preserved': True,
                'mcid': self.mcid, 'artifact_preserved': self.mcid is None,
                'scope': 'Figure/Alt o Artifact, MCID y ParentTree conservados; no certificación PDF/UA.'}
