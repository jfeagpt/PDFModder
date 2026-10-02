from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import TextStringObject
import pytest

from pdfmodder.model import EditError
from pdfmodder.page_catalog import destinations
from pdfmodder.pageops import merge_pdfs, organize_pages_pdf
from test_page_catalog_v093 import fixture, change


def unnamed():
    with fitz.open() as doc:
        doc.new_page(width=180, height=160).insert_text((20, 40), 'EXTERNAL')
        return doc.tobytes()


@pytest.mark.parametrize('named_first', [True, False])
def test_append_preserves_disjoint_names_and_null_target(named_first):
    sources = [fixture(), unnamed()] if named_first else [unnamed(), fixture()]
    output, report = merge_pdfs(sources[0], [sources[1]])
    rows = destinations(PdfReader(BytesIO(output)))
    offset = 0 if named_first else 1
    assert [(str(name), page) for name, page, _, _ in rows] == [
        ('page-0', offset), ('page-1', offset+1), ('page-2', offset+2), ('unresolved', None)]
    assert rows[1][3] is True
    assert all(page['pixels_above_8'] == 0 for page in report['pages'])


def test_insert_same_page_number_from_distinct_sources_is_not_duplicate():
    output, report = organize_pages_pdf(fixture(), [
        {'source': 'current', 'page': 0}, {'source': 'added', 'page': 0},
        {'source': 'current', 'page': 2}], {'added': unnamed()})
    assert [(str(name), page) for name, page, _, _ in destinations(PdfReader(BytesIO(output)))] == [
        ('page-0', 0), ('page-2', 2), ('unresolved', None)]
    assert report['page_count'] == 3
    assert all(page['pixels_above_8'] == 0 for page in report['pages'])


def test_merge_two_disjoint_name_trees_keeps_both():
    def rename(writer):
        for kid in writer.root_object['/Names']['/Dests']['/Kids']:
            pairs = kid.get_object()['/Names']
            pairs[0] = TextStringObject('external-' + str(pairs[0]))
    other = change(fixture(), rename)
    output, _ = merge_pdfs(fixture(), [other])
    rows = destinations(PdfReader(BytesIO(output)))
    assert len(rows) == 8
    assert next(page for name, page, _, _ in rows if str(name) == 'external-page-2') == 5
    assert next(page for name, page, _, _ in rows if str(name) == 'page-2') == 2


def test_actual_name_collision_and_same_source_duplication_stay_blocked():
    with pytest.raises(EditError, match='mismo nombre'):
        merge_pdfs(fixture(), [fixture()])
    with pytest.raises(EditError, match='duplicar'):
        organize_pages_pdf(fixture(), [{'source': 'current', 'page': 0}] * 2)
