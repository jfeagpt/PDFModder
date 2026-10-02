"""Synthetic keys only: signed output, tampering, errors and protected source."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
import pytest

from pdfmodder.model import EditError
from pdfmodder.signing import sign_pdf, verify_signed_pdf, atomic_save_signed


@pytest.fixture(scope='module')
def certificate(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PDF Modder TEST ONLY')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, None, None), critical=True)
            .sign(key, hashes.SHA256()))
    path = tmp_path_factory.mktemp('signing') / 'synthetic-only.p12'
    path.write_bytes(pkcs12.serialize_key_and_certificates(
        b'PDF Modder test', key, cert, None, serialization.BestAvailableEncryption(b'test-only')))
    return path


@pytest.fixture
def document():
    doc = fitz.open()
    doc.new_page().insert_text((50, 70), 'Firma de prueba 2026')
    doc.new_page().insert_text((80, 100), 'Segunda pagina intacta')
    return doc.tobytes()


def test_signature_is_cryptographic_preserves_text_and_pixels_and_writes_exact_copy(certificate, document, tmp_path):
    original = tmp_path / 'original.pdf'
    original.write_bytes(document)
    before_hash = sha256(document).hexdigest()
    signed, report = sign_pdf(document, certificate, 'test-only', reason='Prueba', location='Local')
    assert report['cryptographic_integrity'] and report['covers_entire_file']
    assert report['trust_verified'] is False and report['trusted_timestamp'] is False
    assert 'test-only' not in str(report)
    assert 'TEST ONLY' in report['certificate_subject']
    with fitz.open(stream=document) as before, fitz.open(stream=signed) as after:
        assert len(before) == len(after) == 2
        for p, q in zip(before, after):
            assert p.get_text() == q.get_text()
            assert p.rect == q.rect
            assert p.get_pixmap().samples == q.get_pixmap().samples
    target = tmp_path / 'signed.pdf'
    atomic_save_signed(signed, target, protected_paths=[original], certificate_sha256=report['certificate_sha256'])
    assert target.read_bytes() == signed
    assert verify_signed_pdf(target.read_bytes())['cryptographic_integrity']
    assert sha256(original.read_bytes()).hexdigest() == before_hash


def test_wrong_password_is_safe_and_does_not_leak_secret(certificate, document):
    with pytest.raises(EditError, match='contraseña') as error:
        sign_pdf(document, certificate, 'private-secret-never-logged')
    assert 'private-secret-never-logged' not in str(error.value)


def test_tampered_signature_and_appended_revision_are_rejected(certificate, document):
    signed, _ = sign_pdf(document, certificate, 'test-only')
    # The PDF header is covered by the signature and is harmless to parsing.
    changed = signed.replace(b'%PDF-1.7', b'%PDF-1.6', 1)
    if changed == signed:
        changed = signed.replace(b'%PDF-1.3', b'%PDF-1.4', 1)
    assert changed != signed
    with pytest.raises(EditError):
        verify_signed_pdf(changed)
    with pytest.raises(EditError, match='totalidad'):
        verify_signed_pdf(signed + b'\n% untrusted append\n')


def test_original_and_failed_export_preserve_bytes(certificate, document, tmp_path, monkeypatch):
    import pdfmodder.signing as signing
    signed, _ = sign_pdf(document, certificate, 'test-only')
    original = tmp_path / 'original.pdf'
    original.write_bytes(document)
    with pytest.raises(EditError, match='original'):
        atomic_save_signed(signed, original, protected_paths=[original])
    target = tmp_path / 'existing.pdf'
    target.write_bytes(b'old result')
    def fail(*args):
        raise PermissionError('Synthetic lock')
    monkeypatch.setattr(signing.os, 'replace', fail)
    with pytest.raises(PermissionError):
        atomic_save_signed(signed, target)
    assert target.read_bytes() == b'old result'
    assert original.read_bytes() == document
    assert not list(tmp_path.glob('.pdfmodder-firma-*'))


def test_existing_signature_and_encryption_blocked(certificate, document):
    signed, _ = sign_pdf(document, certificate, 'test-only')
    with pytest.raises(EditError, match='firmas'):
        sign_pdf(signed, certificate, 'test-only')
    writer = PdfWriter(clone_from=PdfReader(BytesIO(document)))
    writer.encrypt('secret')
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(EditError, match='cifrados'):
        sign_pdf(stream.getvalue(), certificate, 'test-only')


def test_windows_store_signs_prehashed_digest_without_exporting_key(certificate, document, monkeypatch):
    import base64
    import pdfmodder.signing as signing
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, utils
    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
    key, cert, _ = load_key_and_certificates(certificate.read_bytes(), b'test-only')
    der = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode('ascii')
    public = {'thumbprint': 'AA' * 20, 'store': 'CurrentUser', 'subject': 'Synthetic test',
              'issuer': 'Synthetic test', 'not_after': cert.not_valid_after_utc.isoformat(),
              'certificate_der_base64': der}
    requests = []
    def bridge(request):
        requests.append(request)
        if request['command'] == 'list':
            return {'ok': True, 'certificates': [public]}
        assert request['command'] == 'sign'
        assert set(request) == {'command', 'thumbprint', 'store', 'algorithm', 'digest_base64'}
        assert request['algorithm'] == 'rsa_pkcs1_sha256'
        raw = key.sign(base64.b64decode(request['digest_base64']), padding.PKCS1v15(),
                       utils.Prehashed(hashes.SHA256()))
        return {'ok': True, 'certificate_der_base64': der,
                'signature_base64': base64.b64encode(raw).decode('ascii')}
    monkeypatch.setattr(signing, '_bridge_call', bridge)
    signed, report = sign_pdf(document, certificate_thumbprint=public['thumbprint'])
    assert verify_signed_pdf(signed)['cryptographic_integrity']
    assert report['certificate_source'] == 'windows'
    assert [r['command'] for r in requests] == ['list', 'sign']
