"""Ejecuta la batería actual y liga el resultado al código probado."""
from datetime import datetime, timezone
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__
from scripts.package_v09 import digest, source_fingerprint, write


def main():
    before = source_fingerprint()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    report = ROOT / 'output/pytest-v150-results.xml'
    result = subprocess.run([
        sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
        '--basetemp', str(ROOT / 'tmp' / ('pytest-v150-final-' + stamp)),
        '--junitxml', str(report),
    ], cwd=ROOT)
    after = source_fingerprint()
    evidence = {
        'application_version': __version__, 'started_utc': stamp,
        'exit_code': result.returncode, 'app_source_sha256': before,
        'source_unchanged': before == after,
        'report_sha256': digest(report) if report.exists() else None,
    }
    write(ROOT / 'output/v150-source-tests.json', evidence)
    return result.returncode or (0 if before == after else 2)


if __name__ == '__main__':
    raise SystemExit(main())
