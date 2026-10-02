"""Validación transaccional de contenido, geometría y apariencia (144 ppp)."""
from collections import Counter
import hashlib
import io
import math
import numpy as np
import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream
from .model import EditError, transform_rect


def document_issues(data, doc):
    issues = []
    encrypted=bool(doc.is_encrypted or doc.needs_pass or (doc.metadata or {}).get('encryption'))
    if encrypted:
        issues.append("Documento cifrado: edición y exportación desactivadas en esta versión.")
    if not (doc.permissions & fitz.PDF_PERM_MODIFY):
        issues.append("El documento no concede permiso para modificar contenido.")
    if doc.is_form_pdf:
        issues.append("Contiene campos de formulario; sus valores y cálculos necesitan un editor de formularios.")
    if doc.get_sigflags()>0:
        issues.append("El PDF declara firmas digitales; editar su contenido afectaría a su validación.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt('')  # Empty user password, never bypass owner restrictions.
        root = reader.trailer['/Root']
        form=root.get('/AcroForm')
        if form and form.get_object().get('/XFA'):
            issues.append("Formulario XFA: esta versión no modifica sus datos ni sus apariencias.")
        if root.get('/Perms'):
            issues.append("Documento firmado o certificado: modificar contenido afectaría a la firma.")
        if root.get('/StructTreeRoot'):
            from .tagged import analyze
            try:
                analyze(data)
            except EditError as exc:
                issues.append(str(exc))
        for f in (reader.get_fields() or {}).values():
            if f.get('/FT') == '/Sig':
                issues.append("Contiene un campo de firma digital; se conserva el original y se bloquea la edición.")
    except Exception:
        if not encrypted:
            issues.append("El analizador independiente no puede verificar la estructura de este PDF.")
    return list(dict.fromkeys(issues))


def page_issues(data, number):
    """Analiza operadores con parser PDF, nunca expresiones sobre el binario."""
    issues = []
    try:
        reader = PdfReader(io.BytesIO(data))
        page = reader.pages[number]
        ops = ContentStream(page.get_contents(), reader).operations
        if any(op in (b'W',b'W*') for _,op in ops):
            issues.append("Página con recortes gráficos explícitos: no se puede reconstruir el texto con seguridad.")
        if any(op in (b'BDC', b'BMC') for _,op in ops):
            from .tagged import analyze
            try:
                if analyze(data) is None:
                    issues.append("Página con contenido marcado o capas sin estructura accesible verificable.")
            except EditError as exc:
                issues.append(str(exc))
        from .graphics_state import page_color_issues
        issues.extend(page_color_issues(reader, page, ops))
    except Exception as exc:
        issues.append(f"No se pudo analizar los operadores de esta página: {type(exc).__name__}.")
    return list(dict.fromkeys(issues))


def trace_chars(page):
    return [(chr(c[0]), tuple(c[2]), s['font'], float(s['size']))
            for s in page.get_texttrace() for c in s['chars']]


def assert_characters(expected, page, tolerance=.035):
    actual = trace_chars(page)
    if len(expected) != len(actual):
        raise EditError(f"Validación: se esperaban {len(expected)} caracteres reales y se obtuvieron {len(actual)}.")
    by_char = {}
    for text, origin, *_ in actual:
        by_char.setdefault(text, []).append(origin)
    for text, origin, *_ in expected:
        possibilities = by_char.get(text, [])
        index = next((i for i,p in enumerate(possibilities)
                      if abs(origin[0]-p[0]) <= tolerance and abs(origin[1]-p[1]) <= tolerance), None)
        if index is None:
            raise EditError(f"Validación: el carácter {text!r} cambió o no está en su posición prevista ({origin[0]:.2f}, {origin[1]:.2f}).")
        possibilities.pop(index)


def _canonical(value):
    if isinstance(value, dict):
        # References and paint sequence numbers naturally change after full
        # writing / insertion. Geometry, paint order within this list and all
        # visible properties still must match.
        return {k:_canonical(v) for k,v in value.items() if k not in ('xref','id','seqno','number')}
    if isinstance(value,(tuple,list,fitz.Rect,fitz.Point,fitz.Matrix)):
        return tuple(_canonical(v) for v in value)
    if isinstance(value,float):
        return round(value,3)
    return value


def related(page):
    return _canonical({
        'links':page.get_links(),
        'annots':[(a.type, tuple(a.rect),a.info,a.colors,a.opacity,
                   a.vertices,a.flags,a.border,a.line_ends,a.blendmode) for a in page.annots() or []],
        'widgets':[(w.field_name,w.field_value,w.field_type,tuple(w.rect)) for w in page.widgets() or []],
        'drawings':page.get_drawings(),
        # Compressed stream length can change under a lossless full write.
        # Compare decoded pixel digest, dimensions, mask, placement and colour
        # properties instead; the independent page render checks appearance.
        'images':[{k:v for k,v in info.items() if k!='size'} for info in page.get_image_info(hashes=True)],
    })


def _ink_exclusions(page, excluded):
    """Prove small glyph overhangs from embedded outlines, never infer them from diff pixels.

    Some PDF font ascenders omit the tilde of Ñ. Text extraction rectangles
    describe advances/metrics, not painted outlines. Only unique embedded
    TrueType resources and horizontal filled glyphs with matching advance are
    eligible. Unsupported fonts/transforms keep the original strict mask.
    """
    if not excluded:
        return []
    from fontTools.ttLib import TTFont
    from fontTools.pens.boundsPen import BoundsPen

    def font_name(value):
        parts=value.split('+',1)
        value=parts[-1] if len(parts)==2 and len(parts[0])==6 and parts[0].isupper() else value
        # MuPDF may report the PostScript name while /BaseFont uses the full
        # name (spaces versus hyphens). More than one matching resource blocks.
        return ''.join(c.casefold() for c in value if c.isalnum())

    resources={}
    for info in page.get_fonts():
        resources.setdefault(font_name(info[3]),set()).add(info[0])
    raw={}
    for block in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT|fitz.TEXT_IGNORE_ACTUALTEXT)['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                for char in span['chars']:
                    if not char.get('synthetic'):
                        point=char['origin']
                        if all(math.isfinite(v) for v in point):
                            key=(char['c'],math.floor(point[0]*20),math.floor(point[1]*20))
                            raw.setdefault(key,[]).append((point,char['bbox']))
    fonts={}
    outlines={}
    result=[]
    try:
        for span in page.get_texttrace():
            if span['type']!=0 or span.get('opacity',0)<=0 or span.get('wmode') or tuple(span['dir'])!=(1.,0.):
                continue
            candidates=resources.get(font_name(span['font']),())
            if len(candidates)!=1:
                continue
            for code,gid,origin,trace_box in span['chars']:
                if not all(math.isfinite(v) for v in origin):
                    continue
                cell=(math.floor(origin[0]*20),math.floor(origin[1]*20))
                nearby=[item for dx in (-1,0,1) for dy in (-1,0,1)
                        for item in raw.get((chr(code),cell[0]+dx,cell[1]+dy),())]
                boxes=[trace_box]+[bbox for point,bbox in nearby
                    if max(abs(a-b) for a,b in zip(point,origin))<.025]
                matched=[fitz.Rect(r) for r in excluded
                    if any(max(abs(a-b) for a,b in zip(r,bbox))<.035 for bbox in boxes)]
                if not matched or gid<0:
                    continue
                xref=next(iter(candidates))
                if xref not in fonts:
                    try:
                        content=page.parent.extract_font(xref)[3]
                        font=TTFont(io.BytesIO(content),lazy=True) if content else None
                        if font is not None and ('glyf' not in font or 'fvar' in font):
                            font.close();font=None
                        fonts[xref]=font
                    except Exception:
                        fonts[xref]=None
                font=fonts[xref]
                if font is None or gid>=len(font.getGlyphOrder()):
                    continue
                key=(xref,gid)
                if key not in outlines:
                    glyph=font.getGlyphOrder()[gid]
                    pen=BoundsPen(font.getGlyphSet())
                    font.getGlyphSet()[glyph].draw(pen)
                    outlines[key]=(pen.bounds,font['hmtx'].metrics[glyph][0],font['head'].unitsPerEm)
                bounds,advance,units=outlines[key]
                size=float(span['size'])
                if bounds is None or not math.isfinite(size) or size<=0 or advance<=0:
                    continue
                ascender=float(span.get('ascender',0));descender=float(span.get('descender',0))
                if not (ascender>0 and descender<0):
                    continue
                metric_top=origin[1]-size*ascender/(ascender-descender)
                metric_bottom=origin[1]-size*descender/(ascender-descender)
                if max(abs(metric_top-trace_box[1]),abs(metric_bottom-trace_box[3]))>.025:
                    # A mirrored vertical axis can still report dir=(1,0).
                    # Never place an assumed upright outline over such text.
                    continue
                scale=size/units
                # Do not guess an independent Tz / CTM scale from glyph metrics.
                # This narrow route handles equal-axis advances; others stay strict.
                measured=trace_box[2]-trace_box[0]
                if abs(measured-advance*scale)>.01+.005*advance*scale:
                    continue
                x0,y0,x1,y1=bounds
                ink=fitz.Rect(origin[0]+x0*scale,origin[1]-y1*scale,
                              origin[0]+x1*scale,origin[1]-y0*scale)
                if not all(math.isfinite(v) for v in ink):
                    continue
                for rect in matched:
                    expanded=rect|ink
                    growth=max(abs(a-b) for a,b in zip(expanded,rect))
                    if .01<growth<=min(2.,size*.25):
                        result.append(tuple(expanded))
    except Exception:
        # An outline that cannot be proved never relaxes validation.
        return []
    finally:
        for font in fonts.values():
            if font is not None:
                font.close()
    return list(dict.fromkeys(result))


def _exclude_pixels(mask, rect, matrix, pixmap):
    # Keep the same 0.75 pt antialias envelope, now around proven ink when needed.
    r=(fitz.Rect(rect)+(-.75,-.75,.75,.75))*matrix
    if not all(math.isfinite(v) for v in r):
        raise EditError('Región no finita en la validación visual.')
    x0,y0,x1,y1=r.irect
    x0=max(0,min(pixmap.width,x0-pixmap.x));x1=max(0,min(pixmap.width,x1-pixmap.x))
    y0=max(0,min(pixmap.height,y0-pixmap.y));y1=max(0,min(pixmap.height,y1-pixmap.y))
    if x1>x0 and y1>y0:
        mask[y0:y1,x0:x1]=False


def pixel_diff(before, after, excluded=(), dpi=144):
    scale = dpi/72
    if before.rect.width*before.rect.height*scale*scale > 16_000_000:
        raise EditError("Página demasiado grande para la validación visual limitada a 16 millones de píxeles.")
    a = before.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False, colorspace=fitz.csRGB)
    b = after.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False, colorspace=fitz.csRGB)
    if (a.width,a.height) != (b.width,b.height):
        raise EditError("La validación detectó un cambio de dimensiones de página.")
    aa = np.frombuffer(a.samples,dtype=np.uint8).reshape(a.height,a.width,3)
    bb = np.frombuffer(b.samples,dtype=np.uint8).reshape(b.height,b.width,3)
    delta = np.abs(aa.astype(np.int16)-bb.astype(np.int16)).max(axis=2)
    mask = np.ones(delta.shape,dtype=bool)
    excluded=tuple(tuple(r) for r in excluded)
    matrix=before.rotation_matrix*fitz.Matrix(scale,scale)
    for rect in excluded:
        _exclude_pixels(mask,rect,matrix,a)
    ink_regions=[]
    before_ink=int(np.count_nonzero(mask))
    if excluded and np.any((delta>8)&mask):
        ink_regions=list(dict.fromkeys(_ink_exclusions(before,excluded)+_ink_exclusions(after,excluded)))
        for rect in ink_regions:
            _exclude_pixels(mask,rect,matrix,a)
    values = delta[mask]
    maximum = int(values.max()) if values.size else 0
    changed = int(np.count_nonzero(values > 8))
    return {'max_channel_delta': maximum, 'pixels_above_8': changed,
            'checked_pixels': int(values.size), 'dpi':dpi,
            'ink_exclusion_regions':ink_regions,
            'ink_extra_pixels':before_ink-int(values.size)}


def assert_pixels(before, after, excluded=(), reproduction=False):
    stats = pixel_diff(before, after, excluded)
    # Eight 8-bit levels allow minor decimal serialization/AA differences, but
    # no pixel may exceed this outside the individual changed glyph envelopes.
    if stats['pixels_above_8']:
        what = "La fuente no reproduce exactamente la apariencia original" if reproduction else "Se detectaron cambios visuales fuera de los caracteres editados"
        raise EditError(f"{what}: {stats['pixels_above_8']} píxeles exceden la tolerancia de 8/255 a 144 ppp.")
    return stats


def validate_transition(before_data, after_data, page_number, expected, excluded, tagged_expected=None):
    report = []
    with fitz.open(stream=before_data,filetype='pdf') as before, fitz.open(stream=after_data,filetype='pdf') as after:
        if before.page_count != after.page_count:
            raise EditError("La validación detectó un cambio en el número de páginas.")
        if before.metadata != after.metadata or before.get_xml_metadata() != after.get_xml_metadata():
            raise EditError("La validación detectó cambios ajenos en metadatos.")
        if _canonical(before.get_toc(False)) != _canonical(after.get_toc(False)):
            raise EditError("La validación detectó cambios en los marcadores.")
        for i in range(before.page_count):
            a,b = before[i],after[i]
            if (tuple(a.mediabox),tuple(a.cropbox),a.rotation) != (tuple(b.mediabox),tuple(b.cropbox),b.rotation):
                raise EditError("Se alteraron los límites o la rotación de una página.")
            if related(a) != related(b):
                raise EditError("Se alteraron imágenes, vectores, enlaces, anotaciones o campos; operación cancelada.")
            assert_characters(expected if i==page_number else trace_chars(a), b)
            report.append(assert_pixels(a,b,excluded if i==page_number else ()))
    # Independent parser proves that output is a structurally readable PDF.
    independent = PdfReader(io.BytesIO(after_data), strict=True)
    if len(independent.pages) != len(report):
        raise EditError("El lector independiente no confirma el número de páginas.")
    from .tagged import assert_structure
    assert_structure(before_data,after_data,tagged_expected)
    return {'pages':report, 'independent_parser':'pypdf', 'verified':True}
