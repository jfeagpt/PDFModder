"""Prepara el código actual para GitHub, sin archivos de trabajo ni ejecutables."""
from pathlib import Path
import hashlib
import json
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pdfmodder import __version__
from scripts.collect_licenses import source_files


def prepare():
    selected = [(path, relative.as_posix()) for path, relative in source_files()]
    label = 'v'+(__version__ if __version__.split('.')[-1]!='0' else '.'.join(__version__.split('.')[:2]))
    target = ROOT / 'releases' / label / f'PDFModder-{label}-proyecto-actual.zip'
    if target.exists():
        raise FileExistsError("El archivo de fuentes de esta versión ya existe; no se sobrescribe: " + str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    rows = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in selected:
            content = path.read_bytes()
            archive.writestr("PDFModder/" + name, content)
            rows.append({"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n", encoding="ascii")
    inventory = {"project": "PDF Modder "+__version__, "files": rows, "archive_sha256": digest,
                 "published_to_github": False}
    (target.parent / "PROYECTO-ACTUAL.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"source_archive": str(target), "files": len(rows), "bytes": target.stat().st_size,
                      "sha256": digest, "published_to_github": False}, ensure_ascii=False))


if __name__ == "__main__":
    prepare()
