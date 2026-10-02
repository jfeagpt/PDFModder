"""Reproducible, synthetic PDF fixtures. No user documents or system fonts.

Run scripts/generate_examples.py to produce the complete corpus and its manifest.
Coordinates in the manifest are PyMuPDF unrotated page points, with y down.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, ByteStringObject, DictionaryObject, NameObject, NumberObject,
    TextStringObject,
)
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "assets" / "fonts"
PAGE_WIDTH, PAGE_HEIGHT = 595.0, 842.0
FIXED_DATE = "D:20260910000000Z"


def prepare_fonts() -> dict[str, Path]:
    """Use bundled OFL Liberation and copy unmodified Vera for restriction tests."""
    source = Path(reportlab.__file__).resolve().parent / "fonts"
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in ("Vera.ttf", "VeraBd.ttf", "VeraIt.ttf", "VeraBI.ttf"):
        target = FONT_DIR / name
        shutil.copyfile(source / name, target)
        result[name] = target
    # ReportLab ships the original licence beside the font, under this name.
    license_candidates = [source / "bitstream-vera-license.txt", source / "Vera-Copyright.txt"]
    license_source = next((p for p in license_candidates if p.exists()), None)
    if license_source is None:
        raise FileNotFoundError("No se encuentra la licencia Bitstream Vera en ReportLab; no se publican fuentes sin ella.")
    shutil.copyfile(license_source, FONT_DIR / "LICENSE-Bitstream-Vera.txt")
    for name in ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"):
        target = FONT_DIR / name
        if not target.exists():
            raise FileNotFoundError(f"Falta la fuente OFL incluida en el proyecto: {target}")
        result[name] = target
    return result


def _save(doc: fitz.Document, target: Path) -> None:
    doc.set_metadata({
        "title": "PDF Modder - corpus sintético", "author": "PDF Modder",
        "subject": "Datos ficticios para pruebas reproducibles; no es un documento comercial",
        "creator": "PDF Modder corpus.py", "creationDate": FIXED_DATE, "modDate": FIXED_DATE,
    })
    doc.save(target, garbage=4, deflate=True, no_new_id=True)
    doc.close()


def _font(page: fitz.Page, path: Path, name: str = "Corpus") -> None:
    page.insert_font(fontname=name, fontfile=str(path))


def _text(page: fitz.Page, point, text: str, *, name="Corpus", size=11.25, color=(0.08, 0.13, 0.18), **kwargs) -> None:
    page.insert_text(point, text, fontname=name, fontsize=size, color=color, **kwargs)


def _image() -> bytes:
    image = Image.new("RGB", (120, 90), "#e0ebf7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((7, 7, 112, 82), outline="#204660", width=3)
    draw.polygon(((18, 70), (45, 31), (67, 56), (87, 21), (104, 70)), fill="#4b866a")
    draw.ellipse((18, 15, 35, 32), fill="#edc354")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _main(target: Path, fonts: dict[str, Path]) -> None:
    """Full embedded Liberation, coloured table, image, neighbours and 2 pages."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _font(page, fonts["LiberationSans-Regular.ttf"])
    _font(page, fonts["LiberationSans-Bold.ttf"], "CorpusBold")
    page.draw_rect((34, 32, 561, 92), color=None, fill=(0.08, 0.21, 0.30))
    _text(page, (48, 58), "PDF MODDER", name="CorpusBold", size=17.5, color=(1, 1, 1))
    _text(page, (48, 79), "Documento digital de prueba | datos ficticios", size=9.25, color=(0.85, 0.93, 0.97))
    _text(page, (48, 125), "Fecha:", name="CorpusBold")
    _text(page, (125, 125), "10/09/2026")
    _text(page, (330, 125), "Referencia: PRUEBA-001", size=10.5)
    _text(page, (48, 164), "Español: año, piñón, café, útil, acción y 25,50 €")
    _text(page, (48, 197), "TOTAL", name="CorpusBold")
    _text(page, (170, 197), "TOTAL")
    _text(page, (310, 197), "TOTAL")

    table = fitz.Rect(44, 225, 550, 352)
    page.draw_rect(table, fill=(0.92, 0.97, 0.93), color=(0.30, 0.50, 0.39), width=0.8)
    page.draw_rect((44, 225, 550, 255), fill=(0.76, 0.88, 0.79), color=None)
    for y in (255, 303):
        page.draw_line((44, y), (550, y), color=(0.30, 0.50, 0.39), width=0.7)
    page.draw_line((380, 225), (380, 352), color=(0.30, 0.50, 0.39), width=0.7)
    _text(page, (58, 245), "Concepto", name="CorpusBold")
    _text(page, (435, 245), "Importe", name="CorpusBold")
    _text(page, (58, 283), "Semillas de otoño")
    amount = "1.234,56 €"
    face = fitz.Font(fontfile=str(fonts["LiberationSans-Regular.ttf"]))
    _text(page, (530 - face.text_length(amount, fontsize=11.25), 283), amount)
    _text(page, (58, 331), "Texto vecino inalterado")
    _text(page, (439, 331), "250,00 €")
    page.insert_image((443, 369, 539, 441), stream=_image())
    page.draw_line((44, 385), (410, 385), color=(0.2, 0.4, 0.6), width=1.2)
    _text(page, (48, 415), "Mover esta línea conserva su distribución.", size=10.75)
    _text(page, (48, 455), "PALABRA destino libre a la derecha.", size=10.75)
    _text(page, (48, 515), "Columna izquierda: UNO", size=10.5)
    _text(page, (330, 515), "Columna derecha: DOS", size=10.5)
    _text(page, (48, 540), "Grupo uno", size=10.5)
    _text(page, (48, 558), "Grupo dos", size=10.5)
    _text(page, (330, 540), "Vecino de otra columna", size=10.5)
    _text(page, (48, 650), "Enlace de prueba", size=10)
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(48, 637, 145, 654), "uri": "https://example.org/pdf-modder"})
    annotation = page.add_text_annot((515, 645), "Nota independiente de los textos editables.")
    annotation.set_info(title="Corpus PDF Modder", creationDate=FIXED_DATE, modDate=FIXED_DATE)
    annotation.update()
    _text(page, (48, 787), "Página 1 / 2 - los márgenes y elementos de control deben conservarse", size=8.5)

    second = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _font(second, fonts["LiberationSans-Regular.ttf"])
    _text(second, (48, 72), "PÁGINA DE CONTROL SIN EDITAR", size=16)
    _text(second, (48, 120), "10/09/2026 - TOTAL - 1.234,56 €")
    second.draw_rect((48, 145, 547, 710), color=(0.2, 0.3, 0.5), fill=(0.96, 0.97, 0.99), width=1)
    _text(second, (65, 185), "Esta página comparte recursos tipográficos con la primera.")
    second.insert_image((80, 245, 320, 425), stream=_image())
    doc.set_toc([[1, "Documento de prueba", 1], [1, "Página de control", 2]])
    _save(doc, target)


def _rotated(target: Path, fonts: dict[str, Path]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=640, height=880)
    _font(page, fonts["LiberationSans-Regular.ttf"])
    _text(page, (90, 120), "10/09/2026")
    _text(page, (90, 170), "Mover línea rotada")
    page.draw_rect((72, 90, 550, 240), color=(0.2, 0.4, 0.6), width=1)
    page.set_cropbox(fitz.Rect(30, 40, 610, 840))
    page.set_rotation(90)
    _save(doc, target)


def _subset(target: Path, fonts: dict[str, Path]) -> None:
    # ReportLab deliberately embeds a TrueType subset and a ToUnicode map.
    pdfmetrics.registerFont(TTFont("CorpusLiberationSubset", str(fonts["LiberationSans-Regular.ttf"])))
    c = canvas.Canvas(str(target), pagesize=(PAGE_WIDTH, PAGE_HEIGHT), invariant=1, pageCompression=1)
    c.setTitle("Subconjunto incrustado - faltan caracteres nuevos")
    c.setFont("CorpusLiberationSubset", 11.25)
    c.drawString(48, PAGE_HEIGHT - 90, "10/09/2026")
    c.drawString(48, PAGE_HEIGHT - 130, "Texto ASCII de prueba")
    c.showPage()
    c.save()


def _unembedded(target: Path, fonts: dict[str, Path], *, missing: bool) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    font_xref = page.insert_font(fontname="Corpus", fontfile=str(fonts["LiberationSans-Regular.ttf"]), set_simple=True)
    _text(page, (48, 90), "10/09/2026 - Texto sin incrustar")
    descriptor_ref = doc.xref_get_key(font_xref, "FontDescriptor")[1]
    descriptor = int(descriptor_ref.split()[0])
    doc.xref_set_key(descriptor, "FontFile2", "null")
    if missing:
        # A deliberate fixture dictionary mutation, not content-stream replacement.
        doc.xref_set_key(font_xref, "BaseFont", "/PDFModderMissing-Regular")
        doc.xref_set_key(descriptor, "FontName", "/PDFModderMissing-Regular")
        doc.xref_set_key(descriptor, "FontFamily", "(PDF Modder Missing)")
    _save(doc, target)


def _unsupported(target: Path, fonts: dict[str, Path]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _font(page, fonts["LiberationSans-Regular.ttf"])
    _text(page, (48, 80), "Texto normal editable")
    _text(page, (48, 130), "Texto con escala horizontal", morph=(fitz.Point(48, 130), fitz.Matrix(1.3, 1)))
    _text(page, (48, 210), "Texto inclinado", morph=(fitz.Point(48, 210), fitz.Matrix(1, 0.25, 0.15, 1, 0, 0)))
    _text(page, (48, 290), "Texto semitransparente", fill_opacity=0.45)
    _text(page, (48, 360), "Contorno sin relleno", render_mode=1)
    # A neighbour deliberately intersects the target's glyph bounds.
    _text(page, (48, 420), "SOLAPADO")
    _text(page, (48, 422), "VECINO")
    # Same visual line with two independent styles.
    _text(page, (48, 490), "Normal ")
    _font(page, fonts["LiberationSans-Bold.ttf"], "CorpusBold")
    _text(page, (98, 490), "negrita", name="CorpusBold")
    _save(doc, target)


def _form(target: Path, fonts: dict[str, Path]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _font(page, fonts["LiberationSans-Regular.ttf"])
    _text(page, (48, 80), "Formulario: los campos no son texto ordinario")
    widget = fitz.Widget()
    widget.field_name = "importe"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(48, 115, 260, 145)
    widget.field_value = "1234.56"
    widget.text_font = "Helv"
    widget.text_fontsize = 11
    page.add_widget(widget)
    _save(doc, target)


def _signature_marker(source: Path, target: Path) -> None:
    """Invalid, conspicuously labelled signature marker for detection, NOT a signature."""
    with fitz.open(source) as marked:
        _text(marked[0], (48, 205), "MARCADOR DE FIRMA INVALIDO - SOLO PRUEBA", color=(0.7, 0.08, 0.08))
        _text(marked[0], (48, 227), "Este archivo no contiene una firma criptografica valida.", size=10)
        reader = PdfReader(io.BytesIO(marked.tobytes(garbage=4, deflate=True)))
    writer = PdfWriter(clone_from=reader)
    signature = DictionaryObject({
        NameObject("/Type"): NameObject("/Sig"),
        NameObject("/Filter"): NameObject("/Adobe.PPKLite"),
        NameObject("/SubFilter"): NameObject("/adbe.pkcs7.detached"),
        NameObject("/ByteRange"): ArrayObject([NumberObject(0)] * 4),
        NameObject("/Contents"): ByteStringObject(b"SYNTHETIC_INVALID_TEST_SIGNATURE"),
        NameObject("/Reason"): TextStringObject("Marcador sintético inválido para probar detección; NO es una firma criptográfica."),
    })
    field = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Sig"), NameObject("/T"): TextStringObject("FIRMA_SINTETICA_INVALIDA"),
        NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (48, 590, 320, 635)]),
        NameObject("/V"): writer._add_object(signature),
        NameObject("/P"): writer.pages[0].indirect_reference,
        NameObject("/F"): NumberObject(4),
    })
    field_ref = writer._add_object(field)
    page = writer.pages[0]
    page.setdefault(NameObject("/Annots"), ArrayObject()).append(field_ref)
    form = writer.root_object.get("/AcroForm")
    if form is None:
        form = DictionaryObject({NameObject("/Fields"): ArrayObject(), NameObject("/SigFlags"): NumberObject(3)})
        writer.root_object[NameObject("/AcroForm")] = writer._add_object(form)
    else:
        form = form.get_object()
        form[NameObject("/SigFlags")] = NumberObject(3)
    form["/Fields"].append(field_ref)
    with target.open("wb") as stream:
        writer.write(stream)


def _encrypted(source: Path, target: Path, user_password: str) -> None:
    with fitz.open(source) as doc:
        doc.save(target, encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="propietario-pruebas", user_pw=user_password,
                 permissions=fitz.PDF_PERM_PRINT, garbage=4, deflate=True)


def _embedding_restricted(target: Path, fonts: dict[str, Path]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _font(page, fonts["Vera.ttf"])
    _text(page, (48, 90), "Vera: fsType 4, Preview and Print")
    _text(page, (48, 130), "10/09/2026")
    _save(doc, target)


def _manifest(paths: dict[str, Path], target: Path) -> None:
    entries = {}
    for key, path in paths.items():
        with fitz.open(path) as doc:
            if key in {"restricted", "encrypted"}:
                # We generated these files and use their explicit owner credential
                # when extracting the reference manifest, never bypassing a user PDF.
                doc.authenticate("propietario-pruebas")
            pages = []
            for page in doc:
                texts = page.get_text("text")
                regions = {needle: [list(rect) for rect in page.search_for(needle)] for needle in (
                    "10/09/2026", "1.234,56 €", "TOTAL", "PALABRA", "Mover esta línea conserva su distribución.",
                    "Mover línea rotada", "Texto vecino inalterado", "Columna izquierda: UNO", "Columna derecha: DOS",
                    "SOLAPADO", "VECINO", "Texto normal editable",
                ) if needle in texts}
                pages.append({
                    "rotation": page.rotation, "mediabox": list(page.mediabox), "cropbox": list(page.cropbox),
                    "rect": list(page.rect), "text": texts, "regions": regions,
                    "images": len(page.get_images()), "drawings": len(page.get_drawings()),
                    "links": len(page.get_links()), "annotations": len(list(page.annots() or [])),
                    "widgets": len(list(page.widgets() or [])),
                })
            entries[key] = {"file": path.name, "pages": pages, "page_count": len(doc),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    payload = {
        "schema": 1, "coordinates": "PyMuPDF unrotated page points, y down; 72 pt = 25.4 mm",
        "synthetic_only": True,
        "reproducibility": "Geometría, fuentes y contenido estables; cifrado usa aleatoriedad y no se espera identidad binaria.",
        "test_passwords": {"encrypted_user": "lectura-pruebas", "owner": "propietario-pruebas"},
        "fonts": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FONT_DIR.glob("*.ttf")},
        "documents": entries,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def make_corpus(output: Path) -> dict[str, Path]:
    """Generate all fixtures; return stable keys and absolute PDF paths."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    fonts = prepare_fonts()
    names = {
        "main": "digital.pdf", "rotated": "rotated_crop.pdf", "subset": "subset.pdf",
        "local_font": "font_local.pdf", "missing_font": "font_missing.pdf",
        "unsupported": "unsupported_regions.pdf", "form": "form.pdf",
        "signature": "signature_marker_invalid.pdf", "restricted": "restricted.pdf", "encrypted": "encrypted.pdf",
        "embedding_restricted": "font_embedding_restricted.pdf",
    }
    paths = {key: output / name for key, name in names.items()}
    _main(paths["main"], fonts)
    _rotated(paths["rotated"], fonts)
    _subset(paths["subset"], fonts)
    _unembedded(paths["local_font"], fonts, missing=False)
    _unembedded(paths["missing_font"], fonts, missing=True)
    _unsupported(paths["unsupported"], fonts)
    _form(paths["form"], fonts)
    _signature_marker(paths["form"], paths["signature"])
    _encrypted(paths["main"], paths["restricted"], "")
    _encrypted(paths["main"], paths["encrypted"], "lectura-pruebas")
    _embedding_restricted(paths["embedding_restricted"], fonts)
    _manifest(paths, output / "expected.json")
    return paths
