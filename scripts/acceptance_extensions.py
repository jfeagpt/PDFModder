"""Audit real text/image insertion and page transactions with independent renders.

Run directly with the project's Python. Outputs stay in the requested directory;
there is no Session, GUI, native temporary directory or change to the source PDF.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
import pymupdf as fitz
import pypdf
from pypdf import PdfReader

from acceptance_report import (
    CHANNEL_TOLERANCE, DPI, MARGIN_PT, compare_poppler, find_poppler,
    glyph_records, render_poppler,
)
from pdfmodder.composition import AddTextRequest, insert_text_pdf
from pdfmodder.engine import atomic_save
from pdfmodder.media import add_image_pdf, image_items, transform_image_pdf
from pdfmodder.pageops import delete_pages_pdf, extract_pages_pdf, merge_pdfs


ADDED_TEXT = "Añadido en negrita: café, piñón y 25,50 €"
FONT_SIZE = 13.25
TEXT_COLOR = (.55, .05, .12)
INITIAL_IMAGE = (360, 730, 420, 775)
MOVED_IMAGE = (440, 700, 500, 745)
FINAL_IMAGE = (440, 700, 520, 760)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def record_key(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def make_image():
    image = Image.new("RGB", (80, 60), "#c52f3d")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 71, 51), outline="#f9e268", width=5)
    draw.line((0, 59, 79, 0), fill="#183858", width=3)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue(), image.tobytes()


def selected_image(data, rectangle):
    with fitz.open(stream=data, filetype="pdf") as doc:
        matches = [item for item in image_items(doc, 0)
                   if all(abs(a-b) < .035 for a, b in zip(item["rect"], rectangle))]
        assert len(matches) == 1, "Imagen ausente o duplicada en su posición esperada"
        assert matches[0]["editable"], matches[0]["reason"]
        return matches[0]


def added_glyph_boxes(before, after):
    """Use actual new character boxes, never a whole text area or line mask."""
    old_records = glyph_records(before)
    new_records = glyph_records(after)
    counts = Counter(map(record_key, new_records))
    expected = Counter(map(record_key, old_records))
    assert not (expected - counts), "Se alteró un carácter original o su formato"
    additions = counts - expected
    assert sum(additions.values()) == len(ADDED_TEXT)
    found, boxes = [], []
    index = 0
    with fitz.open(stream=after, filetype="pdf") as doc:
        for span in doc[0].get_texttrace():
            for char in span["chars"]:
                record = new_records[index]
                index += 1
                key = record_key(record)
                if additions[key]:
                    additions[key] -= 1
                    found.append(record)
                    boxes.append(list(char[3]))
    assert "".join(record["text"] for record in found) == ADDED_TEXT
    assert all("Bold" in record["font"] for record in found), "No se utilizó la variante negrita real"
    assert all(abs(record["size"]-FONT_SIZE) < .001 for record in found)
    assert all(all(abs(a-b) < .0001 for a, b in zip(record["color"], TEXT_COLOR)) for record in found)
    return boxes, {"preserved_original_characters": len(old_records),
                   "new_characters": len(found), "font": found[0]["font"],
                   "size_pt": FONT_SIZE, "color_rgb": TEXT_COLOR}


def execute(source, output, poppler):
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    source_sha = digest(source_bytes)
    original_reader = PdfReader(io.BytesIO(source_bytes), strict=True)
    assert len(original_reader.pages) == 2, "Este recorrido requiere el corpus digital.pdf de dos páginas"
    operations = []
    original_path = output / "original.pdf"
    assert original_path.resolve() != source.resolve(), "La salida debe estar separada del PDF fuente"
    original_path.write_bytes(source_bytes)

    font_path = ROOT / "assets/fonts/LiberationSans-Bold.ttf"
    request = AddTextRequest(0, 48, 690, 380, 30, ADDED_TEXT,
                             font_name="LiberationSans-Bold", font_file=str(font_path),
                             size=FONT_SIZE, color=TEXT_COLOR, reflow=False,
                             revision=source_sha)
    state, report = insert_text_pdf(source_bytes, request)
    boxes, text_checks = added_glyph_boxes(source_bytes, state)
    text_state = state
    (output / "01-texto.pdf").write_bytes(state)
    operations.append({"operation": "insert_text", "checks": text_checks, "engine_report": report})

    png, rgb = make_image()
    (output / "imagen.png").write_bytes(png)
    state, report = add_image_pdf(state, 0, png, INITIAL_IMAGE, revision=digest(state))
    (output / "02-imagen.pdf").write_bytes(state)
    operations.append({"operation": "add_image", "rect_pt": INITIAL_IMAGE, "engine_report": report})
    for label, old, new in (("move_image", INITIAL_IMAGE, MOVED_IMAGE),
                             ("resize_image", MOVED_IMAGE, FINAL_IMAGE)):
        item = selected_image(state, old)
        state, report = transform_image_pdf(state, 0, item["id"], new, revision=digest(state))
        operations.append({"operation": label, "source_rect_pt": old,
                           "destination_rect_pt": new, "engine_report": report})
    (output / "03-imagen-transformada.pdf").write_bytes(state)
    selected_image(state, FINAL_IMAGE)
    assert glyph_records(state) == glyph_records(text_state), "La imagen alteró caracteres"

    extracted, report = extract_pages_pdf(state, [1])
    extracted_path = output / "extraidas.pdf"
    atomic_save(extracted, extracted_path, source)
    extracted = extracted_path.read_bytes()
    operations.append({"operation": "extract_page_2", "engine_report": report})
    state, report = delete_pages_pdf(state, [1])
    (output / "04-pagina-eliminada.pdf").write_bytes(state)
    assert len(PdfReader(io.BytesIO(state)).pages) == 1
    operations.append({"operation": "delete_page_2", "engine_report": report})
    state, report = merge_pdfs(state, [extracted])
    operations.append({"operation": "merge_extracted_page", "engine_report": report})

    destination = output / "final.pdf"
    atomic_save(state, destination, source)
    reopened = destination.read_bytes()
    assert glyph_records(reopened) == glyph_records(text_state), "Guardar o reorganizar alteró el texto de página 1"
    assert glyph_records(reopened, 1) == glyph_records(source_bytes, 1)
    assert glyph_records(extracted) == glyph_records(source_bytes, 1)
    for number in (0, 1):
        assert glyph_records(state, number) == glyph_records(reopened, number)

    selected_image(reopened, FINAL_IMAGE)
    with fitz.open(stream=reopened, filetype="pdf") as doc:
        infos = doc[0].get_image_info(hashes=True, xrefs=True)
        assert len(infos) == 2, "Se perdió la imagen original o se duplicó la añadida"
        inserted = [info for info in infos if all(abs(a-b)<.035 for a,b in zip(info["bbox"], FINAL_IMAGE))]
        assert len(inserted) == 1 and inserted[0]["width"] == 80 and inserted[0]["height"] == 60
        pixmap = fitz.Pixmap(doc, inserted[0]["xref"])
        assert pixmap.n == 3 and pixmap.samples == rgb, "Mover/redimensionar cambió los píxeles de la imagen"
        image_digest = digest(pixmap.samples)

    reader = PdfReader(io.BytesIO(reopened), strict=True)
    extracted_reader = PdfReader(io.BytesIO(extracted), strict=True)
    assert len(reader.pages) == 2 and len(extracted_reader.pages) == 1
    texts = [page.extract_text() for page in reader.pages]
    assert texts[0].count(ADDED_TEXT) == 1
    assert texts[0].replace(ADDED_TEXT, "").strip() == original_reader.pages[0].extract_text().strip()
    assert texts[1] == extracted_reader.pages[0].extract_text() == original_reader.pages[1].extract_text()

    stderr = [render_poppler(poppler, original_path, output / "antes"),
              render_poppler(poppler, destination, output / "despues"),
              render_poppler(poppler, extracted_path, output / "extraida")]
    excluded = [*boxes, list(FINAL_IMAGE)]
    with fitz.open(stream=source_bytes, filetype="pdf") as original:
        comparisons = [
            {"comparison": "original_1_vs_final_1", **compare_poppler(
                output / "antes-1.png", output / "despues-1.png", excluded, original[0].rotation_matrix)},
            {"comparison": "original_2_vs_final_2", **compare_poppler(
                output / "antes-2.png", output / "despues-2.png", [], original[1].rotation_matrix)},
            {"comparison": "original_2_vs_extracted_1", **compare_poppler(
                output / "antes-2.png", output / "extraida-1.png", [], original[1].rotation_matrix)},
        ]
    assert digest(source.read_bytes()) == source_sha, "Se ha modificado el archivo original"
    version = subprocess.run([str(poppler), "-v"], capture_output=True,
                             text=True, errors="replace", check=True).stderr.strip()
    return {"verified": True, "scope": "Corpus digital sintético de dos páginas; no archivos reales del usuario.",
            "platform": platform.platform(), "python": platform.python_version(),
            "pymupdf": fitz.VersionBind, "pypdf": pypdf.__version__, "poppler": version,
            "source": str(source), "destination": str(destination), "extracted": str(extracted_path),
            "source_sha256": source_sha, "destination_sha256": digest(reopened),
            "extracted_sha256": digest(extracted), "font_sha256": digest(font_path.read_bytes()),
            "source_unchanged": True, "saved_preview_identical_characters": True,
            "elapsed_seconds": round(time.perf_counter()-started, 3), "operations": operations,
            "image_checks": {"pixel_size": [80,60], "rgb_sha256": image_digest,
                             "pixels_identical_to_generated_png": True, "final_rect_pt": FINAL_IMAGE},
            "pypdf_text": texts, "pypdf_text_checks_passed": True,
            "extractor_note": "pypdf contrasta el texto escrito por MuPDF, pero también interviene en la copia de páginas. Poppler es el renderizador independiente de toda la cadena.",
            "poppler_stderr": stderr, "poppler_comparisons": comparisons,
            "mask_policy": {"rectangles": "Sólo caracteres nuevos individuales y rectángulo final de la imagen; no se excluyen las posiciones intermedias de la imagen.",
                            "rectangles_pt": excluded, "margin_pt": MARGIN_PT,
                            "dpi": DPI, "channel_tolerance_255": CHANNEL_TOLERANCE,
                            "justification": "0,75 pt = 1,5 px a 144 ppp para antialias; se permiten diferencias de hasta 8/255 fuera de máscara. La página 2 final y extraída exigen identidad exacta sin máscaras."}}


def main():
    parser = argparse.ArgumentParser(description="Aceptación independiente: texto añadido, imágenes y páginas")
    parser.add_argument("--source", type=Path, default=ROOT / "examples/digital.pdf")
    parser.add_argument("--output", type=Path, default=ROOT / "output/acceptance-extensions")
    parser.add_argument("--poppler")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        report = execute(args.source.resolve(), args.output.resolve(), find_poppler(args.poppler))
    except Exception as error:
        report = {"verified": False, "error": str(error), "traceback": traceback.format_exc(),
                  "elapsed_seconds": round(time.perf_counter()-started, 3)}
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verified": report["verified"], "report": str(report_path),
                      "elapsed_seconds": report["elapsed_seconds"], "error": report.get("error")},
                     ensure_ascii=True))
    if not report["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
