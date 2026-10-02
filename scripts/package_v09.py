"""Empaqueta la entrega actual con su estado de verificación explícito.

--prepare reúne la evidencia y los documentos antes de compilar el instalador.
--finish exige la prueba de instalación/desinstalación y crea ZIP y sumas SHA-256.
--prepare-unverified y --finish-unverified son rutas separadas que no ejecutan
ni consultan pruebas: identifican el paquete como compilado sin verificación final.
No incluye facturas ni resultados privados.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__
from scripts.collect_licenses import source_files

BUNDLE = ROOT / 'dist/PDFModder'
RELEASE = ROOT / ('releases/v' + __version__)
LABEL = 'PDFModder-v' + __version__
FROZEN_SUITES = ('extended', 'tagged', 'clipped', 'v08', 'v09', 'compat')
V091_CASES = {
    'anexo_direccion', 'anexo_titular', 'mapa_2026', 'anexo_eliminar_p2',
    'anexo_extraer_p2', 'anexo_reordenar',
}
V092_CASES = {
    name + '_' + route
    for name in ('ha_naturales', 'ha_franjas', 'ha_total_superior', 'ha_agricultor',
                 'ha_porcentaje', 'ha_total_inferior', 'ha_ampliar', 'ha_acortar',
                 'nombre_acortar', 'nombre_ampliar', 'fecha_regresion')
    for route in ('pagina', 'panel')
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    # Use identical LF bytes in the folder and ZIP payload also on Windows.
    Path(path).write_bytes(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))


def application_sources():
    return sorted(
        [*(ROOT / 'pdfmodder').rglob('*.py'), ROOT / 'run_pdfmodder.py'],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def source_fingerprint():
    """Bind acceptance reports to the precise productive Python source tested."""
    result = hashlib.sha256()
    for path in application_sources():
        result.update(path.relative_to(ROOT).as_posix().encode('utf-8'))
        result.update(b'\0')
        result.update(bytes.fromhex(digest(path)))
        result.update(b'\n')
    return result.hexdigest()


def checked_acceptance(path, names, fingerprint):
    acceptance = read(path)
    assert acceptance['verified'], path
    assert acceptance['application_version'] == __version__, path
    assert acceptance['app_source_sha256'] == fingerprint, 'La aceptación corresponde a otro código.'
    cases = acceptance['cases']
    assert len(cases) == len(names) and {c['name'] for c in cases} == set(names), path
    for case in cases:
        assert case['verified'] and case['source_unchanged'], case['name']
        output = Path(case['output']).resolve()
        assert output.is_relative_to(path.parent.resolve()), 'Salida de aceptación fuera de su carpeta.'
        assert digest(output) == case['output_sha256'], case['name']
    return acceptance


def prepare():
    exe_hash = digest(BUNDLE / 'PDFModder.exe')
    # Compare every executable Python module with source frozen during build.
    for path in application_sources():
        assert digest(path) == digest(BUNDLE / '_internal/source/PDFModder' / path.relative_to(ROOT)), path
    fingerprint = source_fingerprint()
    test_report = ROOT / 'output/pytest-v092-results.xml'
    suites = [s for s in ET.parse(test_report).getroot().iter('testsuite') if not s.findall('testsuite')]
    assert suites and all(int(s.get(k, '0')) == 0 for s in suites for k in ('failures', 'errors', 'skipped'))
    tests = sum(int(s.get('tests', '0')) for s in suites)
    # This is the previous delivered suite size, not a claimed new result.
    # Report the actual new total from the complete XML after it has passed.
    assert tests >= 653, tests
    frozen = {}
    for name in FROZEN_SUITES:
        report_path = ROOT / f'output/packaged-{name}-smoke.json'
        report = read(report_path)
        assert report['ok'] and report['frozen'] and report['stage'] == 'complete', name
        assert report['app_version'] == __version__ and report['exe_sha256'] == exe_hash, name
        assert report['steps'] and all(s['ok'] for s in report['steps']), name
        frozen[name] = {'steps': len(report['steps']), 'seconds': report['elapsed_seconds'], 'ok': True,
                        'report_sha256': digest(report_path)}
    verification = read(ROOT / 'output/packaged-verification.json')
    assert verification['ok'] and verification['executable_unchanged']
    assert verification['expected_version'] == __version__ and verification['exe_sha256'] == exe_hash
    assert {r['name'] for r in verification['runs']} == set(FROZEN_SUITES)
    assert len(verification['runs']) == len(FROZEN_SUITES)
    for run in verification['runs']:
        assert run['ok'] and run['source_unchanged'] and run['exe_sha256'] == exe_hash, run['name']
        assert run['report_sha256'] == frozen[run['name']]['report_sha256'], run['name']
    regression_path = ROOT / 'tmp/acceptance-v092-regression/report.json'
    regression = checked_acceptance(regression_path, {
        'digital_fecha', 'digital_fragmento', 'digital_parrafos', 'factura_espana',
        'factura_fecha', 'factura_nueva_linea', 'factura_fragmento', 'factura_concepto',
    }, fingerprint)
    previous_path = ROOT / 'tmp/compat-v092-private/v091-regression/report.json'
    previous = checked_acceptance(previous_path, V091_CASES, fingerprint)
    actual_path = ROOT / 'tmp/compat-v092-private/acceptance/report.json'
    actual = checked_acceptance(actual_path, V092_CASES, fingerprint)
    acceptances = (regression, previous, actual)
    rendered = [p for a in acceptances for c in a['cases'] for p in c['poppler_pages']]
    assert rendered and all(p['dpi'] == 144 and p['pixels_above_8_outside_mask'] == 0 for p in rendered)
    extractors = {'pypdf'}
    for acceptance in acceptances:
        for case in acceptance['cases']:
            additional = case.get('additional_extractor', {}).get('name')
            if additional:
                extractors.add(additional)
    RELEASE.mkdir(parents=True, exist_ok=True)
    evidence = {
        'application': 'PDF Modder ' + __version__, 'platform': 'Windows 11 x64',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'delivery_status': 'executable_verified', 'frozen_verified': True, 'tested': True,
        'exe_sha256': exe_hash, 'app_source_sha256': fingerprint,
        'pytest': {'passed': tests, 'failures': 0, 'errors': 0, 'skipped': 0,
                                        'report_sha256': digest(test_report),
                                        'seconds': round(sum(float(s.get('time', '0')) for s in suites), 3)},
        'frozen_runs': frozen,
        'independent_acceptance': {'passed': sum(len(a['cases']) for a in acceptances),
                                  'regression_passed': len(regression['cases']),
                                  'previous_reported_documents_passed': len(previous['cases']),
                                  'reported_documents_passed': len(actual['cases']),
                                  'extractors': sorted(extractors), 'renderer': 'Poppler',
                                  'dpi': 144, 'max_pixels_outside_tolerance': 0,
                                  'reports_sha256': [digest(regression_path), digest(previous_path), digest(actual_path)],
                                  'private_documents_included': False},
        'source_manifest': '_internal/source/MANIFEST.json',
        'scope': 'Comprobado en este Windows, con entorno del ejecutable sin Python/Qt de desarrollo en PATH. No probado en otro equipo físico.',
    }
    for path in (BUNDLE / 'ENTREGA.json', RELEASE / 'ENTREGA.json'):
        write(path, evidence)
    # Only documentation/source packaging changes after frozen verification.
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
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


def finish(report_path):
    evidence = read(RELEASE / 'ENTREGA.json')
    assert evidence['exe_sha256'] == digest(BUNDLE / 'PDFModder.exe')
    assert evidence['application'] == 'PDF Modder ' + __version__
    assert evidence['app_source_sha256'] == source_fingerprint()
    inventory = read(BUNDLE / '_internal/source/MANIFEST.json')
    expected_inventory = [{'path': relative.as_posix(), 'sha256': digest(path)} for path, relative in source_files()]
    assert inventory == expected_inventory, 'Las fuentes cambiaron después de preparar la entrega.'
    for row in inventory:
        assert digest(BUNDLE / '_internal/source/PDFModder' / row['path']) == row['sha256'], row['path']
    installer = RELEASE / (LABEL + '-Instalar.exe')
    installed = read(report_path)
    assert installed['ok'] and installed['installer_sha256'] == digest(installer)
    assert installed['application_version'] == __version__
    assert len(installed['tests']) == 4 and all(t['passed'] for t in installed['tests'])
    # Publish only fixed summary fields. The private reports may contain paths,
    # source text, or identifiers which are deliberately excluded here.
    summary_fields = {'name', 'passed', 'files', 'steps', 'removed', 'preserved', 'remaining'}
    summary = {'ok': True, 'application_version': __version__, 'installer_sha256': digest(installer),
               'started_utc': installed['started_utc'],
               'tests': [{k: v for k, v in t.items() if k in summary_fields} for t in installed['tests']]}
    write(RELEASE / 'INSTALACION-VERIFICADA.json', summary)
    metadata = read(RELEASE / 'INSTALADOR.json')
    assert metadata['installer_sha256'] == digest(installer)
    assert metadata['application'] == 'PDF Modder ' + __version__
    staging = ROOT / 'build' / ('installer-v' + __version__)
    assert metadata['payload_sha256'] == digest(staging / 'PDFModderPayload.zip')
    payload = {}
    for row in (staging / 'PDFModderPayload.tsv').read_text(encoding='utf-8').splitlines():
        sha256, size, name = row.split('\t')
        assert name.startswith('PDFModder/') and name not in payload, name
        payload[name] = (sha256, int(size))
    bundle_files = {p for p in BUNDLE.rglob('*') if p.is_file()}
    assert {'PDFModder/' + p.relative_to(BUNDLE).as_posix() for p in bundle_files} == set(payload)
    for path in bundle_files:
        sha256, size = payload['PDFModder/' + path.relative_to(BUNDLE).as_posix()]
        assert path.stat().st_size == size and digest(path) == sha256, path
    editor_steps = next(t['steps'] for t in installed['tests'] if t['name']=='editor_instalado_editar_guardar_reabrir')
    metadata.update(tested=True, verification_report='INSTALACION-VERIFICADA.json',
                    note=f'Instalación aislada, {editor_steps} pasos del editor instalado y desinstalación conservando archivos personales/modificados.')
    write(RELEASE / 'INSTALADOR.json', metadata)
    for suffix, files in (
        ('-Windows-x64.zip', [(p, Path('PDFModder') / p.relative_to(BUNDLE)) for p in BUNDLE.rglob('*') if p.is_file()]),
        ('-codigo.zip', [(p, Path('PDFModder') / r) for p, r in source_files()]),
    ):
        target = RELEASE / (LABEL + suffix)
        if target.exists():
            raise FileExistsError(target)
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path, relative in sorted(files):
                archive.write(path, relative.as_posix())
        target.with_suffix(target.suffix + '.sha256').write_text(f'{digest(target)}  {target.name}\n', encoding='ascii')
    entries = [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': digest(p)}
               for p in sorted(RELEASE.iterdir()) if p.suffix in ('.exe', '.zip')]
    write(RELEASE / 'ARCHIVOS.json', entries)
    print(json.dumps(entries, ensure_ascii=False, indent=2))


def prepare_unverified():
    """Stage current documentation/source without crediting any test results."""
    RELEASE.mkdir(parents=True, exist_ok=True)
    evidence = {
        'application': 'PDF Modder ' + __version__,
        'platform': 'Windows 11 x64',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'delivery_status': 'compiled_unverified',
        'tested': False,
        'frozen_verified': False,
        'exe_sha256': digest(BUNDLE / 'PDFModder.exe'),
        'app_source_sha256': source_fingerprint(),
        'source_manifest': '_internal/source/MANIFEST.json',
        'previous_results_used': False,
        'private_documents_included': False,
        'scope': 'Compilación y empaquetado sin ejecutar comprobaciones adicionales. '
                 'No se acredita la verificación final del ejecutable ni del instalador.',
        'pending': [
            'Batería completa de la versión final.',
            'Aceptación completa con los PDF aportados y las dos rutas de edición.',
            'Recorridos del ejecutable final y prueba de instalación/desinstalación.',
        ],
    }
    for path in (BUNDLE / 'ENTREGA.json', RELEASE / 'ENTREGA.json'):
        write(path, evidence)
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
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


def finish_unverified():
    """Create archives and hashes, without running or importing verification."""
    metadata_path = RELEASE / 'INSTALADOR.json'
    metadata = read(metadata_path)
    metadata.update(tested=False, delivery_status='compiled_unverified',
                    note='Compilado y empaquetado sin comprobaciones adicionales. '
                         'La verificación del ejecutable final y de instalación/desinstalación queda pendiente.')
    metadata.pop('verification_report', None)
    write(metadata_path, metadata)
    for suffix, files in (
        ('-Windows-x64.zip', [(p, Path('PDFModder') / p.relative_to(BUNDLE))
                             for p in BUNDLE.rglob('*') if p.is_file()]),
        ('-codigo.zip', [(p, Path('PDFModder') / relative) for p, relative in source_files()]),
    ):
        target = RELEASE / (LABEL + suffix)
        if target.exists():
            raise FileExistsError(target)
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path, relative in sorted(files):
                archive.write(path, relative.as_posix())
        target.with_suffix(target.suffix + '.sha256').write_text(
            f'{digest(target)}  {target.name}\n', encoding='ascii')
    entries = [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': digest(p)}
               for p in sorted(RELEASE.iterdir()) if p.suffix in ('.exe', '.zip')]
    write(RELEASE / 'ARCHIVOS.json', entries)
    print(json.dumps({'delivery_status': 'compiled_unverified', 'tested': False,
                      'files': entries}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--finish', type=Path, metavar='INFORME_INSTALACION')
    group.add_argument('--prepare-unverified', action='store_true')
    group.add_argument('--finish-unverified', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.finish:
        finish(args.finish)
    elif args.prepare_unverified:
        prepare_unverified()
    else:
        finish_unverified()
