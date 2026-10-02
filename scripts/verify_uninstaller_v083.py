"""Verifica el desinstalador 0.8.3 con instalaciones sintéticas aisladas.

Sólo crea fixtures en build/uninstaller-tests; no instala el editor, no crea
accesos directos ni escribe en el registro. Comprueba que HKCU no cambie. Las
carpetas y los informes se conservan para revisión, sin limpieza recursiva.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "installer/PdfModderUninstaller.cs"
MARKER = ".pdfmodder-installation.json"
MANIFEST = ".pdfmodder-files.tsv"
VERSION = "0.8.3"


def native(path: Path) -> Path:
    """Use Win32 extended paths only inside the independent fixture verifier."""
    value=str(path.absolute())
    if value.startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\UNC\\"+value[2:] if value.startswith("\\\\") else "\\\\?\\"+value)


def sha(path: Path) -> str:
    with native(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    root=native(root)
    if not root.exists():
        return {}
    return {path.relative_to(root).as_posix(): sha(path)
            for path in root.rglob("*") if path.is_file()}


def registry_snapshot():
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFModder-0.8.3"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return None
    with key:
        result = {}
        index = 0
        while True:
            try:
                name, value, kind = winreg.EnumValue(key, index)
            except OSError:
                break
            result[name] = {"value": value.hex() if isinstance(value, bytes) else value, "type": kind}
            index += 1
        return result


def run_hidden(args, cwd: Path, timeout=45):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    start = time.perf_counter()
    completed = subprocess.run([str(arg) for arg in args], cwd=cwd, timeout=timeout,
                               startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                               capture_output=True)
    return {"exit_code": completed.returncode, "seconds": round(time.perf_counter()-start, 3),
            "stdout": completed.stdout.decode("utf-8", errors="replace"),
            "stderr": completed.stderr.decode("utf-8", errors="replace")}


class Verification:
    def __init__(self, supplied_exe=None):
        assert os.name == "nt", "La comprobación requiere Windows."
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.base = ROOT / "build/uninstaller-tests" / stamp
        self.base.mkdir(parents=True, exist_ok=False)
        self.output = ROOT / "output/portability" / ("desinstalador-"+stamp)
        self.output.mkdir(parents=True, exist_ok=False)
        self.reg_before = registry_snapshot()
        source_digest = sha(SOURCE)
        self.exe = Path(supplied_exe).resolve() if supplied_exe else self.compile()
        self.report = {"ok": False, "version": VERSION,
                       "started_utc": datetime.now(timezone.utc).isoformat(),
                       "source_sha256": source_digest, "executable": str(self.exe),
                       "executable_sha256": sha(self.exe), "fixtures": str(self.base),
                       "registry_before": self.reg_before, "cases": []}
        self.counter = 0

    def compile(self):
        compiler = Path(os.environ["SystemRoot"])/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        assert compiler.is_file() and SOURCE.is_file()
        exe = self.base / "Desinstalar-verificado.exe"
        args = [compiler, "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                "/out:"+str(exe), "/win32manifest:"+str(ROOT/"installer/asInvoker.manifest"),
                "/win32icon:"+str(ROOT/"assets/icons/pdfmodder.ico"),
                "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                "/reference:System.Web.Extensions.dll", SOURCE]
        result = run_hidden(args, ROOT)
        assert result["exit_code"] == 0, result
        (self.output / "compilacion.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return exe

    def fixture(self, name):
        target = self.base / name
        assert target.resolve().is_relative_to(self.base.resolve())
        target.mkdir(exist_ok=False)
        (target/"_internal/sub").mkdir(parents=True)
        shutil.copyfile(self.exe, target/"Desinstalar.exe")
        (target/"PDFModder.exe").write_bytes(b"synthetic editor fixture; not executable\n")
        (target/"_internal/sub/library.bin").write_bytes(b"synthetic immutable payload\n")
        (target/MARKER).write_text(json.dumps({"application_id":"PDFModder.Windows.PerUser",
                                             "version":VERSION,"installer_revision":1}), encoding="utf-8")
        paths = ["PDFModder.exe", "_internal/sub/library.bin", "Desinstalar.exe"]
        self.write_inventory(target, paths)
        return target

    @staticmethod
    def row(path, relative):
        return sha(path)+"\t"+str(native(path).stat().st_size)+"\t"+relative

    def write_inventory(self, target, paths):
        (target/MANIFEST).write_text("\n".join(self.row(target/name, name) for name in paths)+"\n",encoding="utf-8")

    def launch(self, target, *, executable=None, protected_probe=False, report_path=None):
        if not protected_probe:
            assert target.resolve().is_relative_to(self.base.resolve()), target
        self.counter += 1
        path = report_path or self.output / f"operation-{self.counter:02d}.json"
        result = run_hidden([executable or self.exe, "--silent", "--dir", target, "--report", path], self.base)
        if result["exit_code"] == 0:
            # The public entry point returns once its verified temporary copy
            # starts. The report is the worker's completion result.
            deadline = time.monotonic()+45
            while time.monotonic() < deadline:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8-sig"))
                    result["worker_report"] = payload
                    break
                except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                    time.sleep(.1)
            else:
                raise AssertionError("El worker no completó un informe JSON: "+str(path))
        elif path.is_file():
            result["worker_report"]=json.loads(path.read_text(encoding="utf-8-sig"))
        result["report_path"] = str(path)
        return result

    @staticmethod
    def success(result):
        assert result["exit_code"] == 0 and result.get("worker_report", {}).get("ok") is True, result

    @staticmethod
    def blocked(result):
        assert result["exit_code"] != 0 or result.get("worker_report", {}).get("ok") is False, result

    def case(self, name, operation):
        started = time.perf_counter()
        entry = {"name": name}
        try:
            entry["evidence"] = operation()
            entry["passed"] = True
        except Exception as exc:
            entry.update(passed=False, error=str(exc), diagnostic=traceback.format_exc())
        entry["seconds"] = round(time.perf_counter()-started,3)
        self.report["cases"].append(entry)
        print(json.dumps({"case":name,"passed":entry["passed"],"error":entry.get("error")},ensure_ascii=True),flush=True)

    def ordinary(self):
        target = self.fixture("01 Instalada con acentos á")
        user = target/"factura del usuario.pdf"
        user.write_bytes(b"%PDF synthetic user-owned document; must survive\n")
        nested = target/"_internal/sub/foto-usuario.png"
        nested.write_bytes(b"synthetic user photo\n")
        known = {user:sha(user),nested:sha(nested)}
        result = self.launch(target)
        self.success(result)
        assert snapshot(target) == {p.relative_to(target).as_posix():digest for p,digest in known.items()}
        assert result["worker_report"]["preserved"] == 2
        repeat_before = snapshot(target)
        repeat = self.launch(target)
        self.blocked(repeat)
        assert snapshot(target) == repeat_before
        return {"first":result,"second_no_changes":repeat,"preserved":repeat_before}

    def modified(self):
        target = self.fixture("02 Modificado")
        altered = target/"_internal/sub/library.bin"
        altered.write_bytes(b"modified by user; preserve even though inventoried\n")
        digest = sha(altered)
        result = self.launch(target)
        self.success(result)
        assert snapshot(target) == {"_internal/sub/library.bin":digest}
        assert result["worker_report"]["preserved"] == 1
        return result

    def missing_payload(self):
        target = self.fixture("03 Parcial anterior")
        selected = target/"_internal/sub/library.bin"
        assert selected.resolve().is_relative_to(self.base.resolve())
        selected.unlink()
        result = self.launch(target)
        self.success(result)
        assert not target.exists(), "La carpeta vacía debería poder retirarse."
        repeat = self.launch(target)
        self.blocked(repeat)
        assert not target.exists()
        return {"first":result,"already_absent_no_changes":repeat}

    def malformed(self, name, extra):
        target = self.fixture(name)
        with (target/MANIFEST).open("a",encoding="utf-8") as stream:
            stream.write(extra(target)+"\n")
        before = snapshot(target)
        result = self.launch(target)
        self.blocked(result)
        assert snapshot(target) == before, "Un manifiesto inválido no permite borrados parciales."
        return result

    def marker(self, name, mode):
        target = self.fixture(name)
        path = target/MARKER
        if mode == "missing":
            assert path.resolve().is_relative_to(self.base.resolve())
            path.unlink()
        else:
            path.write_text(json.dumps({"application_id":"OtraAplicacion","version":VERSION}),encoding="utf-8")
        before = snapshot(target)
        result = self.launch(target)
        self.blocked(result)
        assert snapshot(target) == before
        return result

    def locked(self):
        target = self.fixture("12 Archivo abierto")
        path = target/"_internal/sub/library.bin"
        before = snapshot(target)
        kernel = ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(path),0x80000000,0,None,3,0x80,None)
        assert handle not in (None,ctypes.c_void_p(-1).value), ctypes.get_last_error()
        try:
            blocked = self.launch(target)
            self.blocked(blocked)
        finally:
            assert kernel.CloseHandle(handle)
        assert snapshot(target) == before, "El bloqueo debe detectarse antes de borrar archivos."
        retry = self.launch(target)
        self.success(retry)
        assert not target.exists()
        return {"while_locked":blocked,"after_close":retry}

    def self_running(self):
        target = self.fixture("13 Ejecución desde carpeta propia á")
        own = target/"Desinstalar.exe"
        digest = sha(own)
        result = self.launch(target,executable=own)
        self.success(result)
        assert not own.exists() and not target.exists()
        assert "Desinstalar.exe" in result["worker_report"]["removed_files"]
        return {"self_executable_sha256":digest,**result}

    def existing_report(self):
        target = self.fixture("14 Informe existente")
        path = self.output/"informe-del-usuario.json"
        path.write_text('{"usuario":"conservar"}',encoding="utf-8")
        digest = sha(path)
        before = snapshot(target)
        # This fails in the temporary worker before the uninstall operation.
        # Public launcher returns zero, so inspect the protected report and
        # payload after a bounded process-settle interval rather than treating
        # its unrelated JSON as an uninstall completion.
        result = run_hidden([self.exe,"--silent","--dir",target,"--report",path],self.base)
        time.sleep(1)
        assert sha(path) == digest and snapshot(target) == before
        return result

    def long_paths(self):
        target=self.fixture("15 Rutas largas con acentos á")
        relative="_internal/licenses/"+"fuente-y-biblioteca-"*5+"/"+"licencia-"*15+"terminos.txt"
        payload=target/relative
        personal=payload.parent/("documento-personal-"*6+"á.pdf")
        assert len(str(payload))>300 and len(str(personal))>300
        assert payload.resolve().is_relative_to(self.base.resolve()) and personal.resolve().is_relative_to(self.base.resolve())
        native(payload.parent).mkdir(parents=True,exist_ok=True)
        native(payload).write_bytes(b"inventoried immutable long-path dependency\n")
        native(personal).write_bytes(b"%PDF personal long-path file: must survive\n")
        digest=sha(personal)
        with (target/MANIFEST).open("a",encoding="utf-8") as stream:
            stream.write(self.row(payload,relative)+"\n")
        result=self.launch(target)
        self.success(result)
        assert not native(payload).exists()
        assert snapshot(target)=={personal.relative_to(target).as_posix():digest}
        assert result["worker_report"]["preserved"]==1
        return {"payload_absolute_length":len(str(payload)),"personal_absolute_length":len(str(personal)),**result}

    def early_failure_report(self):
        target=self.fixture("16 Fallo previo con informe")
        marker=target/MARKER
        assert marker.resolve().is_relative_to(self.base.resolve())
        marker.unlink()
        before=snapshot(target)
        result=self.launch(target)
        self.blocked(result)
        failure=result.get("worker_report",{})
        assert failure.get("ok") is False and failure.get("error"), result
        assert snapshot(target)==before
        return result

    def invalid_report_path(self):
        target=self.fixture("17 Informe dentro de instalación")
        before=snapshot(target)
        forbidden=target/"informe-no-permitido.json"
        result=self.launch(target,report_path=forbidden)
        self.blocked(result)
        assert not forbidden.exists() and snapshot(target)==before
        return result

    def verify(self):
        sentinel = self.base/"sentinel-exterior.txt"
        sentinel.write_bytes(b"external to every installation fixture\n")
        sentinel_hash = sha(sentinel)
        self.case("Sólo inventario; PDF e imagen de usuario conservados; repetición inocua",self.ordinary)
        self.case("Archivo inventariado modificado conservado",self.modified)
        self.case("Instalación parcial e idempotencia con carpeta ya ausente",self.missing_payload)
        self.case("Traversal rechazado sin modificar sentinel externo",lambda:self.malformed("04 Traversal",lambda target:self.row(sentinel,"../sentinel-exterior.txt")))
        self.case("Ruta absoluta externa rechazada",lambda:self.malformed("05 Absoluta",lambda target:self.row(sentinel,str(sentinel))))
        self.case("Ruta raíz rechazada",lambda:self.malformed("06 Raíz",lambda target:self.row(sentinel,"/")))
        self.case("Entrada duplicada ignorando mayúsculas rechazada",lambda:self.malformed("07 Duplicada",lambda target:self.row(target/"PDFModder.exe","pdfmodder.EXE")))
        self.case("Marcador protegido no admitido como payload",lambda:self.malformed("08 Marcador protegido",lambda target:self.row(target/MARKER,MARKER)))
        self.case("Inventario protegido no admitido como payload",lambda:self.malformed("08b Inventario protegido",lambda target:self.row(target/MANIFEST,MANIFEST)))
        self.case("Flujo alternativo NTFS rechazado",lambda:self.malformed("09 Flujo alternativo",lambda target:self.row(sentinel,"PDFModder.exe:otro")))
        self.case("Directorio sin marcador intacto",lambda:self.marker("10 Sin marcador","missing"))
        self.case("Marcador de aplicación ajena intacto",lambda:self.marker("11 Aplicación ajena","foreign"))
        self.case("Archivo bloqueado: preflight sin borrado y reintento",self.locked)
        self.case("Autodesinstalación desde su propia carpeta",self.self_running)
        self.case("Informe existente nunca se sobrescribe",self.existing_report)
        self.case("Rutas absolutas largas: inventario retirado y PDF personal conservado",self.long_paths)
        self.case("Fallo previo a worker produce informe de error",self.early_failure_report)
        self.case("Ruta de informe dentro de instalación rechazada sin cambios",self.invalid_report_path)
        self.case("Raíz de unidad protegida rechazada",lambda:self.protected(Path(self.base.anchor)))
        self.case("Raíz del perfil protegida rechazada",lambda:self.protected(Path(os.environ["USERPROFILE"])))
        self.report["sentinel_unchanged"] = sha(sentinel) == sentinel_hash
        self.report["registry_after"] = registry_snapshot()
        self.report["registry_unchanged"] = self.report["registry_after"] == self.reg_before
        self.report["source_unchanged_during_test"] = sha(SOURCE) == self.report["source_sha256"]
        self.report["ok"] = (all(case["passed"] for case in self.report["cases"])
                             and self.report["sentinel_unchanged"] and self.report["registry_unchanged"]
                             and self.report["source_unchanged_during_test"])
        self.report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        path = self.output/"verificacion-desinstalador.json"
        path.write_text(json.dumps(self.report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"ok":self.report["ok"],"cases":len(self.report["cases"]),"report":str(path)},ensure_ascii=True),flush=True)
        return 0 if self.report["ok"] else 1

    def protected(self, target):
        # These preflight-only probes are allowed only for exact known protected
        # roots after source inspection of InstallationRoot's early rejection.
        assert target in (Path(self.base.anchor),Path(os.environ["USERPROFILE"]))
        result = self.launch(target,protected_probe=True)
        self.blocked(result)
        return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe",type=Path,help="Verificar un Desinstalar.exe ya compilado sin recompilarlo.")
    args=parser.parse_args()
    raise SystemExit(Verification(args.exe).verify())
