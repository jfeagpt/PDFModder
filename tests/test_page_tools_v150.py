"""Directed tests for full-page replacement, split and non-destructive crop."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.engine import full_write
from pdfmodder.model import EditError
from pdfmodder.page_tools_v150 import (
    crop_pages_pdf, parse_split_groups, replace_pages_pdf, split_pdf,
)
from test_pageops import fixture_pdf, texts


def test_replace_complete_pages_preserves_other_pages_and_source():
    original = fixture_pdf("BASE", count=3, links=False)
    replacement = fixture_pdf("NEW", count=2, links=False)
    before = sha256(original).hexdigest()
    output, report = replace_pages_pdf(original, [2, 0], replacement, [0, 1])
    assert texts(output) == [texts(replacement)[1], texts(original)[1], texts(replacement)[0]]
    assert report["operation"] == "replace_pages" and report["replaced_pages"] == [2, 0]
    assert all(p["pixels_above_8"] == 0 for p in report["pages"])
    assert PdfReader(BytesIO(output)).metadata == PdfReader(BytesIO(original)).metadata
    assert sha256(original).hexdigest() == before


def test_replace_rejects_mismatched_counts_and_inbound_links():
    data = fixture_pdf()
    replacement = fixture_pdf("NEW", count=2, links=False)
    with pytest.raises(EditError, match="mismo número"):
        replace_pages_pdf(data, [1], replacement)
    with pytest.raises(EditError, match="quedaría excluida"):
        replace_pages_pdf(data, [2], replacement, [0])


def test_split_by_size_keeps_every_page_once_and_metadata():
    source = fixture_pdf(links=False, count=5)
    outputs, report = split_pdf(source, pages_per_part=2)
    assert [len(PdfReader(BytesIO(p)).pages) for p in outputs] == [2, 2, 1]
    assert [text for pdf in outputs for text in texts(pdf)] == texts(source)
    assert report["page_groups"] == [[0, 1], [2, 3], [4]]
    assert all(PdfReader(BytesIO(p)).metadata == PdfReader(BytesIO(source)).metadata for p in outputs)
    assert all(page["pixels_above_8"] == 0 for part in report["parts"] for page in part["pages"])


def test_split_explicit_groups_supports_intentional_order():
    source = fixture_pdf(links=False)
    groups = parse_split_groups("3,1;2", 3)
    outputs, report = split_pdf(source, page_groups=groups)
    assert texts(outputs[0]) == [texts(source)[2], texts(source)[0]]
    assert texts(outputs[1]) == [texts(source)[1]]
    assert report["part_count"] == 2


@pytest.mark.parametrize("expression", ["", "1;1-3", "1;2", "1-3;", "1-4"])
def test_split_invalid_groups_never_omit_or_duplicate_pages(expression):
    with pytest.raises(EditError):
        parse_split_groups(expression, 3)


@pytest.mark.parametrize("kwargs", [{}, {"pages_per_part": 0}, {"pages_per_part": True},
                                   {"pages_per_part": 4}, {"pages_per_part": 1, "page_groups": [[0, 1, 2]]}])
def test_split_invalid_parameters(kwargs):
    with pytest.raises(EditError):
        split_pdf(fixture_pdf(links=False), **kwargs)


def test_split_preserves_guard_against_broken_cross_part_links():
    with pytest.raises(EditError, match="quedaría excluida"):
        split_pdf(fixture_pdf(), pages_per_part=1)


@pytest.mark.parametrize("rotation,expected_box", [
    (0, (25, 40, 365, 430)), (90, (30, 45, 360, 445)),
    (180, (35, 50, 375, 440)), (270, (40, 35, 370, 435)),
])
def test_crop_visual_margins_with_rotation_and_offset_keeps_hidden_content(rotation, expected_box):
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=500)
        page.insert_text((22, 40), "HIDDEN EDGE")
        page.insert_text((100, 150), "Visible text")
        page.draw_rect((60, 70, 260, 200), color=(1, 0, 0), width=.75)
        page.set_cropbox((20, 30, 380, 450))
        page.set_rotation(rotation)
        source = full_write(doc)
    unchanged = bytes(source)
    output, report = crop_pages_pdf(source, [0], (5, 10, 15, 20))
    with fitz.open(stream=source, filetype="pdf") as before, fitz.open(stream=output, filetype="pdf") as after:
        assert tuple(after[0].cropbox) == expected_box
        assert after[0].rotation == rotation
        assert after[0].mediabox == before[0].mediabox
        assert before[0].read_contents() == after[0].read_contents()
    assert texts(output) == texts(source)  # independent extraction ignores CropBox
    assert "HIDDEN EDGE" in texts(output)[0]
    assert source == unchanged and report["non_destructive"]
    assert report["pages"][0]["max_channel_delta"] == 0


def test_crop_keeps_annotations_links_toc_metadata_and_unselected_page_pixels():
    source = fixture_pdf()
    output, report = crop_pages_pdf(source, [0, 2], (5, 6, 7, 8))
    assert texts(output) == texts(source)
    with fitz.open(stream=source, filetype="pdf") as before, fitz.open(stream=output, filetype="pdf") as after:
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert before.metadata == after.metadata
        assert before.get_xml_metadata() == after.get_xml_metadata()
        for number in range(len(before)):
            assert len(list(before[number].annots())) == len(list(after[number].annots()))
            assert len(before[number].get_links()) == len(after[number].get_links())
    assert all(p["max_channel_delta"] == 0 for p in report["pages"])


def test_crop_preserves_tags_and_reading_order():
    from tagged_corpus import make_tagged_pdf
    from pdfmodder.tagged import analyze
    source = make_tagged_pdf()
    output, _ = crop_pages_pdf(source, [0], (5, 6, 7, 8))
    assert analyze(source).semantic() == analyze(output).semantic()


def xmp_with_unreachable_objects():
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.insert_text((30, 60), 'Texto real y metadatos')
        for _ in range(12):
            unused = doc.get_new_xref()
            doc.update_object(unused, '<</PrivateUnused true>>')
        doc.set_xml_metadata('<x:xmpmeta xmlns:x="adobe:ns:meta/">METADATA ORIGINAL</x:xmpmeta>')
        doc.set_metadata({'title':'Documento original', 'author':'Prueba reproducible'})
        return doc.tobytes(garbage=0)


def test_crop_compaction_keeps_independent_expected_metadata():
    source = xmp_with_unreachable_objects()
    output, report = crop_pages_pdf(source, [0], (4, 4, 4, 4))
    with fitz.open(stream=source, filetype='pdf') as before, fitz.open(stream=output, filetype='pdf') as after:
        assert after.xref_length() < before.xref_length()
        assert before.get_xml_metadata() == after.get_xml_metadata()
        assert before.metadata == after.metadata
        assert before[0].read_contents() == after[0].read_contents()
    assert report['pages'][0]['max_channel_delta'] == 0


def test_crop_still_rejects_actual_metadata_change(monkeypatch):
    from pdfmodder import page_tools_v150
    source = xmp_with_unreachable_objects()
    real_write = page_tools_v150._write_crop_boxes
    def changed_metadata(reader, boxes):
        with fitz.open(stream=real_write(reader, boxes), filetype='pdf') as doc:
            doc.set_xml_metadata('<x:xmpmeta xmlns:x="adobe:ns:meta/">ALTERED</x:xmpmeta>')
            return full_write(doc)
    monkeypatch.setattr(page_tools_v150, '_write_crop_boxes', changed_metadata)
    with pytest.raises(EditError, match='metadatos'):
        crop_pages_pdf(source, [0], (4, 4, 4, 4))


def test_crop_preserves_unrelated_high_precision_mediabox_values():
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, FloatObject, NameObject
    with fitz.open() as doc:
        doc.new_page(width=595, height=842).insert_text((30, 60), 'Unchanged decimals')
        writer = PdfWriter(clone_from=PdfReader(BytesIO(doc.tobytes())))
    writer.pages[0][NameObject('/MediaBox')] = ArrayObject([FloatObject(v) for v in
        ('0.0', '0.0', '595.32000732421875', '841.9200439453125')])
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    output, report = crop_pages_pdf(source, [0], (4, 4, 4, 4))
    assert PdfReader(BytesIO(source)).pages[0].mediabox == PdfReader(BytesIO(output)).pages[0].mediabox
    assert report['pages'][0]['max_channel_delta'] == 0


@pytest.mark.parametrize("margins", [(-1, 0, 0, 0), (0, float("inf"), 0, 0),
                                    (True, 0, 0, 0), (0, 0, 0), (400, 0, 400, 0)])
def test_crop_rejects_invalid_or_empty_area(margins):
    with pytest.raises(EditError):
        crop_pages_pdf(fixture_pdf(links=False), [0], margins)


@pytest.mark.parametrize("filename", ["form.pdf", "restricted.pdf", "encrypted.pdf", "signature_marker_invalid.pdf"])
def test_all_tools_preserve_protected_document_blocks(filename):
    source = (Path(__file__).resolve().parents[1] / "examples" / filename).read_bytes()
    with pytest.raises(EditError):
        crop_pages_pdf(source, [0], (1, 1, 1, 1))
    with pytest.raises(EditError):
        split_pdf(source, pages_per_part=1)
    with pytest.raises(EditError):
        replace_pages_pdf(source, [0], fixture_pdf(links=False, count=1))
