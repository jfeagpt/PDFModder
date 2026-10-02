"""Instala y retira el paquete 0.8.3 en un directorio aislado del proyecto.

Requiere que la clave HKCU de 0.8.3 no exista: nunca cambia una instalación
previa. La prueba registra temporalmente la copia y la retira mediante su
propio desinstalador. No abre el editor ni modifica documentos existentes.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import winreg

ROOT = Path(__file__).resolve().parents[1]
KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFModder-0.8.3'
INSTALLER = ROOT / 'releases/v0.8.3/PDFModder-v0.8.3-Instalar.exe'


def registry():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY)
    except FileNotFoundError:
        return None
    with key:
        values = {}
        for index in range(winreg.QueryInfoKey(key)[1]):
            name, value, _kind = winreg.EnumValue(key, index)
            values[name] = value
        return values


def run(args, cwd):
    return subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)


def main():
    if registry() is not None:
        raise RuntimeError('Existe una entrada real de 0.8.3; no se modifica durante la prueba.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    base = ROOT / 'output/portability' / ('install-uninstall-v083-' + stamp)
    base.mkdir(parents=True)
    target = base / 'Aplicacion instalada'
    install_report = base / 'instalacion.json'
    uninstall_report = base / 'desinstalacion.json'
    report = {'ok': False, 'started_utc': datetime.now(timezone.utc).isoformat(), 'tests': [],
              'installer_sha256': hashlib.sha256(INSTALLER.read_bytes()).hexdigest()}
    report_path = base / 'resultado.json'
    try:
        result = run([INSTALLER, '--silent', '--dir', target, '--no-shortcut', '--no-launch', '--report', install_report], base)
        assert result.returncode == 0, (result.returncode, result.stderr)
        installed = json.loads(install_report.read_text(encoding='utf-8-sig'))
        assert installed['ok'] and not installed['warnings'], installed
        assert (target / 'PDFModder.exe').is_file() and (target / 'Desinstalar.exe').is_file()
        records = (target / '.pdfmodder-files.tsv').read_text(encoding='utf-8-sig').splitlines()
        assert any(row.endswith('\tDesinstalar.exe') for row in records)
        values = registry()
        assert values['DisplayVersion'] == '0.8.3' and Path(values['InstallLocation']) == target, values
        assert str(target / 'Desinstalar.exe') in values['UninstallString'] and '--silent' in values['QuietUninstallString']
        programs = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/PDF Modder 0.8.3'
        app_link = programs / 'PDF Modder 0.8.3.lnk'
        uninstall_link = programs / 'Desinstalar PDF Modder 0.8.3.lnk'
        assert app_link.is_file() and uninstall_link.is_file()
        report['tests'].append({'name': 'instalacion_registro_inventario_accesos', 'passed': True, 'files': installed['files']})
        sentinel = target / 'documento-personal.pdf'
        sentinel.write_bytes(b'%PDF-1.4\nDocumento de prueba que debe conservarse\n%%EOF\n')
        modified = target / '_internal/README.md'
        modified.write_text('Archivo modificado por el usuario. Conservar.', encoding='utf-8')
        expected_pdf = sentinel.read_bytes()
        expected_modified = modified.read_bytes()
        result = run([target / 'Desinstalar.exe', '--silent', '--dir', target, '--report', uninstall_report], base)
        assert result.returncode == 0, result.returncode
        deadline = time.monotonic() + 90
        outcome = None
        while time.monotonic() < deadline:
            try:
                outcome = json.loads(uninstall_report.read_text(encoding='utf-8-sig'))
                break
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                time.sleep(0.2)
        assert outcome is not None and outcome['ok'], outcome
        assert not outcome['warnings'], outcome
        assert sentinel.read_bytes() == expected_pdf and modified.read_bytes() == expected_modified
        assert not (target / 'PDFModder.exe').exists() and not (target / 'Desinstalar.exe').exists()
        assert not (target / '.pdfmodder-installation.json').exists()
        assert not (target / '.pdfmodder-files.tsv').exists()
        assert registry() is None and not app_link.exists() and not uninstall_link.exists()
        remaining = sorted(p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file())
        assert remaining == ['_internal/README.md', 'documento-personal.pdf'], remaining
        report['tests'].append({'name': 'desinstalacion_real_conserva_documento_y_modificado', 'passed': True,
                                'removed': outcome['removed'], 'preserved': outcome['preserved'], 'remaining': remaining})
        report['ok'] = True
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(report_path), **report}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
