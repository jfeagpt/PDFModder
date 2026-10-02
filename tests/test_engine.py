"""Aceptación sobre PDFs digitales sintéticos incluidos, sin datos del usuario.

Además de los controles transaccionales del motor, contrastamos contenido con
pypdf, apariciones concretas y coordenadas de todos los caracteres vecinos.
"""
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.fonts import FontResolver
from pdfmodder.model import EditError, EditRequest, transform, union
from pdfmodder.validation import assert_characters, related, trace_chars


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def load(name="digital.pdf"):
    return (EXAMPLES / name).read_bytes()


def model_for(data, page=0):
    with fitz.open(stream=data, filetype="pdf") as doc:
        return extract_page(doc, page, data)


def select(data, text, *, x=None, y=None, page=0):
    model = model_for(data, page)
    glyphs = model.glyphs
    # MuPDF's font insertion maps the shared space/NBSP glyph to NBSP. Match
    # the fixture label only; preserve the actual codepoint in every assertion.
    joined = "".join(g.text for g in glyphs).replace("\u00a0", " ")
    start = 0
    while True:
        start = joined.find(text, start)
        if start < 0:
            raise AssertionError(f"No se encontró {text!r} en x={x}, y={y}")
        group = glyphs[start:start + len(text)]
        if (x is None or abs(group[0].origin[0] - x) < .05) and (y is None or abs(group[0].origin[1] - y) < .05):
            return model, group
        start += 1


def request_for(model, glyphs, **kwargs):
    return EditRequest(model.number, [g.id for g in glyphs], revision=model.revision, **kwargs)


def assert_unchanged_neighbours(before, after, selected, *, page=0):
    old = model_for(before, page)
    selected_ids = {g.id for g in selected}
    expected = [(g.text, g.origin, g.font, g.size) for g in old.glyphs if g.id not in selected_ids]
    with fitz.open(stream=after, filetype="pdf") as doc:
        actual = trace_chars(doc[page])
    # Test independently checks exactly one matching origin for every neighbour,
    # including neighbours that may lie within an excluded pixel envelope.
    for char, origin, font, size in expected:
        matches = [entry for entry in actual if entry[0] == char and abs(entry[1][0] - origin[0]) < .035 and abs(entry[1][1] - origin[1]) < .035]
        assert len(matches) == 1
        assert matches[0][2] == font
        assert matches[0][3] == pytest.approx(size, abs=.001)


def assert_moved_once(before, after, chosen, dx, dy, *, page=0):
    old = model_for(before, page)
    ids = {g.id for g in chosen}
    expected = [(g.text, (g.origin[0] + dx, g.origin[1] + dy) if g.id in ids else g.origin, g.font, g.size) for g in old.glyphs]
    with fitz.open(stream=after, filetype="pdf") as result:
        assert_characters(expected, result[page])
        actual = trace_chars(result[page])
    for g in chosen:
        old_matches = [a for a in actual if a[0] == g.text and abs(a[1][0] - g.origin[0]) < .035 and abs(a[1][1] - g.origin[1]) < .035]
        new_matches = [a for a in actual if a[0] == g.text and abs(a[1][0] - g.origin[0] - dx) < .035 and abs(a[1][1] - g.origin[1] - dy) < .035]
        assert not old_matches
        assert len(new_matches) == 1
        assert new_matches[0][2] == g.font
        assert new_matches[0][3] == pytest.approx(g.size, abs=.001)


def test_change_date_keeps_position_shared_page_and_other_occurrence():
    data = load()
    model, selected = select(data, "10/09/2026", x=125, y=125)
    changed, report = edit_pdf(data, request_for(model, selected, text="11/09/2026"))
    _, result = select(changed, "11/09/2026", x=125, y=125)
    assert result[0].size == selected[0].size == 11.25
    assert result[0].font == selected[0].font
    assert report["verified"] and report["pages"][0]["pixels_above_8"] == 0
    with fitz.open(stream=data, filetype="pdf") as before, fitz.open(stream=changed, filetype="pdf") as after:
        assert before[1].get_text() == after[1].get_text()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        assert after[0].search_for("10/09/2026") == []
        assert len(after[1].search_for("10/09/2026")) == 1
        assert before.metadata == after.metadata
        assert before.get_toc() == after.get_toc()
    reader = PdfReader(BytesIO(changed), strict=True)
    assert "11/09/2026" in reader.pages[0].extract_text()
    assert "10/09/2026" in reader.pages[1].extract_text()
    assert_unchanged_neighbours(data, changed, selected)


def test_longer_amount_requires_explicit_width_and_preserves_right_edge():
    data = load()
    model, selected = select(data, "1.234,56 €", y=283)
    with pytest.raises(EditError, match="supera el espacio"):
        edit_pdf(data, request_for(model, selected, text="12.345,67 €", anchor="right"))
    changed, report = edit_pdf(data, request_for(model, selected, text="12.345,67 €", width=130, anchor="right"))
    _, result = select(changed, "12.345,67 €", y=283)
    assert union(g.bbox for g in result)[2] == pytest.approx(union(g.bbox for g in selected)[2], abs=.035)
    # The fixture's nominal 530 pt is already rounded by PDF font widths.
    # Preservation above is checked against the actual original at .035 pt.
    assert union(g.bbox for g in result)[2] == pytest.approx(530, abs=.05)
    assert all(g.size == 11.25 for g in result)
    assert report["pages"][0]["pixels_above_8"] == 0
    assert "12.345,67 €" in PdfReader(BytesIO(changed)).pages[0].extract_text()
    assert_unchanged_neighbours(data, changed, selected)


def test_explicit_decimal_anchor_keeps_comma():
    data = load()
    model, selected = select(data, "1.234,56 €", y=283)
    changed, _ = edit_pdf(data, request_for(model, selected, text="12.345,67 €", width=130, anchor="decimal", decimal_separator=","))
    _, result = select(changed, "12.345,67 €", y=283)
    old_comma = next(g for g in selected if g.text == ",")
    new_comma = next(g for g in result if g.text == ",")
    assert new_comma.origin == pytest.approx(old_comma.origin, abs=.035)


def test_span_replacement_preserves_accents_enye_and_euro():
    data = load()
    model, selected = select(data, "Español: año, piñón, café, útil, acción y 25,50 €", y=164)
    replacement = "Español: niño, piñón, té, útil, acción y 35,50 €"
    changed, _ = edit_pdf(data, request_for(model, selected, text=replacement, width=460))
    _, result = select(changed, replacement, x=48, y=164)
    assert {g.font for g in result} == {selected[0].font}
    assert replacement in PdfReader(BytesIO(changed), strict=True).pages[0].extract_text()
    assert_unchanged_neighbours(data, changed, selected)


def test_edit_over_colour_in_table_keeps_background_vectors_images_and_links():
    data = load()
    model, selected = select(data, "Semillas de otoño", x=58, y=283)
    changed, report = edit_pdf(data, request_for(model, selected, text="Semillas de verano", width=250))
    with fitz.open(stream=data, filetype="pdf") as before, fitz.open(stream=changed, filetype="pdf") as after:
        assert related(before[0]) == related(after[0])
        for rect in [(44, 225, 550, 255), (443, 369, 539, 441), (44, 301, 550, 305)]:
            a = before[0].get_pixmap(clip=fitz.Rect(rect), matrix=fitz.Matrix(2, 2)).samples
            b = after[0].get_pixmap(clip=fitz.Rect(rect), matrix=fitz.Matrix(2, 2)).samples
            assert a == b
    assert report["pages"][0]["pixels_above_8"] == 0
    assert_unchanged_neighbours(data, changed, selected)


def test_only_selected_repeated_word_changes():
    data = load()
    model, selected = select(data, "TOTAL", x=170, y=197)
    changed, _ = edit_pdf(data, request_for(model, selected, text="FINAL", width=60))
    select(changed, "TOTAL", x=48, y=197)
    select(changed, "TOTAL", x=310, y=197)
    select(changed, "FINAL", x=170, y=197)
    with fitz.open(stream=changed, filetype="pdf") as doc:
        assert len(doc[0].search_for("TOTAL")) == 2
        assert len(doc[0].search_for("FINAL")) == 1
        assert len(doc[1].search_for("TOTAL")) == 1
    assert_unchanged_neighbours(data, changed, selected)


@pytest.mark.parametrize("text,x,y,dx,dy", [
    ("PALABRA", 48, 455, 300, 25),
    ("Mover esta línea conserva su distribución.", 48, 415, 20, 20),
])
def test_move_word_and_line_once(text, x, y, dx, dy):
    data = load()
    model, selected = select(data, text, x=x, y=y)
    changed, report = edit_pdf(data, request_for(model, selected, dx=dx, dy=dy))
    assert_moved_once(data, changed, selected, dx, dy)
    assert report["pages"][0]["pixels_above_8"] == 0


def test_mixed_style_group_moves_without_concatenation_or_reformatting():
    data = load("unsupported_regions.pdf")
    model = model_for(data)
    selected = [g for g in model.glyphs if abs(g.origin[1] - 490) < .05]
    assert len({g.font for g in selected}) == 2
    with pytest.raises(EditError, match="mezcla estilos"):
        edit_pdf(data, request_for(model, selected, text="Normal y negrita", width=180))
    changed, _ = edit_pdf(data, request_for(model, selected, dx=15.5, dy=35.25))
    assert_moved_once(data, changed, selected, 15.5, 35.25)


def test_multiline_group_keeps_internal_distribution_and_other_column():
    data = load()
    model = model_for(data)
    selected = [g for g in model.glyphs if g.origin[0] < 220 and (abs(g.origin[1] - 540) < .05 or abs(g.origin[1] - 558) < .05)]
    assert len({g.line for g in selected}) == 2
    changed, _ = edit_pdf(data, request_for(model, selected, dx=14.25, dy=40))
    assert_moved_once(data, changed, selected, 14.25, 40)
    select(changed, "Vecino de otra columna", x=330, y=540)


@pytest.mark.parametrize("zoom", [.6, 1.75, 3.0])
def test_crop_rotation_zoom_coordinates_match_reopened_destination(zoom):
    data = load("rotated_crop.pdf")
    model, date = select(data, "10/09/2026", x=60, y=80)
    changed, _ = edit_pdf(data, request_for(model, date, text="11/09/2026"))
    model, line = select(changed, "Mover línea rotada", x=60, y=130)
    assert model.rotation == 90 and model.cropbox == (30, 40, 610, 840)
    desired = (line[0].origin[0] + 23.25, line[0].origin[1] + 17.5)
    rotated = transform(desired, model.rotation_matrix)
    screen = tuple(value * zoom for value in rotated)
    recovered = transform(tuple(value / zoom for value in screen), model.derotation_matrix)
    assert recovered == pytest.approx(desired, abs=1e-9)
    dx, dy = recovered[0] - line[0].origin[0], recovered[1] - line[0].origin[1]
    moved, report = edit_pdf(changed, request_for(model, line, dx=dx, dy=dy))
    assert_moved_once(changed, moved, line, dx, dy)
    with fitz.open(stream=moved, filetype="pdf") as doc:
        assert doc[0].rotation == 90
        assert tuple(doc[0].cropbox) == (30, 40, 610, 840)
    assert report["pages"][0]["pixels_above_8"] == 0


@pytest.mark.parametrize("name,needle,error", [
    ("unsupported_regions.pdf", "Texto con escala horizontal", "Escala horizontal|no reproduce exactamente"),
    ("unsupported_regions.pdf", "Texto inclinado", "orientación propia"),
    ("unsupported_regions.pdf", "Contorno sin relleno", "trazado"),
    ("unsupported_regions.pdf", "SOLAPADO", "solapa|aislar"),
    ("font_missing.pdf", "10/09/2026", "Falta la fuente exacta"),
    ("font_embedding_restricted.pdf", "10/09/2026", "no permite incrustación editable"),
])
def test_unsupported_region_refuses_and_original_bytes_stay_available(name, needle, error):
    data = load(name)
    model, chosen = select(data, needle)
    resolver = FontResolver(config_path=ROOT / "build" / "unused-font-test-settings.json", installed_dirs=[])
    with pytest.raises(EditError, match=error):
        edit_pdf(data, request_for(model, chosen, dx=2), resolver)
    assert load(name) == data


def test_chain_change_move_and_reedit_without_duplicate_content():
    data = load()
    model, date = select(data, "10/09/2026", x=125, y=125)
    first, _ = edit_pdf(data, request_for(model, date, text="11/09/2026"))
    model, chosen = select(first, "11/09/2026", x=125, y=125)
    moved, _ = edit_pdf(first, request_for(model, chosen, dx=12, dy=10))
    model, chosen = select(moved, "11/09/2026", x=137, y=135)
    final, _ = edit_pdf(moved, request_for(model, chosen, text="12/09/2026"))
    select(final, "12/09/2026", x=137, y=135)
    independent = PdfReader(BytesIO(final), strict=True)
    text = independent.pages[0].extract_text()
    assert text.count("12/09/2026") == 1
    assert "10/09/2026" not in text and "11/09/2026" not in text
    assert independent.pages[1].extract_text().count("10/09/2026") == 1


def test_distinct_space_nbsp_and_hyphen_codepoints_survive_insert_move_and_reopen():
    data = load()
    model, date = select(data, "10/09/2026", x=125, y=125)
    replacement = "A B\u00a0C-D ñ €"
    changed, _ = edit_pdf(data, request_for(model, date, text=replacement, width=180))
    edited_model = model_for(changed)
    edited = [g for g in edited_model.glyphs if abs(g.origin[1] - 125) < .035 and 125 <= g.origin[0] < 300]
    # Do not normalize Unicode: U+0020/U+00A0 and U+002D/U+00AD have different
    # semantics even when a font uses the same outlines for each pair.
    assert "".join(g.text for g in edited) == replacement
    assert replacement in PdfReader(BytesIO(changed)).pages[0].extract_text()
    moved, _ = edit_pdf(changed, request_for(edited_model, edited, dx=0, dy=14))
    assert_moved_once(changed, moved, edited, 0, 14)
    final_model = model_for(moved)
    final_text = "".join(g.text for g in final_model.glyphs if abs(g.origin[1] - 139) < .035)
    assert final_text == replacement
    assert_unchanged_neighbours(data, changed, date)


def test_base14_euro_cp1252_symbols_are_real_unicode_and_can_be_reedited():
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 100), "1234.56", fontname="helv", fontsize=11.25)
        page.insert_text((300, 100), "NEIGHBOUR", fontname="hebo", fontsize=11.25)
        data = doc.tobytes()
    model, chosen = select(data, "1234.56", x=50, y=100)
    requested = "12.345,67 € — niño"
    changed, _ = edit_pdf(data, request_for(model, chosen, text=requested, width=220))
    model, edited = select(changed, requested, x=50, y=100)
    assert model.text([g.id for g in edited]) == requested
    assert requested in PdfReader(BytesIO(changed)).pages[0].extract_text()
    changed_again, _ = edit_pdf(changed, request_for(model, edited, text="13.345,67 € — niño", width=220))
    select(changed_again, "13.345,67 € — niño", x=50, y=100)
    assert_unchanged_neighbours(data, changed_again, chosen)


def test_two_font_variants_each_keep_winansi_and_unicode_resources_when_moved():
    with fitz.open() as doc:
        page = doc.new_page()
        for alias, name, text, x in [
            ("Regular", "LiberationSans-Regular.ttf", "A\u00a0B\u00a0€", 50),
            ("Bold", "LiberationSans-Bold.ttf", "C\u00a0D\u00a0ñ", 180),
        ]:
            page.insert_font(fontname=alias, fontfile=str(ROOT / "assets" / "fonts" / name))
            page.insert_text((x, 100), text, fontname=alias, fontsize=11.375)
        data = doc.tobytes()
    model = model_for(data)
    selected = model.glyphs
    assert len({g.font for g in selected}) == 2
    assert "".join(g.text for g in selected) == "A\u00a0B\u00a0€C\u00a0D\u00a0ñ"
    assert sum(g.text == "\u00a0" for g in selected) == 4
    changed, _ = edit_pdf(data, request_for(model, selected, dx=20.25, dy=30.5))
    assert_moved_once(data, changed, selected, 20.25, 30.5)
    changed_model = model_for(changed)
    assert sorted((g.text, g.font, g.size) for g in changed_model.glyphs) == sorted((g.text, g.font, g.size) for g in selected)
    with fitz.open(stream=changed, filetype="pdf") as doc:
        # One simple and one composite resource per variant; unused original
        # resources may also be present, and are harmless after a full write.
        resources = doc.get_page_fonts(0, full=True)
        # Simple and composite resources may expose different PDF names for
        # the same face. Match their embedded bytes, not a spelling alias.
        types_by_face = {}
        for resource in resources:
            embedded = doc.extract_font(resource[0])[3]
            assert embedded
            types_by_face.setdefault(embedded, set()).add(resource[2])
        assert len(types_by_face) == 2
        assert all(types >= {"TrueType", "Type0"} for types in types_by_face.values())


def test_existing_nbsp_and_soft_hyphen_move_without_unicode_normalization():
    fixture_text = "EXPLICIT\u00a0SOFT\u00adHYPHEN"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_font(fontname="Explicit", fontfile=str(ROOT / "assets" / "fonts" / "LiberationSans-Regular.ttf"))
        page.insert_text((50, 100), fixture_text, fontname="Explicit", fontsize=11.25)
        page.insert_text((300, 100), "NEIGHBOUR", fontname="Explicit", fontsize=11.25)
        data = doc.tobytes()
    model = model_for(data)
    selected = [g for g in model.glyphs if abs(g.origin[1] - 100) < .035 and g.origin[0] < 250]
    original_text = "".join(g.text for g in selected)
    assert original_text == fixture_text
    changed, _ = edit_pdf(data, request_for(model, selected, dx=5, dy=10))
    assert_moved_once(data, changed, selected, 5, 10)
    after = model_for(changed)
    copied_text = "".join(g.text for g in after.glyphs if abs(g.origin[1] - 110) < .035 and g.origin[0] < 250)
    assert copied_text == original_text
    assert_unchanged_neighbours(data, changed, selected)
    # Reproducing an existing glyph is distinct from introducing a new control.
    with pytest.raises(EditError, match="controles"):
        edit_pdf(data, request_for(model, selected, text=original_text, width=180))


def _layout_fixture():
    """Digital Base14 text with room below it and an untouched control page."""
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 80), "Inicio", fontname="helv", fontsize=12.375)
        page.insert_text((350, 80), "VECINO", fontname="hebo", fontsize=10.5)
        page.draw_line((40, 250), (550, 250), color=(.2, .4, .6), width=.75)
        page.insert_text((50, 290), "PIE INALTERADO", fontname="helv", fontsize=10.5)
        control = doc.new_page()
        control.insert_text((50, 80), "PAGINA DE CONTROL", fontname="helv", fontsize=12.375)
        control.draw_rect((50, 120, 300, 250), fill=(.85, .95, .9), color=None)
        return doc.tobytes()


def test_reflow_requires_explicit_height_and_keeps_real_text_font_and_neighbours():
    data = _layout_fixture()
    model, selected = select(data, "Inicio", x=50, y=80)
    replacement = "Uno dos tres cuatro cinco seis siete ocho nueve diez"
    with pytest.raises(EditError, match="supera la altura"):
        edit_pdf(data, request_for(model, selected, text=replacement, width=100, height=18, reflow=True))
    changed, report = edit_pdf(data, request_for(model, selected, text=replacement, width=100, height=100, reflow=True))
    result = model_for(changed)
    body = [g for g in result.glyphs if g.origin[0] < 200 and 79 <= g.origin[1] < 200]
    lines = {}
    for g in body:
        lines.setdefault(round(g.origin[1], 3), []).append(g)
    assert len(lines) > 1
    assert min(lines) == pytest.approx(80, abs=.001)
    line_text = ["".join(g.text for g in sorted(chars, key=lambda g: g.origin[0])) for _, chars in sorted(lines.items())]
    assert " ".join(line_text) == replacement
    for chars in lines.values():
        bounds = union(g.bbox for g in chars)
        assert bounds[0] == pytest.approx(50, abs=.035)
        assert bounds[2] - bounds[0] <= 100 + .035
    assert {g.font for g in body} == {selected[0].font}
    assert all(g.size == pytest.approx(12.375, abs=.001) for g in body)
    with fitz.open(stream=data, filetype="pdf") as before, fitz.open(stream=changed, filetype="pdf") as after:
        assert not after[0].search_for("Inicio")
        assert before[1].get_text() == after[1].get_text()
        assert before[1].get_pixmap(matrix=fitz.Matrix(2, 2)).samples == after[1].get_pixmap(matrix=fitz.Matrix(2, 2)).samples
        assert related(before[0]) == related(after[0])
    independent = PdfReader(BytesIO(changed), strict=True)
    independent_text = " ".join(independent.pages[0].extract_text().split())
    assert replacement in independent_text
    assert len(independent.pages) == 2
    assert all(page["pixels_above_8"] == 0 for page in report["pages"])
    assert_unchanged_neighbours(data, changed, selected)


def test_wider_edit_area_changes_capacity_without_stretching_letters_or_font_size():
    data = _layout_fixture()
    model, selected = select(data, "Inicio", x=50, y=80)
    replacement = "Texto con espacio"
    with pytest.raises(EditError, match="supera el espacio"):
        edit_pdf(data, request_for(model, selected, text=replacement))
    narrow, _ = edit_pdf(data, request_for(model, selected, text=replacement, width=150))
    wide, _ = edit_pdf(data, request_for(model, selected, text=replacement, width=300))
    _, narrow_chars = select(narrow, replacement, x=50, y=80)
    _, wide_chars = select(wide, replacement, x=50, y=80)
    natural = fitz.Font("helv")
    for a, b in zip(narrow_chars, wide_chars, strict=True):
        assert a.origin == pytest.approx(b.origin, abs=.001)
        assert a.size == b.size == pytest.approx(12.375, abs=.001)
        assert a.font == b.font == selected[0].font
        assert a.trace_bbox[2] - a.trace_bbox[0] == pytest.approx(natural.text_length(a.text, fontsize=12.375), abs=.001)
        assert b.trace_bbox[2] - b.trace_bbox[0] == pytest.approx(natural.text_length(b.text, fontsize=12.375), abs=.001)
    with fitz.open(stream=narrow, filetype="pdf") as a, fitz.open(stream=wide, filetype="pdf") as b:
        assert a[0].get_pixmap(matrix=fitz.Matrix(2, 2)).samples == b[0].get_pixmap(matrix=fitz.Matrix(2, 2)).samples
        assert a[1].get_pixmap().samples == b[1].get_pixmap().samples
    assert replacement in PdfReader(BytesIO(wide), strict=True).pages[0].extract_text()
    assert_unchanged_neighbours(data, wide, selected)
