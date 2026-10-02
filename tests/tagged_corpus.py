"""Synthetic logical-structure fixtures and a pypdf-only audit for their scope.

These files exercise tags; they do not claim PDF/UA certification. All visible
text uses Base-14 Helvetica, and the tiny RGB illustration is generated here.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image
import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, ByteStringObject, ContentStream,
    DecodedStreamObject, DictionaryObject, IndirectObject, NameObject,
    NumberObject, TextStringObject,
)


DATE_TEXT = "Fecha: 10/09/2026"
MOVE_TEXT = "Mover PALABRA fin."
CONTROL_TEXT = "PAGINA DE CONTROL 10/09/2026"
FIGURE_ALT = "Rectángulo azul de prueba, sin información adicional."
WORD_X = 48 + fitz.get_text_length("Mover ", fontname="helv", fontsize=12)


def dictionary(**items):
    return DictionaryObject({NameObject('/' + key): value for key, value in items.items()})


def _ref(value):
    return value.indirect_reference if not isinstance(value, IndirectObject) else value


def _key(value):
    ref = _ref(value)
    return ref.idnum, ref.generation


def _list(value):
    value = value.get_object() if hasattr(value, 'get_object') else value
    return list(value) if isinstance(value, (ArrayObject, list)) else [value]


def make_tagged_pdf(*, named_properties=False, mixed_styles=False, mcr_references=False, actual_text=None,
                    actual_on="content", include_objr=False, reverse_paint_order=False, defect=None):
    """Return a deterministic two-page test PDF without touching the filesystem.

    Base MCIDs: page 0 date paragraph=0, movement paragraph=1, figure=2;
    page 1 control paragraph=0. mixed_styles splits movement into 1/2/3 and
    moves figure to 4. The optional link follows the figure's MCID.
    Defects: duplicate_mcid, broken_parenttree, missing_parenttree,
    untagged_glyph, malformed_layer, unclosed_marked_content.
    actual_text describes the WHOLE visible date paragraph, including "Fecha: ".
    reverse_paint_order reverses page 0 streams but preserves its logical tree.
    """
    if actual_on not in ('content', 'structure', 'paragraph'):
        raise ValueError(actual_on)
    valid_defects = {None, 'duplicate_mcid', 'broken_parenttree', 'missing_parenttree',
                     'untagged_glyph', 'malformed_layer', 'unclosed_marked_content'}
    if defect not in valid_defects:
        raise ValueError(defect)
    source = fitz.open()
    first = source.new_page(width=420, height=420)
    # Two operators in one semantic paragraph, with a deliberate layout gap.
    first.insert_text((48, 100), "Fecha: ", fontname='helv', fontsize=12)
    first.insert_text((100, 100), "10/09/2026", fontname='helv', fontsize=12)
    first.insert_text((48, 150), "Mover ", fontname='helv', fontsize=12)
    first.insert_text((WORD_X, 150), "PALABRA", fontname='hebo' if mixed_styles else 'helv', fontsize=12)
    suffix_x = WORD_X + fitz.get_text_length('PALABRA', fontname='hebo' if mixed_styles else 'helv', fontsize=12)
    first.insert_text((suffix_x, 150), " fin.", fontname='helv', fontsize=12)
    png = BytesIO()
    Image.new('RGB', (16, 12), '#286c9e').save(png, format='PNG')
    first.insert_image((48, 210, 128, 270), stream=png.getvalue())
    if include_objr:
        first.insert_text((48, 310), 'Enlace de prueba', fontname='helv', fontsize=12)
        first.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(48, 298, 148, 313),
                           'uri': 'https://example.org/tagged-fixture'})
    if defect == 'untagged_glyph':
        first.insert_text((48, 350), 'SIN ETIQUETA', fontname='helv', fontsize=12)
    second = source.new_page(width=420, height=420)
    second.insert_text((48, 100), CONTROL_TEXT, fontname='helv', fontsize=12)
    second.draw_rect((48, 140, 360, 350), fill=(.94, .97, .99), color=(.2, .4, .6))
    source.set_metadata({'title': 'Corpus etiquetado PDF Modder', 'author': 'PDF Modder',
                         'creationDate': 'D:20260910090000Z', 'modDate': 'D:20260910090000Z'})
    initial = source.tobytes(garbage=3, deflate=False)
    source.close()
    writer = PdfWriter(clone_from=PdfReader(BytesIO(initial)))
    writer._ID = ArrayObject([ByteStringObject(b'PDFMODDER-TAG001'), ByteStringObject(b'PDFMODDER-TAG001')])
    catalog = writer._root_object
    catalog[NameObject('/Lang')] = TextStringObject('es-ES')
    catalog[NameObject('/MarkInfo')] = dictionary(Marked=BooleanObject(True))
    root = dictionary(Type=NameObject('/StructTreeRoot'))
    root_ref = writer._add_object(root)
    catalog[NameObject('/StructTreeRoot')] = root_ref
    root[NameObject('/RoleMap')] = dictionary(FixtureParagraph=NameObject('/P'))
    owner_arrays = [ArrayObject(), ArrayObject()]

    def element(role, parent, page=None, **attributes):
        node = dictionary(Type=NameObject('/StructElem'), S=NameObject('/'+role), P=parent)
        if page is not None:
            node[NameObject('/Pg')] = writer.pages[page].indirect_reference
        for key, value in attributes.items():
            node[NameObject('/'+key)] = TextStringObject(value)
        return writer._add_object(node)

    document = element('Document', root_ref, Lang='es-ES')
    root[NameObject('/K')] = document
    date_paragraph = element('FixtureParagraph', document, 0, Lang='es-ES')
    date_span = element('Span', date_paragraph, 0)
    date_span.get_object()[NameObject('/K')] = NumberObject(0)
    date_paragraph.get_object()[NameObject('/K')] = date_span
    owner_arrays[0].append(date_span)
    if actual_text is not None and actual_on in ('structure', 'paragraph'):
        holder = date_span if actual_on == 'structure' else date_paragraph
        holder.get_object()[NameObject('/ActualText')] = TextStringObject(actual_text)
    move_paragraph = element('P', document, 0)
    spans = []
    for mcid in (range(1, 4) if mixed_styles else [1]):
        span = element('Span', move_paragraph, 0)
        span.get_object()[NameObject('/K')] = NumberObject(mcid)
        spans.append(span)
        owner_arrays[0].append(span)
    move_paragraph.get_object()[NameObject('/K')] = ArrayObject(spans)
    figure_mcid = len(owner_arrays[0])
    figure = element('Figure', document, 0, Alt=FIGURE_ALT)
    figure.get_object()[NameObject('/K')] = NumberObject(figure_mcid)
    owner_arrays[0].append(figure)
    document_kids = [date_paragraph, move_paragraph, figure]
    link_mcid = figure_mcid + 1
    link = None
    if include_objr:
        link = element('Link', document, 0)
        annotation = writer.pages[0]['/Annots'][0]
        annotation.get_object()[NameObject('/StructParent')] = NumberObject(2)
        objr = dictionary(Type=NameObject('/OBJR'), Obj=annotation,
                          Pg=writer.pages[0].indirect_reference)
        link.get_object()[NameObject('/K')] = ArrayObject([NumberObject(link_mcid), objr])
        owner_arrays[0].append(link)
        document_kids.append(link)
    control = element('P', document, 1)
    control.get_object()[NameObject('/K')] = NumberObject(0)
    owner_arrays[1].append(control)
    document_kids.append(control)
    document.get_object()[NameObject('/K')] = ArrayObject(document_kids)
    if mcr_references:
        for page_number, owners in enumerate(owner_arrays):
            for mcid, owner in enumerate(owners):
                node = owner.get_object()
                old = node['/K']
                mcr = dictionary(Type=NameObject('/MCR'), MCID=NumberObject(mcid),
                                 Pg=writer.pages[page_number].indirect_reference)
                node[NameObject('/K')] = ArrayObject([mcr, *old[1:]]) if isinstance(old, ArrayObject) else mcr
    for number, page in enumerate(writer.pages):
        page[NameObject('/StructParents')] = NumberObject(number)
        page[NameObject('/Tabs')] = NameObject('/S')

    original_streams = [list(page['/Contents']) for page in writer.pages]

    def wrap(page_number, indices, mcid=None, role='Span', actual=None, artifact=False):
        page = writer.pages[page_number]
        operations = []
        if artifact:
            operations.append(([NameObject('/Artifact')], b'BMC'))
        else:
            properties = dictionary(MCID=NumberObject(mcid))
            if actual is not None:
                properties[NameObject('/ActualText')] = TextStringObject(actual)
            operand = properties
            if named_properties:
                resources = page['/Resources']
                if '/Properties' not in resources:
                    resources[NameObject('/Properties')] = DictionaryObject()
                operand = NameObject('/Tag'+str(mcid))
                resources['/Properties'][operand] = writer._add_object(properties)
            operations.append(([NameObject('/'+role), operand], b'BDC'))
        if defect == 'malformed_layer' and page_number == 0 and mcid == 0:
            operations.append(([NameObject('/OC'), NameObject('/MissingLayer')], b'BDC'))
        for index in indices:
            operations.extend(ContentStream(original_streams[page_number][index], writer).operations)
        if defect == 'malformed_layer' and page_number == 0 and mcid == 0:
            operations.append(([], b'EMC'))
        if not (defect == 'unclosed_marked_content' and page_number == 0 and mcid == 0):
            operations.append(([], b'EMC'))
        stream = ContentStream(None, writer)
        stream.operations = operations
        return writer._add_object(stream)

    page0_streams = [wrap(0, [0, 1], 0, actual=actual_text if actual_on == 'content' else None)]
    if mixed_styles:
        page0_streams.extend(wrap(0, [index], index-1) for index in (2, 3, 4))
    else:
        page0_streams.append(wrap(0, [2, 3, 4], 0 if defect == 'duplicate_mcid' else 1))
    page0_streams.append(wrap(0, [5], figure_mcid, role='Figure'))
    if include_objr:
        page0_streams.append(wrap(0, [6], link_mcid, role='Link'))
    if defect == 'untagged_glyph':
        page0_streams.append(original_streams[0][-1])
    if reverse_paint_order:
        page0_streams.reverse()
    writer.pages[0][NameObject('/Contents')] = ArrayObject(page0_streams)
    writer.pages[1][NameObject('/Contents')] = ArrayObject([wrap(1, [0], 0, role='P'), wrap(1, [1], artifact=True)])
    if defect == 'broken_parenttree':
        owner_arrays[0][0] = figure
    nums = ArrayObject([NumberObject(0), owner_arrays[0], NumberObject(1), owner_arrays[1]])
    if include_objr:
        nums.extend([NumberObject(2), link])
    if defect != 'missing_parenttree':
        root[NameObject('/ParentTree')] = writer._add_object(dictionary(Nums=nums))
    root[NameObject('/ParentTreeNextKey')] = NumberObject(3 if include_objr else 2)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def audit_tagged(data):
    """Audit fixture scope via pypdf only, preserving logical rather than paint order.

    Checks reverse ParentTree ownership, MCID uniqueness/coverage, parent links,
    inherited page references, role mapping, language, Alt and OBJR associations.
    Text decoding is deliberately limited to this corpus's simple WinAnsi fonts.
    """
    reader = PdfReader(BytesIO(data), strict=True)
    catalog = reader.trailer['/Root']
    root_ref = catalog.raw_get('/StructTreeRoot')
    root = root_ref.get_object()
    page_numbers = {_key(page): n for n, page in enumerate(reader.pages)}
    content, content_actual, occurrences = {}, {}, {}
    for number, page in enumerate(reader.pages):
        stack = []
        for operands, operator in ContentStream(page.get_contents(), reader).operations:
            if operator in (b'BDC', b'BMC'):
                tag = str(operands[0])
                properties = operands[1] if operator == b'BDC' else {}
                if isinstance(properties, NameObject):
                    properties = page['/Resources']['/Properties'][properties]
                properties = properties.get_object() if hasattr(properties, 'get_object') else properties
                assert tag != '/OC', 'Capa no admitida por el corpus'
                mcid = properties.get('/MCID')
                key = (number, int(mcid)) if mcid is not None else None
                stack.append((tag, key))
                if key is not None:
                    occurrences[key] = occurrences.get(key, 0) + 1
                    assert occurrences[key] == 1, 'MCID duplicado'
                    content[key] = ''
                    if '/ActualText' in properties:
                        content_actual[key] = str(properties['/ActualText'])
            elif operator == b'EMC':
                assert stack, 'EMC sin apertura'
                stack.pop()
            elif operator in (b'Tj', b'TJ', b"'", b'"'):
                parts = operands[0] if operator == b'TJ' else [operands[-1]]
                shown = ''.join(bytes(value).decode('cp1252') if isinstance(value, ByteStringObject) else str(value)
                                for value in parts if isinstance(value, (TextStringObject, ByteStringObject)))
                if shown:
                    mcids = [key for _, key in stack if key is not None]
                    assert mcids or any(tag == '/Artifact' for tag, _ in stack), 'Texto sin etiqueta'
                    if mcids:
                        content[mcids[-1]] += shown
        assert not stack, 'Contenido marcado sin cerrar'

    owner_paths, forward, objrs = {}, {}, []
    rolemap = {str(k): str(v) for k, v in root.get('/RoleMap', {}).items()}

    def visit(ref, parent_ref, path, inherited_page=None):
        node = ref.get_object()
        assert node.get('/Type') == '/StructElem'
        assert _key(node.raw_get('/P')) == _key(parent_ref), 'Padre estructural incorrecto'
        owner_paths[_key(ref)] = path
        page_number = page_numbers[_key(node.raw_get('/Pg'))] if '/Pg' in node else inherited_page
        result = {key: str(node[key]) for key in ('/S', '/Lang', '/Alt', '/ActualText') if key in node}
        result['role'] = rolemap.get(result['/S'], result['/S'])
        result['kids'] = []
        logical = []
        for index, child in enumerate(_list(node.get('/K', []))):
            value = child.get_object() if hasattr(child, 'get_object') else child
            if isinstance(value, int):
                key = (page_number, int(value))
                assert key in content and key not in forward, 'MCID perdido o estructura duplicada'
                forward[key] = path
                result['kids'].append(('mcid', *key))
                logical.append(content_actual.get(key, content[key]))
            elif isinstance(value, dict) and value.get('/Type') == '/MCR':
                key = (page_numbers[_key(value.raw_get('/Pg'))] if '/Pg' in value else page_number, int(value['/MCID']))
                assert key in content and key not in forward
                forward[key] = path
                result['kids'].append(('mcid', *key))
                logical.append(content_actual.get(key, content[key]))
            elif isinstance(value, dict) and value.get('/Type') == '/OBJR':
                annotation = value['/Obj']
                objrs.append((int(annotation['/StructParent']), path))
                result['kids'].append(('objr', page_number, str(annotation['/Subtype']),
                                       str(annotation.get('/A', {}).get('/URI', ''))))
            else:
                child_result, child_text = visit(child, ref, path+'/'+str(index), page_number)
                result['kids'].append(child_result)
                logical.append(child_text)
        if '/ActualText' in node:
            logical = [str(node['/ActualText'])]
        if result['role'] == '/Figure':
            assert '/Alt' in node
            logical = ['[Imagen: '+str(node['/Alt'])+']']
        return result, ''.join(logical)

    structures, reading = [], []
    for index, child in enumerate(_list(root['/K'])):
        structure, text = visit(child, root_ref, str(index))
        structures.append(structure)
        reading.append(text)
    assert set(forward) == set(content), 'MCID visible sin propietario estructural'
    parent_numbers = {}

    def number_tree(value):
        value = value.get_object()
        nums = value.get('/Nums', [])
        assert len(nums) % 2 == 0
        for i in range(0, len(nums), 2):
            assert int(nums[i]) not in parent_numbers
            parent_numbers[int(nums[i])] = nums[i+1].get_object()
        for kid in value.get('/Kids', []):
            number_tree(kid)

    number_tree(root['/ParentTree'])
    reverse = {}
    for (page_number, mcid), path in forward.items():
        array = parent_numbers[int(reader.pages[page_number]['/StructParents'])]
        assert mcid < len(array) and owner_paths[_key(array[mcid])] == path, 'ParentTree roto'
        reverse[(page_number, mcid)] = path
    for key, path in objrs:
        assert owner_paths[_key(parent_numbers[key])] == path, 'ParentTree de OBJR roto'
    return {'lang': str(catalog.get('/Lang', '')), 'rolemap': rolemap,
            'marked': bool(catalog['/MarkInfo']['/Marked']),
            'struct_parents': tuple(int(page['/StructParents']) for page in reader.pages),
            'parent_tree_next_key': int(root['/ParentTreeNextKey']),
            'structure': structures, 'content': content, 'actual_text': content_actual,
            'parent_tree': reverse, 'objrs': objrs, 'reading_order': ''.join(reading)}
