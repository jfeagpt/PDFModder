"""Local export acceptance: no private documents, internet or GUI dependency."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pymupdf as fitz
import pytest

from pdfmodder import export_v150
from pdfmodder.export_v150 import ExportError, export_document


@pytest.fixture
def pdf():
    with fitz.open() as doc:
        for i, text in enumerate(("España 2025", "Árbol niño", "Final 2026")):
            page = doc.new_page(width=240, height=160)
            page.draw_rect((10, 10, 220, 140), color=(0, .2, .8), fill=(.9, .95, 1))
            page.insert_text((20, 40), text, fontsize=12)
            if i == 1:
                page.set_rotation(90)
        return doc.tobytes()


def test_text_unicode_selection_order_and_report(pdf, tmp_path):
    target = tmp_path / "texto.txt"
    report = export_document(pdf, str(target), "txt", [1, 0])
    text = target.read_text(encoding="utf-8")
    assert "Árbol niño" in text and "España 2025" in text
    assert text.index("Árbol") < text.index("España") and "\f" in text
    assert "Final" not in text
    assert report["source_page_count"] == 3 and report["page_numbers"] == [2, 1]
    assert report["files"][0]["bytes"] == target.stat().st_size
    assert json.loads(json.dumps(report))["warnings"]


@pytest.mark.parametrize("fmt,ext", [("png", "png"), ("jpeg", "jpg")])
def test_images_dimensions_rotation_and_contents(pdf, tmp_path, fmt, ext):
    folder = tmp_path / "imagenes"
    report = export_document(pdf, str(folder), fmt, [0, 1], dpi=144)
    assert len(report["files"]) == 2
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        for n in (0, 1):
            actual = fitz.Pixmap(str(folder / f"pagina-{n + 1:04d}.{ext}"))
            expected = doc[n].get_pixmap(dpi=144, alpha=False, annots=True)
            assert (actual.width, actual.height) == (expected.width, expected.height)
            if fmt == "png":
                assert actual.samples == expected.samples
            else:
                assert sum(abs(a-b) for a, b in zip(actual.samples, expected.samples)) / len(actual.samples) < 3
    assert not list(folder.glob("*.tmp"))


def test_svg_is_vector_outlines_and_warns_about_text(pdf, tmp_path):
    folder = tmp_path / "vector"
    report = export_document(pdf, str(folder), "svg", [1])
    document = ET.parse(folder / "pagina-0002.svg")
    assert document.getroot().tag.endswith("svg")
    assert document.findall(".//{http://www.w3.org/2000/svg}path")
    assert not document.findall(".//{http://www.w3.org/2000/svg}text")
    assert "contornos" in report["warnings"][0]
    assert report["dpi"] is None


@pytest.mark.parametrize("kwargs", [
    {"pages": []}, {"pages": [-1]}, {"pages": [3]}, {"pages": [True]},
    {"pages": [0, 0]}, {"pages": "1"}, {"dpi": 0}, {"dpi": 601},
    {"dpi": 144.0}, {"dpi": True}, {"format": "docx"},
])
def test_invalid_arguments_write_nothing(pdf, tmp_path, kwargs):
    arguments = {"format": "png", **kwargs}
    with pytest.raises(ExportError):
        export_document(pdf, str(tmp_path / "salida"), **arguments)
    assert not list(tmp_path.iterdir())


def test_collision_preflight_preserves_every_existing_file(pdf, tmp_path):
    folder = tmp_path / "salida"
    folder.mkdir()
    original = folder / "pagina-0002.png"
    original.write_bytes(b"existing user's image")
    with pytest.raises(ExportError, match="ya existe"):
        export_document(pdf, str(folder), "png", [0, 1])
    assert list(folder.iterdir()) == [original]
    assert original.read_bytes() == b"existing user's image"


def test_race_during_publication_cannot_overwrite(pdf, tmp_path, monkeypatch):
    target = tmp_path / "texto.txt"
    original_publish = export_v150._publish
    def competitor(temporary, destination):
        destination.write_bytes(b"created concurrently")
        original_publish(temporary, destination)
    monkeypatch.setattr(export_v150, "_publish", competitor)
    with pytest.raises(ExportError):
        export_document(pdf, str(target), "txt")
    assert target.read_bytes() == b"created concurrently"
    assert list(tmp_path.iterdir()) == [target]


def test_render_failure_leaves_no_incomplete_or_complete_outputs(pdf, tmp_path, monkeypatch):
    original = fitz.Page.get_pixmap
    def fail_second(page, *args, **kwargs):
        if page.number == 1:
            raise RuntimeError("simulated render failure")
        return original(page, *args, **kwargs)
    monkeypatch.setattr(fitz.Page, "get_pixmap", fail_second)
    folder = tmp_path / "salida"
    with pytest.raises(ExportError, match="simulated render failure"):
        export_document(pdf, str(folder), "png")
    assert not list(folder.iterdir())


def test_publication_failure_keeps_completed_outputs_and_reports_them(pdf, tmp_path, monkeypatch):
    original = export_v150._publish
    def fail_second(temporary, destination):
        if destination.name == "pagina-0002.png":
            raise OSError("simulated disk failure")
        original(temporary, destination)
    monkeypatch.setattr(export_v150, "_publish", fail_second)
    folder = tmp_path / "salida"
    with pytest.raises(ExportError) as error:
        export_document(pdf, str(folder), "png")
    assert error.value.files == [str(folder / "pagina-0001.png")]
    assert [p.name for p in folder.iterdir()] == ["pagina-0001.png"]
    assert fitz.Pixmap(error.value.files[0]).width == 480


@pytest.mark.parametrize("name", ["original.pdf", "invalid\x00.txt", "CON.txt", "texto.txt."])
def test_invalid_text_path_is_blocked(pdf, tmp_path, name):
    with pytest.raises(ExportError):
        export_document(pdf, str(tmp_path / name), "txt")
    assert not list(tmp_path.iterdir())


def test_encrypted_pdf_and_excessive_raster_size_are_blocked(pdf, tmp_path, monkeypatch):
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        encrypted = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
                               owner_pw="owner", user_pw="user")
    with pytest.raises(ExportError, match="credenciales"):
        export_document(encrypted, str(tmp_path / "protegido.txt"), "txt")
    monkeypatch.setattr(export_v150, "MAX_PAGE_PIXELS", 10)
    with pytest.raises(ExportError, match="resolución"):
        export_document(pdf, str(tmp_path / "demasiado"), "png")
    assert not list(tmp_path.iterdir())
