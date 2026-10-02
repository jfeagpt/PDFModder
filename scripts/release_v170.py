"""Pruebas dirigidas de la versión actual; --start reanuda el empaquetado."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.package_v09 import digest, read, source_fingerprint, write
from pdfmodder import __version__

PYTHON = str(ROOT / '.venv/Scripts/python.exe')
SUITE = 'v' + __version__.replace('.', '')
STATE = ROOT / f'output/release-{SUITE}-state.json'
PHASES = ('source', 'build', 'binary', 'installer', 'finish')


def run(name, args, *, clean=False):
    print(name + '...', flush=True)
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    if clean:
        for key in list(environment):
            if key.startswith(('PYTHON', 'PYSIDE', 'QT_', 'QML', 'VIRTUAL_ENV', 'CONDA', '_PYI')):
                environment.pop(key, None)
        win = Path(environment.get('SystemRoot', 'C:/Windows'))
        environment['PATH'] = os.pathsep.join(str(win / p) for p in ('System32', '', 'System32/Wbem'))
    log = ROOT / f'output/release-{SUITE}-{name}.log'
    with log.open('w', encoding='utf-8') as output:
        result = subprocess.run(args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, env=environment)
    value = log.read_text(encoding='utf-8', errors='replace')
    if result.returncode:
        print('\n'.join(value.splitlines()[-45:]), flush=True)
        raise RuntimeError(f'{name}: código {result.returncode}; {log}')
    print(name + ': terminado.', flush=True)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', choices=PHASES, default='source')
    parser.add_argument('--tests', nargs='+')
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    start = PHASES.index(args.start)
    (ROOT / 'output').mkdir(exist_ok=True)
    (ROOT / 'tmp').mkdir(exist_ok=True)
    state = read(STATE) if STATE.exists() else {}
    if start == 0:
        if not args.tests:
            parser.error('Indique los módulos de pruebas dirigidas con --tests.')
        fingerprint = source_fingerprint()
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        run('source-tests', [PYTHON, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                             '--basetemp', f'tmp/pytest-{SUITE}-' + stamp,
                             '--junitxml', f'output/pytest-{SUITE}-results.xml', *args.tests])
        assert fingerprint == source_fingerprint(), 'El código cambió durante la prueba.'
        write(ROOT / f'output/{SUITE}-source-tests.json', {
            'application_version': __version__,
            'exit_code': 0, 'source_unchanged': True, 'app_source_sha256': fingerprint,
            'report_sha256': digest(ROOT / f'output/pytest-{SUITE}-results.xml'), 'tests': args.tests})
        state = {'application_version': __version__, 'app_source_sha256': fingerprint}
        write(STATE, state)
        if args.source_only:
            return
    assert state.get('app_source_sha256') == source_fingerprint(), 'Ejecute las pruebas dirigidas sobre el código actual.'
    if start <= 1:
        run('build', ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts/build.ps1', '-SkipTests'])
    if start <= 2:
        run('windows-certificate', [PYTHON, 'scripts/build_signing_bridge.py', '--self-test'])
        run('binary', [str(ROOT / 'dist/PDFModder/PDFModder.exe'), '--smoke-' + SUITE,
                       str(ROOT / f'output/packaged-{SUITE}-smoke.json')], clean=True)
    if start <= 3:
        run('prepare', [PYTHON, 'scripts/package_v170.py', '--prepare'])
        run('installer-build', [PYTHON, 'scripts/build_current_installer.py'])
        output = run('installer-tests', [PYTHON, 'scripts/verify_install_uninstall_v09.py', '--suite', SUITE])
        state['installation'] = json.loads(output)['report']
        if SUITE == 'v180':
            output = run('upgrade-tests', [PYTHON, 'scripts/verify_upgrade_v180.py'])
            state['upgrade'] = json.loads(output)['report']
        write(STATE, state)
    if start <= 4:
        run('finish', [PYTHON, 'scripts/package_v170.py', '--finish', state['installation']])
        run('update-manifest', [PYTHON, 'scripts/publish_github_releases.py', '--prepare-only'])
    print('Entrega lista: ' + str(ROOT / ('releases/v' + __version__)), flush=True)


if __name__ == '__main__':
    main()
