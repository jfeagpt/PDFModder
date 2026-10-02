"""Construye y verifica la entrega Windows; puede reanudarse tras un fallo.

Uso: python scripts/release_v150.py --pdfs FACTURA MAPA OCR ANEXO
Los PDF sólo se leen. Instalación/desinstalación usan output/portability y
requieren que no exista una instalación real de 1.5.0. --start permite retomar
una fase sin repetir las anteriores; el empaquetador sigue exigiendo sus huellas.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.package_v09 import read, source_fingerprint, write

PHASES = ('source', 'build', 'binary', 'installer', 'finish')
STATE = ROOT / 'output/release-v150-state.json'
PYTHON = str(ROOT / '.venv/Scripts/python.exe')


def run(name, arguments):
    print(name + '...', flush=True)
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    log = ROOT / ('output/release-v150-' + name + '.log')
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run(arguments, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, env=environment)
    output = log.read_text(encoding='utf-8', errors='replace')
    if result.returncode:
        print('\n'.join(output.splitlines()[-60:]), flush=True)
        raise RuntimeError(f'{name}: código {result.returncode}; consulte {log}')
    print(name + ': terminado. ' + str(log), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', choices=PHASES, default='source')
    parser.add_argument('--pdfs', nargs=4, type=Path)
    args = parser.parse_args()
    (ROOT / 'output').mkdir(exist_ok=True)
    state = read(STATE) if STATE.exists() else {}
    start = PHASES.index(args.start)
    if start == 0:
        if not args.pdfs or not all(path.is_file() for path in args.pdfs):
            parser.error('Indique los cuatro PDF de aceptación existentes con --pdfs.')
        run('source-workflow', [PYTHON, 'run_pdfmodder.py', '--smoke-v150',
                                'output/source-smoke-v150.json'])
        run('source-tests', [PYTHON, 'scripts/verify_source_v150.py'])
        output = run('acceptance', [PYTHON, 'scripts/acceptance_v150.py', '--poppler',
                                   *[str(path.resolve()) for path in args.pdfs]])
        summary = json.loads(output.strip().splitlines()[-1])
        state = {'app_source_sha256': source_fingerprint(),
                 'acceptance': str((ROOT / summary['report']).resolve())}
        write(STATE, state)
    if state.get('app_source_sha256') != source_fingerprint():
        raise RuntimeError('Falta una aceptación del código actual. Reinicie desde source.')
    if start <= 1:
        run('build', ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                      '-File', 'scripts/build.ps1', '-SkipTests'])
    if start <= 2:
        run('binary', ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                       '-File', 'scripts/verify_executable.ps1'])
    if start <= 3:
        run('prepare', [PYTHON, 'scripts/package_v150.py', '--prepare', state['acceptance']])
        run('installer-build', [PYTHON, 'scripts/build_current_installer.py'])
        output = run('installer-tests', [PYTHON, 'scripts/verify_install_uninstall_v09.py'])
        state['installation'] = json.loads(output)['report']
        write(STATE, state)
    if start <= 4:
        run('finish', [PYTHON, 'scripts/package_v150.py', '--finish', state['installation']])
    print('Entrega lista: ' + str(ROOT / 'releases/v1.5.0'), flush=True)


if __name__ == '__main__':
    main()
