"""Local approval signatures; never rewrite the resulting signed PDF.

The Personal Windows store is accessed locally; no trust service, OCSP, CRL or
timestamp requests are performed. Verification means ByteRange coverage and cryptographic integrity,
not that a certification authority or the signer's identity has been trusted.
"""
from datetime import datetime, timezone
import base64
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from .model import EditError


SIGNING_NOTICE = (
    'Firma criptográfica local con un certificado instalado en Windows o un archivo PFX/P12. Sin sello de tiempo ni '
    'consulta de revocación. La confianza del certificado debe comprobarse en '
    'el lector PDF del destinatario. Se guarda una copia; el documento de '
    'trabajo continúa sin firmar.'
)


def _bridge_call(request):
    """Use only our packaged helper; private keys never cross this boundary."""
    if getattr(sys, 'frozen', False):
        executable = Path(sys.executable).resolve().parent / 'PDFModderSigningBridge.exe'
    else:
        executable = Path(__file__).resolve().parents[1] / 'tmp' / 'native-v160' / 'PDFModderSigningBridge.exe'
    if not executable.is_file():
        raise EditError('Falta el componente de certificados de Windows. Reinstala PDF Modder completo.')
    try:
        result = subprocess.run(
            [str(executable)], input=json.dumps(request, ensure_ascii=True),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8-sig',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=180,
            check=False,
        )
        reply = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise EditError('El proveedor del certificado no respondió en tres minutos. Cancela cualquier petición de PIN pendiente y vuelve a intentarlo.') from None
    except Exception:
        raise EditError('No se ha podido consultar el almacén de certificados de Windows.') from None
    if result.returncode or not reply.get('ok'):
        raise EditError(reply.get('error') or 'El proveedor de Windows no ha podido completar la firma.')
    return reply


def list_signing_certificates():
    """Only public metadata is returned; listing does not sign or request a PIN."""
    reply = _bridge_call({'command': 'list'})
    return {'certificates': reply.get('certificates', [])}


def _windows_signer(thumbprint, store):
    if store not in ('CurrentUser', 'LocalMachine'):
        raise EditError('El almacén de certificados de Windows no es válido.')
    thumbprint = thumbprint.replace(' ', '').upper()
    certificate = next((cert for cert in list_signing_certificates()['certificates']
                        if cert['thumbprint'].replace(' ', '').upper() == thumbprint and cert['store'] == store), None)
    if certificate is None:
        raise EditError('El certificado seleccionado ya no está disponible, no tiene clave privada RSA o ha caducado.')
    from asn1crypto import algos, x509
    from pyhanko.sign import signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore
    from cryptography import x509 as crypto_x509
    from cryptography.hazmat.primitives.asymmetric import rsa
    try:
        cert_der = base64.b64decode(certificate['certificate_der_base64'], validate=True)
        cert = x509.Certificate.load(cert_der)
        public_key = crypto_x509.load_der_x509_certificate(cert_der).public_key()
        if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
            raise ValueError('RSA key required')
    except Exception:
        raise EditError('El certificado instalado no contiene una clave RSA compatible de al menos 2048 bits.') from None

    class WindowsStoreSigner(signers.Signer):
        async def async_sign_raw(self, data, digest_algorithm, dry_run=False):
            if digest_algorithm.lower() != 'sha256':
                raise EditError('El proveedor de firma sólo admite SHA-256 en este flujo.')
            if dry_run:
                return bytes(public_key.key_size // 8)
            response = _bridge_call({
                'command': 'sign', 'thumbprint': thumbprint, 'store': store,
                'algorithm': 'rsa_pkcs1_sha256',
                'digest_base64': base64.b64encode(sha256(data).digest()).decode('ascii'),
            })
            if base64.b64decode(response['certificate_der_base64'], validate=True) != cert_der:
                raise EditError('El proveedor utilizó un certificado distinto al seleccionado.')
            signature = base64.b64decode(response['signature_base64'], validate=True)
            if len(signature) != public_key.key_size // 8:
                raise EditError('El proveedor devolvió una firma de longitud incorrecta.')
            return signature

    return WindowsStoreSigner(
        signing_cert=cert, cert_registry=SimpleCertificateStore(),
        signature_mechanism=algos.SignedDigestAlgorithm({'algorithm': 'sha256_rsa'}),
    )


def _imports():
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import signers, fields
        return PdfFileReader, IncrementalPdfFileWriter, signers, fields
    except ImportError:
        raise EditError('Falta el componente de firma digital pyHanko. Reinstala PDF Modder completo.') from None


def _signable(data):
    """Refuse locks, encryption and earlier signatures before touching key data."""
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise EditError('La firma de PDF cifrados no está habilitada en esta versión.')
        root = reader.trailer['/Root']
        if root.get('/Perms'):
            raise EditError('El PDF contiene permisos de certificación; se conserva sin modificar.')
        fields = reader.get_fields() or {}
        if any(field.get('/FT') == '/Sig' for field in fields.values()):
            raise EditError('El PDF ya contiene firmas o campos de firma. La firma adicional requiere un flujo específico.')
        if not len(reader.pages):
            raise EditError('No se puede firmar un PDF sin páginas.')
        return reader
    except EditError:
        raise
    except Exception:
        raise EditError('No se puede verificar la estructura del PDF antes de firmarlo.') from None


def _certificate_details(signer):
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import rsa, ec
    cert = x509.load_der_x509_certificate(signer.signing_cert.dump())
    now = datetime.now(timezone.utc)
    if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
        raise EditError('El certificado está caducado o todavía no es válido según la fecha del equipo.')
    try:
        usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        if not (usage.digital_signature or usage.content_commitment):
            raise EditError('El certificado no permite firmar documentos.')
    except x509.ExtensionNotFound:
        pass
    public_key = cert.public_key()
    if isinstance(public_key, rsa.RSAPublicKey):
        if public_key.key_size < 2048:
            raise EditError('La clave RSA debe tener al menos 2048 bits.')
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        if public_key.key_size < 256:
            raise EditError('La clave de curva elíptica debe tener al menos 256 bits.')
    else:
        raise EditError('Esta versión admite certificados RSA o de curva elíptica ECDSA.')
    return {
        'certificate_subject': cert.subject.rfc4514_string(),
        'certificate_issuer': cert.issuer.rfc4514_string(),
        'certificate_sha256': sha256(signer.signing_cert.dump()).hexdigest(),
        'certificate_expires': cert.not_valid_after_utc.isoformat(),
    }


def verify_signed_pdf(data, expected_certificate_sha256=None):
    """Verify our single, final SHA-256 signature, without asserting trust."""
    PdfFileReader, _, _, _ = _imports()
    from pyhanko.sign.validation.generic_cms import validate_sig_integrity
    from pyhanko.sign.validation.status import SignatureCoverageLevel
    try:
        reader = PdfFileReader(BytesIO(data), strict=True)
        signatures = reader.embedded_signatures
        if len(signatures) != 1:
            raise EditError('Se esperaba exactamente una firma digital en la copia.')
        signature = signatures[0]
        if signature.md_algorithm != 'sha256':
            raise EditError('La firma no usa el resumen SHA-256 previsto.')
        if signature.evaluate_signature_coverage() != SignatureCoverageLevel.ENTIRE_FILE:
            raise EditError('La firma no cubre la totalidad del archivo final.')
        fingerprint = sha256(signature.signer_cert.dump()).hexdigest()
        if expected_certificate_sha256 and fingerprint != expected_certificate_sha256:
            raise EditError('El certificado de la copia no coincide con el seleccionado.')
        intact, valid = validate_sig_integrity(
            signature.signer_info, signature.signer_cert,
            expected_content_type='data', actual_digest=signature.compute_digest(),
        )
        if not intact or not valid:
            raise EditError('La comprobación criptográfica de la firma ha fallado.')
        return {
            'cryptographic_integrity': True, 'covers_entire_file': True,
            'digest_algorithm': 'sha256', 'certificate_sha256': fingerprint,
            'trust_verified': False, 'revocation_checked': False,
            'trusted_timestamp': False,
        }
    except EditError:
        raise
    except Exception:
        raise EditError('No se ha podido comprobar la firma criptográfica. No se guarda la copia.') from None


def preview_signature(data, certificate_path=None, password='', *, reason='', location='',
                      certificate_thumbprint='', certificate_store='CurrentUser', visible_signature=None):
    """Public-certificate appearance only: no signing, PIN or store key access."""
    from .signature_appearance import preview_appearance, signature_geometry
    _signable(data)
    signature_geometry(data, visible_signature)
    if certificate_thumbprint:
        thumbprint = certificate_thumbprint.replace(' ', '').upper()
        certificate = next((cert for cert in list_signing_certificates()['certificates']
                            if cert['thumbprint'].replace(' ', '').upper() == thumbprint
                            and cert['store'] == certificate_store), None)
        if certificate is None:
            raise EditError('El certificado seleccionado ya no está disponible en Windows.')
        try:
            certificate_der = base64.b64decode(certificate['certificate_der_base64'], validate=True)
        except Exception:
            raise EditError('No se pueden leer los datos públicos del certificado.') from None
    else:
        from cryptography.hazmat.primitives.serialization import pkcs12, Encoding
        if not certificate_path:
            raise EditError('Selecciona un certificado antes de previsualizar la firma.')
        try:
            pfx_data = Path(certificate_path).read_bytes()
            if len(pfx_data) > 16 * 1024 * 1024:
                raise ValueError()
            bundle = pkcs12.load_pkcs12(pfx_data, password.encode('utf-8') if password else None)
            if bundle.cert is None:
                raise ValueError()
            certificate_der = bundle.cert.certificate.public_bytes(Encoding.DER)
        except Exception:
            raise EditError('No se puede abrir el certificado. Comprueba el archivo PFX/P12 y su contraseña.') from None
        finally:
            pfx_data = bundle = password = None
    return preview_appearance(data, certificate_der, visible_signature)


def sign_pdf(data, certificate_path=None, password='', *, reason='', location='',
             certificate_thumbprint='', certificate_store='CurrentUser', visible_signature=None):
    """Return (signed bytes, public report), using the normal full-write first.

    The password and decrypted key stay in this worker call. They are never
    put into history, reports, configuration or exceptions. Python cannot
    promise deterministic erasure of immutable strings from process memory.
    """
    _signable(data)
    appearance_geometry = None
    if visible_signature is not None:
        from .signature_appearance import signature_geometry
        appearance_geometry = signature_geometry(data, visible_signature)
    PdfFileReader, IncrementalPdfFileWriter, signers, fields = _imports()
    if certificate_thumbprint:
        signer = _windows_signer(certificate_thumbprint, certificate_store)
    else:
        if not certificate_path:
            raise EditError('Selecciona un certificado instalado en Windows o un archivo PFX/P12.')
        try:
            pfx_data = Path(certificate_path).read_bytes()
        except OSError:
            raise EditError('No se puede leer el certificado PFX/P12 seleccionado.') from None
        if len(pfx_data) > 16 * 1024 * 1024:
            raise EditError('El archivo PFX/P12 supera el tamaño admitido de 16 MB.')
        try:
            signer = signers.SimpleSigner.load_pkcs12_data(
                pfx_data, other_certs=[], passphrase=password.encode('utf-8') if password else None,
            )
        except Exception:
            raise EditError('No se puede abrir el certificado. Comprueba el archivo PFX/P12 y su contraseña.') from None
        finally:
            pfx_data = None
            password = None
    if signer is None:
        raise EditError('El archivo no contiene un certificado con su clave privada utilizable.')
    report = _certificate_details(signer)
    # Complete rewrite removes old editing revisions before the signature's
    # own required incremental update. The normal export validator checks it.
    from .engine import full_write
    from .validation import document_issues, validate_transition
    import pymupdf as fitz
    with fitz.open(stream=data, filetype='pdf') as original:
        issues = document_issues(data, original)
        if issues:
            raise EditError('\n'.join(issues))
        canonical = full_write(original)
    validate_transition(data, canonical, -1, [], [])
    field_name = 'PDFModder_' + uuid.uuid4().hex
    metadata = signers.PdfSignatureMetadata(
        field_name=field_name, md_algorithm='sha256',
        reason=reason.strip()[:512] or None, location=location.strip()[:256] or None,
        certify=False, embed_validation_info=False,
    )
    try:
        writer = IncrementalPdfFileWriter(BytesIO(canonical), strict=True)
        style = None
        field_spec = fields.SigFieldSpec(sig_field_name=field_name, on_page=0)
        if appearance_geometry is not None:
            from .signature_appearance import CertificateStampStyle, signature_geometry
            appearance_geometry = signature_geometry(canonical, visible_signature)
            style = CertificateStampStyle(certificate_der=signer.signing_cert.dump(), rotation=appearance_geometry['rotation'])
            field_spec = fields.SigFieldSpec(sig_field_name=field_name, on_page=appearance_geometry['page'],
                                             box=appearance_geometry['box'], readable_field_name='Firma digital del documento')
        output = signers.PdfSigner(
            signature_meta=metadata, signer=signer, stamp_style=style,
            new_field_spec=field_spec,
        ).sign_pdf(writer).getvalue()
    except EditError:
        raise
    except Exception:
        raise EditError('El motor no ha podido firmar este PDF con el certificado seleccionado.') from None
    finally:
        signer = None
    if not output.startswith(canonical):
        raise EditError('La firma no ha conservado la copia PDF preparada.')
    report.update(verify_signed_pdf(output, report['certificate_sha256']))
    report['visible_signature'] = None if appearance_geometry is None else {
        'page': appearance_geometry['page'], 'rect': appearance_geometry['rect'],
        **style.appearance_info,
    }
    report.update(operation='digital_signature', field_name=field_name,
                  certificate_source='windows' if certificate_thumbprint else 'pkcs12',
                  source_sha256=sha256(data).hexdigest(),
                  signed_sha256=sha256(output).hexdigest(), notice=SIGNING_NOTICE)
    return output, report


def atomic_save_signed(data, destination, *, protected_paths=(), certificate_sha256=None):
    """Save the exact signature bytes atomically, then leave history untouched."""
    target = Path(destination).resolve()
    for source in protected_paths:
        original = Path(source).resolve()
        if target == original or (target.exists() and original.exists() and os.path.samefile(target, original)):
            raise EditError('Guarda la copia firmada en otra ruta para conservar el PDF original.')
    verify_signed_pdf(data, certificate_sha256)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.pdfmodder-firma-', suffix='.pdf', dir=target.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        written = Path(temporary).read_bytes()
        if sha256(written).digest() != sha256(data).digest():
            raise EditError('La copia temporal de la firma no coincide con el archivo validado.')
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return str(target)
