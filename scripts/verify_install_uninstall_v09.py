"""Instala y retira la versión del proyecto en un directorio aislado.

Requiere que la clave HKCU de esa versión no exista: nunca cambia una instalación
previa. La prueba registra temporalmente la copia y la retira mediante su
propio desinstalador. Ejecuta el editor con documentos de prueba, sin modificar
documentos existentes.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__ as VERSION

CURRENT_SUITE = 'v' + VERSION.replace('.', '')
SUPPORTED_SUITES = tuple(dict.fromkeys(('v09', 'compat', 'v160', 'v161', 'v162', 'v170', 'v171', CURRENT_SUITE)))
KEY = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PDFModder-' + VERSION
INSTALLER = ROOT / ('releases/v' + VERSION) / ('PDFModder-v' + VERSION + '-Instalar.exe')


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
    environment = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'QT_PLUGIN_PATH',
                 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        environment.pop(name, None)
    windows = Path(environment.get('SystemRoot', 'C:/Windows'))
    environment['PATH'] = os.pathsep.join(str(windows / part) for part in ('System32', '', 'System32/Wbem'))
    return subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True,
                          env=environment, creationflags=subprocess.CREATE_NO_WINDOW, timeout=210)


def readable_file(path):
    # The installer supports extended Windows paths even when the development
    # Python launcher does not opt into the system's long-path policy.
    resolved = Path(path).resolve()
    return Path('\\\\?\\' + str(resolved)) if os.name == 'nt' else resolved


def main(suites=None):
    suites = (CURRENT_SUITE,) if suites is None else suites
    if registry() is not None:
        raise RuntimeError(f'Existe una entrada real de {VERSION}; no se modifica durante la prueba.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    base = ROOT / 'output/portability' / ('install-uninstall-v' + VERSION.replace('.', '') + '-' + stamp)
    base.mkdir(parents=True)
    target = base / 'Aplicacion con espacios y acentos á'
    if not target.resolve().is_relative_to((ROOT / 'output/portability').resolve()):
        raise RuntimeError('La carpeta de prueba debe estar dentro del proyecto.')
    install_report = base / 'instalacion.json'
    uninstall_report = base / 'desinstalacion.json'
    report = {'ok': False, 'application_version': VERSION,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'tests': [],
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
        assert values['DisplayVersion'] == VERSION and Path(values['InstallLocation']) == target, values
        assert str(target / 'Desinstalar.exe') in values['UninstallString'] and '--silent' in values['QuietUninstallString']
        programs = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs' / ('PDF Modder ' + VERSION)
        app_link = programs / ('PDF Modder ' + VERSION + '.lnk')
        uninstall_link = programs / ('Desinstalar PDF Modder ' + VERSION + '.lnk')
        assert app_link.is_file() and uninstall_link.is_file()
        report['tests'].append({'name': 'instalacion_registro_inventario_accesos', 'passed': True, 'files': installed['files']})
        for row in records:
            digest, size, relative = row.split('\t')
            file = readable_file(target / relative)
            assert file.is_file() and file.stat().st_size == int(size), relative
            assert hashlib.sha256(file.read_bytes()).hexdigest() == digest, relative
        report['tests'].append({'name':'todos_los_archivos_instalados_coinciden','passed':True,'files':len(records)})
        editor_runs=[]
        for suite in suites:
            smoke_report = base / ('editor-instalado-'+suite+'.json')
            result = run([target / 'PDFModder.exe', '--smoke-'+suite, smoke_report], base)
            assert result.returncode == 0, (result.returncode, result.stderr)
            smoke = json.loads(smoke_report.read_text(encoding='utf-8'))
            assert smoke['ok'] and smoke['frozen'] and smoke['app_version'] == VERSION, smoke
            assert all(step['ok'] for step in smoke['steps'])
            assert smoke['exe_sha256'] == hashlib.sha256((target / 'PDFModder.exe').read_bytes()).hexdigest()
            editor_runs.append({'suite':suite,'steps':len(smoke['steps'])})
        report['tests'].append({'name':'editor_instalado_editar_guardar_reabrir','passed':True,
                               'steps':sum(r['steps'] for r in editor_runs),'runs':editor_runs})
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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', action='append', choices=SUPPORTED_SUITES)
    selected_suites = parser.parse_args().suite
    main(tuple(selected_suites) if selected_suites else None)
