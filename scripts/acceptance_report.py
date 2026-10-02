"""Run a reproducible edit/save/reopen audit and independent Poppler comparison.

No mask is based on a whole line or block: all excluded rectangles are individual
source/destination glyph bounds returned by each of the four transactions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image
import pymupdf as fitz
import pypdf
from pypdf import PdfReader

from pdfmodder.engine import atomic_save, edit_pdf, extract_page
from pdfmodder.model import EditRequest, union


DPI = 144
MARGIN_PT = .75
CHANNEL_TOLERANCE = 8
ORIGIN_TOLERANCE = .035


def normalized_label(text):
    # Match a fixture label only. Content preservation below compares the actual
    # code points, including NBSP, and does not normalize retained characters.
    return text.replace("\u00a0", " ")


def page_model(data, number=0):
    with fitz.open(stream=data, filetype="pdf") as doc:
        return extract_page(doc, number, data)


def select(data, label, y, x=None):
    model = page_model(data)
    text = normalized_label("".join(g.text for g in model.glyphs))
    offset = 0
    while True:
        index = text.find(label, offset)
        if index < 0:
            raise AssertionError(f"No se encuentra {label!r} en la línea base y={y}, x={x}")
        glyphs = model.glyphs[index:index + len(label)]
        first = glyphs[0]
        if abs(first.origin[1] - y) < .05 and (x is None or abs(first.origin[0] - x) < .05):
            return model, glyphs
        offset = index + 1


def glyph_records(data, page=0):
    # Read directly from PDF texttrace instead of invoking engine validation.
    with fitz.open(stream=data, filetype="pdf") as doc:
        return [{"text": chr(char[0]), "origin": list(char[2]), "font": span["font"],
                 "size": float(span["size"]), "opacity": float(span["opacity"]),
                 "color": list(span["color"]), "direction": list(span["dir"]), "mode": span["type"]}
                for span in doc[page].get_texttrace() for char in span["chars"]]


def same_origin(a, b):
    return abs(a[0] - b[0]) < ORIGIN_TOLERANCE and abs(a[1] - b[1]) < ORIGIN_TOLERANCE


def verify_neighbours(before, after, selected):
    selected_origins = [(g.text, g.origin) for g in selected]
    original = glyph_records(before)
    remaining = [r for r in original if not any(r["text"] == c and same_origin(r["origin"], p) for c, p in selected_origins)]
    actual = glyph_records(after)
    for expected in remaining:
        matches = [r for r in actual if r["text"] == expected["text"] and same_origin(r["origin"], expected["origin"])]
        assert len(matches) == 1, f"Vecino perdido o duplicado: {expected}"
        match = matches[0]
        for prop in ("font", "color", "direction", "mode"):
            assert match[prop] == expected[prop], f"Formato de vecino alterado: {prop}"
        assert abs(match["size"] - expected["size"]) < .001
        assert abs(match["opacity"] - expected["opacity"]) < .0001
    return len(remaining)


def find_poppler(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("POPPLER_BIN"):
        candidates.append(Path(os.environ["POPPLER_BIN"]) / "pdftoppm.exe")
    located = shutil.which("pdftoppm")
    if located:
        candidates.append(Path(located))
    candidates.append(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe")
    for candidate in candidates:
        if candidate.is_dir():
            candidate = candidate / ("pdftoppm.exe" if os.name == "nt" else "pdftoppm")
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No se encuentra Poppler. Instala pdftoppm y usa --poppler RUTA o POPPLER_BIN.")


def render_poppler(tool, pdf, prefix):
    result = subprocess.run([str(tool), "-cropbox", "-r", str(DPI), "-png", str(pdf), str(prefix)],
                            capture_output=True, text=True, errors="replace", check=True)
    return result.stderr.strip()


def compare_poppler(before, after, rects, matrix):
    a = np.asarray(Image.open(before).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(after).convert("RGB"), dtype=np.int16)
    assert a.shape == b.shape, "Poppler detecta dimensiones de imagen diferentes"
    delta = np.abs(a - b).max(axis=2)
    mask = np.ones(delta.shape, dtype=bool)
    scale = DPI / 72
    pixel_regions = []
    for coordinates in rects:
        r = (fitz.Rect(coordinates) + (-MARGIN_PT, -MARGIN_PT, MARGIN_PT, MARGIN_PT)) * matrix
        left, top = math.floor(r.x0 * scale), math.floor(r.y0 * scale)
        right, bottom = math.ceil(r.x1 * scale), math.ceil(r.y1 * scale)
        left, right = max(0, left), min(a.shape[1], right)
        top, bottom = max(0, top), min(a.shape[0], bottom)
        mask[top:bottom, left:right] = False
        pixel_regions.append([left, top, right, bottom])
    values = delta[mask]
    result = {
        "width_px": a.shape[1], "height_px": a.shape[0], "dpi": DPI,
        "checked_pixels": int(mask.sum()), "excluded_pixels": int((~mask).sum()),
        "excluded_percent": round(float((~mask).mean() * 100), 6),
        "max_channel_delta_outside_mask": int(values.max()) if values.size else 0,
        "pixels_different_outside_mask": int(np.count_nonzero(values)),
        "pixels_above_8_outside_mask": int(np.count_nonzero(values > CHANNEL_TOLERANCE)),
        "total_changed_pixels": int(np.count_nonzero(delta)),
        "mask_rectangles_px": pixel_regions,
    }
    assert result["pixels_above_8_outside_mask"] == 0, f"Poppler: daño fuera de caracteres editados: {result}"
    if not rects:
        assert result["max_channel_delta_outside_mask"] == 0, "La página de control no es idéntica píxel a píxel"
    return result


def execute(source, output, poppler):
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    state = source_bytes
    operations, excluded = [], []
    recipes = [
        ("fecha", "10/09/2026", 125, 125, {"text": "11/09/2026"}),
        ("importe", "1.234,56 €", 283, None, {"text": "12.345,67 €", "width": 180, "anchor": "right"}),
        ("palabra", "PALABRA", 455, 48, {"text": "VOCABLO", "width": 70, "anchor": "right"}),
        ("mover_linea", "Mover esta línea conserva su distribución.", 415, 48, {"dx": 10, "dy": 15}),
    ]
    movement_label = None
    for name, label, baseline, x, params in recipes:
        model, selected = select(state, label, baseline, x)
        actual_text = "".join(g.text for g in selected)
        before = state
        state, engine_report = edit_pdf(state, EditRequest(0, [g.id for g in selected], revision=model.revision, **params))
        neighbours_checked = verify_neighbours(before, state, selected)
        excluded.extend(engine_report["source_regions"])
        excluded.extend(engine_report["destination_regions"])
        verification = {"unchanged_neighbours_checked": neighbours_checked}
        if name == "importe":
            _, new_glyphs = select(state, params["text"], baseline)
            edge_before, edge_after = union(g.bbox for g in selected)[2], union(g.bbox for g in new_glyphs)[2]
            assert abs(edge_after - edge_before) < ORIGIN_TOLERANCE
            verification.update(right_edge_before_pt=edge_before, right_edge_after_pt=edge_after)
        if name == "fecha":
            _, new_glyphs = select(state, params["text"], baseline, x)
            assert same_origin(new_glyphs[0].origin, selected[0].origin)
            assert all(abs(g.size - 11.25) < .001 for g in new_glyphs)
        if name == "mover_linea":
            movement_label = actual_text
            records = glyph_records(state)
            for g in selected:
                old = [r for r in records if r["text"] == g.text and same_origin(r["origin"], g.origin)]
                destination = (g.origin[0] + params["dx"], g.origin[1] + params["dy"])
                new = [r for r in records if r["text"] == g.text and same_origin(r["origin"], destination)]
                assert not old and len(new) == 1, "Movimiento deja un origen residual o un destino duplicado"
            verification["moved_characters_checked"] = len(selected)
        operations.append({"operation": name, "selection_original_codepoints": actual_text,
                           "parameters": params, "checks": verification, "engine_report": engine_report})

    destination = output / "edicion.pdf"
    atomic_save(state, destination, source)
    reopened = destination.read_bytes()
    # Saving must preserve the same content as the final real-PDF preview.
    for page_number in (0, 1):
        assert glyph_records(state, page_number) == glyph_records(reopened, page_number)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha

    independent = PdfReader(io.BytesIO(reopened), strict=True)
    original_reader = PdfReader(io.BytesIO(source_bytes), strict=True)
    assert len(independent.pages) == len(original_reader.pages) == 2
    texts = [p.extract_text() for p in independent.pages]
    text0 = normalized_label(texts[0])
    assert text0.count("11/09/2026") == 1 and "10/09/2026" not in text0
    assert text0.count("12.345,67 €") == 1 and "1.234,56 €" not in text0
    assert text0.count("VOCABLO") == 1 and "PALABRA" not in text0
    assert text0.count(normalized_label(movement_label)) == 1
    assert text0.count("TOTAL") == 3
    assert texts[1] == original_reader.pages[1].extract_text()

    before_path = output / "original.pdf"
    before_path.write_bytes(source_bytes)
    stderr_before = render_poppler(poppler, before_path, output / "antes")
    stderr_after = render_poppler(poppler, destination, output / "despues")
    image_report = []
    with fitz.open(stream=source_bytes, filetype="pdf") as before_doc, fitz.open(destination) as after_doc:
        for number, page in enumerate(before_doc):
            after_page = after_doc[number]
            assert tuple(page.mediabox) == tuple(after_page.mediabox)
            assert tuple(page.cropbox) == tuple(after_page.cropbox)
            assert page.rotation == after_page.rotation
            image_report.append(compare_poppler(output / f"antes-{number+1}.png", output / f"despues-{number+1}.png",
                                                 excluded if number == 0 else [], page.rotation_matrix))

    version = subprocess.run([str(poppler), "-v"], capture_output=True, text=True, errors="replace").stderr.strip()
    return {
        "verified": True, "scope": "Cuatro operaciones encadenadas en corpus digital sintético; no archivos reales del usuario.",
        "platform": platform.platform(), "python": platform.python_version(), "pymupdf": fitz.VersionBind,
        "pypdf": pypdf.__version__, "poppler": version, "source": str(source), "destination": str(destination),
        "source_sha256": source_sha, "destination_sha256": hashlib.sha256(reopened).hexdigest(),
        "source_unchanged": True, "saved_preview_identical_characters": True,
        "elapsed_seconds": round(time.perf_counter() - started, 3), "operations": operations,
        "independent_text": texts, "independent_text_checks_passed": True,
        "poppler_stderr": [stderr_before, stderr_after], "poppler_pages": image_report,
        "mask_policy": {"rectangles": "Per-character source plus destination, every operation included",
                        "rectangles_pt": excluded, "margin_pt": MARGIN_PT, "channel_tolerance_255": CHANNEL_TOLERANCE,
                        "justification": "0,75 pt = 1,5 px a 144 ppp para bordes antialias; 8/255 permite redondeo leve. Cero píxeles por encima fuera de máscara. Página 2 exige identidad exacta."},
    }


def write_markdown(report, target):
    if not report.get("verified"):
        target.write_text("# Resultado de aceptación independiente\n\nLa ejecución falló; no se declara aceptación.\n\n````\n" + report.get("error", "Error") + "\n````\n", encoding="utf-8")
        return
    lines = ["# Resultado de aceptación independiente", "", "Resultado: **PASS**, medido sobre el corpus sintético indicado en `output/acceptance/report.json`.", "",
             "Se cambió la fecha a 11/09/2026, el importe a 12.345,67 € con ancho explícito de 180 pt y anclaje derecho, PALABRA a VOCABLO con ancho explícito de 70 pt y anclaje derecho, y se movió una línea +10 pt en X, +15 pt en Y. VOCABLO es más largo: el anclaje derecho lo amplía hacia el margen izquierdo libre conservando el espacio y el texto vecino. Se guardó una copia y se reabrió.", "",
             f"Ejecución: {report['platform']}; Python {report['python']}; PyMuPDF {report['pymupdf']}; pypdf {report['pypdf']}. Tiempo total medido: {report['elapsed_seconds']} s.", "",
             "La extracción independiente pypdf confirma los cambios, tres TOTAL legítimos en página 1 y la página 2 sin cambios. Cada operación comprueba caracteres vecinos, incluidos los que se encuentran dentro de las regiones excluidas del análisis visual. Cada carácter movido desaparece del origen y existe una sola vez en el destino. El archivo original conserva su SHA-256.", "",
             "| Página | Píxeles comprobados | Excluidos | Máximo cambio fuera de máscara | Píxeles > 8/255 |", "|---|---:|---:|---:|---:|"]
    for n, stats in enumerate(report["poppler_pages"], 1):
        lines.append(f"| {n} | {stats['checked_pixels']} | {stats['excluded_percent']} % | {stats['max_channel_delta_outside_mask']} | {stats['pixels_above_8_outside_mask']} |")
    lines.extend(["", "Poppler usa `-cropbox -r 144`. Solo se excluyen las cajas de los caracteres originales y nuevos de las cuatro operaciones, ampliadas 0,75 pt; no líneas, bloques ni páginas completas. El umbral 8/255 permite redondeo leve del antialias. La página 2 exige identidad exacta píxel a píxel sin exclusiones.", "",
                  "Reproducir: `.\\.venv\\Scripts\\python.exe scripts\\acceptance_report.py`. Si Poppler no se descubre automáticamente, indicar `--poppler RUTA_A_PDFTOPPM`.", "",
                  "Este informe solo acredita estas operaciones y este corpus. No mide compatibilidad universal ni valida firmas criptográficas reales; los demás escenarios se comprueban en las pruebas automatizadas del proyecto.", ""])
    target.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Aceptación independiente del PDF exportado")
    parser.add_argument("--source", type=Path, default=ROOT / "examples/digital.pdf")
    parser.add_argument("--output", type=Path, default=ROOT / "output/acceptance")
    parser.add_argument("--poppler")
    parser.add_argument("--report-doc", type=Path, default=ROOT / "docs/RESULTADOS_CORPUS.md")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = execute(args.source.resolve(), args.output.resolve(), find_poppler(args.poppler))
    except Exception as error:
        report = {"verified": False, "error": str(error), "traceback": traceback.format_exc()}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report_doc.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(report, args.report_doc)
    print(json.dumps({"verified": report["verified"], "report": str(args.output / "report.json"),
                      "error": report.get("error"), "elapsed_seconds": report.get("elapsed_seconds")}, ensure_ascii=True))
    if not report["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
