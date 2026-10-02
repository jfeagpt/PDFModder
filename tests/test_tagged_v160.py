"""Directed v1.6 additions/movement: independent structure audit and neighbours."""
from io import BytesIO

import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, FloatObject, NameObject, NullObject
import pytest

from pdfmodder.composition import AddTextRequest, insert_text_pdf
from pdfmodder.engine import edit_pdf
from pdfmodder.media import add_image_pdf
from pdfmodder.media import image_items
from pdfmodder.model import EditError
from pdfmodder.tagged import analyze
from tagged_corpus import CONTROL_TEXT, audit_tagged, make_tagged_pdf
from test_engine import select, request_for, assert_moved_once, assert_unchanged_neighbours
from test_tagged import assert_control_page_unchanged, assert_structure_preserved


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (20, 12), '#184d75').save(output, format='PNG')
    return output.getvalue()


@pytest.mark.parametrize('order', ['page_start', 'page_end'])
def test_add_paragraph_preserves_existing_order_objr_and_next_page(order):
    source = make_tagged_pdf(named_properties=True, include_objr=True, mcr_references=True)
    before = audit_tagged(source)
    text = 'Nuevo párrafo: año 2026'
    output, report = insert_text_pdf(source, AddTextRequest(0, 48, 350, 240, 30, text,
                                                          accessibility_order=order))
    after = audit_tagged(output)
    expected = (text + before['reading_order'] if order == 'page_start' else
                before['reading_order'].replace(CONTROL_TEXT, text + CONTROL_TEXT))
    assert after['reading_order'] == expected
    assert len(after['content']) == len(before['content']) + 1
    assert all(after['content'][key] == value for key, value in before['content'].items())
    assert len(after['objrs']) == len(before['objrs']) == 1
    assert report['accessibility']['role'] == 'P'
    assert report['accessibility']['reading_order'] == order
    assert_control_page_unchanged(source, output)
    assert text in PdfReader(BytesIO(output)).pages[0].extract_text()


@pytest.mark.parametrize('decorative', [False, True])
def test_add_figure_has_explicit_semantics_and_preserves_other_content(decorative):
    source = make_tagged_pdf(named_properties=True, include_objr=True)
    before = audit_tagged(source)
    output, report = add_image_pdf(source, 0, image_bytes(), (160, 260, 200, 284),
                                  accessibility_order=None if decorative else 'page_end',
                                  alt_text=None if decorative else 'Rectángulo de prueba',
                                  decorative=decorative)
    after = audit_tagged(output)
    if decorative:
        assert analyze(source).semantic() == analyze(output).semantic()
        assert after['reading_order'] == before['reading_order']
    else:
        assert after['reading_order'] == before['reading_order'].replace(
            CONTROL_TEXT, '[Imagen: Rectángulo de prueba]' + CONTROL_TEXT)
    assert report['accessibility']['role'] == ('Artifact' if decorative else 'Figure')
    assert_control_page_unchanged(source, output)
    with fitz.open(stream=source, filetype='pdf') as a, fitz.open(stream=output, filetype='pdf') as b:
        assert len(b[0].get_image_info()) == len(a[0].get_image_info()) + 1
        assert a[0].get_texttrace() == b[0].get_texttrace()


def clipped_word():
    source = make_tagged_pdf(mixed_styles=True, named_properties=True)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    page = writer.pages[0]
    # PALABRA is a single own MCID/stream. Put a local rectangle inside its
    # existing q/Q, leaving its semantic BDC/EMC outside the movable scope.
    stream = ContentStream(page['/Contents'][2], writer)
    index = next(i for i, (_, operator) in enumerate(stream.operations) if operator == b'q')
    stream.operations[index+1:index+1] = [([FloatObject(v) for v in (80, 260, 80, 30)], b're'),
                                         ([], b'W'), ([], b'n')]
    page['/Contents'][2] = writer._add_object(stream)
    buffer = BytesIO(); writer.write(buffer)
    return buffer.getvalue()


def test_move_tagged_word_outside_clip_keeps_mcid_order_neighbors_and_pixels():
    source = clipped_word()
    model, selected = select(source, 'PALABRA')
    output, report = edit_pdf(source, request_for(model, selected, dx=20, dy=30))
    old, new = assert_structure_preserved(source, output)
    assert new['reading_order'] == old['reading_order']
    assert report['accessibility']['reading_order_preserved']
    assert report['clip_translated'] and not report['clip_enlarged']
    assert all(page['pixels_above_8'] == 0 for page in report['pages'])
    assert_moved_once(source, output, selected, 20, 30)
    assert_unchanged_neighbours(source, output, selected)
    assert_control_page_unchanged(source, output)


def test_unsafe_partial_mcid_reorder_and_missing_semantics_remain_explicit():
    source = clipped_word()
    model, selected = select(source, 'PALA')
    with pytest.raises(EditError, match='orden de lectura'):
        edit_pdf(source, request_for(model, selected, dx=20, dy=30))
    with pytest.raises(EditError, match='inicio o al final'):
        insert_text_pdf(source, AddTextRequest(0, 48, 350, 200, 30, 'Sin orden'))
    with pytest.raises(EditError, match='texto alternativo'):
        add_image_pdf(source, 0, image_bytes(), (160, 260, 200, 284), accessibility_order='page_end')
    with pytest.raises(EditError, match='párrafo por separado'):
        insert_text_pdf(source, AddTextRequest(0, 48, 350, 200, 40, 'Uno\nDos',
                                              accessibility_order='page_end'))


def test_parenttree_trailing_nulls_are_preserved_when_adding_content():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())) )
    array = writer._root_object['/StructTreeRoot']['/ParentTree']['/Nums'][1].get_object()
    array.extend([NullObject(), NullObject()])
    buffer = BytesIO(); writer.write(buffer)
    source = buffer.getvalue()
    before = analyze(source)
    old_length = len(before.parents[0])
    output, report = insert_text_pdf(source, AddTextRequest(0, 48, 350, 200, 25, 'Con huecos',
                                                          accessibility_order='page_end'))
    after = analyze(output)
    assert report['accessibility']['mcid'] == old_length
    assert isinstance(after.parents[0][old_length-1], NullObject)
    assert len(after.parents[0]) == old_length + 1


def test_added_image_instance_is_editable_only_with_verifiable_layout_semantics():
    from pdfmodder.tagged_image_v160 import TaggedImageTransform
    from tagged_corpus import dictionary
    source, _ = add_image_pdf(make_tagged_pdf(), 0, image_bytes(), (160, 260, 200, 284),
                              accessibility_order='page_end', alt_text='Nueva figura')
    with fitz.open(stream=source, filetype='pdf') as doc:
        item = image_items(doc, 0)[-1]
        assert item['editable'] and item['tagged_geometry']
    guard = TaggedImageTransform(source, 0, item)
    assert guard.validate(source)['structure_preserved']
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    figure = writer._root_object['/StructTreeRoot']['/K']['/K'][-2].get_object()
    assert figure['/S'] == '/Figure' and figure['/Alt'] == 'Nueva figura'
    figure[NameObject('/A')] = dictionary(O=NameObject('/Layout'),
                                         BBox=ArrayObject([FloatObject(v) for v in (160, 136, 200, 160)]))
    buffer = BytesIO(); writer.write(buffer)
    with fitz.open(stream=buffer.getvalue(), filetype='pdf') as doc:
        restricted = image_items(doc, 0)[-1]
        assert not restricted['editable']
        assert 'disposición' in restricted['reason']
