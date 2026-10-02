"""Compila el desinstalador Windows en la carpeta de distribución actual."""
from pathlib import Path
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__


def build(destination: Path | None = None) -> Path:
    target = destination or ROOT / 'dist/PDFModder/Desinstalar.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    template = (ROOT / 'installer/PdfModderUninstaller.cs').read_text(encoding='utf-8-sig')
    template_version = re.search(r'const string Version = "([0-9.]+)"', template).group(1)
    generated = ROOT / 'build' / ('uninstaller-v' + __version__) / 'PdfModderUninstaller.cs'
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(template.replace(template_version, __version__), encoding='utf-8-sig')
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([
        str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        '/out:' + str(target),
        '/win32manifest:' + str(ROOT / 'installer/asInvoker.manifest'),
        '/win32icon:' + str(ROOT / 'assets/icons/pdfmodder.ico'),
        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
        '/reference:System.Web.Extensions.dll',
        str(generated),
    ], check=True, cwd=ROOT)
    return target


if __name__ == '__main__':
    print(build())
