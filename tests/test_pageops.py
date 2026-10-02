"""Whole-page acceptance: mapped content, destinations, metadata and atomic bytes."""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, TextStringObject
import pytest

from pdfmodder.engine import full_write
from pdfmodder.model import EditError
from pdfmodder.pageops import delete_pages_pdf, extract_pages_pdf, merge_pdfs, parse_pages


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fixture_pdf(prefix="BASE", links=True, count=3, rotated=True):
    doc = fitz.open()
    for number in range(count):
        page = doc.new_page(width=400 + number * 20, height=500 + number * 30)
        page.draw_rect((35, 40, 330, 210), color=(.2, .4, .6), fill=(.9, .95, .97), width=.75)
        page.insert_text((50, 80), f"{prefix} PAGINA {number+1}", fontsize=11.25)
        page.insert_text((50, 140), "Texto y vectores conservados", fontsize=10.5)
        note = page.add_text_annot((340, 240), f"NOTA {prefix} {number+1}")
        note.set_info(title="Autor de prueba", subject="Conservar nota")
        note.update()
    if rotated and count > 2:
        page = doc[2]
        page.set_cropbox(fitz.Rect(20, 30, 420, 530))
        page.set_rotation(90)
    if links:
        doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(50, 160, 160, 180),
                            "page": count-1, "to": fitz.Point(90, 130), "zoom": 1.25})
        doc[count-1].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(50, 185, 160, 205),
                                 "page": 0, "to": fitz.Point(60, 70), "zoom": 0})
        doc[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(50, 215, 160, 235), "uri": "https://example.org/keep?q=1"})
    toc = [[1, f"{prefix} inicio", 1]]
    toc += [[2, f"{prefix} detalle {number+1}", number+1] for number in range(1, count)]
    doc.set_toc(toc, collapse=0)
    doc.set_toc_item(0, dest_dict={"kind": fitz.LINK_GOTO, "page": 0, "to": fitz.Point(50, 80),
                                  "zoom": 1.1, "color": (.2, .4, .6), "bold": True, "collapse": False})
    doc.set_metadata({"title": f"Metadatos {prefix}", "author": "Autor preservado", "subject": "Documento local"})
    doc.set_xml_metadata(f'<?xml version="1.0"?><provenance>{prefix}</provenance>')
    payload = full_write(doc)
    doc.close()
    return payload


def texts(data):
    return [page.extract_text() for page in PdfReader(BytesIO(data), strict=True).pages]


@pytest.mark.parametrize("expression,count,expected", [
    ("1,3-5", 5, [0, 2, 3, 4]), (" 3, 1 - 2, 3, 2 ", 5, [2, 0, 1]), ("2", 2, [1]),
])
def test_parse_pages_preserves_order_and_deduplicates(expression, count, expected):
    assert parse_pages(expression, count) == expected


@pytest.mark.parametrize("expression", ["", "0", "4", "1,", "-1", "1--2", "1;2", "1.2", "3-1", "1,foo", "1, 2x", "1-99"])
def test_parse_pages_rejects_invalid_values(expression):
    with pytest.raises(EditError):
        parse_pages(expression, 3)


def test_delete_middle_page_remaps_links_toc_and_preserves_source():
    data = fixture_pdf()
    exact_original = bytes(data)
    changed, report = delete_pages_pdf(data, [1])
    assert data == exact_original
    assert report["verified"] and report["page_map"] == [0, 2]
    assert report["removed_bookmarks"] == ["BASE detalle 2"]
    assert texts(changed) == [texts(data)[0], texts(data)[2]]
    with fitz.open(stream=changed, filetype="pdf") as doc:
        assert len(doc) == 2 and doc[1].rotation == 90
        assert doc[0].get_links()[0]["page"] == 1
        assert doc[1].get_links()[0]["page"] == 0
        assert doc.get_toc() == [[1, "BASE inicio", 1], [2, "BASE detalle 3", 2]]
        assert doc.metadata["title"] == "Metadatos BASE"
        assert "BASE" in doc.get_xml_metadata()
        assert len(list(doc[0].annots())) == 1
    assert all(page["pixels_above_8"] == 0 for page in report["pages"])
    # Caller can undo exactly by restoring these unmodified original bytes.
    assert texts(exact_original) == texts(data)
    assert len(PdfReader(BytesIO(exact_original)).pages) == 3


def test_extract_reordered_pages_remaps_destinations_and_keeps_geometry():
    data = fixture_pdf()
    output, report = extract_pages_pdf(data, [2, 0])
    assert report["page_map"] == [2, 0]
    assert texts(output) == [texts(data)[2], texts(data)[0]]
    with fitz.open(stream=data, filetype="pdf") as original, fitz.open(stream=output, filetype="pdf") as result:
        assert result[0].rotation == original[2].rotation == 90
        assert result[0].cropbox == original[2].cropbox
        assert result[0].get_links()[0]["page"] == 1
        assert result[1].get_links()[0]["page"] == 0
        assert result.get_toc()[0][2] == 2
        assert result.get_toc()[1][2] == 1


def test_extract_promotes_child_bookmarks_when_parent_page_removed():
    data = fixture_pdf(links=False)
    output, report = extract_pages_pdf(data, [2])
    with fitz.open(stream=output, filetype="pdf") as doc:
        assert doc.get_toc() == [[1, "BASE detalle 3", 1]]
    assert report["removed_bookmarks"] == ["BASE inicio", "BASE detalle 2"]


@pytest.mark.parametrize("operation,pages", [(delete_pages_pdf, [0, 1, 2]), (delete_pages_pdf, []),
                                              (extract_pages_pdf, []), (extract_pages_pdf, [1, 1]),
                                              (extract_pages_pdf, [-1]), (delete_pages_pdf, [False]),
                                              (delete_pages_pdf, [3])])
def test_rejects_empty_invalid_or_duplicate_page_selection(operation, pages):
    data = fixture_pdf(links=False)
    with pytest.raises(EditError):
        operation(data, pages)
    assert len(PdfReader(BytesIO(data)).pages) == 3


@pytest.mark.parametrize("operation,pages", [(delete_pages_pdf, [2]), (extract_pages_pdf, [0])])
def test_internal_link_to_excluded_page_is_blocked(operation, pages):
    with pytest.raises(EditError, match="enlace.*quedaría excluida"):
        operation(fixture_pdf(), pages)


def test_merge_preserves_order_rotated_crop_links_toc_and_base_metadata():
    first, addition, last = fixture_pdf("BASE", links=False, count=1), fixture_pdf("ANEXO"), fixture_pdf("FINAL", links=False, count=1)
    originals = (bytes(first), bytes(addition), bytes(last))
    output, report = merge_pdfs(first, [addition, last])
    assert (first, addition, last) == originals
    assert texts(output) == texts(first) + texts(addition) + texts(last)
    assert report["source_page_counts"] == [1, 3, 1]
    assert report["verified"] and len(report["pages"]) == 5
    with fitz.open(stream=output, filetype="pdf") as doc:
        assert doc[3].rotation == 90
        assert list(doc[3].cropbox) == [20, 30, 420, 530]
        assert doc[1].get_links()[0]["page"] == 3
        assert doc[3].get_links()[0]["page"] == 1
        assert doc.metadata["title"] == "Metadatos BASE"
        assert doc.get_xml_metadata() == '<?xml version="1.0"?><provenance>BASE</provenance>'
        assert [entry[2] for entry in doc.get_toc()] == [1, 2, 3, 4, 5]
        assert len(list(doc[1].annots())) == 1


def test_merge_corpus_preserves_image_uri_annotations_and_shared_fonts():
    data = (EXAMPLES / "digital.pdf").read_bytes()
    rotated = (EXAMPLES / "rotated_crop.pdf").read_bytes()
    output, report = merge_pdfs(rotated, [data])
    assert len(texts(output)) == 3
    with fitz.open(stream=output, filetype="pdf") as doc:
        assert doc[1].get_links()[0]["uri"] == "https://example.org/pdf-modder"
        assert len(doc[1].get_images()) == 1
        assert len(list(doc[1].annots())) == 1
    assert all(page["max_channel_delta"] == 0 for page in report["pages"])


@pytest.mark.parametrize("filename", ["form.pdf", "signature_marker_invalid.pdf", "encrypted.pdf", "restricted.pdf"])
def test_protected_documents_block_all_page_operations(filename):
    data = (EXAMPLES / filename).read_bytes()
    with pytest.raises(EditError):
        extract_pages_pdf(data, [0])
    with pytest.raises(EditError):
        merge_pdfs(fixture_pdf(links=False, count=1), [data])


def altered_catalog(key, value):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(fixture_pdf(links=False))))
    writer.root_object[NameObject(key)] = value
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("key,value", [("/PageLabels", DictionaryObject()), ("/Names", DictionaryObject()),
                                       ("/OCProperties", DictionaryObject()), ("/OpenAction", TextStringObject("named")),
                                       ("/StructTreeRoot", DictionaryObject({NameObject("/Type"): NameObject("/StructTreeRoot")}))])
def test_unsupported_catalog_features_are_explicitly_blocked(key, value):
    with pytest.raises(EditError):
        extract_pages_pdf(altered_catalog(key, value), [0])


def test_custom_info_metadata_is_preserved():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(fixture_pdf(links=False))))
    writer.add_metadata({"/CustomCompany": "Agro prueba", "/Title": "Título propio"})
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    result, _ = extract_pages_pdf(source, [1])
    assert PdfReader(BytesIO(result)).metadata["/CustomCompany"] == "Agro prueba"
    assert PdfReader(BytesIO(result)).metadata["/Title"] == "Título propio"


def test_merge_without_additions_and_invalid_pdf_fail_cleanly():
    with pytest.raises(EditError):
        merge_pdfs(fixture_pdf(links=False), [])
    with pytest.raises(EditError):
        extract_pages_pdf(b"not a PDF", [0])
