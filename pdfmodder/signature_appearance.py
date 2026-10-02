"""Vector signature-widget appearance from public certificate data.

Coordinates at the API boundary are displayed CropBox points, top-left origin.
The appearance is imported as a Form XObject before the CMS signature is made.
No private key, trust lookup or network request is used by this module.
"""
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
import math
from pathlib import Path
import sys

import pymupdf as fitz
from pypdf import PdfReader
from pyhanko.pdf_utils.content import AppearanceContent
from pyhanko.pdf_utils.generic import pdf_name
from pyhanko.pdf_utils.layout import BoxConstraints
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.stamp import TextStampStyle

from .model import EditError


DATE_FORMAT = '%d/%m/%Y %H:%M:%S %z'
MIN_WIDTH = 210.0
MIN_HEIGHT = 70.0


def certificate_identity(certificate_der):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    try:
        cert = x509.load_der_x509_certificate(certificate_der)
    except Exception:
        raise EditError('No se puede leer la identidad del certificado para la firma visible.') from None
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    subject = cert.subject.rfc4514_string()
    name = names[0].value if names else subject
    # No hidden newlines/control characters may impersonate appearance labels.
    name = ' '.join(name.split())
    subject = ' '.join(subject.split())
    if not name or len(subject) > 6000:
        raise EditError('Los datos del certificado no caben en una firma visible compatible.')
    return {'certificate_name': name, 'certificate_subject': subject}


def signature_geometry(data, specification):
    """Validate placement and map display coordinates to PDF default space."""
    try:
        if not isinstance(specification, dict):
            raise ValueError()
        index = specification['page']
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError()
        raw = specification['rect']
        if len(raw) != 4 or any(isinstance(v, bool) for v in raw):
            raise ValueError()
        x0, y0, x1, y1 = map(float, raw)
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
            raise ValueError()
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.trailer['/Root'].get('/StructTreeRoot'):
            raise EditError('Este PDF está etiquetado: la firma visible requiere etiquetar su nuevo campo. Puedes firmarlo desactivando «Firma visible» para conservar su estructura.')
        page = reader.pages[index]
        rotation = int(page.rotation) % 360
        if rotation not in (0, 90, 180, 270):
            raise ValueError()
        if float(page.get('/UserUnit', 1)) != 1:
            raise EditError('La firma visible no admite todavía páginas con unidades PDF especiales (/UserUnit).')
        # An oversized CropBox is clipped to MediaBox by PDF viewers.
        crop, media = page.cropbox, page.mediabox
        cx0, cy0 = max(float(crop.left), float(media.left)), max(float(crop.bottom), float(media.bottom))
        cx1, cy1 = min(float(crop.right), float(media.right)), min(float(crop.top), float(media.top))
        width, height = cx1 - cx0, cy1 - cy0
        display_width, display_height = (height, width) if rotation in (90, 270) else (width, height)
        if not (0 <= x0 < x1 <= display_width + .001 and 0 <= y0 < y1 <= display_height + .001):
            raise EditError('El recuadro de firma debe quedar completamente dentro de la página.')
        if x1 - x0 < MIN_WIDTH or y1 - y0 < MIN_HEIGHT:
            raise EditError('Amplía el recuadro de firma: el tamaño mínimo es 74,1 × 24,7 mm.')
        def point(x, y):
            if rotation == 0:
                return cx0 + x, cy1 - y
            if rotation == 90:
                return cx0 + y, cy0 + x
            if rotation == 180:
                return cx1 - x, cy0 + y
            return cx1 - y, cy1 - x
        a, b = point(x0, y0), point(x1, y1)
        box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        return {'page': index, 'rect': [x0, y0, x1, y1], 'box': box,
                'rotation': rotation, 'width': x1 - x0, 'height': y1 - y0}
    except EditError:
        raise
    except Exception:
        raise EditError('La página o el recuadro de firma visible no son válidos.') from None


def _fonts():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'assets' / 'fonts'
    try:
        regular = (root / 'LiberationSans-Regular.ttf').read_bytes()
        bold = (root / 'LiberationSans-Bold.ttf').read_bytes()
        return regular, bold, fitz.Font(fontbuffer=regular), fitz.Font(fontbuffer=bold)
    except Exception:
        raise EditError('Faltan las fuentes de la firma visible. Reinstala PDF Modder completo.') from None


def _wrap(text, font, size, width):
    """Measured wrapping, including long certificate OIDs without spaces."""
    lines, current = [], ''
    for word in text.split():
        candidate = (current + ' ' + word).strip()
        if font.text_length(candidate, fontsize=size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
        for char in word:
            if current and font.text_length(current + char, fontsize=size) > width:
                lines.append(current)
                current = ''
            current += char
    if current:
        lines.append(current)
    return lines


def appearance_pdf(certificate_der, width, height, signing_time):
    """One-page PDF of the exact vector artwork used in the signature widget."""
    identity = certificate_identity(certificate_der)
    regular_bytes, bold_bytes, regular, bold = _fonts()
    name, subject = identity['certificate_name'], identity['certificate_subject']
    date = signing_time.strftime(DATE_FORMAT) if isinstance(signing_time, datetime) else signing_time
    detail = f'Firmado digitalmente por {name}\nNombre de reconocimiento (DN):\n{subject}\nFecha: {date}'
    if any(not regular.has_glyph(ord(c)) or not bold.has_glyph(ord(c))
           for c in name + detail if not c.isspace()):
        raise EditError('El certificado contiene caracteres que la fuente del sello no puede reproducir. Utiliza la firma sin sello visible.')
    pad = 9.0
    divider = width * .40
    left_width, right_width = divider - 2 * pad, width - divider - 2 * pad
    name_lines, detail_lines = [], []
    for name_size in (18, 16, 14, 12, 10):
        name_lines = _wrap(name, bold, name_size, left_width)
        if len(name_lines) * name_size * 1.18 <= height - 2 * pad - 15:
            break
    else:
        raise EditError('Los datos del titular no caben. Amplía la anchura o la altura del recuadro de firma.')
    for detail_size in (9, 8.5, 8, 7.5, 7, 6.5, 6):
        detail_lines = []
        for paragraph in detail.splitlines():
            detail_lines.extend(_wrap(paragraph, regular, detail_size, right_width))
        if len(detail_lines) * detail_size * 1.18 <= height - 2 * pad:
            break
    else:
        raise EditError('Los datos del certificado superan el espacio disponible. Amplía el recuadro de firma; no se ocultarán datos.')
    with fitz.open() as doc:
        page = doc.new_page(width=width, height=height)
        page.insert_font(fontname='SignatureRegular', fontbuffer=regular_bytes)
        page.insert_font(fontname='SignatureBold', fontbuffer=bold_bytes)
        page.draw_rect(fitz.Rect(.4, .4, width - .4, height - .4), color=(.72, .79, .85), width=.6)
        page.draw_line((divider, pad), (divider, height - pad), color=(.72, .79, .85), width=.7)
        page.draw_line((pad, height - 7), (divider - pad, height - 7), color=(.80, .87, .93), width=2)
        baseline = max(pad + name_size, (height - 15 - len(name_lines) * name_size * 1.18) / 2 + name_size)
        for line in name_lines:
            page.insert_text((pad, baseline), line, fontname='SignatureBold', fontsize=name_size, color=(.06, .20, .32))
            baseline += name_size * 1.18
        page.insert_text((pad, height - 13), 'FIRMA DIGITAL', fontname='SignatureRegular', fontsize=7, color=(.29, .39, .48))
        baseline = pad + detail_size
        for line in detail_lines:
            page.insert_text((divider + pad, baseline), line, fontname='SignatureRegular', fontsize=detail_size, color=(.10, .13, .17))
            baseline += detail_size * 1.18
        doc.subset_fonts()
        data = doc.tobytes(garbage=4, deflate=True)
    return data, {**identity, 'signing_time': date, 'name_font_size': name_size,
                  'detail_font_size': detail_size, 'text': detail}


class _VectorAppearance(AppearanceContent):
    def __init__(self, writer, box, pdf_bytes, rotation):
        super().__init__(writer, box)
        self.pdf_bytes, self.rotation = pdf_bytes, rotation

    def render(self):
        imported = self.writer.import_page_as_xobject(PdfFileReader(BytesIO(self.pdf_bytes)))
        self.resources.xobject[pdf_name('/SignatureArtwork')] = imported
        width, height = self.box.width, self.box.height
        matrix = {0: (1, 0, 0, 1, 0, 0), 90: (0, 1, -1, 0, width, 0),
                  180: (-1, 0, 0, -1, width, height), 270: (0, -1, 1, 0, 0, height)}[self.rotation]
        return (b'q %g %g %g %g %g %g cm /SignatureArtwork Do Q' % matrix)


@dataclass(frozen=True)
class CertificateStampStyle(TextStampStyle):
    """TextStampStyle receives the exact signing-session timestamp from pyHanko."""
    certificate_der: bytes = b''
    rotation: int = 0
    timestamp_format: str = DATE_FORMAT
    appearance_info: dict = field(default_factory=dict, compare=False)

    def create_stamp(self, writer, box, text_params):
        width, height = box.width, box.height
        if self.rotation in (90, 270):
            width, height = height, width
        data, details = appearance_pdf(self.certificate_der, width, height, text_params['ts'])
        self.appearance_info.update(details)
        return _VectorAppearance(writer, box, data, self.rotation)


def preview_appearance(data, certificate_der, specification):
    """Render the real /AP without signing, using a temporary filled widget.

    The dummy value is confined to memory and never exported; it makes readers
    display the supplied /AP rather than a native empty-signature-field control.
    """
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils import generic
    from pyhanko.sign.fields import SigFieldSpec, append_signature_field, enumerate_sig_fields
    geometry = signature_geometry(data, specification)
    writer = IncrementalPdfFileWriter(BytesIO(data), strict=True)
    field_name = 'PDFModder_VisiblePreview'
    append_signature_field(writer, SigFieldSpec(sig_field_name=field_name,
                                               on_page=geometry['page'], box=geometry['box']))
    _, _, field_ref = next(enumerate_sig_fields(writer, with_name=field_name))
    widget = field_ref.get_object()
    style = CertificateStampStyle(certificate_der=certificate_der, rotation=geometry['rotation'])
    box = geometry['box']
    stamp = style.create_stamp(writer, BoxConstraints(width=box[2] - box[0], height=box[3] - box[1]),
                               {'ts': datetime.now().astimezone().strftime(DATE_FORMAT)})
    stamp.apply_appearance(widget)
    widget[pdf_name('/V')] = writer.add_object(generic.DictionaryObject({pdf_name('/Type'): pdf_name('/Sig')}))
    result = BytesIO()
    writer.write(result)
    with fitz.open(stream=result.getvalue(), filetype='pdf') as pdf:
        page = pdf[geometry['page']]
        zoom = min(1.5, 1000 / max(page.rect.width, page.rect.height))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        crop = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(geometry['rect']), alpha=False)
        return {'png': pixmap.tobytes('png'), 'appearance_png': crop.tobytes('png'),
                'width': pixmap.width, 'height': pixmap.height, 'zoom': zoom,
                'page': geometry['page'], 'rect': geometry['rect'], 'preview_only': True,
                **style.appearance_info}
