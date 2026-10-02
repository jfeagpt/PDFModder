"""Compila el instalador del bundle actual sin acreditar pruebas del binario.

Esta ruta de construcción se usa para la compilación actual. Toma
``dist/PDFModder`` tal como está, superpone el código fuente actual permitido y
publica en una carpeta por versión para conservar las entregas anteriores.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfmodder import __version__
from scripts.collect_licenses import source_files
from scripts.build_uninstaller import build as build_uninstaller


BUNDLE = ROOT / "dist" / "PDFModder"
LABEL = "v" + __version__
STAGING = ROOT / "build" / ("installer-" + LABEL)
RELEASE = ROOT / "releases" / LABEL
TARGET = RELEASE / ("PDFModder-" + LABEL + "-Instalar.exe")
PAYLOAD = STAGING / "PDFModderPayload.zip"
PAYLOAD_MANIFEST = STAGING / "PDFModderPayload.tsv"
SOURCE_PREFIX = "PDFModder/_internal/source/PDFModder/"
SOURCE_MANIFEST = "PDFModder/_internal/source/MANIFEST.json"
DELIVERY_NOTE = (
    "Compilación con desinstalador integrado. Las comprobaciones de instalación "
    "y desinstalación se documentan aparte; no se acredita aquí una repetición "
    "de las pruebas del editor PDF."
)


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def row_for(name: str, size: int, digest: str) -> str:
    return f"{digest}\t{size}\t{name}"


def is_replaced_bundle_file(relative: Path) -> bool:
    normalized = relative.as_posix().casefold()
    return (
        normalized == "entrega.json"
        or normalized == "readme.md"
        or normalized == "_internal/readme.md"
        or normalized.startswith("_internal/docs/")
        or normalized == "_internal/source/manifest.json"
        or normalized.startswith("_internal/source/pdfmodder/")
    )


def write_payload() -> int:
    """Create the embedded ZIP and its exact per-file extraction inventory."""
    rows: list[str] = []
    source_inventory: list[dict[str, str]] = []

    with zipfile.ZipFile(
        PAYLOAD, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(BUNDLE.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(BUNDLE)
            if is_replaced_bundle_file(relative):
                continue
            name = "PDFModder/" + relative.as_posix()
            archive.write(path, name)
            rows.append(row_for(name, path.stat().st_size, digest_file(path)))

        documentation = [(ROOT / 'README.md', 'PDFModder/README.md'),
                         (ROOT / 'README.md', 'PDFModder/_internal/README.md')]
        documentation.extend((path, 'PDFModder/_internal/docs/' + path.relative_to(ROOT / 'docs').as_posix())
                             for path in sorted((ROOT / 'docs').rglob('*')) if path.is_file())
        for path, name in documentation:
            content = path.read_bytes()
            archive.writestr(name, content)
            rows.append(row_for(name, len(content), digest_bytes(content)))

        for path, relative in source_files():
            content = path.read_bytes()
            digest = digest_bytes(content)
            name = SOURCE_PREFIX + relative.as_posix()
            archive.writestr(name, content)
            rows.append(row_for(name, len(content), digest))
            source_inventory.append({"path": relative.as_posix(), "sha256": digest})

        manifest_content = json.dumps(
            source_inventory, ensure_ascii=False, indent=2
        ).encode("utf-8")
        archive.writestr(SOURCE_MANIFEST, manifest_content)
        rows.append(
            row_for(
                SOURCE_MANIFEST,
                len(manifest_content),
                digest_bytes(manifest_content),
            )
        )

        evidence_path=BUNDLE / 'ENTREGA.json'
        evidence=json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.exists() else {}
        if evidence.get('frozen_verified'):
            if evidence.get('application') != f'PDF Modder {__version__}' or evidence.get('exe_sha256') != digest_file(BUNDLE/'PDFModder.exe'):
                raise RuntimeError('La evidencia no corresponde al ejecutable que se va a empaquetar.')
        elif evidence.get('delivery_status') == 'compiled_unverified':
            # Preserve the explicit no-final-tests delivery note prepared for
            # this build; it must never inherit historical test claims.
            evidence['tested'] = False
            evidence['frozen_verified'] = False
        else:
            evidence={
                "application": f"PDF Modder {__version__}",
                "platform": "Windows 11 x64",
                "delivery_status": "compiled_pending_verification",
                "frozen_verified": False,
                "tested": False,
                "source_manifest": "_internal/source/MANIFEST.json",
                "verification_note": DELIVERY_NOTE,
            }
        delivery_content = json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        delivery_name = "PDFModder/ENTREGA.json"
        archive.writestr(delivery_name, delivery_content)
        rows.append(
            row_for(delivery_name, len(delivery_content), digest_bytes(delivery_content))
        )

    PAYLOAD_MANIFEST.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def build() -> None:
    STAGING.mkdir(parents=True, exist_ok=True)
    RELEASE.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        raise FileExistsError('Ya existe el instalador; conserve la entrega anterior: ' + str(TARGET))
    build_uninstaller(BUNDLE / 'Desinstalar.exe')
    manifest_files = write_payload()
    template = (ROOT / 'installer/PdfModderInstaller.cs').read_text(encoding='utf-8-sig')
    template_version = re.search(r'const string Version = "([0-9.]+)"', template).group(1)
    generated = STAGING / 'PdfModderInstaller.cs'
    generated.write_text(template.replace(template_version, __version__), encoding='utf-8-sig')

    compiler = (
        Path(os.environ.get("SystemRoot", "C:/Windows"))
        / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    arguments = [
        str(compiler),
        "/nologo",
        "/target:winexe",
        "/platform:x64",
        "/optimize+",
        "/out:" + str(TARGET),
        "/win32manifest:" + str(ROOT / "installer/asInvoker.manifest"),
        "/win32icon:" + str(ROOT / "assets/icons/pdfmodder.ico"),
        "/resource:" + str(PAYLOAD) + ",PDFModderPayload.zip",
        "/resource:" + str(PAYLOAD_MANIFEST) + ",PDFModderPayload.tsv",
        "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll",
        "/reference:System.IO.Compression.dll",
        "/reference:System.IO.Compression.FileSystem.dll",
        "/reference:System.Web.Extensions.dll",
        str(generated),
    ]
    subprocess.run(arguments, check=True, cwd=ROOT)

    report = {
        "application": f"PDF Modder {__version__}",
        "version_label": LABEL,
        "installer_revision": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "compiled": True,
        "tested": False,
        "manifest_files": manifest_files,
        "output": TARGET.name,
        "installer_sha256": digest_file(TARGET),
        "payload_sha256": digest_file(PAYLOAD),
        "note": DELIVERY_NOTE,
    }
    (RELEASE / "INSTALADOR.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    TARGET.with_suffix('.exe.sha256').write_text(f'{digest_file(TARGET)}  {TARGET.name}\n',encoding='ascii')
    print(json.dumps({"installer": str(TARGET), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
