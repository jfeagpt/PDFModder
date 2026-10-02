"""Prueba el instalador EXE y el editor instalado en carpetas aisladas.

Ejecutar en Windows. No instala en el perfil ni crea accesos directos.
Conserva todos los resultados, la copia incompleta simulada y los informes.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pdfmodder import __version__
LABEL = 'v'+(__version__ if __version__.split('.')[-1]!='0' else '.'.join(__version__.split('.')[:2]))
INSTALLER = ROOT / 'releases' / LABEL / f'PDFModder-{LABEL}-Instalar.exe'


def native(path):
    """Use the same Win32 long-path support for the independent verifier."""
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return Path(value)
    return Path("\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value)


def sha(path):
    with native(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, cwd):
    env = dict(os.environ)
    for key in list(env):
        if key.upper() in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"}:
            del env[key]
    env["PATH"] = os.environ["SystemRoot"] + "\\System32;" + os.environ["SystemRoot"]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    started = time.perf_counter()
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                            startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                            capture_output=True, timeout=90)
    return {"exit_code": result.returncode, "seconds": round(time.perf_counter() - started, 3),
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace")}


def snapshot(folder):
    folder = native(folder)
    if not folder.exists():
        return {}
    return {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob("*") if path.is_file()}


def verify():
    assert os.name == "nt", "Esta prueba requiere Windows."
    build_report=json.loads((INSTALLER.parent/'INSTALADOR.json').read_text(encoding='utf-8'))
    assert build_report['application']=='PDF Modder '+__version__
    assert build_report['installer_sha256']==sha(INSTALLER)
    assert build_report['payload_sha256']==sha(ROOT/'build/installer/PDFModderPayload.zip')
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    base = ROOT / "output/portability" / ("instalador-" + stamp)
    base.mkdir(parents=True, exist_ok=False)
    report = {"ok": False, "app_version": __version__, "started_utc": datetime.now(timezone.utc).isoformat(),
              "installer_sha256": sha(INSTALLER), "test_directory": str(base), "tests": []}
    expected = {}
    with zipfile.ZipFile(ROOT / "build/installer/PDFModderPayload.zip") as archive:
        for item in archive.infolist():
            if not item.is_dir():
                expected[item.filename.removeprefix("PDFModder/")] = hashlib.sha256(archive.read(item)).hexdigest()

    def installed_matches(target):
        for name, digest in expected.items():
            file = native(target / name)
            assert file.is_file() and sha(file) == digest, "Archivo incorrecto: " + str(file)
        marker=json.loads((target / ".pdfmodder-installation.json").read_text(encoding='utf-8-sig'))
        assert marker['application_id']=='PDFModder.Windows.PerUser' and marker['version']==__version__
        return len(expected)

    def install(target, name):
        result_path = base / (name + ".json")
        result = run([INSTALLER, "--silent", "--dir", target, "--no-shortcut", "--no-launch", "--report", result_path], base)
        if result_path.is_file():
            result["installer_report"] = json.loads(result_path.read_text(encoding="utf-8-sig"))
        report["tests"].append({"name": name, **result})
        return result

    try:
        target = base / "Instalacion con espacios y acentos á"
        result = install(target, "instalacion_completa")
        assert result["exit_code"] == 0, result
        report["verified_installed_files"] = installed_matches(target)

        # Simula exactamente la ausencia que activa la ruta libshiboken.
        missing = (target / "_internal/shiboken6").resolve()
        displaced = (target / "_internal/shiboken6-qa-incompleto").resolve()
        assert missing.is_relative_to(base.resolve()) and displaced.is_relative_to(base.resolve())
        missing.rename(displaced)
        user_pdf = target / "documento-del-usuario.pdf"
        shutil.copyfile(ROOT / "examples/herramientas-v08.pdf", user_pdf)
        before_repair = snapshot(target)
        sibling_names = set(base.iterdir())
        result = install(target, "reparacion_dependencia_ausente")
        assert result["exit_code"] == 0, result
        installed_matches(target)
        backups = [p for p in set(base.iterdir()) - sibling_names if p.is_dir() and p != target]
        assert len(backups) == 1, "Debe conservar una sola copia completa de la instalacion anterior."
        assert snapshot(backups[0]) == before_repair, "La copia anterior se ha alterado."
        report["preserved_backup"] = str(backups[0])

        other = base / "Carpeta ajena"
        other.mkdir()
        shutil.copyfile(ROOT / "examples/herramientas-v08.pdf", other / "factura.pdf")
        before = snapshot(other)
        result = install(other, "rechazo_carpeta_ajena")
        assert result["exit_code"] != 0, "No debe reemplazar una carpeta no reconocida."
        assert snapshot(other) == before, "Se ha alterado una carpeta ajena."

        saved_report = base / "informe_existente.json"
        saved_report.write_text("CONSERVAR INFORME", encoding="utf-8")
        forbidden = base / "No instalar con informe existente"
        result = run([INSTALLER, "--silent", "--dir", forbidden, "--no-shortcut", "--no-launch", "--report", saved_report], base)
        assert result["exit_code"] != 0 and saved_report.read_text(encoding="utf-8") == "CONSERVAR INFORME"
        assert not forbidden.exists(), "Debe validar el informe antes de instalar."
        report["tests"].append({"name": "rechazo_informe_existente", **result})

        # Ensaya la validación real del instalador, no sólo la comprobación
        # externa: una DLL tiene un SHA esperado deliberadamente incorrecto.
        manifest = (ROOT / "build/installer/PDFModderPayload.tsv").read_text(encoding="utf-8")
        rows = manifest.splitlines()
        changed = False
        for index, row in enumerate(rows):
            digest, size, name = row.split("\t")
            if name == "PDFModder/_internal/shiboken6/Shiboken.pyd":
                rows[index] = "0" * 64 + "\t" + size + "\t" + name
                changed = True
        assert changed
        bad_manifest = base / "manifiesto-corrupto.tsv"
        bad_manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
        bad_installer = base / "Instalador-SOLO-PRUEBA-corrupto.exe"
        compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                        "/out:" + str(bad_installer),
                        "/win32manifest:" + str(ROOT / "installer/asInvoker.manifest"),
                        "/resource:" + str(ROOT / "build/installer/PDFModderPayload.zip") + ",PDFModderPayload.zip",
                        "/resource:" + str(bad_manifest) + ",PDFModderPayload.tsv",
                        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                        "/reference:System.IO.Compression.dll", "/reference:System.IO.Compression.FileSystem.dll",
                        "/reference:System.Web.Extensions.dll", str(ROOT / "installer/PdfModderInstaller.cs")],
                       check=True, capture_output=True, timeout=60)
        corrupt_target = base / "No publicar archivos corruptos"
        corrupt_report = base / "rechazo_dependencia_corrupta.json"
        result = run([bad_installer, "--silent", "--dir", corrupt_target, "--no-shortcut", "--no-launch",
                      "--report", corrupt_report], base)
        assert result["exit_code"] != 0 and not corrupt_target.exists(), result
        error = json.loads(corrupt_report.read_text(encoding="utf-8-sig"))
        assert "SHA-256" in error.get("error", "") and "Shiboken.pyd" in error["error"], error
        report["tests"].append({"name": "rechazo_dependencia_corrupta", **result, "installer_report": error})

        app_report = base / "editor-instalado-v08.json"
        result = run([target / "PDFModder.exe", "--smoke-v08", app_report], base)
        assert result["exit_code"] == 0, result
        app = json.loads(app_report.read_text(encoding="utf-8"))
        assert app["ok"] and app["frozen"] and app["stage"] == "complete"
        assert app['app_version']==__version__
        assert len(app["steps"]) == 23 and all(step["ok"] for step in app["steps"])
        assert app["exe_sha256"] == expected["PDFModder.exe"]
        assert Path(app["source"]).is_relative_to(target)
        report["tests"].append({"name": "editor_instalado_23_pasos", **result,
                                "steps": len(app["steps"]), "report": str(app_report)})
        report["ok"] = True
    except Exception as exc:
        report["error"] = repr(exc)
        raise
    finally:
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        destination = base / "verificacion-instalador.json"
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(destination), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    verify()
