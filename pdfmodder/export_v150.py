"""Exportaciones locales; llamar desde el proceso PDF, nunca desde la GUI.

API contrastada con PyMuPDF 1.26.7 y la documentación oficial de Page y Pixmap.
La autorización y protección del documento de origen corresponde a Session.
No se utiliza OCR, red ni conversión a Word.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import tempfile

import pymupdf as fitz

from .model import EditError


MAX_PAGE_PIXELS = 40_000_000
FORMATS = {"txt", "png", "jpeg", "svg"}


class ExportError(EditError):
    """Incluye archivos completos publicados si falló una exportación múltiple."""

    def __init__(self, message, files=None):
        self.files = list(files or [])
        if self.files:
            message += " Archivos completos ya exportados: " + "; ".join(self.files)
        super().__init__(message)


def _destination(value, fmt):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ExportError("Elige un destino para la exportación.")
    raw = str(value)
    if any(ord(char) < 32 for char in raw):
        raise ExportError("El destino contiene caracteres de control no válidos.")
    input_path = Path(raw)
    # Windows treats reserved names, trailing periods/spaces and alternate data
    # streams differently from ordinary filenames. Do not create those paths.
    for component in input_path.parts:
        if component == input_path.anchor or component in {".", ".."}:
            continue
        stem = component.split(".", 1)[0].upper()
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                    *(f"LPT{n}" for n in range(1, 10))}
        if (component.endswith((".", " ")) or any(c in component for c in '<>:"|?*')
                or stem in reserved):
            raise ExportError("El destino contiene un nombre de archivo no válido en Windows.")
    path = Path(os.path.abspath(raw))
    if path.is_symlink():
        raise ExportError("Elige un destino que no sea un enlace simbólico.")
    if fmt == "txt":
        if path.suffix.lower() != ".txt":
            raise ExportError("El archivo de texto debe tener la extensión .txt.")
        if os.path.lexists(path):
            raise ExportError(f"El destino ya existe; elige otro nombre: {path}")
        if not path.parent.is_dir():
            raise ExportError("La carpeta de destino no existe.")
    elif path.exists():
        if not path.is_dir():
            raise ExportError("Para exportar páginas el destino debe ser una carpeta.")
    elif not path.parent.is_dir():
        raise ExportError("La carpeta superior de destino no existe.")
    return path


def _stage(parent, write):
    """Write and flush one complete output, keeping its temporary path private."""
    fd, name = tempfile.mkstemp(prefix=".pdfmodder-export-", suffix=".tmp", dir=parent)
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _publish(temporary, destination):
    # Windows rename refuses an existing destination. POSIX rename overwrites;
    # link is instead an atomic create-if-absent on the same filesystem.
    if os.name == "nt":
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)
        temporary.unlink()


def _file_report(temporary, destination, page=None, dimensions=None):
    digest = hashlib.sha256()
    with temporary.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    result = {"path": str(destination), "bytes": temporary.stat().st_size,
              "sha256": digest.hexdigest()}
    if page is not None:
        result["page"] = page
        result["page_number"] = page + 1
    if dimensions:
        result.update(dimensions)
    return result


def export_document(data: bytes, destination: str, format: str,
                    pages: list[int] | None = None, dpi: int = 144) -> dict:
    """Export selected 0-based pages in the supplied order, without overwriting.

    TXT writes one UTF-8 file with form-feed page separators. Other formats write
    ``pagina-0001.ext`` etc. into the destination directory; numbering references
    the source page. All pages are staged before publishing any file. Publication
    is atomic per file, not across a group; an exceptional commit failure retains
    completed outputs and reports their paths via ``ExportError.files``.
    """
    if not isinstance(data, bytes) or not data:
        raise ExportError("No hay datos PDF para exportar.")
    if not isinstance(format, str):
        raise ExportError("Formato no válido; elige TXT, PNG, JPEG o SVG.")
    fmt = {"text": "txt", "texto": "txt", "jpg": "jpeg"}.get(format.lower(), format.lower())
    if fmt not in FORMATS:
        raise ExportError("Formato no admitido; elige TXT, PNG, JPEG o SVG.")
    if type(dpi) is not int or not 36 <= dpi <= 600:
        raise ExportError("La resolución debe ser un entero entre 36 y 600 ppp.")
    destination_path = _destination(destination, fmt)
    staged = []
    published = []
    reports = []
    warnings = []
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if not doc.is_pdf or doc.is_encrypted:
                raise ExportError("El PDF debe estar abierto con sus credenciales antes de exportar.")
            if not doc.page_count:
                raise ExportError("El PDF no contiene páginas.")
            source_page_count = doc.page_count
            selected = list(range(doc.page_count)) if pages is None else pages
            if (not isinstance(selected, list) or not selected
                    or any(type(n) is not int or not 0 <= n < doc.page_count for n in selected)):
                raise ExportError("Selecciona páginas válidas del documento.")
            if len(selected) != len(set(selected)):
                raise ExportError("La selección contiene páginas repetidas.")
            selected = list(selected)
            ext = "jpg" if fmt == "jpeg" else fmt
            targets = ([destination_path] if fmt == "txt" else
                       [destination_path / f"pagina-{number + 1:04d}.{ext}" for number in selected])
            for target in targets:
                if os.path.lexists(target):
                    raise ExportError(f"El destino ya existe; elige otra carpeta o nombre: {target}")
            if fmt in {"png", "jpeg"}:
                for number in selected:
                    rect = doc[number].rect
                    width, height = math.ceil(rect.width * dpi / 72), math.ceil(rect.height * dpi / 72)
                    if width <= 0 or height <= 0 or width * height > MAX_PAGE_PIXELS:
                        raise ExportError(f"Página {number + 1}: reduce la resolución; supera el límite de 40 millones de píxeles.")
            if fmt != "txt":
                destination_path.mkdir(exist_ok=True)
            if fmt == "txt":
                def write_text(stream):
                    for index, number in enumerate(selected):
                        if index:
                            stream.write(b"\n\f\n")
                        stream.write(doc[number].get_text("text", sort=True).encode("utf-8"))
                temporary = _stage(destination_path.parent, write_text)
                staged.append(temporary)
                reports.append(_file_report(temporary, destination_path))
                warnings.append("TXT contiene texto extraído, sin imágenes ni formato; el orden de lectura en columnas y tablas puede variar. No se realiza OCR.")
            else:
                for number, target in zip(selected, targets):
                    page = doc[number]
                    dimensions = {"width_pt": float(page.rect.width), "height_pt": float(page.rect.height)}
                    if fmt == "svg":
                        payload = page.get_svg_image(text_as_path=True).encode("utf-8")
                    else:
                        pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False, annots=True)
                        dimensions.update(width_px=pixmap.width, height_px=pixmap.height)
                        payload = pixmap.tobytes(output=fmt, jpg_quality=95)
                        del pixmap
                    temporary = _stage(target.parent, lambda stream: stream.write(payload))
                    staged.append(temporary)
                    reports.append(_file_report(temporary, target, number, dimensions))
                    del payload
                if fmt == "svg":
                    warnings.append("SVG conserva dibujos vectoriales; los caracteres se convierten en contornos para evitar sustituciones de fuente y dejan de ser texto seleccionable. Las imágenes siguen siendo mapas de bits. No conserva etiquetas, vínculos ni formularios interactivos; los efectos PDF pueden variar según el visor SVG.")
                else:
                    warnings.append("Las páginas exportadas son imágenes RGB con fondo blanco y anotaciones visibles; pierden texto seleccionable, vectores e interactividad.")
                    if fmt == "jpeg":
                        warnings.append("JPEG utiliza compresión con pérdida (calidad 95); PNG conserva mejor textos y líneas.")
        for temporary, target in zip(staged, targets):
            _publish(temporary, target)
            published.append(str(target))
        return {"format": fmt, "destination": str(destination_path), "pages": selected,
                "page_numbers": [n + 1 for n in selected], "source_page_count": source_page_count,
                "dpi": dpi if fmt in {"png", "jpeg"} else None,
                "files": reports, "warnings": warnings, "atomic_per_file": True,
                "source_unchanged": True}
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"No se pudo completar la exportación: {exc}", published) from exc
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
