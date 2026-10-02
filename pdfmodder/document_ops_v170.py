"""Document metadata and independent AES-256 copies.

All entry points take immutable bytes and return plain values. They belong in
the serial PDF worker. A recipient certificate grants the ability to open a
copy; it does not sign it and never requires the sender's private key.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from io import BytesIO
import base64
import os
from pathlib import Path
import re
import tempfile

import pymupdf as fitz

from .model import EditError


METADATA_FIELDS = {
    'title': 'Título', 'author': 'Autor', 'subject': 'Asunto',
    'keywords': 'Palabras clave', 'creator': 'Aplicación de creación',
    'producer': 'Productor PDF', 'creationDate': 'Fecha de creación',
    'modDate': 'Fecha de modificación',
}
_INFO_KEYS = {key: '/' + key[0].upper() + key[1:] for key in METADATA_FIELDS}
_INFO_KEYS['modDate'] = '/ModDate'
_NS = {
    'x': 'adobe:ns:meta/', 'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dc': 'http://purl.org/dc/elements/1.1/', 'pdf': 'http://ns.adobe.com/pdf/1.3/',
    'xmp': 'http://ns.adobe.com/xap/1.0/', 'xml': 'http://www.w3.org/XML/1998/namespace',
}


def _open(data, password=''):
    try:
        document = fitz.open(stream=data, filetype='pdf')
        if not document.is_pdf or not document.page_count:
            raise ValueError()
        if document.needs_pass and not document.authenticate(password):
            document.close()
            raise EditError('El PDF necesita una contraseña válida para consultar sus propiedades.')
        return document
    except EditError:
        raise
    except Exception:
        raise EditError('No se puede abrir la estructura del documento PDF.') from None


def _restriction(data, document, password=''):
    """Independent signature checks precede every full rewrite."""
    if document.get_sigflags() > 0:
        return 'El documento contiene firmas digitales; sus propiedades se muestran sólo para lectura.', True
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted and not reader.decrypt(password):
            return 'No se puede verificar la estructura del PDF cifrado.', False
        if reader.trailer['/Root'].get('/Perms') or any(
                field.get('/FT') == '/Sig' for field in (reader.get_fields() or {}).values()):
            return 'El documento está firmado o certificado; se conserva sin modificar.', True
        if reader.is_encrypted:
            return 'Este PDF ya está cifrado. Sus propiedades se muestran sólo para lectura.', False
    except Exception:
        return 'No se puede verificar la estructura del PDF; sus propiedades se muestran sólo para lectura.', False
    if not document.permissions & fitz.PDF_PERM_MODIFY:
        return 'El documento no concede permiso para modificarlo.', False
    return '', False


def document_properties(data, path='', password=''):
    """Inspect the current snapshot, including locked and signed documents."""
    with _open(data, password) as document:
        metadata = document.metadata or {}
        reason, signed = _restriction(data, document, password)
        return {
            'path': str(Path(path).resolve()) if path else '',
            'size_bytes': len(data), 'page_count': document.page_count,
            'format': metadata.get('format', 'PDF'),
            'metadata': {key: metadata.get(key) or '' for key in METADATA_FIELDS},
            'encryption': metadata.get('encryption') or '',
            'has_xmp': bool(document.get_xml_metadata()),
            'signed': signed, 'editable': not bool(reason), 'edit_reason': reason,
        }


def _date(value):
    """Accept PDF dates or ISO dates and return (PDF syntax, ISO syntax)."""
    value = value.strip()
    if not value:
        return '', ''
    if value.startswith('D:'):
        match = re.fullmatch(r'D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(Z|[+-]\d{2}\'?\d{2}\'?)?', value)
        if not match:
            raise EditError('Introduce la fecha como AAAA-MM-DD o AAAA-MM-DD HH:MM:SS, con zona horaria opcional.')
        year, month, day, hour, minute, second, zone = match.groups()
        values = [int(year), int(month or 1), int(day or 1), int(hour or 0), int(minute or 0), int(second or 0)]
        tz = None
        if zone:
            if zone == 'Z':
                tz = timezone.utc
            else:
                digits = zone[1:].replace("'", '')
                hours, minutes = int(digits[:2]), int(digits[2:])
                if hours > 23 or minutes > 59:
                    raise EditError('La zona horaria de la fecha no es válida.')
                tz = timezone((1 if zone[0] == '+' else -1) * timedelta(hours=hours, minutes=minutes))
        try:
            parsed = datetime(*values, tzinfo=tz)
        except ValueError:
            raise EditError('La fecha indicada no existe o contiene una hora no válida.') from None
        return value, parsed.isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise EditError('Introduce una fecha válida como AAAA-MM-DD o AAAA-MM-DD HH:MM:SS, con zona horaria opcional.') from None
    pdf = parsed.strftime('D:%Y%m%d%H%M%S')
    offset = parsed.utcoffset()
    if offset is not None:
        if not offset:
            pdf += 'Z'
        else:
            minutes = int(offset.total_seconds() / 60)
            pdf += ('+' if minutes >= 0 else '-') + f"{abs(minutes)//60:02d}'{abs(minutes)%60:02d}'"
    return pdf, parsed.isoformat()


def validate_metadata(metadata):
    if not isinstance(metadata, dict) or any(key not in METADATA_FIELDS for key in metadata):
        raise EditError('Sólo se pueden editar los campos de metadatos del documento.')
    result = {}
    for key, value in metadata.items():
        if not isinstance(value, str) or '\x00' in value or len(value) > 8192:
            raise EditError('Los metadatos deben contener texto válido de hasta 8192 caracteres por campo.')
        result[key] = _date(value)[0] if key in ('creationDate', 'modDate') else value
    return result


def _updated_xmp(packet, changes):
    """Keep custom namespaces, descriptions, qualifiers and language variants."""
    from lxml import etree
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
        root = etree.fromstring(packet.encode('utf-8'), parser)
        if root.getroottree().docinfo.doctype:
            raise ValueError()
        rdf = root if root.tag == '{' + _NS['rdf'] + '}RDF' else root.find('.//rdf:RDF', _NS)
        if rdf is None:
            raise ValueError()
        descriptions = rdf.findall('rdf:Description', _NS)
        description = next((item for item in descriptions if item.get('{' + _NS['rdf'] + '}about', '') == ''), None)
        if description is None:
            description = etree.SubElement(rdf, '{' + _NS['rdf'] + '}Description')
            description.set('{' + _NS['rdf'] + '}about', '')
            descriptions.append(description)
        mapping = {
            'title': ('dc', 'title', 'Alt'), 'author': ('dc', 'creator', 'Seq'),
            'subject': ('dc', 'description', 'Alt'), 'keywords': ('pdf', 'Keywords', ''),
            'creator': ('xmp', 'CreatorTool', ''), 'producer': ('pdf', 'Producer', ''),
            'creationDate': ('xmp', 'CreateDate', ''), 'modDate': ('xmp', 'ModifyDate', ''),
        }
        for key, value in changes.items():
            prefix, local, container = mapping[key]
            tag = '{' + _NS[prefix] + '}' + local
            if key in ('creationDate', 'modDate'):
                value = _date(value)[1]
            # Attribute and child representations both occur in real XMP.
            for desc in descriptions:
                desc.attrib.pop(tag, None)
            existing = [(desc, item) for desc in descriptions for item in desc.findall(tag)]
            if not value:
                for desc, item in existing:
                    desc.remove(item)
                continue
            prop = existing[0][1] if existing else etree.SubElement(description, tag)
            for desc, item in existing[1:]:
                desc.remove(item)
            if container == 'Alt':
                alt = prop.find('rdf:Alt', _NS)
                if alt is None:
                    for child in list(prop):
                        prop.remove(child)
                    prop.text = None
                    alt = etree.SubElement(prop, '{' + _NS['rdf'] + '}Alt')
                items = alt.findall('rdf:li', _NS)
                item = next((item for item in items if item.get('{' + _NS['xml'] + '}lang') == 'x-default'), None)
                if item is None:
                    item = etree.SubElement(alt, '{' + _NS['rdf'] + '}li')
                    item.set('{' + _NS['xml'] + '}lang', 'x-default')
                item.text = value
            elif container == 'Seq':
                for child in list(prop):
                    prop.remove(child)
                prop.text = None
                seq = etree.SubElement(prop, '{' + _NS['rdf'] + '}Seq')
                etree.SubElement(seq, '{' + _NS['rdf'] + '}li').text = value
            else:
                for child in list(prop):
                    prop.remove(child)
                prop.text = value
        return etree.tostring(root.getroottree(), encoding='unicode')
    except EditError:
        raise
    except Exception:
        raise EditError('Los metadatos XMP no se pueden actualizar con seguridad. Se conserva el PDF sin cambios.') from None


def _assert_content(before, after):
    """Metadata and encryption may never change text, page geometry or pixels."""
    if before.page_count != after.page_count:
        raise EditError('La copia no conserva el número de páginas; no se guarda.')
    from .validation import related
    for left, right in zip(before, after):
        if (left.rect != right.rect or left.mediabox != right.mediabox
                or left.cropbox != right.cropbox or left.rotation != right.rotation
                or left.get_text() != right.get_text()):
            raise EditError('La copia no conserva el texto o la geometría de las páginas; no se guarda.')
        if left.get_pixmap().samples != right.get_pixmap().samples:
            raise EditError('La copia no conserva la apariencia de las páginas; no se guarda.')
        if related(left) != related(right):
            raise EditError('La copia no conserva imágenes, enlaces, anotaciones o valores de formulario; no se guarda.')


def update_document_metadata(data, metadata, password=''):
    """Return an undoable snapshot. Unspecified Info keys remain intact."""
    metadata = validate_metadata(metadata)
    with _open(data, password) as document:
        reason, _ = _restriction(data, document, password)
        if reason:
            raise EditError(reason)
        old = document.metadata or {}
        changes = {key: value for key, value in metadata.items() if value != (old.get(key) or '')}
        if not changes:
            return data, {'operation': 'document_metadata', 'changed_fields': [], 'pages': document.page_count}
        xmp = document.get_xml_metadata()
        updated_xmp = _updated_xmp(xmp, changes) if xmp else None
        info_type, info_ref = document.xref_get_key(-1, 'Info')
        if info_type == 'xref':
            info = int(info_ref.split()[0])
        else:
            info = document.get_new_xref()
            document.update_object(info, '<<>>')
            document.xref_set_key(-1, 'Info', f'{info} 0 R')
        for key, value in changes.items():
            document.xref_set_key(info, _INFO_KEYS[key][1:], fitz.get_pdf_str(value) if value else 'null')
        if updated_xmp is not None:
            document.set_xml_metadata(updated_xmp)
        candidate = document.tobytes(garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_KEEP)
    with _open(data, password) as before, _open(candidate, password) as after:
        _assert_content(before, after)
        page_count = after.page_count
        actual = after.metadata or {}
        if any((actual.get(key) or '') != value for key, value in changes.items()):
            raise EditError('No se han podido verificar los metadatos escritos.')
        if xmp and after.get_xml_metadata() != updated_xmp:
            raise EditError('No se han podido verificar los metadatos XMP escritos.')
    return candidate, {
        'operation': 'document_metadata', 'changed_fields': list(changes),
        'pages': page_count,
        'text_preserved': True, 'appearance_preserved': True, 'xmp_preserved': True,
        'source_regions': [], 'destination_regions': [],
    }


def save_metadata_snapshot(data,path,*,protected_paths=()):
    """Save validated metadata-only bytes, including unchanged form fields.

    Session permits this route only when every committed operation was a
    metadata edit. Signatures and existing encryption remain prohibited.
    """
    target=Path(path).resolve()
    for value in protected_paths:
        source=Path(value).resolve()
        if target==source or (target.exists() and source.exists() and os.path.samefile(target,source)):
            raise EditError('Guarda las propiedades en una copia distinta del PDF original.')
    with _open(data) as document:
        reason,_=_restriction(data,document)
        if reason:raise EditError(reason)
    temporary=None
    try:
        fd,temporary=tempfile.mkstemp(prefix='.pdfmodder-propiedades-',suffix='.pdf',dir=target.parent)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        if Path(temporary).read_bytes()!=data:
            raise EditError('La copia temporal no conserva las propiedades validadas.')
        os.replace(temporary,target);temporary=None
        return str(target)
    finally:
        if temporary and Path(temporary).exists():Path(temporary).unlink()


def _recipient_certificate(raw):
    from asn1crypto import x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding
    try:
        certificate = x509.load_pem_x509_certificate(raw) if b'-----BEGIN CERTIFICATE-----' in raw else x509.load_der_x509_certificate(raw)
    except Exception:
        raise EditError('No se puede leer el certificado público. Selecciona un archivo CER, CRT o PEM válido.') from None
    now = datetime.now(timezone.utc)
    if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
        raise EditError('El certificado del destinatario está caducado o todavía no es válido.')
    key = certificate.public_key()
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise EditError('El cifrado por certificado requiere una clave RSA de al menos 2048 bits.')
    try:
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
        if not usage.key_encipherment:
            raise EditError('El certificado permite firmar pero no cifrar claves para el destinatario.')
    except x509.ExtensionNotFound:
        pass
    der = certificate.public_bytes(Encoding.DER)
    return asn1_x509.Certificate.load(der), {
        'certificate_subject': certificate.subject.rfc4514_string(),
        'certificate_sha256': sha256(der).hexdigest(),
        'certificate_expires': certificate.not_valid_after_utc.isoformat(),
    }


def list_encryption_certificates():
    """Reuse public DER only; never issue the bridge's sign command or a PIN."""
    from .signing import list_signing_certificates
    try:
        listing = list_signing_certificates()
    except EditError as exc:
        return {'certificates': [], 'error': str(exc)}
    compatible = []
    for entry in listing.get('certificates', []):
        try:
            raw = base64.b64decode(entry.get('certificate_der_base64', ''), validate=True)
            _recipient_certificate(raw)
        except (ValueError, EditError):
            continue
        compatible.append(entry)
    return {'certificates': compatible, 'error': ''}


def _load_recipient(certificate_path='', certificate_thumbprint='', certificate_store='CurrentUser'):
    if certificate_path and certificate_thumbprint:
        raise EditError('Selecciona un único certificado de destinatario.')
    if certificate_thumbprint:
        if certificate_store not in ('CurrentUser', 'LocalMachine'):
            raise EditError('El almacén de certificados seleccionado no es válido.')
        thumbprint = certificate_thumbprint.replace(' ', '').upper()
        entry = next((item for item in list_encryption_certificates()['certificates']
                      if item['thumbprint'].replace(' ', '').upper() == thumbprint and item['store'] == certificate_store), None)
        if entry is None:
            raise EditError('El certificado compatible seleccionado ya no está disponible en Windows.')
        try:
            raw = base64.b64decode(entry['certificate_der_base64'], validate=True)
        except Exception:
            raise EditError('No se pueden leer los datos públicos del certificado seleccionado.') from None
    else:
        if not certificate_path:
            raise EditError('Selecciona el certificado público del destinatario.')
        try:
            certificate_file = Path(certificate_path)
            if certificate_file.stat().st_size > 1024 * 1024:
                raise ValueError()
            raw = certificate_file.read_bytes()
        except Exception:
            raise EditError('No se puede abrir el certificado público del destinatario.') from None
    return _recipient_certificate(raw)


def _preserving_writer(reader):
    from pyhanko.pdf_utils.writer import copy_into_new_writer
    writer = copy_into_new_writer(reader)
    # pyHanko 0.33's normal _update_meta replaces ModDate/Producer and rebuilds
    # XMP. This copy operation explicitly preserves those bytes. Its object
    # importer already brings over Info and the metadata stream, so disable
    # only automatic metadata authoring on this isolated writer (never global).
    writer._update_meta = lambda: None
    return writer


def _encrypted_certificate_copy(data, certificate):
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.crypt import SecurityHandlerVersion
    reader = PdfFileReader(BytesIO(data), strict=True)
    writer = _preserving_writer(reader)
    # PDF MAC is a newer PDF 2.0 extension. AES-256 /adbe.pkcs7.s5 keeps this
    # export usable by current certificate-aware desktop readers.
    writer.encrypt_pubkey([certificate], version=SecurityHandlerVersion.AES256, encrypt_metadata=True, pdf_mac=False)
    stream = BytesIO()
    writer.write(stream)
    encrypted = stream.getvalue()
    encrypted_reader = PdfFileReader(BytesIO(encrypted), strict=True)
    encryption = encrypted_reader.encrypt_dict
    if (encryption.get('/Filter') != '/Adobe.PubSec' or int(encryption.get('/V', 0)) != 5
            or int(encryption.get('/Length', 0)) != 256):
        raise EditError('La copia no contiene el cifrado AES de 256 bits previsto.')
    # Reopen the actual encrypted bytes with the symmetric handler created by
    # this export. No recipient private key is requested or persisted. Real
    # recipient-key decryption is covered by our synthetic-key regression.
    encrypted_reader._security_handler = writer.security_handler
    clear = _preserving_writer(encrypted_reader)
    clear_stream = BytesIO()
    clear.write(clear_stream)
    return encrypted, clear_stream.getvalue()


def export_secure_pdf(data, path, mode='password', password='', certificate_path='',
                      certificate_thumbprint='', certificate_store='CurrentUser', *,
                      source_password='', protected_paths=()):
    """Validate a protected copy, fsync it, then atomically replace destination.

    Passwords and encryption state never enter the return value or history.
    Existing encrypted documents and any signature/certification are refused.
    """
    target = Path(path).resolve()
    protected = [*protected_paths, *([certificate_path] if certificate_path else [])]
    for value in protected:
        source = Path(value).resolve()
        if target == source or (target.exists() and source.exists() and os.path.samefile(target, source)):
            raise EditError('La copia protegida no puede sobrescribir un PDF original ni el certificado seleccionado.')
    temporary = None
    try:
        with _open(data, source_password) as before:
            reason, _ = _restriction(data, before, source_password)
            if reason:
                raise EditError(reason)
            original_xmp = before.get_xml_metadata()
            original_metadata = before.metadata or {}
            report = {'mode': mode, 'algorithm': 'AES-256', 'signed': False}
            if mode == 'password':
                if not isinstance(password, str) or not password or '\x00' in password:
                    raise EditError('Introduce una contraseña no vacía para abrir la copia protegida.')
                # MuPDF accepts at most 40 UTF-8 bytes. Refuse truncation.
                if len(password.encode('utf-8')) > 40:
                    raise EditError('La contraseña puede contener hasta 40 bytes UTF-8; las letras con acento pueden ocupar más de un byte.')
                output = before.tobytes(garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_AES_256,
                                       owner_pw=password, user_pw=password, permissions=before.permissions)
                after = _open(output, password)
                from pypdf import PdfReader
                independent=PdfReader(BytesIO(output),strict=True)
                security=independent.trailer['/Encrypt']
                aes=security.get('/CF',{}).get('/StdCF',{}).get('/CFM')
                if (not independent.is_encrypted or int(security.get('/V',0))!=5
                        or int(security.get('/Length',0))!=256 or aes!='/AESV3'
                        or not independent.decrypt(password)):
                    after.close()
                    raise EditError('La copia no contiene el cifrado AES de 256 bits previsto.')
                report['password_verified'] = True
            elif mode == 'certificate':
                certificate, details = _load_recipient(certificate_path, certificate_thumbprint, certificate_store)
                output, clear = _encrypted_certificate_copy(data, certificate)
                after = _open(clear)
                report.update(details, recipient_decryption_verified=False, encrypted_content_verified=True)
            else:
                raise EditError('Elige cifrado por contraseña o por certificado de destinatario.')
            with after:
                _assert_content(before, after)
                if after.get_xml_metadata() != original_xmp or any(
                        ((after.metadata or {}).get(key) or '') != (original_metadata.get(key) or '') for key in METADATA_FIELDS):
                    raise EditError('La copia protegida no conserva los metadatos del PDF; no se guarda.')
                report.update(page_count=before.page_count, text_preserved=True, appearance_preserved=True, xmp_preserved=True)
        fd, temporary = tempfile.mkstemp(prefix='.pdfmodder-seguro-', suffix='.pdf', dir=target.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        if Path(temporary).read_bytes() != output:
            raise EditError('La verificación del archivo temporal cifrado ha fallado.')
        os.replace(temporary, target)
        temporary = None
        return {'path': str(target), 'security': report}
    except EditError:
        raise
    except OSError:
        raise EditError('No se ha podido guardar la copia protegida. Comprueba la carpeta de destino y si el archivo está abierto.') from None
    except Exception:
        raise EditError('No se ha podido cifrar y verificar la copia del PDF. El documento original se conserva.') from None
    finally:
        password = source_password = None
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
