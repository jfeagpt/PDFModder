"""Empaqueta 1.6.1 con pruebas dirigidas, sin atribuirle la batería de 1.5.0."""
import argparse
from datetime import datetime, timezone
import json
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


def prepare():
    assert __version__ == '1.6.1'
    binding = read(ROOT / 'output/v161-source-tests.json')
    xml = ROOT / 'output/pytest-v161-results.xml'
    assert binding['exit_code'] == 0 and binding['source_unchanged']
    assert binding['app_source_sha256'] == source_fingerprint()
    assert binding['report_sha256'] == digest(xml)
    suites = [s for s in ET.parse(xml).getroot().iter('testsuite') if not s.findall('testsuite')]
    assert suites and all(int(s.get(k, '0')) == 0 for s in suites for k in ('failures', 'errors'))
    tests = sum(int(s.get('tests', '0')) for s in suites)
    skipped = sum(int(s.get('skipped', '0')) for s in suites)
    for path in application_sources():
        assert digest(path) == digest(BUNDLE / '_internal/source/PDFModder' / path.relative_to(ROOT)), path
    smoke_path = ROOT / 'output/packaged-v161-smoke.json'
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
    evidence = {
        'application': 'PDF Modder ' + __version__, 'platform': 'Windows 11 x64',
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
        'scope': 'Comprobaciones dirigidas a los cambios de 1.6.1 y recorrido del ejecutable. '
                 'No se repite la batería completa ni el corpus completo de 1.5.0. '
                 'Firma ensayada con certificado sintético; sin TSA, revocación ni confianza externa. '
                 'Instalación y retirada se acreditan por separado; no otro ordenador físico.',
    }
    (ROOT / 'docs/RESULTADOS_V161.md').write_text(
        '# Comprobaciones de PDF Modder 1.6.1\n\n'
        f'- Pruebas dirigidas: {tests-skipped} aprobadas; {skipped} omitidas; cero fallos.\n'
        f'- Ejecutable Windows: {len(smoke["steps"])} pasos aprobados.\n'
        '- La firma usa un certificado sintético generado para la prueba; se comprueban '
        'integridad criptográfica y cobertura del archivo. No valida un certificado personal.\n'
        '- Instalación y desinstalación: informe separado INSTALACION-VERIFICADA.json.\n'
        '- No se ha repetido la batería completa ni las 64 operaciones de la versión 1.5.0.\n'
        '- No se ha probado en otro equipo físico. Límites en GUIA_V161.md.\n', encoding='utf-8')
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
