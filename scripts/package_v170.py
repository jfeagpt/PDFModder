"""Empaqueta la versión actual con evidencia de sus propias pruebas dirigidas."""
import argparse
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_licenses import source_files
from scripts.package_v09 import (BUNDLE, RELEASE, application_sources, digest,
                                 finish, read, source_fingerprint, write)
from pdfmodder import __version__

SUITE = 'v' + __version__.replace('.', '')


def prepare():
    binding = read(ROOT / f'output/{SUITE}-source-tests.json')
    xml = ROOT / f'output/pytest-{SUITE}-results.xml'
    assert binding['exit_code'] == 0 and binding['source_unchanged']
    assert binding.get('application_version', __version__) == __version__
    assert binding['app_source_sha256'] == source_fingerprint()
    assert binding['report_sha256'] == digest(xml)
    suites = [s for s in ET.parse(xml).getroot().iter('testsuite') if not s.findall('testsuite')]
    assert suites and all(int(s.get(k, '0')) == 0 for s in suites for k in ('failures', 'errors'))
    tests = sum(int(s.get('tests', '0')) for s in suites)
    skipped = sum(int(s.get('skipped', '0')) for s in suites)
    for path in application_sources():
        assert digest(path) == digest(BUNDLE / '_internal/source/PDFModder' / path.relative_to(ROOT)), path
    smoke_path = ROOT / f'output/packaged-{SUITE}-smoke.json'
    smoke = read(smoke_path)
    exe_hash = digest(BUNDLE / 'PDFModder.exe')
    assert smoke['ok'] and smoke['frozen'] and smoke['stage'] == 'complete'
    assert smoke['app_version'] == __version__ and smoke['exe_sha256'] == exe_hash
    assert smoke['steps'] and all(step['ok'] for step in smoke['steps'])
    assert smoke['source_sha256'] == digest(smoke['source'])
    bridge = read(ROOT / 'output/signing-bridge-v160.json')
    assert bridge['ok'] and bridge['temporary_certificate_and_key_removed']
    assert bridge['signature_verified_independently'] and not bridge['private_keys_exported']
    assert bridge['exe_sha256'] == digest(BUNDLE / 'PDFModderSigningBridge.exe')
    assert bridge['source_sha256'] == digest(ROOT / 'installer/PdfModderSigningBridge.cs')
    if SUITE == 'v171':
        checked_scope = 'Lectura, selección de texto y navegación con documentos sintéticos'
        checked_note = 'Se comprueban lectura, selección de texto y navegación con documentos sintéticos.'
    else:
        checked_scope = 'Cifrado y portapapeles con corpus sintético'
        checked_note = 'Se contrastan metadatos y cifrado con documentos y certificados sintéticos.'
    evidence = {
        'application': 'PDF Modder ' + __version__, 'platform': platform.platform(),
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'delivery_status': 'targeted_checks_passed', 'tested': True, 'frozen_verified': True,
        'app_source_sha256': source_fingerprint(), 'exe_sha256': exe_hash,
        'pytest': {'passed': tests-skipped, 'skipped': skipped, 'failures': 0,
                   'report_sha256': digest(xml), 'selection': binding['tests']},
        'frozen_smoke': {'steps': len(smoke['steps']), 'seconds': smoke['elapsed_seconds'],
                         'report_sha256': digest(smoke_path)},
        'windows_certificate_bridge': bridge,
        'private_documents_included': False, 'personal_certificates_included': False,
        'source_manifest': '_internal/source/MANIFEST.json',
        'scope': f'Comprobaciones dirigidas a los cambios de {__version__} y recorrido del ejecutable. '
                 'No se repite la batería completa ni el corpus completo de 1.5.0. '
                 f'{checked_scope}; sin publicación remota acreditada. '
                 'Instalación y retirada se acreditan por separado; no otro ordenador físico.',
    }
    (ROOT / f'docs/RESULTADOS_{SUITE.upper()}.md').write_text(
        f'# Comprobaciones de PDF Modder {__version__}\n\n'
        f'- Pruebas dirigidas: {tests-skipped} aprobadas; {skipped} omitidas; cero fallos.\n'
        f'- Ejecutable Windows: {len(smoke["steps"])} pasos aprobados.\n'
        f'- {checked_note} '
        'No se prueba una clave personal ni otro ordenador físico.\n'
        '- Instalación y desinstalación: informe separado INSTALACION-VERIFICADA.json.\n'
        '- No se ha repetido la batería completa ni las 64 operaciones de la versión 1.5.0.\n'
        f'- No se ha probado en otro equipo físico. Límites en GUIA_{SUITE.upper()}.md.\n', encoding='utf-8')
    RELEASE.mkdir(parents=True, exist_ok=True)
    for target in (BUNDLE / 'ENTREGA.json', RELEASE / 'ENTREGA.json'):
        write(target, evidence)
    for path in [ROOT / 'README.md', *[p for p in (ROOT / 'docs').rglob('*') if p.is_file()]]:
        target = BUNDLE / '_internal' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(ROOT / 'README.md', BUNDLE / 'README.md')
    inventory = []
    for path, relative in source_files():
        target = BUNDLE / '_internal/source/PDFModder' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        inventory.append({'path': relative.as_posix(), 'sha256': digest(path)})
    write(BUNDLE / '_internal/source/MANIFEST.json', inventory)
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument('--prepare', action='store_true')
    choices.add_argument('--finish', type=Path)
    args = parser.parse_args()
    prepare() if args.prepare else finish(args.finish)
