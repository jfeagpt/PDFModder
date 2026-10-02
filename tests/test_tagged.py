"""Tagged-text acceptance: logical structure is checked independently with pypdf."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, FloatObject, NameObject, TextStringObject
import pytest

from pdfmodder.engine import atomic_save, edit_pdf
from pdfmodder.model import EditError, union
from tagged_corpus import (
    CONTROL_TEXT, DATE_TEXT, FIGURE_ALT, MOVE_TEXT, WORD_X,
    audit_tagged, dictionary, make_tagged_pdf,
)
from test_engine import (
    assert_moved_once, assert_unchanged_neighbours, request_for, select,
)


def assert_structure_preserved(before, after):
    old, new = audit_tagged(before), audit_tagged(after)
    for key in ('lang', 'marked', 'rolemap', 'structure', 'struct_parents',
                'parent_tree_next_key', 'parent_tree', 'objrs'):
        assert old[key] == new[key], f'Estructura accesible alterada: {key}'
    return old, new


def assert_control_page_unchanged(before, after):
    with fitz.open(stream=before, filetype='pdf') as a, fitz.open(stream=after, filetype='pdf') as b:
        assert len(a) == len(b) == 2
        assert a[1].get_texttrace() == b[1].get_texttrace()
        assert tuple(a[1].rect) == tuple(b[1].rect)
        assert a[1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).samples == b[1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).samples
    assert PdfReader(BytesIO(before)).pages[1].extract_text() == PdfReader(BytesIO(after)).pages[1].extract_text()


@pytest.mark.parametrize('options', [{}, {'named_properties': True}, {'mcr_references': True},
                                    {'named_properties': True, 'mixed_styles': True, 'include_objr': True}])
def test_fixture_is_reproducible_and_has_independent_logical_order(options):
    data = make_tagged_pdf(**options)
    assert data == make_tagged_pdf(**options)
    audit = audit_tagged(data)
    expected = DATE_TEXT + MOVE_TEXT + '[Imagen: '+FIGURE_ALT+']'
    if options.get('include_objr'):
        expected += 'Enlace de prueba'
        assert len(audit['objrs']) == 1
    assert audit['reading_order'] == expected + CONTROL_TEXT
    assert audit['lang'] == 'es-ES' and audit['marked']
    assert audit['rolemap'] == {'/FixtureParagraph': '/P'}


@pytest.mark.parametrize('options', [{}, {'named_properties': True}, {'mcr_references': True}])
def test_date_edit_preserves_structure_neighbours_and_control_page(options):
    source = make_tagged_pdf(**options, include_objr=True)
    original_hash = sha256(source).hexdigest()
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    output, report = edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    old, new = assert_structure_preserved(source, output)
    assert new['reading_order'] == old['reading_order'].replace(DATE_TEXT, 'Fecha: 11/09/2026', 1)
    assert new['content'][(0, 0)] == 'Fecha: 11/09/2026'
    assert new['content'][(1, 0)] == CONTROL_TEXT
    assert '11/09/2026' in PdfReader(BytesIO(output), strict=True).pages[0].extract_text()
    assert report['verified']
    select(output, '11/09/2026', x=100, y=100)
    assert_unchanged_neighbours(source, output, chosen)
    assert_control_page_unchanged(source, output)
    assert sha256(source).hexdigest() == original_hash


@pytest.mark.parametrize('mixed', [False, True])
def test_move_word_keeps_logical_order_and_single_occurrence(mixed):
    source = make_tagged_pdf(named_properties=True, mixed_styles=mixed)
    model, chosen = select(source, 'PALABRA', x=WORD_X, y=150)
    output, report = edit_pdf(source, request_for(model, chosen, dx=25, dy=20))
    old, new = assert_structure_preserved(source, output)
    assert new['reading_order'] == old['reading_order']
    assert new['content'] == old['content']
    assert_moved_once(source, output, chosen, 25, 20)
    assert_unchanged_neighbours(source, output, chosen)
    assert_control_page_unchanged(source, output)
    assert report['verified']


def test_mixed_mcids_can_move_together_but_replacement_is_explicitly_blocked():
    source = make_tagged_pdf(mixed_styles=True)
    model, chosen = select(source, MOVE_TEXT, x=48, y=150)
    assert len({g.font for g in chosen}) == 2
    output, _ = edit_pdf(source, request_for(model, chosen, dx=8, dy=25))
    old, new = assert_structure_preserved(source, output)
    assert new['reading_order'] == old['reading_order']
    assert_moved_once(source, output, chosen, 8, 25)
    with pytest.raises(EditError, match=r'(?i)MCID|semántic|varios.*estilo|mezcla.*estilo'):
        edit_pdf(source, request_for(model, chosen, text='Cambiar todo el párrafo', width=300))


@pytest.mark.parametrize('where', ['content', 'structure', 'paragraph'])
def test_actualtext_matching_visible_paragraph_is_updated(where):
    source = make_tagged_pdf(named_properties=True, actual_text=DATE_TEXT, actual_on=where)
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    output, _ = edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    old, new = audit_tagged(source), audit_tagged(output)
    assert new['reading_order'] == old['reading_order'].replace(DATE_TEXT, 'Fecha: 11/09/2026', 1)
    assert new['content'][(0, 0)] == 'Fecha: 11/09/2026'

    def updated(value):
        if isinstance(value, dict):
            return {key: ('Fecha: 11/09/2026' if key == '/ActualText' else updated(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [updated(item) for item in value]
        return value

    assert new['structure'] == updated(deepcopy(old['structure']))
    assert new['parent_tree'] == old['parent_tree']
    if where == 'content':
        assert new['actual_text'] == {(0, 0): 'Fecha: 11/09/2026'}
    assert_control_page_unchanged(source, output)


@pytest.mark.parametrize('where', ['content', 'structure', 'paragraph'])
def test_semantic_actualtext_is_blocked_instead_of_becoming_stale(where):
    source = make_tagged_pdf(actual_text='Fecha diez de septiembre de dos mil veintiséis', actual_on=where)
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)ActualText|texto alternativo|semántic'):
        edit_pdf(source, request_for(model, chosen, text='11/09/2026'))


@pytest.mark.parametrize('defect', ['duplicate_mcid', 'broken_parenttree', 'missing_parenttree',
                                   'untagged_glyph', 'malformed_layer', 'unclosed_marked_content'])
def test_invalid_tagged_constructions_block_before_modifying_bytes(defect):
    source = make_tagged_pdf(defect=defect)
    original_hash = sha256(source).hexdigest()
    with pytest.raises((AssertionError, KeyError, IndexError)):
        audit_tagged(source)
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)MCID|ParentTree|etiquet|marcad|capa|estructura|semántic'):
        edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    assert sha256(source).hexdigest() == original_hash


def test_save_reopen_and_second_edit_keep_tags_and_original_file(tmp_path):
    source = make_tagged_pdf(named_properties=True, include_objr=True)
    original = tmp_path / 'original-etiquetado.pdf'
    original.write_bytes(source)
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    changed, _ = edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    destination = tmp_path / 'editado-etiquetado.pdf'
    atomic_save(changed, destination, original)
    reopened = destination.read_bytes()
    assert audit_tagged(reopened) == audit_tagged(changed)
    model, chosen = select(reopened, '11/09/2026', x=100, y=100)
    edited_again, _ = edit_pdf(reopened, request_for(model, chosen, text='12/09/2026'))
    assert audit_tagged(edited_again)['content'][(0, 0)] == 'Fecha: 12/09/2026'
    assert_structure_preserved(source, edited_again)
    assert_control_page_unchanged(source, edited_again)
    assert original.read_bytes() == source


@pytest.mark.parametrize('kind', ['encryption', 'form', 'signature'])
def test_tagged_support_does_not_disable_existing_document_protections(kind):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    if kind == 'encryption':
        writer.encrypt('', 'propietario-pruebas')
    elif kind == 'form':
        field = writer._add_object(dictionary(FT=NameObject('/Tx'), T=TextStringObject('CampoPrueba'), V=TextStringObject('valor')))
        writer._root_object[NameObject('/AcroForm')] = writer._add_object(dictionary(Fields=ArrayObject([field])))
    else:
        # An invalid marker tests conservative detection, not cryptographic validity.
        marker = writer._add_object(dictionary(Type=NameObject('/Sig')))
        writer._root_object[NameObject('/Perms')] = dictionary(DocMDP=marker)
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)cifrad|formulario|firma|certificad|permiso'):
        edit_pdf(source, request_for(model, chosen, text='11/09/2026'))


def test_tagged_line_reflow_retains_neighbour_owners_styles_and_second_edit():
    source = make_tagged_pdf(mixed_styles=True, named_properties=True)
    original_model, original_line = select(source, MOVE_TEXT, x=48, y=150)
    original_edges = union(g.bbox for g in original_line)
    model, chosen = select(source, 'PALABRA', x=WORD_X, y=150)
    changed, report = edit_pdf(source, request_for(model, chosen, text='VOZ', line_reflow=True))
    old, new = assert_structure_preserved(source, changed)
    assert report['line_reflow']
    assert new['content'][(0, 1)] == old['content'][(0, 1)] == 'Mover '
    assert new['content'][(0, 2)] == 'VOZ'
    assert new['content'][(0, 3)] == old['content'][(0, 3)] == ' fin.'
    assert new['reading_order'] == old['reading_order'].replace(MOVE_TEXT, 'Mover VOZ fin.')
    model, chosen = select(changed, 'VOZ', y=150)
    assert {g.font for g in chosen} == {'Helvetica-Bold'}
    again, second_report = edit_pdf(changed, request_for(model, chosen, text='CANTO', line_reflow=True))
    _, final = assert_structure_preserved(source, again)
    assert second_report['line_reflow']
    assert final['content'][(0, 2)] == 'CANTO'
    assert final['content'][(0, 1)] == 'Mover ' and final['content'][(0, 3)] == ' fin.'
    assert final['reading_order'] == old['reading_order'].replace(MOVE_TEXT, 'Mover CANTO fin.')
    _, new_line = select(again, 'Mover CANTO fin.', x=48, y=150)
    new_edges = union(g.bbox for g in new_line)
    assert new_edges[0] == pytest.approx(original_edges[0], abs=.035)
    assert new_edges[2] == pytest.approx(original_edges[2], abs=.035)
    for token in ('Mover', 'fin.'):
        _, before = select(source, token, y=150)
        _, after = select(again, token, y=150)
        assert len(before) == len(after)
        for a, b in zip(before, after):
            assert (a.font, a.size, a.color, a.opacity, a.origin[1]) == (b.font, b.size, b.color, b.opacity, b.origin[1])
            assert b.origin[0]-after[0].origin[0] == pytest.approx(a.origin[0]-before[0].origin[0], abs=.035)
    assert_control_page_unchanged(source, again)


def test_named_actualtext_does_not_leave_an_unused_stale_resource():
    source = make_tagged_pdf(named_properties=True, actual_text=DATE_TEXT)
    before = PdfReader(BytesIO(source), strict=True)
    properties = before.pages[0]['/Resources']['/Properties']
    assert properties['/Tag0']['/ActualText'] == DATE_TEXT
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    output, _ = edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    after = PdfReader(BytesIO(output), strict=True)
    properties = after.pages[0]['/Resources'].get('/Properties', {}).get_object()
    assert all(str(value.get_object().get('/ActualText', '')) != DATE_TEXT for value in properties.values())
    assert audit_tagged(output)['actual_text'] == {(0, 0): 'Fecha: 11/09/2026'}
    before_second = before.pages[1]['/Resources']['/Properties']['/Tag0']
    after_second = after.pages[1]['/Resources']['/Properties']['/Tag0']
    assert dict(before_second) == dict(after_second), 'Se modificaron recursos de la página de control'


def test_logical_order_different_from_paint_order_survives_edit_and_move():
    source = make_tagged_pdf(named_properties=True, reverse_paint_order=True)
    audit = audit_tagged(source)
    assert list(audit['content'])[:3] == [(0, 2), (0, 1), (0, 0)]
    assert audit['reading_order'].startswith(DATE_TEXT+MOVE_TEXT)
    assert PdfReader(BytesIO(source)).pages[0].extract_text().startswith(MOVE_TEXT)
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    output, _ = edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    model, chosen = select(output, 'PALABRA', x=WORD_X, y=150)
    moved, _ = edit_pdf(output, request_for(model, chosen, dx=20, dy=25))
    old, new = assert_structure_preserved(source, moved)
    assert new['reading_order'] == old['reading_order'].replace(DATE_TEXT, 'Fecha: 11/09/2026', 1)
    assert new['content'][(0, 1)] == MOVE_TEXT
    assert_moved_once(output, moved, chosen, 20, 25)
    assert_control_page_unchanged(source, moved)


def test_layout_bbox_blocks_only_its_affected_structural_element():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    paragraph = writer._root_object['/StructTreeRoot']['/K']['/K'][0].get_object()
    paragraph[NameObject('/A')] = dictionary(O=NameObject('/Layout'),
                                            BBox=ArrayObject([FloatObject(v) for v in (48, 316, 167, 333)]))
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    original_hash = sha256(source).hexdigest()
    audit_tagged(source)
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)atributos.*disposición|BBox'):
        edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    assert sha256(source).hexdigest() == original_hash
    model, chosen = select(source, 'PALABRA', x=WORD_X, y=150)
    output, _ = edit_pdf(source, request_for(model, chosen, dx=20, dy=20))
    after = PdfReader(BytesIO(output), strict=True)
    after_attributes = after.trailer['/Root']['/StructTreeRoot']['/K']['/K'][0]['/A']
    assert after_attributes == paragraph['/A']
    assert_structure_preserved(source, output)


@pytest.mark.parametrize('operation', ['text', 'image_add', 'image_delete', 'image_transform',
                                      'pages_merge'])
def test_tagged_operations_without_semantic_choices_have_specific_blocks(operation):
    from pdfmodder.composition import AddTextRequest, insert_text_pdf
    from pdfmodder.media import add_image_pdf, delete_image_pdf, transform_image_pdf
    from pdfmodder.pageops import delete_pages_pdf, extract_pages_pdf, merge_pdfs
    from pdfmodder.validation import document_issues

    source = make_tagged_pdf()
    original_hash = sha256(source).hexdigest()
    with fitz.open(stream=source, filetype='pdf') as pdf:
        assert document_issues(source, pdf) == [], 'El documento válido no debe quedar bloqueado globalmente'
        image = pdf.extract_image(pdf[0].get_images()[0][0])['image']
    operations = {
        'text': lambda: insert_text_pdf(source, AddTextRequest(0, 48, 350, 200, 25, 'Texto nuevo')),
        'image_add': lambda: add_image_pdf(source, 0, image, (160, 210, 240, 270)),
        'image_delete': lambda: delete_image_pdf(source, 0, '0'),
        'image_transform': lambda: transform_image_pdf(source, 0, '0', (160, 210, 240, 270)),
        'pages_delete': lambda: delete_pages_pdf(source, [1]),
        'pages_extract': lambda: extract_pages_pdf(source, [1]),
        'pages_merge': lambda: merge_pdfs(source, [source]),
    }
    with pytest.raises(EditError, match=r'(?i)etiquetado:.*(?:(?:asignar|remapear).*etiquetas|fusionar.*accesibilidad|orden de lectura|descripci[oó]n)'):
        operations[operation]()
    assert sha256(source).hexdigest() == original_hash
    assert audit_tagged(source)['reading_order'].startswith(DATE_TEXT+MOVE_TEXT)


def test_text_paragraph_alt_requires_manual_semantics_for_replacement_but_allows_movement():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    paragraph = writer._root_object['/StructTreeRoot']['/K']['/K'][0].get_object()
    alternative = 'Fecha de emisión expresada en números.'
    paragraph[NameObject('/Alt')] = TextStringObject(alternative)
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    original_hash = sha256(source).hexdigest()
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)Alt|alternativo|semántic'):
        edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    moved, _ = edit_pdf(source, request_for(model, chosen, dx=0, dy=20))
    before, after = assert_structure_preserved(source, moved)
    assert before['reading_order'] == after['reading_order']
    reader = PdfReader(BytesIO(moved), strict=True)
    children = reader.trailer['/Root']['/StructTreeRoot']['/K']['/K']
    assert children[0]['/Alt'] == alternative
    assert children[2]['/Alt'] == FIGURE_ALT
    assert_moved_once(source, moved, chosen, 0, 20)
    assert_unchanged_neighbours(source, moved, chosen)
    assert sha256(source).hexdigest() == original_hash


def test_actualtext_wrapper_without_mcid_blocks_reconstruction_of_nested_date():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    page = writer.pages[0]
    date_stream = ContentStream(page['/Contents'][0], writer)
    date_stream.operations = [([NameObject('/Span'), dictionary(ActualText=TextStringObject(DATE_TEXT))], b'BDC'),
                              *date_stream.operations, ([], b'EMC')]
    page['/Contents'][0] = writer._add_object(date_stream)
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    original_hash = sha256(source).hexdigest()
    model, chosen = select(source, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)propiedades semánticas anidadas'):
        edit_pdf(source, request_for(model, chosen, text='11/09/2026'))
    assert sha256(source).hexdigest() == original_hash
