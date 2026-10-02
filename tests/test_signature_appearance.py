"""Visible signature tests use ephemeral synthetic certificates only."""
from datetime import datetime, timedelta, timezone
from io import BytesIO

import numpy as np
import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.model import EditError
from pdfmodder.signing import preview_signature, sign_pdf, verify_signed_pdf
from pdfmodder.signature_appearance import appearance_pdf, signature_geometry


@pytest.fixture(scope='module')
def visible_certificate(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'María Núñez — PRUEBA'),
                     x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Organización de pruebas'),
                     x509.NameAttribute(NameOID.SERIAL_NUMBER, 'TEST-2026-001')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
    path = tmp_path_factory.mktemp('visible-certificate') / 'synthetic.p12'
    path.write_bytes(pkcs12.serialize_key_and_certificates(b'test', key, cert, None,
                                                          serialization.BestAvailableEncryption(b'test-only')))
    return path, cert.public_bytes(serialization.Encoding.DER)


def source_document(rotation=0):
    with fitz.open() as doc:
        page = doc.new_page(width=650, height=850)
        page.draw_rect((40, 45, 600, 795), fill=(.93, .97, .99), color=(.2, .3, .4))
        page.insert_text((65, 95), 'Texto original junto a la firma', fontsize=12)
        page.set_cropbox(fitz.Rect(30, 40, 610, 810))
        page.set_rotation(rotation)
        doc.new_page().insert_text((60, 75), 'Pagina sin cambios')
        return doc.tobytes()


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_visible_crypto_pixels_crop_rotation_and_public_preview(visible_certificate, rotation, tmp_path):
    path, der = visible_certificate
    data = source_document(rotation)
    rect = [95, 180, 455, 305]
    spec = {'page': 0, 'rect': rect}
    preview = preview_signature(data, path, 'test-only', visible_signature=spec)
    signed, report = sign_pdf(data, path, 'test-only', visible_signature=spec)
    assert report['visible_signature']['certificate_name'] == 'María Núñez — PRUEBA'
    assert verify_signed_pdf(signed)['cryptographic_integrity']
    assert report['trust_verified'] is False
    reader = PdfReader(BytesIO(signed), strict=True)
    widget = reader.pages[0]['/Annots'][-1].get_object()
    assert widget['/FT'] == '/Sig' and widget['/AP']['/N'].get_object()['/Resources']['/XObject']
    assert widget['/F'] & 4  # printable
    assert tuple(map(float, widget['/Rect'])) == pytest.approx(signature_geometry(data, spec)['box'])
    # The visible time is the same as the signed PDF dictionary time, not preview time.
    from pyhanko.pdf_utils.reader import PdfFileReader
    embedded = PdfFileReader(BytesIO(signed)).embedded_signatures[0]
    pdf_date = widget['/V']['/M']
    date = datetime.strptime(report['visible_signature']['signing_time'], '%d/%m/%Y %H:%M:%S %z')
    assert date.strftime('%Y%m%d%H%M%S') in str(pdf_date)
    assert embedded.self_reported_timestamp.replace(microsecond=0) == date
    with fitz.open(stream=data) as before, fitz.open(stream=signed) as after:
        # Widget text is also extractable; original words retain exact positions.
        from collections import Counter
        original_words = Counter(tuple(word[:5]) for word in before[0].get_text('words'))
        signed_words = Counter(tuple(word[:5]) for word in after[0].get_text('words'))
        assert all(signed_words[word] == count for word, count in original_words.items())
        assert 'María' in after[0].get_text() and 'Núñez' in after[0].get_text()
        assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
        matrix = fitz.Matrix(2, 2)
        old, new = before[0].get_pixmap(matrix=matrix), after[0].get_pixmap(matrix=matrix)
        a = np.frombuffer(old.samples, dtype=np.uint8).reshape(old.height, old.width, 3)
        b = np.frombuffer(new.samples, dtype=np.uint8).reshape(new.height, new.width, 3)
        changed = np.any(a != b, axis=2)
        mask = np.zeros(changed.shape, dtype=bool)
        mask[rect[1]*2:rect[3]*2, rect[0]*2:rect[2]*2] = True
        assert changed.sum() > 500
        assert not np.any(changed & ~mask), 'Unselected page pixels changed'
        original_preview = before[0].get_pixmap(matrix=fitz.Matrix(preview['zoom'], preview['zoom']))
        preview_page = fitz.Pixmap(preview['png'])
        op = np.frombuffer(original_preview.samples, dtype=np.uint8).reshape(original_preview.height, original_preview.width, 3)
        pp = np.frombuffer(preview_page.samples, dtype=np.uint8).reshape(preview_page.height, preview_page.width, 3)
        preview_changes = np.any(op != pp, axis=2)
        zoom = preview['zoom']
        import math
        preview_changes[math.floor(rect[1]*zoom):math.ceil(rect[3]*zoom), math.floor(rect[0]*zoom):math.ceil(rect[2]*zoom)] = False
        assert not preview_changes.any(), 'Preview changed pixels outside the exact stamp rectangle'
        # Text rendered upright in the preview and final output; date may differ.
        crop = after[0].get_pixmap(matrix=matrix, clip=fitz.Rect(rect))
        preview_crop = fitz.Pixmap(preview['appearance_png'])
        assert (crop.width, crop.height) == (preview_crop.width, preview_crop.height)
        c = np.frombuffer(crop.samples, dtype=np.uint8).reshape(crop.height, crop.width, 3)
        p = np.frombuffer(preview_crop.samples, dtype=np.uint8).reshape(crop.height, crop.width, 3)
        assert np.array_equal(c[:, :int(crop.width * .4)], p[:, :int(crop.width * .4)])
        assert after[0].rotation == rotation and before[0].cropbox == after[0].cropbox
    art, details = appearance_pdf(der, 360, 125, date)
    with fitz.open(stream=art) as doc:
        text = doc[0].get_text()
        assert 'María' in text and 'Núñez' in text and 'Organización' in text
        assert 'Fecha:' in text
        assert all(doc.extract_font(f[0])[3] for f in doc[0].get_fonts())
    (tmp_path / f'visible-{rotation}.pdf').write_bytes(signed)
    (tmp_path / f'visible-{rotation}.png').write_bytes(preview['appearance_png'])


def test_preview_windows_uses_only_public_certificate(visible_certificate, monkeypatch):
    import base64
    import pdfmodder.signing as signing
    _, der = visible_certificate
    requests = []
    def bridge(request):
        requests.append(request)
        assert request == {'command': 'list'}
        return {'certificates': [{'thumbprint': 'AB'*20, 'store': 'CurrentUser',
                                 'certificate_der_base64': base64.b64encode(der).decode('ascii')}]}
    monkeypatch.setattr(signing, '_bridge_call', bridge)
    preview = preview_signature(source_document(), certificate_thumbprint='AB'*20,
                                visible_signature={'page': 1, 'rect': [40, 180, 400, 305]})
    assert preview['preview_only'] is True and preview['png'].startswith(b'\x89PNG')
    assert requests == [{'command': 'list'}]


def test_invalid_or_small_rectangle_and_long_certificate_not_silently_truncated(visible_certificate):
    path, der = visible_certificate
    data = source_document()
    for spec in ({'page': True, 'rect': [40, 40, 400, 170]}, {'page': 0, 'rect': [0, 0, float('nan'), 100]},
                 {'page': -1, 'rect': [40, 40, 400, 170]}, {'page': 8, 'rect': [40, 40, 400, 170]},
                 {'page': 0, 'rect': [40, 40, 120, 70]}, {'page': 0, 'rect': [400, 100, 780, 250]}):
        with pytest.raises(EditError):
            sign_pdf(data, path, 'test-only', visible_signature=spec)
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
    from cryptography.x509.oid import NameOID
    key, cert, _ = load_key_and_certificates(path.read_bytes(), b'test-only')
    long_name = x509.Name([*cert.subject, *[
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f'Unidad {index}: ' + 'dato ' * 9)
        for index in range(16)]])
    long_cert = (x509.CertificateBuilder().subject_name(long_name).issuer_name(cert.issuer)
                 .public_key(key.public_key()).serial_number(x509.random_serial_number())
                 .not_valid_before(cert.not_valid_before_utc).not_valid_after(cert.not_valid_after_utc)
                 .sign(key, hashes.SHA256()))
    with pytest.raises(EditError, match='superan|no caben'):
        appearance_pdf(long_cert.public_bytes(serialization.Encoding.DER), 210, 70,
                       datetime.now().astimezone())


def test_tagged_pdf_visible_is_explicitly_blocked_before_key_access(monkeypatch):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject
    import pdfmodder.signing as signing
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source_document())))
    writer._root_object[NameObject('/StructTreeRoot')] = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/StructTreeRoot')}))
    out = BytesIO()
    writer.write(out)
    def no_key(*args):
        pytest.fail('Invalid appearance placement must be rejected before selecting keys')
    monkeypatch.setattr(signing, '_windows_signer', no_key)
    with pytest.raises(EditError, match='etiquetado'):
        sign_pdf(out.getvalue(), certificate_thumbprint='AB'*20, visible_signature={'page': 0, 'rect': [40, 180, 400, 305]})
