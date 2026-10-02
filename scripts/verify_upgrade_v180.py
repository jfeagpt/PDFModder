"""Exercise the Windows upgrade transaction with an isolated previous instance.

The small fixture uses the actual historical uninstaller compiled from its
versioned template. No real prior installation or document is touched. The new
installer is the release executable, with its full payload and inventory checks.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import winreg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__ as VERSION


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(arguments, directory):
    result = subprocess.run([str(item) for item in arguments], cwd=directory,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            capture_output=True, timeout=210)
    return result


def completed_report(path, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            report = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(report, dict) and 'ok' in report:
                return report
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    raise RuntimeError('No se recibió el informe final: ' + str(path))


def historical_uninstaller(destination, base):
    template = (ROOT / 'installer/PdfModderUninstaller.cs').read_text(encoding='utf-8-sig')
    original = re.search(r'const string Version = "([0-9.]+)"', template).group(1)
    source = base / 'Desinstalador-1.7.1.cs'
    source.write_text(template.replace(original, '1.7.1'), encoding='utf-8-sig')
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    arguments = [compiler, '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                 '/out:' + str(destination), '/reference:System.Windows.Forms.dll',
                 '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
                 '/win32manifest:' + str(ROOT / 'installer/asInvoker.manifest'), source]
    result = run(arguments, base)
    if result.returncode:
        raise RuntimeError(result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))


def main():
    installer = ROOT / 'releases' / ('v' + VERSION) / ('PDFModder-v' + VERSION + '-Instalar.exe')
    key = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PDFModder-' + VERSION
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise RuntimeError('Existe una instalación real de ' + VERSION + '; no se modifica durante la prueba.')
    except FileNotFoundError:
        pass
    parent = (ROOT / 'output/portability').resolve()
    base = parent / ('upgrade-v180-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    if not base.is_relative_to(parent):
        raise RuntimeError('La carpeta de prueba sale del proyecto.')
    base.mkdir(parents=True)
    old, new, foreign = base / 'Anterior á', base / 'Nueva á', base / 'Carpeta ajena'
    old.mkdir(); foreign.mkdir()
    foreign_file = foreign / 'archivo-personal.txt'
    foreign_file.write_bytes(b'Este directorio no se puede reemplazar')
    historical_uninstaller(old / 'Desinstalar.exe', base)
    (old / 'PDFModder.exe').write_bytes(b'MZ previous application fixture')
    (old / 'archivo-modificado.txt').write_bytes(b'Contenido distribuido original')
    records = [f'{sha(path)}\t{path.stat().st_size}\t{path.name}' for path in sorted(old.iterdir())]
    (old / '.pdfmodder-files.tsv').write_text('\n'.join(records) + '\n', encoding='utf-8')
    marker = old / '.pdfmodder-installation.json'
    marker.write_text(json.dumps({'application_id': 'PDFModder.Windows.PerUser', 'version': '1.7.1'}), encoding='utf-8')
    marker_bytes = marker.read_bytes()
    personal = old / 'documento-personal.pdf'
    personal.write_bytes(b'%PDF-1.4\nDocumento personal de prueba\n%%EOF\n')
    personal_hash = sha(personal)
    (old / 'archivo-modificado.txt').write_bytes(b'Cambios personales que deben conservarse')
    modified_hash = sha(old / 'archivo-modificado.txt')
    settings = base / 'preferencias-locales.json'
    settings.write_bytes(b'{"test":"conservar"}')
    settings_hash = sha(settings)
    evidence = {'ok': False, 'application_version': VERSION, 'previous_version': '1.7.1',
                'fixture': 'instalacion_minima_representativa_con_desinstalador_real',
                'started_utc': datetime.now(timezone.utc).isoformat(),
                'installer_sha256': sha(installer), 'tests': []}
    new_installed = False
    try:
        bad_report = base / 'destino-ajeno.json'
        result = run([installer, '--update', '--silent', '--dir', foreign, '--previous-dir', old,
                      '--no-shortcut', '--no-launch', '--report', bad_report], base)
        rejected = completed_report(bad_report)
        assert result.returncode == 1 and not rejected['ok']
        assert (old / 'PDFModder.exe').exists() and marker.read_bytes() == marker_bytes
        assert foreign_file.read_bytes() == b'Este directorio no se puede reemplazar'
        evidence['tests'].append({'name': 'fallo_destino_conserva_instalacion_anterior_y_archivos_ajenos', 'passed': True})

        marker.write_text(json.dumps({'application_id': 'OtraApp', 'version': '1.7.1'}), encoding='utf-8')
        foreign_report = base / 'origen-ajeno.json'
        result = run([installer, '--update', '--silent', '--dir', new, '--previous-dir', old,
                      '--no-shortcut', '--no-launch', '--report', foreign_report], base)
        assert result.returncode == 1 and not completed_report(foreign_report)['ok'] and not new.exists()
        assert (old / 'PDFModder.exe').exists() and sha(personal) == personal_hash
        marker.write_bytes(marker_bytes)
        evidence['tests'].append({'name': 'rechaza_retirar_instalacion_sin_identidad_valida', 'passed': True})

        uninstaller = old / 'Desinstalar.exe'
        original_uninstaller = uninstaller.read_bytes()
        uninstaller.write_bytes(original_uninstaller + b'modified')
        tamper_report = base / 'desinstalador-modificado.json'
        result = run([installer, '--update', '--silent', '--dir', new, '--previous-dir', old,
                      '--no-shortcut', '--no-launch', '--report', tamper_report], base)
        assert result.returncode == 1 and not completed_report(tamper_report)['ok'] and not new.exists()
        uninstaller.write_bytes(original_uninstaller)
        evidence['tests'].append({'name': 'rechaza_desinstalador_modificado_sin_ejecutarlo', 'passed': True})

        upgrade_report = base / 'actualizacion.json'
        result = run([installer, '--update', '--silent', '--dir', new, '--previous-dir', old,
                      '--no-shortcut', '--no-launch', '--report', upgrade_report], base)
        upgrade = completed_report(upgrade_report)
        new_installed = (new / 'Desinstalar.exe').is_file()
        assert result.returncode == 0 and upgrade['ok'] and upgrade['previous_removed'], upgrade
        assert not (old / 'PDFModder.exe').exists() and not marker.exists()
        assert new_installed and (new / 'PDFModder.exe').is_file()
        assert sha(personal) == personal_hash and sha(old / 'archivo-modificado.txt') == modified_hash and sha(settings) == settings_hash
        evidence['tests'].append({'name': 'actualiza_retira_anterior_conserva_pdf_archivos_modificados_y_preferencias',
                                  'passed': True, 'verified_new_files': upgrade['files'],
                                  'previous_uninstaller_report': upgrade['uninstall_report']})
        evidence['ok'] = True
    finally:
        if new_installed:
            cleanup = base / 'retirada-nueva.json'
            run([new / 'Desinstalar.exe', '--silent', '--dir', new, '--report', cleanup], base)
            cleaned = completed_report(cleanup)
            if not cleaned['ok']:
                evidence['ok'] = False
                evidence['cleanup_error'] = cleaned
                raise RuntimeError('No se retiró la instalación aislada: ' + str(cleanup))
        report = base / 'resultado.json'
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(report), 'ok': evidence['ok'], 'tests': len(evidence['tests'])}))
    return evidence


if __name__ == '__main__':
    main()
