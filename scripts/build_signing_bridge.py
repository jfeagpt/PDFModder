"""Compila el puente local de certificados Windows; no exporta claves privadas."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build(destination: Path | None = None) -> Path:
    """Build once to the source runtime path and copy that executable to bundle."""
    target = destination or ROOT / 'dist/PDFModder/PDFModderSigningBridge.exe'
    development = ROOT / 'tmp/native-v160/PDFModderSigningBridge.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    development.parent.mkdir(parents=True, exist_ok=True)
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('Falta el compilador .NET Framework de Windows para crear el puente de certificados.')
    subprocess.run([
        str(compiler), '/nologo', '/target:exe', '/platform:x64', '/optimize+',
        '/out:' + str(development),
        '/win32manifest:' + str(ROOT / 'installer/asInvoker.manifest'),
        '/reference:System.Web.Extensions.dll', '/reference:System.Security.dll',
        str(ROOT / 'installer/PdfModderSigningBridge.cs'),
    ], check=True, cwd=ROOT)
    if target.resolve() != development.resolve():
        shutil.copy2(development, target)
    return target


if __name__ == '__main__':
    if '--self-test' not in sys.argv:
        print(build())
    else:
        import base64
        import hashlib
        import json
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, utils

        executable = build()
        native = subprocess.run([str(executable), '--self-test'], capture_output=True,
                                encoding='utf-8', check=False, timeout=45,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        result = json.loads(native.stdout)
        if native.returncode or not result.get('ok') or not result.get('cleanup_completed'):
            raise RuntimeError(result.get('error', 'Falló la prueba sintética del puente de certificados.'))
        signature = result['result']
        certificate = x509.load_der_x509_certificate(base64.b64decode(signature['certificate_der_base64']))
        certificate.public_key().verify(base64.b64decode(signature['signature_base64']),
                                        base64.b64decode(result['digest_base64']),
                                        padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
        listing = subprocess.run([str(executable)], input=json.dumps({'command': 'list'}),
                                 capture_output=True, encoding='utf-8-sig', check=False,
                                 timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        certificates = json.loads(listing.stdout)
        if listing.returncode or not certificates.get('ok'):
            raise RuntimeError('No se pudo leer el listado de certificados de Windows.')
        report = {'ok': True, 'certificate': 'synthetic leaf only',
                  'signature_verified_independently': True,
                  'temporary_certificate_and_key_removed': True,
                  'list_read_only_ok': True, 'listed_count': len(certificates['certificates']),
                  'utf8_bom_request_ok': True,
                  'warnings_count': len(certificates.get('warnings', [])),
                  'private_keys_exported': False, 'personal_certificates_signed': False,
                  'exe_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                  'source_sha256': hashlib.sha256((ROOT / 'installer/PdfModderSigningBridge.cs').read_bytes()).hexdigest()}
        output = ROOT / 'output/signing-bridge-v160.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'ok': True, 'report': str(output)}))
