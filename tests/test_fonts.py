"""Fuentes TTF originales de prueba generadas aquí: sin archivos de terceros."""
from io import BytesIO
import json
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import pymupdf
import pytest

from pdfmodder.fonts import FontError, FontResolver, normalized_name


def make_font(path: Path, name="PDFModderTest-Regular", text=" ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/.,-+ñáéíóúüÑÁÉÍÓÚÜ€", flags=0, variable=False):
    points = sorted({ord(c) for c in text})
    glyph_names = [".notdef"] + [f"uni{point:04X}" for point in points]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_names)
    builder.setupCharacterMap({point: f"uni{point:04X}" for point in points})
    glyphs = {}
    for index, glyph_name in enumerate(glyph_names):
        pen = TTGlyphPen(None)
        if glyph_name != "uni0020":
            # Formas propias deliberadamente sencillas para probar recursos/cmap.
            pen.moveTo((50, 0))
            pen.lineTo((500, 0))
            pen.lineTo((500, 650 + index % 4 * 10))
            pen.lineTo((50, 650 + index % 4 * 10))
            pen.closePath()
        glyphs[glyph_name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (600, 50) for name in glyph_names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "PDF Modder Test", "styleName": "Regular", "uniqueFontIdentifier": "PDFModderTest-1.0", "fullName": name, "psName": name, "version": "Version 1.0", "licenseDescription": "Original test font; public domain (CC0).", "licenseInfoURL": "https://creativecommons.org/publicdomain/zero/1.0/"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200, fsType=flags)
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)
    return path


class FontDocument:
    """Recursos controlados, las fuentes son Font reales de MuPDF."""
    def __init__(self, name, content=b"", kind="TrueType", resource="F1"):
        self.name, self.content, self.kind, self.resource = name, content, kind, resource

    def get_page_fonts(self, page_number, full=True):
        assert page_number == 0
        return [(5, "ttf" if self.content else "n/a", self.kind, self.name, self.resource, "WinAnsiEncoding", 0)]

    def extract_font(self, xref):
        assert xref == 5
        return self.name, "ttf" if self.content else "n/a", self.kind, self.content


@pytest.fixture
def resolver(tmp_path):
    return FontResolver(config_path=tmp_path / "settings" / "fonts.json", installed_dirs=[])


def test_base14_character_coverage_and_fractional_width(resolver):
    doc = FontDocument("Helvetica", kind="Type1")
    font = resolver.resolve(doc, 0, "Helvetica", "Fecha 12/09/2026: niño áéíóú €")
    assert font.base14 == "helv"
    assert font.source == "Base14"
    assert font.width("12/09/2026", 10.375) == pytest.approx(font.font.text_length("12/09/2026", fontsize=10.375))
    with pytest.raises(FontError, match="U\\+4E2D"):
        font.width("中", 10.375)


def test_embedded_original_font_metadata(resolver, tmp_path):
    path = make_font(tmp_path / "test.ttf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="Test", fontfile=str(path))
    page.insert_text((72, 72), "Fecha 12/09/2026", fontname="Test", fontsize=10.375)
    with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as reopened:
        info = resolver.inspect(reopened, 0)[0]
        assert info["embedded"] is True
        assert info["family"] == "PDF Modder Test"
        assert info["version"] == "Version 1.0"
        assert info["embedding_permission"] == "instalable"
        assert info["license_url"] == "https://creativecommons.org/publicdomain/zero/1.0/"
        assert info["available_count"] >= 70
        assert info["identity_verified"] is False
        font = resolver.resolve(reopened, 0, "PDFModderTest-Regular", "niño áéíóú €")
        assert font.source == "incrustada"
        assert font.buffer == path.read_bytes()


def test_subset_only_accepts_present_characters(resolver, tmp_path):
    path = make_font(tmp_path / "partial.ttf", text=" ABC123/")
    doc = FontDocument("ABCDEF+PDFModderTest-Regular", path.read_bytes())
    font = resolver.resolve(doc, 0, "PDFModderTest-Regular", "ABC123")
    assert font.metadata["subset"]
    assert font.metadata["available_count"] == 8
    with pytest.raises(FontError, match="Faltan caracteres.*U\\+20AC"):
        resolver.resolve(doc, 0, "PDFModderTest-Regular", "ABC €")


def test_installed_uses_exact_postscript_not_family(tmp_path):
    make_font(tmp_path / "regular.ttf")
    resolver = FontResolver(tmp_path / "fonts.json", [tmp_path])
    exact = resolver.resolve(FontDocument("PDFModderTest-Regular"), 0, "F1", "niño €")
    assert exact.source == "instalada"
    assert exact.metadata["identity_verified"] is False
    with pytest.raises(FontError, match="Falta la variante negrita"):
        resolver.resolve(FontDocument("PDFModderTest-Bold"), 0, "F1", "ABC")
    with pytest.raises(FontError, match="Falta la fuente exacta"):
        resolver.resolve(FontDocument("PDF Modder Test"), 0, "F1", "ABC")


def test_manual_association_persists_path_and_revalidates(resolver, tmp_path):
    path = make_font(tmp_path / "manual.ttf")
    resolver.associate("ABCDEF+AbsentFont-Regular", path)
    config = json.loads(resolver.config_path.read_text(encoding="utf-8"))
    assert config["associations"]["AbsentFont-Regular"]["path"] == str(path.resolve())
    restored = FontResolver(resolver.config_path, installed_dirs=[])
    font = restored.resolve(FontDocument("UVWXYZ+AbsentFont-Regular"), 0, "F1", "niño €")
    assert font.source == "importada"
    assert font.metadata["manual_association"]
    with pytest.raises(FontError, match="Faltan caracteres"):
        restored.resolve(FontDocument("AbsentFont-Regular"), 0, "F1", "中")
    make_font(path, name="AnotherFont-Regular")
    with pytest.raises(FontError, match="ha cambiado"):
        restored.resolve(FontDocument("AbsentFont-Regular"), 0, "F1", "ABC")


@pytest.mark.parametrize("flags, expected", [(2, "no permite incrustación editable"), (4, "no permite incrustación editable"), (0x200, "mapas de bits")])
def test_embedding_permissions_blocked(resolver, tmp_path, flags, expected):
    path = make_font(tmp_path / "restricted.ttf", flags=flags)
    with pytest.raises(FontError, match=expected):
        resolver.associate("MissingFont", path)
    assert not resolver.config_path.exists()
    with pytest.raises(FontError, match=expected):
        resolver.resolve(FontDocument("RestrictedFont", path.read_bytes()), 0, "F1", "ABC")


def test_no_subsetting_allows_complete_font_only(resolver, tmp_path):
    path = make_font(tmp_path / "nosubset.ttf", flags=0x108)
    resolved = resolver.resolve(FontDocument("PDFModderTest-Regular", path.read_bytes()), 0, "F1", "ABC")
    assert resolved.metadata["no_subsetting"]
    with pytest.raises(FontError, match="prohíbe subconjuntos"):
        resolver.resolve(FontDocument("ABCDEF+PDFModderTest-Regular", path.read_bytes()), 0, "F1", "ABC")


def test_base14_name_does_not_override_embedded_different_font(resolver, tmp_path):
    content = make_font(tmp_path / "named.ttf", text=" ABC").read_bytes()
    doc = FontDocument("Helvetica", content, kind="TrueType")
    assert resolver.resolve(doc, 0, "F1", "ABC").source == "incrustada"
    with pytest.raises(FontError, match="Faltan caracteres"):
        resolver.resolve(doc, 0, "F1", "niño")


def test_inspector_reports_missing_and_standard_resources(resolver):
    missing = resolver.inspect(FontDocument("Missing-Bold"), 0)[0]
    assert missing["embedded"] is False
    assert "Falta la variante negrita" in missing["status"]
    standard = resolver.inspect(FontDocument("Helvetica", kind="Type1"), 0)[0]
    assert standard["resolved_source"] == "Base14"
    assert standard["available_count"] > 200


def test_missing_mapping_file_does_not_lose_config(resolver, tmp_path):
    path = make_font(tmp_path / "manual.ttf")
    resolver.associate("Missing", path)
    old = resolver.config_path.read_bytes()
    path.unlink()
    with pytest.raises(FontError, match="No se puede cargar"):
        resolver.resolve(FontDocument("Missing"), 0, "F1", "A")
    assert resolver.config_path.read_bytes() == old


def test_normalization_is_limited_to_pdf_escapes_and_subset_prefix():
    assert normalized_name("/ABCDEF+Some#20Font-Bold") == "Some Font-Bold"
    assert normalized_name("Arial") != normalized_name("Helvetica")
    assert normalized_name("SomeFont-Bold") != normalized_name("SomeFont-Regular")
