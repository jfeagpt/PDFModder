"""Empaquetado 1.5.0: exige evidencia actual, sin reutilizar resultados antiguos.

--prepare INFORME_ACEPTACION se usa tras las pruebas de fuente y ejecutable.
--finish INFORME_INSTALACION produce ZIP y sumas tras instalar/desinstalar.
Los PDF y los informes privados no se incluyen en la distribución.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__
from scripts.collect_licenses import source_files
from scripts.package_v09 import (
    BUNDLE, RELEASE, application_sources, digest, finish, read,
    source_fingerprint, write,
)


def prepare(acceptance_path):
    assert __version__ == '1.5.0'
    fingerprint = source_fingerprint()
    exe_hash = digest(BUNDLE / 'PDFModder.exe')
    for path in application_sources():
        frozen_source = BUNDLE / '_internal/source/PDFModder' / path.relative_to(ROOT)
        assert digest(path) == digest(frozen_source), path
    test_binding = read(ROOT / 'output/v150-source-tests.json')
    test_report = ROOT / 'output/pytest-v150-results.xml'
    assert test_binding['application_version'] == __version__
    assert test_binding['exit_code'] == 0 and test_binding['source_unchanged']
    assert test_binding['app_source_sha256'] == fingerprint
    assert test_binding['report_sha256'] == digest(test_report)
    suites = [s for s in ET.parse(test_report).getroot().iter('testsuite') if not s.findall('testsuite')]
    assert suites and all(int(s.get(k, '0')) == 0 for s in suites for k in ('failures', 'errors'))
    tests = sum(int(s.get('tests', '0')) for s in suites)
    skipped = sum(int(s.get('skipped', '0')) for s in suites)
    verification = read(ROOT / 'output/packaged-verification.json')
    assert verification['ok'] and verification['executable_unchanged']
    assert verification['expected_version'] == __version__ and verification['exe_sha256'] == exe_hash
    required = {'extended', 'tagged', 'clipped', 'v08', 'v09', 'compat', 'v150'}
    assert {r['name'] for r in verification['runs']} == required
    frozen = {}
    for run in verification['runs']:
        report_path = ROOT / ('output/packaged-' + run['name'] + '-smoke.json')
        report = read(report_path)
        assert run['ok'] and run['source_unchanged'] and run['exe_sha256'] == exe_hash
        assert run['report_sha256'] == digest(report_path)
        assert report['ok'] and report['frozen'] and report['stage'] == 'complete'
        assert report['app_version'] == __version__ and report['exe_sha256'] == exe_hash
        assert report['steps'] and all(step['ok'] for step in report['steps'])
        frozen[run['name']] = {'ok': True, 'steps': len(report['steps']),
                               'seconds': report['elapsed_seconds'],
                               'report_sha256': digest(report_path)}
    acceptance = read(acceptance_path)
    assert acceptance['application_version'] == __version__
    assert acceptance['app_source_sha256'] == fingerprint and acceptance['app_sources_unchanged']
    assert acceptance['originals_unchanged'] and not acceptance['counts'].get('failed', 0)
    assert len(acceptance['documents']) == 4
    assert sum(acceptance['counts'].values()) == 64
    rendered = [operation['poppler_page_1'] for document in acceptance['documents']
                for operation in document['operations'] if 'poppler_page_1' in operation]
    assert rendered and all(row['dpi'] == 144 and row['pixels_above_8_outside_mask'] == 0
                            for row in rendered)
    evidence = {
        'application': 'PDF Modder ' + __version__, 'platform': 'Windows 11 x64',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'delivery_status': 'executable_verified', 'tested': True, 'frozen_verified': True,
        'exe_sha256': exe_hash, 'app_source_sha256': fingerprint,
        'pytest': {'passed': tests - skipped, 'skipped': skipped, 'failures': 0, 'errors': 0,
                   'seconds': round(sum(float(s.get('time', '0')) for s in suites), 3),
                   'report_sha256': digest(test_report)},
        'frozen_runs': frozen,
        'document_acceptance': {'documents': 4, 'cases': 64, 'counts': acceptance['counts'],
                                'originals_unchanged': True,
                                'report_sha256': digest(acceptance_path),
                                'poppler_edited_page_comparisons': len(rendered),
                                'poppler_dpi': 144, 'poppler_pixels_above_8_outside_masks': 0,
                                'private_documents_included': False,
                                'note': 'Los casos blocked son límites explícitos, no operaciones realizadas. '
                                        'El protocolo y los límites están en docs/RESULTADOS_V150.md.'},
        'source_manifest': '_internal/source/MANIFEST.json',
        'scope': 'Fuente e interfaz probadas en este Windows; ejecutable con PATH sólo Windows. '
                 'La prueba de instalación y desinstalación se registra por separado. '
                 'No probado en otro equipo físico ni equivalencia completa con Acrobat.',
    }
    measured = [
        '# Resultados medidos de PDF Modder 1.5.0', '',
        'Generado a partir de los informes de esta compilación. Las huellas completas '
        'se conservan en ENTREGA.json; los PDF privados no se distribuyen.', '',
        f"- Pruebas de fuente: **{tests-skipped} aprobadas**, {skipped} omitidas; cero fallos y errores.",
        f"- Ejecutable Windows: **{len(frozen)} recorridos aprobados** con PATH reducido a Windows.",
        f"- Cuatro PDF privados: **{acceptance['counts'].get('passed', 0)} operaciones completadas** y "
        f"**{acceptance['counts'].get('blocked', 0)} bloqueadas**; cero fallos inesperados.",
        '- Los cuatro originales conservan sus huellas SHA-256.',
        f'- Poppler: {len(rendered)} comparaciones a 144 ppp; cero píxeles fuera de tolerancia '
        'fuera de las regiones de texto modificadas.',
        f"- Máxima zona excluida en esas comparaciones: {max(row['excluded_percent'] for row in rendered):.6f}% de la página.",
        '', '| Recorrido del ejecutable | Pasos | Segundos |', '| --- | ---: | ---: |',
        *[f"| {name} | {row['steps']} | {row['seconds']} |" for name, row in frozen.items()],
        '', 'La instalación y desinstalación se acreditan por separado en '
        '`INSTALACION-VERIFICADA.json`. Estas pruebas no equivalen a otro ordenador físico '
        'ni a compatibilidad universal. Consulte RESULTADOS_V150.md para el protocolo y límites.', '',
    ]
    (ROOT / 'docs/RESULTADOS_MEDIDOS_V150.md').write_text('\n'.join(measured), encoding='utf-8')
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
    print(evidence)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', type=Path)
    group.add_argument('--finish', type=Path)
    arguments = parser.parse_args()
    if arguments.prepare:
        prepare(arguments.prepare)
    else:
        finish(arguments.finish)
