"""Resolución conservadora de fuentes; nunca recurre a fuentes de sustitución.

El nombre PostScript es una condición de búsqueda, no una prueba de identidad.
El motor debe verificar además métricas y apariencia contra el PDF original.
Las restricciones OS/2 se respetan; no se modifican ni se eliminan permisos.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from fontTools.ttLib import TTFont, TTLibError
import pymupdf


class FontError(ValueError):
    """La operación necesita una fuente que no puede resolverse con fidelidad."""


# Sólo los nombres PDF estándar y sus abreviaturas documentadas por PyMuPDF.
# Arial, Liberation Sans, Nimbus Sans, etc. NO se equiparan a Helvetica.
BASE14 = {
    "Helvetica": "helv", "Helvetica-Bold": "hebo",
    "Helvetica-Oblique": "heit", "Helvetica-BoldOblique": "hebi",
    "Times-Roman": "tiro", "Times-Bold": "tibo",
    "Times-Italic": "tiit", "Times-BoldItalic": "tibi",
    "Courier": "cour", "Courier-Bold": "cobo",
    "Courier-Oblique": "coit", "Courier-BoldOblique": "cobi",
    "Symbol": "symb", "ZapfDingbats": "zadb",
}
_BASE14_ALIASES = {**BASE14, **{alias: alias for alias in BASE14.values()}}
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_PDF_ESCAPE = re.compile(r"#([0-9A-Fa-f]{2})")
_PERMISSIONS_URL = "https://learn.microsoft.com/en-us/typography/opentype/spec/os2#fstype"


def normalized_name(name: str) -> str:
    """Decodifica nombres PDF y elimina exclusivamente el prefijo de subconjunto."""
    return _SUBSET.sub("", _PDF_ESCAPE.sub(lambda m: chr(int(m[1], 16)), name.lstrip("/")))


def _variant(name: str) -> str:
    low = name.casefold()
    bold = any(part in low for part in ("bold", "negrita", "black", "demi", "semibold"))
    italic = any(part in low for part in ("italic", "oblique", "cursiva"))
    return "negrita cursiva" if bold and italic else "negrita" if bold else "cursiva" if italic else "regular"


def _names(tt: TTFont, name_id: int) -> list[str]:
    result: list[str] = []
    if "name" in tt:
        for entry in tt["name"].names:
            if entry.nameID == name_id:
                try:
                    value = entry.toUnicode().strip()
                except (UnicodeError, LookupError):
                    continue
                if value and value not in result:
                    result.append(value)
    return result


def _first_name(tt: TTFont, *ids: int) -> str | None:
    for name_id in ids:
        found = _names(tt, name_id)
        if found:
            return found[0]
    return None


def _font_metadata(buffer: bytes, fallback_name: str) -> dict[str, Any]:
    """Metadatos SFNT si están presentes; no presume permisos de CFF/Type1."""
    result: dict[str, Any] = {
        "name": fallback_name,
        "family": None,
        "variant": _variant(fallback_name),
        "version": None,
        "postscript_name": None,
        "sha256": sha256(buffer).hexdigest(),
        "byte_length": len(buffer),
        "glyph_count": None,
        "glyph_count_basis": "Tabla maxp: entradas de glifo; no equivale a caracteres Unicode disponibles",
        "unicode_cmap": None,
        "cmap_tables": [],
        "table_tags": [],
        "variant_source": "nombre declarado en el PDF",
        "available_characters": None,
        "available_count": None,
        "fs_type": None,
        "os2_version": None,
        "embedding_permission": "desconocida",
        "license": None,
        "license_url": None,
        "manufacturer_url": None,
        "permissions_url": _PERMISSIONS_URL,
        "identity_verified": False,
    }
    try:
        with TTFont(BytesIO(buffer), lazy=False) as tt:
            variant = _first_name(tt, 17, 2)
            result.update({
                "family": _first_name(tt, 16, 1),
                "variant": variant or _variant(fallback_name),
                "variant_source": "tabla name del programa" if variant else "nombre declarado en el PDF",
                "version": _first_name(tt, 5),
                "postscript_name": _first_name(tt, 6),
                "license": _first_name(tt, 13),
                "license_url": _first_name(tt, 14),
                "manufacturer_url": _first_name(tt, 11),
                "variable": "fvar" in tt,
                "glyph_count": int(tt["maxp"].numGlyphs) if "maxp" in tt else None,
                "table_tags": [str(tag) for tag in tt.keys() if tag != "GlyphOrder"],
                "cmap_tables": [{"platform": int(table.platformID), "encoding": int(table.platEncID),
                                  "format": int(table.format), "entries": len(table.cmap),
                                  "unicode": bool(table.isUnicode())}
                                 for table in tt["cmap"].tables] if "cmap" in tt else [],
            })
            cmap = tt.getBestCmap() if "cmap" in tt else None
            result["unicode_cmap"] = cmap is not None
            if cmap is not None:
                points = sorted(cp for cp, glyph in cmap.items() if glyph != ".notdef")
                result["available_characters"] = points
                result["available_count"] = len(points)
            if "OS/2" in tt:
                flags = int(tt["OS/2"].fsType)
                os2_version = int(tt["OS/2"].version)
                usage = flags & 0xF
                result.update({
                    "fs_type": flags, "os2_version": os2_version,
                    "no_subsetting": bool(flags & 0x100) if os2_version >= 2 else False,
                    "embedding_permission": {0: "instalable", 2: "restringida", 4: "solo vista e impresión", 8: "editable"}.get(usage, "ambigua"),
                })
    except (TTLibError, ValueError, KeyError, OSError, AssertionError):
        pass
    return result


def _program_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
    """Values read from the font program, separate from the PDF BaseFont name."""
    keys = ("sha256", "byte_length", "postscript_name", "family", "variant", "variant_source",
            "version", "fs_type", "os2_version", "embedding_permission", "glyph_count", "glyph_count_basis",
            "unicode_cmap", "cmap_tables", "table_tags", "available_count", "subset")
    return {key: metadata.get(key) for key in keys}


def _coverage_evidence(font: pymupdf.Font | None, metadata: dict[str, Any], text: str | None) -> dict[str, Any]:
    """Measure Unicode addressability, without equating it to visible PDF glyphs.

    A subset can contain the shapes for a date while exposing only a symbol
    cmap. Its PDF encoding may render that date, yet Font.has_glyph(U+0030)
    cannot address the same glyph for new Unicode text. Report that distinction.
    """
    result = {"checked": text is not None, "addressable": None, "missing_codepoints": [],
              "requested_codepoints": [], "basis": "MuPDF Font.has_glyph(fallback=False)",
              "status": "not_checked", "detail": "La cobertura se comprueba con el texto concreto de la selección."}
    if text is None:
        return result
    points = sorted({ord(char) for char in text if char not in "\r\n"})
    result["requested_codepoints"] = points
    if font is None:
        result.update(status="unavailable", detail="No se pudo cargar un programa de fuente para comprobar este texto.")
        return result
    missing = [cp for cp in points if not font.has_glyph(cp, fallback=False)]
    result.update(addressable=not missing, missing_codepoints=missing)
    if not missing:
        result.update(status="addressable", detail="Todos los caracteres solicitados son accesibles en este programa sin recurrir a otra fuente.")
    elif metadata.get("unicode_cmap") is False:
        result.update(status="encoding_not_reusable", detail="El programa no tiene un cmap Unicode reutilizable. Que el PDF muestre estos caracteres no significa que el editor pueda insertarlos por Unicode con esta fuente parcial.")
    else:
        result.update(status="missing_characters", detail="Este programa no contiene glifos Unicode accesibles para todos los caracteres solicitados.")
    return result


def _check_embedding(metadata: dict[str, Any], name: str, subset: bool = False) -> None:
    flags = metadata.get("fs_type")
    if flags is None:
        raise FontError(f"No se pueden verificar los permisos de incrustación editable de «{name}». Importe una TTF/OTF con permisos verificables.")
    usage = flags & 0xF
    # En OS/2 antiguo Microsoft permite elegir el permiso menos restrictivo.
    if (metadata.get("os2_version") or 0) <= 2 and usage & 8:
        usage = 8
    if usage not in (0, 8):
        raise FontError(f"«{name}» no permite incrustación editable (fsType={flags}; {metadata['embedding_permission']}).")
    if (metadata.get("os2_version") or 0) >= 2 and flags & 0x200:
        raise FontError(f"«{name}» sólo permite incrustación de mapas de bits; no se puede conservar texto vectorial.")
    if subset and metadata.get("no_subsetting"):
        raise FontError(f"«{name}» prohíbe subconjuntos; se necesita el archivo de fuente completo.")
    if metadata.get("variable"):
        raise FontError(f"«{name}» es una fuente variable. Importe una instancia TTF/OTF estática de la variante exacta.")


def _check_characters(font: pymupdf.Font, text: str, name: str) -> None:
    controls = sorted(set(ch for ch in text if ord(ch) < 32 and ch not in "\r\n"))
    if controls:
        raise FontError("La selección contiene caracteres de control no admitidos; sustituya tabuladores por espacios explícitos.")
    missing = sorted(set(ch for ch in text if ch not in "\r\n" and not font.has_glyph(ord(ch), fallback=False)), key=ord)
    if missing:
        labels = ", ".join(f"«{ch}» (U+{ord(ch):04X})" for ch in missing[:16])
        raise FontError(f"Faltan caracteres en «{name}»: {labels}. Importe la variante completa; no se aplicó ninguna sustitución.")


@dataclass
class ResolvedFont:
    name: str
    font: pymupdf.Font
    buffer: bytes | None
    base14: str | None
    source: str
    metadata: dict[str, Any]

    def width(self, text: str, size: float) -> float:
        if not math.isfinite(size) or size <= 0:
            raise FontError("El tamaño de fuente debe ser un número positivo.")
        _check_characters(self.font, text, self.name)
        return max((float(self.font.text_length(line, fontsize=size)) for line in text.splitlines()), default=0.0)


class FontResolver:
    """No conserva Document/Page; cada llamada pertenece al hilo/proceso del motor."""

    def __init__(self, config_path: Path | None = None, installed_dirs: list[Path] | None = None):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
        self.config_path = Path(config_path) if config_path is not None else base / "PDFModder" / "fonts.json"
        if installed_dirs is None:
            if os.name == "nt":
                installed_dirs = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", base / "Microsoft" / "Windows" / "Fonts"]
            else:
                installed_dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".local/share/fonts", Path.home() / ".fonts"]
        self.installed_dirs = [Path(p) for p in installed_dirs]
        self._installed: dict[str, list[Path]] | None = None
        self._evidence_files: dict[Path, tuple[str, dict[str, Any], bytes]] = {}
        self._associations: dict[str, dict[str, str]] = {}
        self.config_error: str | None = None
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                mappings = data.get("associations", {})
                if data.get("version") != 1 or not isinstance(mappings, dict):
                    raise ValueError("formato no reconocido")
                for key, value in mappings.items():
                    if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
                        raise ValueError("asociación no válida")
                    self._associations[key] = value
            except (OSError, ValueError, TypeError) as exc:
                self.config_error = f"No se pudieron leer las asociaciones de fuentes: {exc}"

    def associate(self, detected_name: str, path: Path | str) -> dict[str, Any]:
        """Registra una elección manual, conservando sólo ruta y huella, no la fuente."""
        font_path = Path(path).expanduser().resolve()
        candidate = self._from_file(font_path, "importada", detected_name, "")
        updated = dict(self._associations)
        updated[normalized_name(detected_name)] = {"path": str(font_path), "sha256": candidate.metadata["sha256"]}
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.config_path.parent, prefix="fonts-", suffix=".json.tmp", delete=False) as stream:
                temporary = stream.name
                json.dump({"version": 1, "associations": updated}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.config_path)
        except OSError as exc:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
            raise FontError(f"No se pudo guardar la asociación de fuente: {exc}") from exc
        self._associations = updated
        self.config_error = None
        return candidate.metadata

    def _from_file(self, path: Path, source: str, detected_name: str, text: str) -> ResolvedFont:
        if path.suffix.casefold() not in (".ttf", ".otf"):
            raise FontError("Importe un archivo TTF u OTF individual; las colecciones TTC/OTC no están admitidas.")
        try:
            content = path.read_bytes()
            metadata = _font_metadata(content, detected_name)
            _check_embedding(metadata, detected_name)
            font = pymupdf.Font(fontbuffer=content)
            _check_characters(font, text, detected_name)
        except (OSError, RuntimeError) as exc:
            raise FontError(f"No se puede cargar la fuente «{path.name}»: {exc}") from exc
        metadata.update({"path": str(path), "source": source, "manual_association": source == "importada", "embedded": False, "subset": False,
                         "bold": bool(font.is_bold), "italic": bool(font.is_italic)})
        return ResolvedFont(font.name or detected_name, font, content, None, source, metadata)

    def resolve_explicit(self, font_name: str, text: str, font_file: str | Path | None = None) -> ResolvedFont:
        """An explicit new face, rather than a substitute for a detected resource.

        A chosen file is authoritative and its actual face is returned to the UI.
        Bold/italic is never simulated. No files are copied or downloaded.
        """
        if font_file:
            resolved = self._from_file(Path(font_file).expanduser().resolve(), "archivo elegido", font_name, text)
            resolved.metadata["identity_basis"] = "Tipografía elegida explícitamente por el usuario"
            return resolved
        target = normalized_name(font_name or "")
        if target in _BASE14_ALIASES:
            alias = _BASE14_ALIASES[target]
            canonical = next(name for name, value in BASE14.items() if value == alias)
            font = pymupdf.Font(alias)
            _check_characters(font, text, canonical)
            return ResolvedFont(canonical, font, None, alias, "Base14 elegido", {
                "name": canonical, "family": canonical.split("-")[0],
                "variant": _variant(canonical), "bold": bool(font.is_bold),
                "italic": bool(font.is_italic), "source": "Base14 elegido",
                "identity_basis": "Tipografía estándar PDF elegida explícitamente",
            })
        failures = []
        for path in self._installed_index().get(target, []):
            try:
                resolved = self._from_file(path, "instalada elegida", target, text)
                if resolved.metadata.get("postscript_name") != target:
                    raise FontError("La fuente instalada cambió; actualice el catálogo de fuentes.")
                resolved.metadata["identity_basis"] = "Tipografía instalada elegida explícitamente"
                return resolved
            except FontError as exc:
                failures.append(str(exc))
        if failures:
            raise FontError(" ".join(dict.fromkeys(failures)))
        raise FontError(f"Falta la fuente o variante exacta «{font_name}». Seleccione una fuente del catálogo o un archivo TTF/OTF; no se aplicó una fuente parecida.")

    def catalog(self) -> list[dict[str, Any]]:
        """Catalogue of real faces; each choice is checked again when inserted.

        Metadata comes from each font's name/OS2/head tables, not filename
        heuristics. Fonts with known embedding restrictions remain listed with
        editable=False and a concrete reason so the UI can explain absence.
        """
        result = []
        for name, alias in BASE14.items():
            face = pymupdf.Font(alias)
            result.append({"family": name.split("-")[0], "variant": _variant(name),
                "name": name, "path": None, "bold": bool(face.is_bold),
                "italic": bool(face.is_italic), "source": "Base14", "editable": True,
                "status": "Recurso estándar PDF; se verifican los caracteres al utilizarlo"})
        seen = set()
        for ps_name, paths in sorted(self._installed_index().items()):
            for path in paths:
                if (ps_name, path) in seen:
                    continue
                seen.add((ps_name, path))
                try:
                    with TTFont(str(path), lazy=True) as face:
                        os2 = face["OS/2"] if "OS/2" in face else None
                        flags = int(os2.fsType) if os2 is not None else None
                        fs_selection = int(os2.fsSelection) if os2 is not None else 0
                        mac_style = int(face["head"].macStyle) if "head" in face else 0
                        metadata = {"fs_type": flags, "os2_version": int(os2.version) if os2 is not None else None,
                            "embedding_permission": {0: "instalable", 2: "restringida", 4: "solo vista e impresión", 8: "editable"}.get((flags or 0) & 15, "ambigua"),
                            "variable": "fvar" in face}
                        entry = {"family": _first_name(face, 16, 1) or ps_name,
                            "variant": _first_name(face, 17, 2) or _variant(ps_name),
                            "name": ps_name, "path": str(path), "source": "instalada",
                            "version": _first_name(face, 5),
                            "bold": bool(fs_selection & 32 or mac_style & 1),
                            "italic": bool(fs_selection & 1 or mac_style & 2)}
                        try:
                            _check_embedding(metadata, ps_name)
                            entry.update(editable=True, status="Permisos verificables; se comprueban los caracteres al utilizarla")
                        except FontError as exc:
                            entry.update(editable=False, status=str(exc))
                        result.append(entry)
                except (OSError, TTLibError, ValueError, KeyError, AssertionError):
                    continue
        return result

    def _installed_index(self) -> dict[str, list[Path]]:
        if self._installed is None:
            self._installed = {}
            for root in self.installed_dirs:
                if not root.is_dir():
                    continue
                try:
                    paths = sorted(p for p in root.rglob("*") if p.suffix.casefold() in (".ttf", ".otf"))
                except OSError:
                    continue
                for path in paths:
                    try:
                        with TTFont(str(path), lazy=True) as font:
                            for name in _names(font, 6):
                                self._installed.setdefault(name, []).append(path)
                    except (OSError, TTLibError, ValueError, KeyError, AssertionError):
                        continue
        return self._installed

    def _records(self, doc: pymupdf.Document, page_number: int) -> list[tuple[dict[str, Any], bytes]]:
        records = []
        for item in doc.get_page_fonts(page_number, full=True):
            xref, ext, kind, base_name, resource, encoding = item[:6]
            try:
                if xref > 0:
                    extracted_name, extracted_ext, _, content = doc.extract_font(xref)
                else:
                    # A direct font dictionary has no indirect object to
                    # extract. Keep the declared resource identity explicit.
                    extracted_name, extracted_ext, content = base_name, ext, b""
            except (ValueError, RuntimeError):
                extracted_name, extracted_ext, content = base_name, ext, b""
            metadata = _font_metadata(content, base_name) if content else {
                "family": None, "variant": _variant(base_name), "version": None,
                "available_characters": None, "available_count": None,
                "fs_type": None, "embedding_permission": "no incrustada",
                "identity_verified": False,
            }
            metadata.update({"xref": xref, "name": base_name, "resource": resource,
                "declared_name": base_name,
                "type": kind, "encoding": encoding, "extension": extracted_ext,
                "embedded": bool(content), "subset": bool(_SUBSET.match(base_name)),
                "extracted_name": extracted_name,
                "referencer": item[6] if len(item) > 6 else 0})
            records.append((metadata, content))
        for metadata, _ in records:
            name = normalized_name(metadata["name"])
            metadata["same_name_resources"] = [
                {"xref": other["xref"], "resource": other["resource"], "sha256": other.get("sha256")}
                for other, _ in records if normalized_name(other["name"]) == name
            ]
        return records

    def _evidence_file(self, path: Path) -> tuple[dict[str, Any], bytes]:
        # Explicit identity inspection reads today's bytes. Timestamps and size
        # can remain identical after replacing a font (including on Windows).
        # Only the metadata parse is cached; coverage uses this same byte buffer.
        data = path.read_bytes()
        key = sha256(data).hexdigest()
        cached = self._evidence_files.get(path)
        if cached is not None and cached[0] == key:
            return dict(cached[1]), data
        metadata = _font_metadata(data, path.stem)
        self._evidence_files[path] = (key, metadata, data)
        # This cache is for the on-demand inspector, not an installed font
        # catalogue. Limit retained bytes even with very large font programs.
        while len(self._evidence_files) > 24 or sum(len(item[2]) for item in self._evidence_files.values()) > 16 * 1024 * 1024:
            self._evidence_files.pop(next(iter(self._evidence_files)))
        return dict(metadata), data

    def _local_evidence(self, original: dict[str, Any], text: str | None) -> list[dict[str, Any]]:
        # The real PostScript name in an embedded name table is evidence; a
        # family alias such as Arial -> ArialMT inferred by spelling is not.
        program_name = original.get("postscript_name")
        target = program_name or normalized_name(original["name"])
        result = []
        for path in self._installed_index().get(target, []):
            try:
                metadata, data = self._evidence_file(path)
                if metadata.get("postscript_name") != target:
                    continue
                same_bytes = metadata["sha256"] == original.get("sha256") if original.get("sha256") else None
                version_match = (metadata.get("version") == original["version"]) if original.get("version") and metadata.get("version") else None
                variant_match = (metadata.get("variant", "").casefold() == original.get("variant", "").casefold()) if program_name else None
                font = pymupdf.Font(fontbuffer=data) if text is not None else None
                entry = {"path": str(path), "matched_name": target,
                         "match_basis": "program_postscript_name" if program_name else "pdf_declared_name",
                         "postscript_match": True, "version_match": version_match, "variant_match": variant_match,
                         "program_bytes_match": same_bytes, "font_program": _program_evidence(metadata),
                         "coverage": _coverage_evidence(font, metadata, text),
                         "identity_verified": same_bytes is True,
                         "identity_detail": "Archivo local idéntico byte a byte al programa incrustado." if same_bytes else
                         "Coincide el nombre PostScript; la versión y variante se comparan por separado. Un subconjunto y una fuente completa pueden tener huellas distintas. El nombre, la versión y la familia por sí solos no prueban identidad de contornos ni métricas.",
                         "automatic_substitution": False}
                try:
                    _check_embedding(metadata, target)
                    entry.update(editable_embedding=True, embedding_status=metadata["embedding_permission"])
                except FontError as exc:
                    entry.update(editable_embedding=False, embedding_status=str(exc))
                result.append(entry)
            except (OSError, RuntimeError, ValueError) as exc:
                result.append({"path": str(path), "matched_name": target, "identity_verified": False,
                               "status": f"No se pudo inspeccionar este candidato local: {exc}"})
        return result

    def _inspect_record(self, doc, page_number, metadata, content, text, include_local):
        metadata = dict(metadata)
        name = normalized_name(metadata["name"])
        metadata["font_program"] = _program_evidence(metadata) if content else None
        metadata["base14"] = _BASE14_ALIASES.get(name) if not content else None
        font = None
        if metadata["base14"]:
            font = pymupdf.Font(metadata["base14"])
            metadata.update({"family": font.name.split("-")[0], "source": "Base14", "available_count": len(font.valid_codepoints()), "available_characters": list(font.valid_codepoints()), "embedding_permission": "recurso estándar PDF"})
        elif content:
            metadata["source"] = "incrustada"
            try:
                font = pymupdf.Font(fontbuffer=content)
            except (RuntimeError, ValueError):
                pass
        else:
            metadata["source"] = "sin resolver"
        resolved = None
        metadata["resolution_scope"] = "unicode_reinsertion"
        try:
            resolved = self.resolve(doc, page_number, metadata["resource"], text or "")
            metadata["resolved_source"] = resolved.source
            metadata["resolved_name"] = resolved.name
            metadata["resolved_program"] = _program_evidence(resolved.metadata)
            metadata["resolved_path"] = resolved.metadata.get("path")
            metadata["status"] = "Disponible; validar los caracteres y la reproducción antes de editar"
        except FontError as exc:
            metadata["resolved_source"] = None
            metadata["resolved_name"] = None
            metadata["resolved_program"] = None
            metadata["resolved_path"] = None
            metadata["status"] = "Reinserción por Unicode: " + str(exc)
        if content:
            identity = {"kind": "embedded_program", "label": "Programa incrustado identificado",
                        "detail": "La huella SHA-256 identifica los bytes extraídos de este recurso PDF. No identifica por sí sola el archivo completo del que procede un subconjunto ni certifica su reutilización para todos los caracteres.",
                        "program_identified": True}
        elif metadata["base14"]:
            identity = {"kind": "base14_nominal", "label": "Fuente estándar PDF declarada",
                        "detail": "El PDF declara una fuente Base14 sin incrustar su programa original. Se deben comprobar las métricas y la apariencia antes de editar.",
                        "program_identified": False}
        elif resolved is not None:
            manual = resolved.source == "importada"
            identity = {"kind": "manual_association" if manual else "exact_local_name",
                        "label": "Asociación manual" if manual else "Coincidencia local por nombre exacto",
                        "detail": "El PDF no contiene un programa con el que demostrar identidad binaria. La fuente resuelta debe superar la comparación de métricas y apariencia del fragmento.",
                        "program_identified": False}
        else:
            identity = {"kind": "unresolved", "label": "Sólo nombre declarado; fuente sin resolver",
                        "detail": "No se ha identificado un programa reutilizable para este recurso.", "program_identified": False}
        identity["requires_reproduction_validation"] = True
        metadata["identity_evidence"] = identity
        metadata["coverage"] = _coverage_evidence(font or (resolved.font if resolved else None), metadata, text)
        metadata["local_candidates"] = self._local_evidence(metadata, text) if include_local and not metadata["base14"] else []
        metadata["local_candidates_checked"] = include_local
        metadata["association"] = self._associations.get(name)
        return metadata

    def inspect(self, doc: pymupdf.Document, page_number: int, text: str | None = None,
                *, include_local: bool = False) -> list[dict[str, Any]]:
        """Page inventory; installed-candidate evidence is explicitly on demand."""
        return [self._inspect_record(doc, page_number, metadata, content, text, include_local)
                for metadata, content in self._records(doc, page_number)]

    @staticmethod
    def _matching_records(records, font_name):
        exact = [(m, b) for m, b in records if font_name in (m["resource"], m["name"], m["extracted_name"])]
        target = normalized_name(font_name)
        return exact or [(m, b) for m, b in records if target in {
            normalized_name(m["name"]), normalized_name(m["extracted_name"]),
            normalized_name(m.get("postscript_name") or "")}]

    def inspect_selection(self, doc: pymupdf.Document, page_number: int, font_name: str, text: str,
                          *, font_xref: int | None = None, resource: str | None = None) -> dict[str, Any]:
        """Identify a selected resource without choosing between equal names.

        ``font_xref``/``resource`` must come from actual PDF text operators, not
        be inferred from family names. Glyph-to-resource binding is the engine's
        responsibility. This method neither edits the PDF nor changes mappings.
        """
        records = self._records(doc, page_number)
        explicit = font_xref is not None or resource is not None
        if explicit:
            candidates = [(m, b) for m, b in records
                          if (font_xref is None or m["xref"] == font_xref)
                          and (resource is None or m["resource"].lstrip("/") == resource.lstrip("/"))]
        else:
            candidates = self._matching_records(records, font_name)
        # A resource referenced twice with the same xref is still one program.
        distinct = {}
        for metadata, content in candidates:
            distinct.setdefault((metadata["xref"], metadata["resource"]), (metadata, content))
        candidates = list(distinct.values())
        inspected = [self._inspect_record(doc, page_number, m, b, text, True) for m, b in candidates]
        if len(inspected) > 1:
            match, certainty = "ambiguous_name", "ambiguous_resource"
            label = "Hay varios recursos distintos con ese nombre"
            detail = "Se necesita la referencia del operador PDF que pinta los caracteres seleccionados; el nombre de familia no permite elegir entre estos programas."
        elif inspected:
            match = "explicit_resource" if explicit else "unique_name"
            identity = inspected[0]["identity_evidence"]
            certainty, label, detail = identity["kind"], identity["label"], identity["detail"]
        else:
            match, certainty = "not_found", "unresolved"
            label = "No se encontró el recurso de esta selección"
            detail = "La referencia facilitada no corresponde a una fuente de la página; vuelva a seleccionar el texto."
        return {"font_name": font_name, "font_xref": font_xref, "resource": resource,
                "resource_match": match, "certainty": certainty, "certainty_label": label,
                "certainty_detail": detail, "candidate_count": len(inspected), "candidates": inspected,
                "requires_reproduction_validation": True}

    def resolve(self, doc: pymupdf.Document, page_number: int, font_name: str, text: str) -> ResolvedFont:
        records = self._records(doc, page_number)
        candidates = self._matching_records(records, font_name)
        if not candidates:
            raise FontError(f"No se encontró el recurso de fuente «{font_name}» en esta página. Seleccione de nuevo el texto.")
        unique = {m.get("sha256") or m["name"] for m, _ in candidates}
        if len(unique) > 1:
            raise FontError(f"Hay varios recursos distintos llamados «{font_name}». No se puede identificar la fuente exacta de este fragmento.")
        metadata, content = candidates[0]
        target = normalized_name(metadata["name"])
        errors: list[str] = []
        if content:
            try:
                _check_embedding(metadata, target, metadata["subset"])
                font = pymupdf.Font(fontbuffer=content)
                _check_characters(font, text, target)
                metadata["source"] = "incrustada"
                return ResolvedFont(font.name or target, font, content, None, "incrustada", metadata)
            except (FontError, RuntimeError, ValueError) as exc:
                errors.append(str(exc))
        elif target in _BASE14_ALIASES and metadata["type"] in ("Type1", "MMType1"):
            alias = _BASE14_ALIASES[target]
            font = pymupdf.Font(alias)
            _check_characters(font, text, target)
            metadata.update({"source": "Base14", "identity_basis": "Recurso nominal estándar PDF; requiere verificación de métricas/apariencia"})
            return ResolvedFont(target, font, None, alias, "Base14", metadata)
        # Coincidencia nominal EXACTA por nombre PostScript, nunca por familia.
        for path in self._installed_index().get(target, []):
            try:
                resolved = self._from_file(path, "instalada", target, text)
                if resolved.metadata.get("postscript_name") != target:
                    raise FontError("El archivo de fuente instalado cambió desde la inspección; vuelva a abrir el documento.")
                resolved.metadata["identity_basis"] = "Nombre PostScript exacto; identidad no demostrada por el nombre"
                return resolved
            except FontError as exc:
                errors.append(str(exc))
        association = self._associations.get(target)
        if association:
            try:
                resolved = self._from_file(Path(association["path"]), "importada", target, text)
                if resolved.metadata["sha256"] != association["sha256"]:
                    raise FontError("El archivo de fuente asociado ha cambiado. Vuelva a asociarlo explícitamente antes de editar.")
                resolved.metadata["identity_basis"] = "Asociación manual explícita; requiere verificación de métricas/apariencia"
                return resolved
            except FontError as exc:
                errors.append(str(exc))
        if errors:
            raise FontError(" ".join(dict.fromkeys(errors)))
        variant = _variant(target)
        detail = f"Falta la variante {variant}" if variant != "regular" else "Falta la fuente exacta"
        raise FontError(f"{detail} «{target}». No está incrustada ni instalada con ese nombre PostScript. Importe y asocie un archivo TTF/OTF adecuado.")
