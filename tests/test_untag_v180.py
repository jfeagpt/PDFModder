"""Untagging removes accessibility relations while preserving actual PDF content."""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject, NumberObject, TextStringObject
import pytest

from pdfmodder.model import EditError
from pdfmodder.untag_v180 import remove_tags
from tagged_corpus import DATE_TEXT, dictionary, make_tagged_pdf


@pytest.mark.parametrize('named', [False, True])
def test_remove_tree_keeps_content_actualtext_and_exact_pixels(named):
    source = make_tagged_pdf(named_properties=named, actual_text=DATE_TEXT,
                             actual_on='content', include_objr=True)
    original_digest = sha256(source).digest()
    candidate, report = remove_tags(source)
    result = PdfReader(BytesIO(candidate), strict=True)
    assert '/StructTreeRoot' not in result.trailer['/Root']
    assert '/MarkInfo' not in result.trailer['/Root']
    assert report['changed'] and report['verified'] and report['accessibility_removed']
    assert report['associations_removed'] == 3  # Two pages and the tagged link.
    assert sha256(source).digest() == original_digest
    for page in result.pages:
        assert '/StructParents' not in page
        for annot in page.get('/Annots', []):
            assert '/StructParent' not in annot.get_object()
    with fitz.open(stream=source) as before, fitz.open(stream=candidate) as after:
        for left, right in zip(before, after):
            assert left.read_contents() == right.read_contents()
            assert left.get_pixmap(matrix=fitz.Matrix(2, 2)).samples == right.get_pixmap(matrix=fitz.Matrix(2, 2)).samples
            assert left.get_text() == right.get_text()
    assert b'/MCID' in result.pages[0].get_contents().get_data() or named
    assert remove_tags(candidate)[0] == candidate


def test_keeps_fields_annotations_bookmarks_metadata_and_optional_layers():
    with fitz.open(stream=make_tagged_pdf(include_objr=True)) as source:
        page = source[0]
        widget = fitz.Widget()
        widget.field_name = 'Dato conservado'
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = 'Valor original'
        widget.rect = fitz.Rect(200, 300, 360, 330)
        page.add_widget(widget)
        page.add_text_annot((350, 190), 'Comentario conservado')
        layer = source.add_ocg('Capa conservada')
        page.insert_text((50, 375), 'Texto de capa', oc=layer)
        source.set_toc([[1, 'Primera página', 1], [1, 'Segunda página', 2]])
        source.embfile_add('adjunto.txt', b'Contenido adjunto', filename='adjunto.txt')
        data = source.tobytes()
    candidate, report = remove_tags(data)
    assert report['marked_content_preserved']
    with fitz.open(stream=data) as before, fitz.open(stream=candidate) as after:
        assert before.metadata == after.metadata
        assert before.embfile_get('adjunto.txt') == after.embfile_get('adjunto.txt')
        assert before.get_toc() == after.get_toc()
        assert [x['name'] for x in before.get_ocgs().values()] == [x['name'] for x in after.get_ocgs().values()]
        assert [x.field_value for x in after[0].widgets()] == ['Valor original']
        assert [x.info['content'] for x in after[0].annots()] == ['Comentario conservado']
    assert PdfReader(BytesIO(candidate)).get_fields()['Dato conservado']['/V'] == 'Valor original'


def test_direct_dictionaries_and_form_xobject_associations_are_removed():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf(include_objr=True))))
    writer.pages[0]['/Resources'][NameObject('/DirectProperty')] = dictionary(StructParents=NumberObject(12))
    form = DecodedStreamObject()
    form.set_data(b'0 0 10 10 re S')
    form.update(dictionary(Type=NameObject('/XObject'), Subtype=NameObject('/Form'),
                           BBox=ArrayObject([NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]),
                           Resources=dictionary(), StructParents=NumberObject(13)))
    writer.pages[0]['/Resources']['/XObject'][NameObject('/FormFixture')] = writer._add_object(form)
    stream = BytesIO(); writer.write(stream)
    candidate, _ = remove_tags(stream.getvalue())
    result = PdfReader(BytesIO(candidate))
    assert '/StructParent' not in result.pages[0]['/Annots'][0].get_object()
    assert '/StructParents' not in result.pages[0]['/Resources']['/DirectProperty']
    assert '/StructParents' not in result.pages[0]['/Resources']['/XObject']['/FormFixture']


@pytest.mark.parametrize('kind', ['encrypted', 'signed', 'signature_field', 'invalid'])
def test_protected_or_unverifiable_documents_are_left_intact(kind):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    if kind == 'encrypted':
        writer.encrypt('lectura', 'propietario', permissions_flag=4)
    elif kind == 'signed':
        writer.root_object[NameObject('/Perms')] = dictionary(DocMDP=dictionary(Type=NameObject('/Sig')))
    elif kind == 'signature_field':
        writer.root_object[NameObject('/AcroForm')] = dictionary(Fields=ArrayObject([
            dictionary(FT=NameObject('/Sig'), T=TextStringObject('Firma'))]))
    stream = BytesIO(); writer.write(stream)
    source = b'%PDF-invalid' if kind == 'invalid' else stream.getvalue()
    digest = sha256(source).digest()
    with pytest.raises(EditError):
        remove_tags(source, password='lectura')
    assert sha256(source).digest() == digest
