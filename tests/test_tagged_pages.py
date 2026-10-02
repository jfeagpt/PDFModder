"""Page structure projection, actual rendering, links and editable reopened text."""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject, TextStringObject
import pytest

from pdfmodder.engine import edit_pdf
from pdfmodder.model import EditError
from pdfmodder.pageops import delete_pages_pdf, extract_pages_pdf, organize_pages_pdf, merge_pdfs
from pdfmodder.tagged import analyze, ref, obj
from pdfmodder.tagged_pages import page_capabilities
from tagged_corpus import make_tagged_pdf, audit_tagged, dictionary, CONTROL_TEXT, DATE_TEXT, FIGURE_ALT
from test_engine import select, request_for


def rewritten(writer):
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def assert_exact_pages(before, after, assignment):
    with fitz.open(stream=before, filetype='pdf') as original, fitz.open(stream=after, filetype='pdf') as copied:
        assert len(copied) == len(assignment)
        for new, old in enumerate(assignment):
            assert copied[new].read_contents() == original[old].read_contents()
            assert copied[new].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).samples == original[old].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).samples
            assert copied[new].get_texttrace() == original[old].get_texttrace()
    a, b = PdfReader(BytesIO(before)), PdfReader(BytesIO(after))
    assert [a.pages[n].extract_text() for n in assignment] == [p.extract_text() for p in b.pages]


@pytest.mark.parametrize('options', [dict(), dict(named_properties=True), dict(mcr_references=True), dict(include_objr=True, mixed_styles=True, actual_text=DATE_TEXT, actual_on='paragraph')])
def test_delete_second_page_keeps_exact_first_page_tags_and_accessible_text(options):
    source = make_tagged_pdf(**options)
    digest = sha256(source).hexdigest()
    output, report = delete_pages_pdf(source, [1])
    before, after = audit_tagged(source), audit_tagged(output)
    assert after['reading_order'] == before['reading_order'].removesuffix(CONTROL_TEXT)
    assert all(page == 0 for page, _ in after['content'])
    assert report['tagged_structure']['verified']
    assert all(p['max_channel_delta'] == 0 and p['pixels_above_8'] == 0 for p in report['pages'])
    assert_exact_pages(source, output, [0])
    assert sha256(source).hexdigest() == digest
    assert analyze(output).reader.trailer['/Root']['/MarkInfo']['/Marked']


def test_extract_second_page_removes_old_objr_alt_and_parent_tree_associations():
    source = make_tagged_pdf(include_objr=True)
    output, report = extract_pages_pdf(source, [1])
    after = audit_tagged(output)
    assert after['reading_order'] == CONTROL_TEXT and after['objrs'] == []
    structure = analyze(output)
    assert sorted(structure.parents) == [1]
    assert structure.reader.pages[0]['/StructParents'] == 1
    assert not any(node.get('/Alt') == FIGURE_ALT for node in structure.nodes.values())
    assert_exact_pages(source, output, [1])
    assert all(p['max_channel_delta'] == 0 for p in report['pages'])


def test_reorder_updates_reading_order_and_objr_page_ownership():
    source = make_tagged_pdf(include_objr=True, mcr_references=True)
    output, report = extract_pages_pdf(source, [1, 0])
    before, after = audit_tagged(source), audit_tagged(output)
    assert after['reading_order'] == CONTROL_TEXT + before['reading_order'].removesuffix(CONTROL_TEXT)
    structure = analyze(output)
    assert {structure.annotations[target][0] for target, _ in structure.object_owners} == {1}
    assert_exact_pages(source, output, [1, 0])
    assert report['page_map'] == [1, 0]


def test_shipped_tagged_fixture_organizes_without_losing_accessibility():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'examples' / 'etiquetado.pdf').read_bytes()
    before = analyze(source)
    result, report = organize_pages_pdf(source, [dict(source='current', page=n) for n in reversed(range(len(before.reader.pages)))])
    after = analyze(result)
    assert len(after.nodes) == len(before.nodes)
    assert len(after.owners) == len(before.owners)
    assert len(after.object_owners) == len(before.object_owners)
    assert after.root['/MarkInfo'] == before.root['/MarkInfo']
    assert report['tagged_structure']['verified']
    assert_exact_pages(source, result, list(reversed(range(len(before.reader.pages)))))


def test_extract_save_reopen_then_edit_text_preserves_remapped_structure(tmp_path):
    source = make_tagged_pdf(include_objr=True)
    output, _ = extract_pages_pdf(source, [0])
    path = tmp_path / 'extraido.pdf'
    path.write_bytes(output)
    model, chosen = select(path.read_bytes(), '10/09/2026', x=100, y=100)
    changed, report = edit_pdf(output, request_for(model, chosen, text='11/09/2026'))
    assert report['verified']
    assert 'Fecha: 11/09/2026' in audit_tagged(changed)['reading_order']
    assert analyze(changed).semantic()['pages'] == analyze(output).semantic()['pages']
    assert analyze(changed).semantic()['tree'] == analyze(output).semantic()['tree']


def test_organizer_reorders_rotates_and_inserts_truly_blank_page():
    source = make_tagged_pdf(include_objr=True)
    plan = [dict(source='current', page=1, rotation=90), dict(source='blank', width=420, height=420), dict(source='current', page=0, rotation=270)]
    result, report = organize_pages_pdf(source, plan)
    after = analyze(result)
    assert len(after.reader.pages) == 3
    assert after.reader.pages[0].rotation == 90 and after.reader.pages[2].rotation == 270
    assert len(after.marks[1]) == 0 and '/StructParents' not in after.reader.pages[1]
    assert all(p['max_channel_delta'] == 0 for p in report['pages'])
    first_owner = next(iter(after.owners))
    assert first_owner == (0, 0)
    assert after.reader.pages[0].extract_text().strip() == CONTROL_TEXT


@pytest.mark.parametrize('operation', ['duplicate', 'merge', 'insert_pdf'])
def test_unsupported_graph_duplication_or_merge_never_silently_strips_tags(operation):
    source = make_tagged_pdf()
    before = sha256(source).hexdigest()
    with pytest.raises(EditError, match='(?i)duplicar|combinar|insertar|fusionar'):
        if operation == 'duplicate':
            organize_pages_pdf(source, [dict(source='current', page=0), dict(source='current', page=0)])
        elif operation == 'merge':
            merge_pdfs(source, [source])
        else:
            organize_pages_pdf(source, [dict(source='current', page=0), dict(source='other', page=1)], {'other': source})
    assert sha256(source).hexdigest() == before


def test_capabilities_support_scoped_page_operations_and_retain_protections():
    caps = page_capabilities(make_tagged_pdf(include_objr=True))
    assert all(caps[k] for k in ('supported', 'delete', 'extract', 'reorder', 'rotate', 'insert_blank'))
    assert not caps['duplicate'] and not caps['insert_pdf']
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    writer.encrypt('', 'password-owner')
    assert not page_capabilities(rewritten(writer))['supported']


def test_idtree_prunes_deleted_ids_and_preserves_surviving_properties():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    root = writer.root_object['/StructTreeRoot']
    kids = root['/K']['/K']
    first, last = kids[0], kids[-1]
    first.get_object()[NameObject('/ID')] = TextStringObject('first')
    last.get_object()[NameObject('/ID')] = TextStringObject('last')
    root[NameObject('/IDTree')] = dictionary(Names=ArrayObject([TextStringObject('first'), first, TextStringObject('last'), last]))
    output, _ = extract_pages_pdf(rewritten(writer), [1])
    tree = PdfReader(BytesIO(output)).trailer['/Root']['/StructTreeRoot']
    assert list(tree['/IDTree']['/Names'][::2]) == ['last']
    assert tree['/IDTree']['/Names'][1].get_object()['/ID'] == 'last'


def test_reference_from_retained_element_to_removed_element_blocks():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    kids = writer.root_object['/StructTreeRoot']['/K']['/K']
    kids[0].get_object()[NameObject('/Ref')] = ArrayObject([kids[-1]])
    with pytest.raises(EditError, match='relación accesible.*excluido'):
        extract_pages_pdf(rewritten(writer), [0])


@pytest.mark.parametrize('key', ['/ActualText', '/Alt', '/E'])
def test_partial_cross_page_semantic_replacement_is_not_left_stale(key):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    writer.root_object['/StructTreeRoot']['/K'][NameObject(key)] = TextStringObject('Descripción de las dos páginas')
    with pytest.raises(EditError, match='ActualText, Alt o expansión'):
        extract_pages_pdf(rewritten(writer), [0])


def test_reordering_cross_page_actualtext_requires_semantic_revision():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    writer.root_object['/StructTreeRoot']['/K'][NameObject('/ActualText')] = TextStringObject('Descripción de las dos páginas en orden original')
    with pytest.raises(EditError, match='nuevo orden.*ActualText'):
        extract_pages_pdf(rewritten(writer), [1, 0])


def test_internal_links_remain_exact_and_excluded_target_is_blocked():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(include_objr=True))))
    link = writer.pages[0]['/Annots'][0].get_object()
    link[NameObject('/A')] = dictionary(S=NameObject('/GoTo'), D=ArrayObject([writer.pages[1].indirect_reference, NameObject('/XYZ'), NumberObject(30), NumberObject(300), NumberObject(0)]))
    source = rewritten(writer)
    result, _ = extract_pages_pdf(source, [1, 0])
    with fitz.open(stream=result, filetype='pdf') as doc:
        assert doc[1].get_links()[0]['page'] == 0
    assert audit_tagged(result)['objrs']
    with pytest.raises(EditError, match='enlace.*excluida'):
        extract_pages_pdf(source, [0])


@pytest.mark.parametrize('defect', ['duplicate_mcid', 'broken_parenttree', 'missing_parenttree', 'unclosed_marked_content'])
def test_malformed_structure_blocks_before_touching_original(defect):
    source = make_tagged_pdf(defect=defect)
    original = bytes(source)
    with pytest.raises(EditError):
        delete_pages_pdf(source, [1])
    assert source == original
