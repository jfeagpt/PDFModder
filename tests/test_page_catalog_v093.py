"""Catalog page references: synthetic, reproducible and no private documents."""
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, FloatObject, NameObject,
                          NullObject, TextStringObject)
import pytest

from pdfmodder.model import EditError
from pdfmodder.page_catalog import destinations
from pdfmodder.pageops import delete_pages_pdf, extract_pages_pdf, organize_pages_pdf, merge_pdfs


def fixture():
    with fitz.open() as doc:
        for index in range(3):
            doc.new_page(width=180, height=160).insert_text((20, 40), f"Pagina {index + 1}")
        writer = PdfWriter(clone_from=PdfReader(BytesIO(doc.tobytes())))
    writer.root_object[NameObject('/AcroForm')] = DictionaryObject({
        NameObject('/Fields'): ArrayObject(), NameObject('/DA'): TextStringObject('/Helv 0 Tf 0 g'),
        NameObject('/DR'): DictionaryObject()})
    kids = ArrayObject()
    for index in range(3):
        dest = ArrayObject([writer.pages[index].indirect_reference, NameObject('/XYZ'),
                            FloatObject(12.125), NullObject(), FloatObject(1.5)])
        if index == 1:
            dest = DictionaryObject({NameObject('/D'): dest})
        kids.append(writer._add_object(DictionaryObject({NameObject('/Names'): ArrayObject([
            TextStringObject(f'page-{index}'), writer._add_object(dest)])})))
    kids.append(writer._add_object(DictionaryObject({NameObject('/Names'): ArrayObject([
        TextStringObject('unresolved'), ArrayObject([NullObject(), NameObject('/Fit')])])})))
    writer.root_object[NameObject('/Names')] = DictionaryObject({NameObject('/Dests'):
        writer._add_object(DictionaryObject({NameObject('/Kids'): kids}))})
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def change(data, mutate):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(data)))
    mutate(writer)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_named_destination_capabilities_match_motor_limits():
    from pdfmodder.tagged_pages import page_capabilities
    capabilities = page_capabilities(fixture())
    assert all(capabilities[key] for key in ('supported', 'delete', 'extract', 'reorder', 'rotate', 'insert_blank'))
    assert not capabilities['duplicate'] and capabilities['insert_pdf']


@pytest.mark.parametrize('operation', ['delete', 'extract', 'organize'])
def test_names_remap_null_and_empty_form_are_preserved(operation):
    data = fixture()
    if operation == 'delete':
        output, report = delete_pages_pdf(data, [1])
        expected = [('page-0', 0), ('page-2', 1), ('unresolved', None)]
    elif operation == 'extract':
        output, report = extract_pages_pdf(data, [2, 0])
        expected = [('page-0', 1), ('page-2', 0), ('unresolved', None)]
    else:
        output, report = organize_pages_pdf(data, [{'source': 'current', 'page': n} for n in [2, 1, 0]])
        expected = [('page-0', 2), ('page-1', 1), ('page-2', 0), ('unresolved', None)]
    rows = destinations(PdfReader(BytesIO(output)))
    assert [(str(key), page) for key, page, _, _ in rows] == expected
    assert all(view == [NameObject('/XYZ'), FloatObject(12.125), NullObject(), FloatObject(1.5)]
               for key, page, view, wrapped in rows if page is not None)
    assert report['named_destinations']['preexisting_null_targets_preserved'] == 1
    assert all(page['max_channel_delta'] == 0 for page in report['pages'])
    assert len(PdfReader(BytesIO(data)).pages) == 3
    assert PdfReader(BytesIO(output)).trailer['/Root']['/AcroForm']['/Fields'] == []
    assert next(row for row in rows if str(row[0]) == 'page-1')[3] if operation == 'organize' else True


@pytest.mark.parametrize('kind', ['fields', 'xfa', 'javascript', 'duplicate', 'merge', 'link', 'action'])
def test_active_structures_and_ambiguous_operations_stay_blocked(kind):
    data = fixture()
    if kind == 'fields':
        data = change(data, lambda w: w.root_object['/AcroForm']['/Fields'].append(DictionaryObject()))
    elif kind == 'xfa':
        data = change(data, lambda w: w.root_object['/AcroForm'].__setitem__(NameObject('/XFA'), TextStringObject('x')))
    elif kind == 'javascript':
        data = change(data, lambda w: w.root_object['/Names'].__setitem__(NameObject('/JavaScript'), DictionaryObject()))
    elif kind == 'action':
        data = change(data, lambda w: w.root_object.__setitem__(NameObject('/OpenAction'), ArrayObject()))
    elif kind == 'link':
        def add_link(writer):
            writer.pages[0][NameObject('/Annots')] = ArrayObject([writer._add_object(DictionaryObject({
                NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                NameObject('/Rect'): ArrayObject([FloatObject(x) for x in [10, 20, 30, 40]]),
                NameObject('/Dest'): TextStringObject('page-1')}))])
        data = change(data, add_link)
    with pytest.raises(EditError):
        if kind == 'duplicate':
            organize_pages_pdf(data, [{'source': 'current', 'page': 0}] * 2)
        elif kind == 'merge':
            merge_pdfs(data, [data])
        else:
            delete_pages_pdf(data, [2])
