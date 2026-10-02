"""Collect installed notices and application source locally; never access the network.

The inventory intentionally includes build/test tools as well as runtime packages,
so transitive notices are retained even if a freezer hook changes its dependencies.
This is an inventory, not an automatic determination of licence compliance.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RUNTIME = {
    "pyside6": "6.10.2",
    "pyside6-addons": "6.10.2",
    "pyside6-essentials": "6.10.2",
    "shiboken6": "6.10.2",
    "pymupdf": "1.26.7",
    "fonttools": "4.61.1",
    "pypdf": "6.6.0",
    "pillow": "12.1.0",
    "numpy": "2.4.1",
    "pyhanko": "0.33.0",
    "pyhanko-certvalidator": "0.29.1",
    "cryptography": "50.0.1",
}
APP_ROOT_FILES = (
    ".gitignore", "LICENSE", "README.md", "requirements.txt", "requirements-dev.txt",
    "requirements-lock-win-py312.txt", "pyproject.toml", "PDFModder.spec",
    "run_pdfmodder.py",
)
APP_DIRECTORIES = ("pdfmodder", "scripts", "tests", "docs", "examples", "assets", "installer", ".github")
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv", "dist", "build", "output", "releases", "tmp"}
FORBIDDEN_SOURCE_SUFFIXES = {".exe", ".zip", ".dll", ".pyd", ".key", ".pem", ".pfx", ".p12", ".log"}
LICENSE_NAMES = re.compile(r"^(?:licen[sc]e|copying|copyright|notice|authors)(?:[._-].*)?$", re.I)


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def notice_path(path: Path) -> bool:
    return any(part.lower() in {"licenses", "licences"} for part in path.parts) or bool(LICENSE_NAMES.match(path.name))


def safe_relative(path: Path) -> Path:
    # Some wheel RECORD entries refer to ../Scripts. Never copy outside staging.
    return Path(*(part for part in path.parts if part not in (".", "..", path.anchor)))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files() -> list[tuple[Path, Path]]:
    """One allowlist for the corresponding source and the GitHub source archive."""
    files = [ROOT / name for name in APP_ROOT_FILES if (ROOT / name).is_file()]
    for dirname in APP_DIRECTORIES:
        directory = ROOT / dirname
        if directory.is_dir():
            files.extend(path for path in directory.rglob("*") if path.is_file())
    selected = []
    seen = set()
    for file in sorted(set(files)):
        relative = file.relative_to(ROOT)
        if any(part.casefold() in EXCLUDE_PARTS for part in relative.parts) or file.suffix.lower() in {".pyc", ".pyo"}:
            continue
        if file.is_symlink() or not file.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"No se empaqueta un enlace a un archivo externo: {relative}")
        if file.suffix.lower() in FORBIDDEN_SOURCE_SUFFIXES:
            raise RuntimeError(f"Archivo no previsto para publicar como fuente: {relative}")
        key = relative.as_posix().casefold()
        if key in seen:
            raise RuntimeError(f"Ruta repetida en las fuentes: {relative}")
        seen.add(key)
        selected.append((file, relative))
    return selected


def stage_source(destination: Path) -> list[dict[str, str]]:
    manifest = []
    for file, relative in source_files():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        manifest.append({"path": relative.as_posix(), "sha256": sha256(file)})
    return manifest


def collect(destination: Path) -> None:
    destination = destination.resolve()
    if not destination.is_relative_to(ROOT / "build"):
        raise RuntimeError("La salida de recopilación debe estar dentro de PDFModder/build.")
    # This directory contains only prior generated delivery data. Validate the final
    # absolute path first, then remove using one Python filesystem operation.
    if destination.exists():
        shutil.rmtree(destination)
    licenses = destination / "licenses"
    licenses.mkdir(parents=True)
    distributions = sorted(metadata.distributions(), key=lambda item: normalized(item.metadata.get("Name", "")))
    by_name = {normalized(item.metadata["Name"]): item for item in distributions}
    for name, expected in EXPECTED_RUNTIME.items():
        actual = by_name.get(name)
        if actual is None or actual.version != expected:
            raise RuntimeError(f"Entorno no reproducible: se requiere {name}=={expected}.")
    rows = []
    for distribution in distributions:
        name = distribution.metadata.get("Name", "unknown")
        dirname = f"{normalized(name)}-{distribution.version}"
        target_root = licenses / dirname
        target_root.mkdir()
        copied = []
        for file in distribution.files or ():
            relative = Path(str(file))
            if not notice_path(relative):
                continue
            source = Path(distribution.locate_file(file))
            if not source.is_file():
                continue
            target = target_root / safe_relative(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append({"path": target.relative_to(licenses).as_posix(), "sha256": sha256(target)})
        # METADATA retains declared licence expressions, source/homepage links and
        # author attribution even for a wheel with no standalone licence file.
        # Retain the original message: reserializing old multiline Description
        # headers can fail email.policy validation (for example altgraph).
        raw_metadata = distribution.read_text("METADATA") or distribution.read_text("PKG-INFO")
        if raw_metadata is None:
            raise RuntimeError(f"No se encontraron los metadatos originales de {name}.")
        (target_root / "METADATA.txt").write_text(raw_metadata, encoding="utf-8")
        rows.append({
            "name": name,
            "version": distribution.version,
            "license_expression": distribution.metadata.get("License-Expression"),
            "license": distribution.metadata.get("License"),
            "homepage": distribution.metadata.get("Home-page"),
            "project_urls": distribution.metadata.get_all("Project-URL") or [],
            "requires_dist": distribution.metadata.get_all("Requires-Dist") or [],
            "notice_files": copied,
            "pypi_version": f"https://pypi.org/project/{name}/{distribution.version}/",
        })
    for name in EXPECTED_RUNTIME:
        row = next(row for row in rows if normalized(row["name"]) == name)
        if not row["notice_files"]:
            raise RuntimeError(f"No se encontró el texto de licencia de {name}; revise su rueda antes de empaquetar.")
    python_notices = []
    for filename in ("LICENSE.txt", "LICENSE"):
        path = Path(sys.base_prefix) / filename
        if path.is_file():
            target = licenses / "python" / filename
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(path, target)
            python_notices.append(target.relative_to(licenses).as_posix())
    if not python_notices:
        raise RuntimeError("No se encontró LICENSE.txt del intérprete Python; copie su licencia antes de distribuir.")
    standard_notices = []
    standard_files = [ROOT / "LICENSE"]
    for directory in (ROOT / "docs" / "licenses", ROOT / "docs" / "licencias"):
        if directory.is_dir():
            standard_files.extend(path for path in directory.rglob("*") if path.is_file())
    for source in standard_files:
        if not source.is_file():
            continue
        relative = source.relative_to(ROOT)
        target = licenses / "standard-texts" / relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
        standard_notices.append({"path":target.relative_to(licenses).as_posix(),"sha256":sha256(target)})
    inventory = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python_notices": python_notices,
        "standard_notices": standard_notices,
        "scope": "Entorno de construcción completo; puede incluir herramientas no presentes en el ejecutable",
        "packages": rows,
    }
    (licenses / "INVENTARIO.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    (licenses / "requirements-build-lock.txt").write_text(
        "# Entorno exacto de esta construcción.\n" + "\n".join(f"{row['name']}=={row['version']}" for row in rows) + "\n",
        encoding="utf-8",
    )
    (licenses / "LEEME.txt").write_text(
        "PDF Modder: software AGPL-3.0-or-later. Consulte LICENSE y docs/LICENCIAS.md.\n"
        "INVENTARIO.json enumera versiones, avisos y enlaces declarados por cada distribución.\n"
        "Se conservan también las licencias de herramientas de construcción y pruebas.\n"
        "Las DLL Qt permanecen separadas y reemplazables en este paquete onedir.\n"
        "El código de la aplicación está en ../source/PDFModder.\n"
        "Los enlaces a fuentes de dependencias no son por sí solos una oferta de código correspondiente.\n"
        "Antes de redistribuir binarios a terceros, acompañe sus fuentes según las licencias aplicables.\n",
        encoding="utf-8",
    )
    manifest = stage_source(destination / "source" / "PDFModder")
    (destination / "source" / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Recopiladas {len(rows)} distribuciones y {len(manifest)} archivos de código/ejemplos en {destination}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "delivery")
    args = parser.parse_args()
    collect(args.output)
