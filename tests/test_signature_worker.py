"""The real session previews and exports a visible signature without editing history."""
from hashlib import sha256

import pymupdf as fitz

from pdfmodder.signing import verify_signed_pdf
from pdfmodder.smoke_v160 import test_certificate as make_test_certificate
from pdfmodder.worker import Session


def test_visible_preview_and_export_preserve_working_history_and_original(tmp_path):
    with fitz.open() as doc:
        doc.new_page(width=595, height=842).insert_text((40, 60), 'Original de prueba')
        doc.new_page(width=595, height=842).insert_text((50, 70), 'Pagina de control intacta')
        original = doc.tobytes()
    source = tmp_path / 'original.pdf'
    source.write_bytes(original)
    certificate, password = make_test_certificate(tmp_path)
    session = Session(source, config_path=tmp_path / 'fonts.json', history_dir=tmp_path)
    try:
        # Sign the current committed snapshot, not the original or a replay.
        with fitz.open(stream=original) as doc:
            doc[0].insert_text((40, 90), 'Edicion confirmada antes de firmar')
            committed = doc.tobytes()
        session.history.push(committed, {'operation': 'synthetic_committed_edit'})
        before_state = session.state()
        before_paths = list(session.history.states)
        before_digest = sha256(session.history.current).hexdigest()
        existing_files = set(tmp_path.iterdir())
        visible = {'page': 0, 'rect': [50., 620., 540., 780.]}
        pages = session.signing_pages()
        assert pages == [{'page': 0, 'width': 595., 'height': 842.},
                         {'page': 1, 'width': 595., 'height': 842.}]
        preview = session.signature_preview(certificate_path=str(certificate), password=password,
                                            visible_signature=visible, reason='Prueba local')
        assert preview['preview_only'] is True and preview['png'].startswith(b'\x89PNG')
        assert preview['page'] == 0 and preview['rect'] == visible['rect']
        assert 'TEST ONLY' in preview['certificate_subject']
        assert set(tmp_path.iterdir()) == existing_files
        assert session.state() == before_state
        assert sha256(session.history.current).hexdigest() == before_digest

        target = tmp_path / 'copia-firmada.pdf'
        result = session.sign_pdf(target, certificate_path=str(certificate), password=password,
                                  visible_signature=visible, reason='Prueba local')
        signed = target.read_bytes()
        assert result['signature']['visible_signature']['rect'] == visible['rect']
        assert result['signature']['cryptographic_integrity'] is True
        assert verify_signed_pdf(signed)['covers_entire_file'] is True
        assert session.state() == before_state and session.history.states == before_paths
        assert session.history.current == committed
        assert source.read_bytes() == original
        assert password not in str(result)
        with fitz.open(stream=committed) as before, fitz.open(stream=signed) as after:
            assert 'Edicion confirmada antes de firmar' in after[0].get_text()
            assert before[1].get_pixmap().samples == after[1].get_pixmap().samples
    finally:
        session.close()
