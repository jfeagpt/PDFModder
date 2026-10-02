"""Synthetic PDFs and recipient keys: metadata and real decrypt round trips."""
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject
import pytest

from pdfmodder.document_ops_v170 import (
    document_properties, update_document_metadata, export_secure_pdf,
    _preserving_writer,
)
from pdfmodder.model import EditError


@pytest.fixture
def document():
    with fitz.open() as document:
        first = document.new_page()
        first.insert_text((50, 70), 'Synthetic content for secure export')
        first.draw_rect(fitz.Rect(50, 100, 200, 160), color=(0, .2, .8))
        widget = fitz.Widget()
        widget.field_name = 'Untouched field'
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = 'Synthetic field value'
        widget.rect = fitz.Rect(50, 180, 200, 210)
        first.add_widget(widget)
        document.new_page().insert_text((50, 70), 'Second synthetic page')
        document.set_metadata({'title': 'Original title', 'author': 'Original author',
                               'creationDate': 'D:20260101083000Z', 'producer': 'Original producer'})
        document.set_xml_metadata('''<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about=""
xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:custom="urn:pdfmodder:synthetic">
<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Original title</rdf:li>
<rdf:li xml:lang="fr">Titre conservé</rdf:li></rdf:Alt></dc:title>
<custom:Keep>Custom metadata must survive</custom:Keep></rdf:Description></rdf:RDF>
</x:xmpmeta><?xpacket end="w"?>''')
        kind, ref = document.xref_get_key(-1, 'Info')
        document.xref_set_key(int(ref.split()[0]), 'CustomEntry', fitz.get_pdf_str('Custom Info preserved'))
        return document.tobytes()


@pytest.fixture(scope='module')
def recipient(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from asn1crypto import keys, x509 as asn1_x509
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PDF Modder encryption TEST ONLY')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.KeyUsage(False, False, True, False, False, False, False, None, None), critical=True)
                   .sign(key, hashes.SHA256()))
    path = tmp_path_factory.mktemp('encryption-recipient') / 'recipient.cer'
    path.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
    return path, asn1_x509.Certificate.load(path.read_bytes()), keys.PrivateKeyInfo.load(key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def _assert_preserved(original, copied):
    with fitz.open(stream=original) as before, fitz.open(stream=copied) as after:
        assert before.page_count == after.page_count == 2
        for left, right in zip(before, after):
            assert left.get_text() == right.get_text()
            assert left.get_pixmap().samples == right.get_pixmap().samples
            assert [(item.field_name, item.field_value) for item in left.widgets() or []] == [
                (item.field_name, item.field_value) for item in right.widgets() or []]


def test_metadata_keeps_pages_form_custom_info_and_xmp(document):
    info = document_properties(document, 'synthetic.pdf')
    assert info['editable'] and info['has_xmp'] and info['size_bytes'] == len(document)
    changed, report = update_document_metadata(document, {'title': 'Título actualizado', 'author': 'New author',
        'creationDate': '2026-02-03T10:11:12+01:00'})
    assert report['changed_fields'] == ['title', 'author', 'creationDate']
    _assert_preserved(document, changed)
    with fitz.open(stream=changed) as result:
        assert result.metadata['title'] == 'Título actualizado'
        assert result.metadata['creationDate'] == "D:20260203101112+01'00'"
        xmp = result.get_xml_metadata()
        assert 'Titre conservé' in xmp and 'Custom metadata must survive' in xmp
        assert 'Título actualizado' in xmp and '2026-02-03T10:11:12+01:00' in xmp
        ref = int(result.xref_get_key(-1, 'Info')[1].split()[0])
        assert result.xref_get_key(ref, 'CustomEntry')[1] == 'Custom Info preserved'
    with pytest.raises(EditError):
        update_document_metadata(document, {'creationDate': '2026-02-30'})
    with pytest.raises(EditError):
        update_document_metadata(document, {'size_bytes': '10'})


def test_form_metadata_session_save_preserves_fields_and_original(document,tmp_path):
    from pdfmodder.worker import Session
    source=tmp_path/'original-form.pdf'
    source.write_bytes(document)
    (tmp_path/'history').mkdir()
    session=Session(source,config_path=tmp_path/'fonts.json',history_dir=tmp_path/'history')
    try:
        assert session.issues and not session.state()['metadata_only_save']
        candidate,report=update_document_metadata(session.history.current,{'title':'Propiedades sin tocar campos'})
        session._put_preview(candidate,report);session.commit()
        assert session.state()['metadata_only_save']
        target=tmp_path/'metadata-copy.pdf'
        session.save(target)
        assert source.read_bytes()==document and not session.state()['dirty']
        _assert_preserved(document,target.read_bytes())
        assert document_properties(target.read_bytes())['metadata']['title']=='Propiedades sin tocar campos'
        session.navigate_history()
        assert not session.state()['metadata_only_save']
    finally:
        session.close()


def test_password_aes256_roundtrip_and_atomic_source_safety(document, tmp_path, monkeypatch):
    source = tmp_path / 'original.pdf'
    source.write_bytes(document)
    target = tmp_path / 'protected.pdf'
    result = export_secure_pdf(document, target, password='synthetic-only-strong-secret', protected_paths=[source])
    assert result['security']['algorithm'] == 'AES-256' and 'synthetic-only-strong-secret' not in str(result)
    encrypted = target.read_bytes()
    reader = PdfReader(BytesIO(encrypted))
    assert reader.is_encrypted and not reader.decrypt('wrong-password')
    assert reader.decrypt('synthetic-only-strong-secret')
    with fitz.open(stream=encrypted) as protected:
        assert protected.needs_pass and protected.authenticate('synthetic-only-strong-secret')
        clear = protected.tobytes(encryption=fitz.PDF_ENCRYPT_NONE)
    _assert_preserved(document, clear)
    with fitz.open(stream=document) as before, fitz.open(stream=clear) as after:
        assert before.get_xml_metadata() == after.get_xml_metadata()
    with pytest.raises(EditError, match='original'):
        export_secure_pdf(document, source, password='test', protected_paths=[source])
    target.write_bytes(b'existing destination')
    def fail_replace(*args):
        raise PermissionError('Synthetic lock')
    monkeypatch.setattr('pdfmodder.document_ops_v170.os.replace', fail_replace)
    with pytest.raises(EditError, match='guardar'):
        export_secure_pdf(document, target, password='test', protected_paths=[source])
    assert target.read_bytes() == b'existing destination' and source.read_bytes() == document
    assert not list(tmp_path.glob('.pdfmodder-seguro-*'))


def test_recipient_certificate_real_private_key_decrypt_preserves_xmp(document, recipient, tmp_path):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.crypt.pubkey import SimpleEnvelopeKeyDecrypter
    from pyhanko.pdf_utils.crypt import AuthStatus
    path, certificate, key = recipient
    target = tmp_path / 'recipient-protected.pdf'
    result = export_secure_pdf(document, target, mode='certificate', certificate_path=path)
    assert result['security']['signed'] is False
    assert result['security']['recipient_decryption_verified'] is False
    reader = PdfFileReader(BytesIO(target.read_bytes()), strict=True)
    assert reader.encrypt_dict['/Filter'] == '/Adobe.PubSec'
    assert reader.encrypt_dict['/V'] == 5 and reader.encrypt_dict['/Length'] == 256
    credential = SimpleEnvelopeKeyDecrypter(cert=certificate, private_key=key)
    assert reader.decrypt_pubkey(credential).status != AuthStatus.FAILED
    clear_writer = _preserving_writer(reader)
    clear_stream = BytesIO()
    clear_writer.write(clear_stream)
    clear = clear_stream.getvalue()
    _assert_preserved(document, clear)
    with fitz.open(stream=document) as before, fitz.open(stream=clear) as after:
        assert before.get_xml_metadata() == after.get_xml_metadata()
        assert before.metadata['title'] == after.metadata['title']
    assert b'Custom metadata must survive' not in target.read_bytes()


def test_signed_and_encrypted_metadata_are_readonly_and_exports_refused(document, tmp_path):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(document)))
    writer.root_object[NameObject('/Perms')] = DictionaryObject({NameObject('/Synthetic'): NumberObject(1)})
    stream = BytesIO()
    writer.write(stream)
    signed = stream.getvalue()
    assert document_properties(signed)['signed']
    assert not document_properties(signed)['editable']
    with pytest.raises(EditError, match='firmado'):
        update_document_metadata(signed, {'title': 'Must not change'})
    with pytest.raises(EditError, match='firmado'):
        export_secure_pdf(signed, tmp_path / 'must-not-exist.pdf', password='test')
    with fitz.open(stream=document) as doc:
        encrypted = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='reader')
    assert not document_properties(encrypted, password='reader')['editable']
    with pytest.raises(EditError, match='cifrado'):
        update_document_metadata(encrypted, {'title': 'Must not change'}, password='reader')
    assert not (tmp_path / 'must-not-exist.pdf').exists()
