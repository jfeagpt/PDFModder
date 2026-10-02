"""Recursos de inserción con códigos nuevos y glifos comprobados.

El recurso original nunca se modifica. Un subconjunto que conserva un cmap
Unicode puede reutilizar sus contornos; una fuente que realmente carece de un
glifo requiere una elección explícita. El nombre de familia no prueba identidad.
"""
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import math

import pymupdf as fitz
from fontTools.ttLib import TTFont, TTLibError, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from pypdf import PdfReader
from pypdf.generic import NameObject, ByteStringObject, FloatObject

from .fonts import FontError, FontResolver, _font_metadata, _check_embedding


@dataclass
class NativeFontExtension:
    data: bytes
    resource: str
    font: object
    catalog: dict
    evidence: dict
    rendered_name: str
    bbox_ratios: tuple[float, float]
    unit: int = 1


def _pdf_name(value):
    raw = value.encode('utf-8')
    return '/' + ''.join(chr(c) if 33 <= c <= 126 and chr(c) not in '#%()/<>[]{}' else f'#{c:02X}' for c in raw)


def _tounicode(catalog):
    entries = [(next(iter(codes)), char.encode('utf-16-be').hex().upper()) for char, codes in catalog.items()]
    chunks = []
    for start in range(0, len(entries), 100):
        group = entries[start:start+100]
        chunks.append(f'{len(group)} beginbfchar\n' + '\n'.join(f'<{code:02X}> <{char}>' for code, char in group) + '\nendbfchar')
    return ('/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n'
            '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
            '/CMapName /PDFModderUnicode def\n/CMapType 2 def\n'
            '1 begincodespacerange\n<00> <FF>\nendcodespacerange\n' + '\n'.join(chunks) +
            '\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend').encode('ascii')


def _new_object(doc, content, stream=None):
    xref = doc.get_new_xref()
    doc.update_object(xref, content)
    if stream is not None:
        doc.update_stream(xref, stream)
    return xref


def _attach_page_font(doc, page_number, font_xref):
    """Clone both dictionaries, so inherited/shared page resources stay intact."""
    page = doc[page_number]
    kind, value = doc.xref_get_key(page.xref, 'Resources')
    if kind == 'xref':
        resources = doc.xref_object(int(value.split()[0]), compressed=False)
    elif kind == 'dict':
        resources = value
    else:
        # Page resources can be inherited from a Pages node.
        parent = page.xref
        resources = None
        while resources is None:
            typ, ref = doc.xref_get_key(parent, 'Parent')
            if typ != 'xref':
                raise FontError('No se han podido aislar los recursos heredados de la página.')
            parent = int(ref.split()[0])
            typ, ref = doc.xref_get_key(parent, 'Resources')
            if typ == 'dict': resources = ref
            elif typ == 'xref': resources = doc.xref_object(int(ref.split()[0]), compressed=False)
    local_resources = _new_object(doc, resources)
    kind, value = doc.xref_get_key(local_resources, 'Font')
    fonts = doc.xref_object(int(value.split()[0]), compressed=False) if kind == 'xref' else value if kind == 'dict' else '<<>>'
    local_fonts = _new_object(doc, fonts)
    existing = set(doc.xref_get_keys(local_fonts))
    counter = 1
    while f'PMEdit{counter}' in existing:
        counter += 1
    resource = f'PMEdit{counter}'
    doc.xref_set_key(local_fonts, resource, f'{font_xref} 0 R')
    doc.xref_set_key(local_resources, 'Font', f'{local_fonts} 0 R')
    doc.xref_set_key(page.xref, 'Resources', f'{local_resources} 0 R')
    return '/' + resource


def _symbol_program(content, text):
    """Change addressing only; retain every outline, metric and hint program."""
    try:
        tt = TTFont(BytesIO(content), recalcBBoxes=False, recalcTimestamp=False)
    except (TTLibError, ValueError) as exc:
        raise FontError('Este programa no es una TTF reutilizable para códigos nuevos.') from exc
    with tt:
        if 'glyf' not in tt or 'hmtx' not in tt:
            raise FontError('La nueva codificación nativa requiere contornos TrueType. Elige una TTF estática.')
        if 'cmap' not in tt:
            raise FontError('La fuente TrueType incrustada es parcial y no conserva un catálogo Unicode. '
                            'No se ha podido verificar el código de los caracteres nuevos en ese mismo programa. '
                            'Importa la fuente completa de la misma variante y versión o elige otra explícitamente.')
        original_cmap = tt.getBestCmap() or {}
        if not original_cmap:
            raise FontError('La fuente parcial sólo conserva códigos internos del PDF, sin un mapa Unicode reutilizable para los caracteres nuevos. '
                            'Abre Tipografía / formato…, activa «Cambiar la fuente explícitamente» y elige una fuente completa que contenga esos caracteres.')
        missing = sorted(set(text) - {chr(cp) for cp, glyph in original_cmap.items() if glyph != '.notdef'})
        if missing:
            raise FontError('La fuente incrustada no contiene un glifo Unicode reutilizable para: ' +
                            ', '.join(f'«{c}» (U+{ord(c):04X})' for c in missing[:16]) +
                            '. Elige explícitamente una fuente completa en Tipografía / formato… mediante «Cambiar la fuente explícitamente»; no se sustituirá por una parecida.')
        unique = list(dict.fromkeys(text))
        if len(unique) > 254:
            raise FontError('Esta selección supera los 254 caracteres distintos de la codificación nativa. Divídela en fragmentos.')
        # Reserve PDF code 32 for the actual space, because Tw applies by code.
        codes = iter(code for code in range(1, 256) if code != 32)
        catalog = {c: {32 if c == ' ' else next(codes)} for c in unique}
        mappings = {next(iter(catalog[c])): original_cmap[ord(c)] for c in unique}
        upem = tt['head'].unitsPerEm
        # PDF simple-font cursor advancement in MuPDF rounds /Widths to whole
        # thousandths of an em, even though its glyph bbox keeps the original
        # fractional hmtx metric. Store that precision explicitly so readers,
        # layout and TJ cursor compensation all consume the same advances.
        widths = {code: math.floor(tt['hmtx'].metrics[glyph][0] * 1000 / upem + .5)
                  for code, glyph in mappings.items()}
        if any(not math.isfinite(width) or width <= 0 for width in widths.values()):
            raise FontError('La fuente tiene avances nulos o no verificables; esta ruta no admite marcas combinantes.')
        cmap = newTable('cmap')
        cmap.tableVersion = 0
        # Format 0 stores glyph IDs in single bytes. A full installed font may
        # have e.g. Euro at glyph 2948 even though its PDF character code fits
        # in one byte; format 6 retains that 16-bit glyph ID without reordering.
        mac = CmapSubtable.newSubtable(6)
        mac.platformID, mac.platEncID, mac.language, mac.cmap = 1, 0, 0, dict(mappings)
        symbol = CmapSubtable.newSubtable(4)
        symbol.platformID, symbol.platEncID, symbol.language = 3, 0, 0
        symbol.cmap = {0xF000 + code: glyph for code, glyph in mappings.items()}
        # Keep Unicode access for a later editing session. PDF symbolic code
        # selection uses the Windows-symbol table, while getBestCmap can still
        # recover any other glyph from the same retained complete program.
        unicode_map = CmapSubtable.newSubtable(12)
        unicode_map.platformID, unicode_map.platEncID, unicode_map.language = 0, 4, 0
        unicode_map.cmap = dict(original_cmap)
        cmap.tables = [mac, symbol, unicode_map]
        tt['cmap'] = cmap
        descriptor = {
            'bbox': [getattr(tt['head'], name) * 1000 / upem for name in ('xMin', 'yMin', 'xMax', 'yMax')],
            'ascent': tt['hhea'].ascent * 1000 / upem,
            'descent': tt['hhea'].descent * 1000 / upem,
            'italic': float(tt['post'].italicAngle) if 'post' in tt else 0,
        }
        buffer = BytesIO()
        tt.save(buffer)
        return buffer.getvalue(), catalog, widths, descriptor


def prepare_native_font(data, page_number, show, text, *, font_name=None, font_file=None, resolver=None):
    """Add a verified isolated font; caller must validate its actual text edit.

    ``show`` is the original operator_glyph_map record. Automatic reuse reads
    only that exact embedded resource. Installed/imported fonts need an explicit
    request, and are labelled accordingly in the returned evidence.
    """
    from .clipping import _serialize
    text = text.replace('\r', '').replace('\n', '')
    if not text:
        raise FontError('No hay caracteres que codificar en una selección vacía.')
    if any(ord(c) < 32 for c in text):
        raise FontError('Sustituye los controles y tabuladores por espacios explícitos.')
    explicit = bool(font_name or font_file)
    resolver = resolver or FontResolver()
    if not explicit:
        mapped=_prepare_existing_tt_mapping(data,page_number,show,text)
        if mapped is not None:
            return mapped
    with fitz.open(stream=data, filetype='pdf') as doc:
        if explicit:
            resolved = resolver.resolve_explicit(font_name or '', text, font_file)
            content, base14, name = resolved.buffer, resolved.base14, resolved.name
            metadata = resolved.metadata
            if content:
                name = metadata.get('postscript_name') or name
        else:
            xref = show.get('xref')
            if not xref:
                raise FontError('La fuente original no tiene un programa incrustado identificable. Elige una tipografía explícitamente.')
            name, _, _, content = doc.extract_font(xref)
            if not content:
                raise FontError('El recurso original no contiene los glifos adicionales. Elige explícitamente una fuente completa.')
            metadata = _font_metadata(content, name)
            _check_embedding(metadata, name, bool(name[:6].isupper() and len(name) > 6 and name[6] == '+'))
            base14 = None
        if base14:
            from .fonts import BASE14
            canonical = next(key for key, value in BASE14.items() if value == base14)
            catalog = {}
            for char in dict.fromkeys(text):
                try:
                    code = char.encode('cp1252')
                except UnicodeEncodeError as exc:
                    raise FontError(f'«{char}» no tiene código WinAnsi en esta fuente estándar. Elige una TTF que lo contenga.') from exc
                if len(code) != 1 or code[0] < 32:
                    raise FontError('La fuente estándar no admite ese carácter en su codificación nativa.')
                catalog[char] = {code[0]}
            widths = {next(iter(catalog[char])): math.floor(resolved.font.text_length(char, fontsize=1000) + .5)
                      for char in catalog}
            cmap_xref = _new_object(doc, '<<>>', _tounicode(catalog))
            first, last = min(widths), max(widths)
            width_array = ' '.join(str(widths.get(code, 0)) for code in range(first, last+1))
            font_xref = _new_object(doc, f'<< /Type /Font /Subtype /Type1 /BaseFont /{canonical} /Encoding /WinAnsiEncoding '
                f'/FirstChar {first} /LastChar {last} /Widths [{width_array}] /ToUnicode {cmap_xref} 0 R >>')
        else:
            program, catalog, widths, descriptor = _symbol_program(content, text)
            program_xref = _new_object(doc, f'<< /Length1 {len(program)} >>', program)
            escaped = _pdf_name(name)
            bbox = ' '.join(str(v) for v in descriptor['bbox'])
            descriptor_xref = _new_object(doc, f'<< /Type /FontDescriptor /FontName {escaped} /Flags {4 | (64 if descriptor["italic"] else 0)} '
                f'/FontBBox [{bbox}] /ItalicAngle {descriptor["italic"]} /Ascent {descriptor["ascent"]} /Descent {descriptor["descent"]} '
                f'/CapHeight {descriptor["ascent"]} /StemV 80 /FontFile2 {program_xref} 0 R >>')
            cmap_xref = _new_object(doc, '<<>>', _tounicode(catalog))
            first, last = min(widths), max(widths)
            width_array = ' '.join(str(widths.get(code, 0)) for code in range(first, last+1))
            font_xref = _new_object(doc, f'<< /Type /Font /Subtype /TrueType /BaseFont {escaped} /FirstChar {first} /LastChar {last} '
                f'/Widths [{width_array}] /FontDescriptor {descriptor_xref} 0 R /ToUnicode {cmap_xref} 0 R >>')
        resource = _attach_page_font(doc, page_number, font_xref)
        updated = doc.tobytes(garbage=0, deflate=True)
    # An isolated probe verifies extraction, glyph availability and declared
    # advances before a new code can reach the editable document.
    chars = list(catalog)
    ops = []
    for char in chars:
        code = next(iter(catalog[char]))
        ops.extend([([], b'BT'), ([NameObject(resource), FloatObject(12)], b'Tf'),
                    ([FloatObject(v) for v in (1, 0, 0, 1, 40, 40)], b'Tm'),
                    ([ByteStringObject(bytes([code, code]))], b'Tj'), ([], b'ET')])
    with fitz.open(stream=updated, filetype='pdf') as probe:
        # This is an isolated, discarded probe. A normal-sized upright page
        # avoids a tiny CropBox clipping the metric sample for a valid font.
        probe[page_number].set_mediabox(fitz.Rect(0, 0, 300, 300))
        probe[page_number].set_rotation(0)
        stream = _new_object(probe, '<<>>', _serialize(ops))
        probe[page_number].set_contents(stream)
        traces = probe[page_number].get_texttrace()
        glyphs = [c for span in traces for c in span['chars']]
        if len(glyphs) != 2 * len(chars) or any(c[0] != ord(char) or c[1] == 0
                for char, pair in zip(chars, zip(glyphs[::2], glyphs[1::2])) for c in pair):
            raise FontError('El programa elegido no reproduce los nuevos códigos como glifos verificables.')
        if any(abs((second[2][0] - first[2][0]) - widths[next(iter(catalog[char]))] * .012) > .002
               for char, first, second in zip(chars, glyphs[::2], glyphs[1::2])):
            raise FontError('Los avances de los nuevos códigos no coinciden con las métricas verificadas de la fuente.')
        rendered_names = {span['font'] for span in traces}
        if len(rendered_names) != 1:
            raise FontError('Los nuevos caracteres requieren más de una fuente; no se aplicará una sustitución implícita.')
        rendered_name = rendered_names.pop()
        rawchars = [char for block in probe[page_number].get_text('rawdict')['blocks'] if block['type'] == 0
                    for line in block['lines'] for span in line['spans'] for char in span['chars']]
        if not rawchars:
            raise FontError('No se han podido medir las dimensiones de los nuevos glifos.')
        bbox_ratios = (min((c['bbox'][1] - c['origin'][1]) / 12 for c in rawchars),
                       max((c['bbox'][3] - c['origin'][1]) / 12 for c in rawchars))
    reader = PdfReader(BytesIO(updated), strict=True)
    font = reader.pages[page_number]['/Resources']['/Font'][resource].get_object()
    evidence = {'source': 'elección explícita' if explicit else 'programa incrustado exacto',
                'explicit': explicit, 'source_program_sha256': sha256(content).hexdigest() if content else None,
                'name': name, 'resource': resource, 'characters': ''.join(chars),
                'original_resource_unchanged': True, 'all_outlines_retained': not bool(base14),
                'pdf_width_precision': '1/1000 em; avances enteros comprobados por orígenes consecutivos',
                'identity_basis': 'Fuente elegida por el usuario' if explicit else 'Los mismos contornos, métricas y programas de glifo del recurso incrustado; sólo cambia el mapa de códigos'}
    return NativeFontExtension(updated, resource, font, catalog, evidence, rendered_name, bbox_ratios)


def _prepare_existing_tt_mapping(data,page_number,show,text):
    """Clone the PDF font dictionary, keeping its original FontFile2 bytes.

    This path gives an already present glyph a proven Unicode label. It never
    adds an outline or turns another font's glyph into the selected face.
    """
    from .native_codes import _tt_font, existing_tt_unicode
    from .clipping import _serialize
    from .richtext import _source_width
    from pypdf._cmap import get_encoding
    if 'font' not in show:
        # Public callers can carry only the stable page resource and xref.
        # Resolve its dictionary from this exact PDF; never substitute by name
        # or use a stale xref belonging to another resource/document revision.
        try:
            source = PdfReader(BytesIO(data), strict=True)
            fonts = source.pages[page_number]['/Resources']['/Font'].get_object()
            font = fonts[show['resource']].get_object()
            reference = getattr(font, 'indirect_reference', None)
            if reference is None or reference.idnum != show.get('xref'):
                raise ValueError('resource identity mismatch')
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise FontError('No se puede verificar la identidad del recurso de fuente original; vuelve a seleccionar el texto.') from exc
        show = {**show, 'font': font}
    target=_tt_font(show)
    if target is None:return None
    with target:
        # A complete embedded cmap already has the normal extension route.
        if 'cmap' in target:return None
        revision=f'{target["head"].fontRevision:.2f}'
    encoding,cmap=get_encoding(show['font'])
    if encoding!='utf-16-be' or cmap.get(-1)!=2:return None
    catalog={}
    for key,char in cmap.items():
        if isinstance(key,str) and len(key)==1 and isinstance(char,str) and len(char)==1:
            catalog.setdefault(char,set()).add(ord(key))
    missing={c for c in text if len(catalog.get(c,set()))!=1}
    completed,proofs=existing_tt_unicode(data,page_number,show,missing)
    for char,codes in completed.items():catalog[char]=codes
    unresolved=sorted(c for c in missing if len(catalog.get(c,set()))!=1)
    if unresolved:
        raise FontError('La fuente TrueType parcial «'+str(show['font'].get('/BaseFont','')).lstrip('/')+
            '», versión '+revision+', no contiene un glifo o código Unicode verificable para: '+
            ', '.join(f'«{c}» (U+{ord(c):04X})' for c in unresolved)+
            '. Importa la fuente completa de la misma variante y versión o elige otra fuente explícitamente; no se sustituirá automáticamente.')
    if not completed:return None
    # Preserve every original mapping, adding only uniquely proven labels.
    entries=[]
    for char,codes in catalog.items():
        for code in codes:entries.append((code,char))
    if len({code for code,_ in entries})!=len(entries):
        raise FontError('El nuevo catálogo Unicode asignaría significados distintos al mismo código; operación bloqueada.')
    chunks=[]
    for start in range(0,len(entries),100):
        group=entries[start:start+100]
        chunks.append(f'{len(group)} beginbfchar\n'+'\n'.join(f'<{code:04X}> <{char.encode("utf-16-be").hex().upper()}>' for code,char in group)+'\nendbfchar')
    unicode_stream=('/CIDInit /ProcSet findresource begin 12 dict begin begincmap '
        '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def '
        '/CMapName /PDFModderExistingGlyphs def /CMapType 2 def '
        '1 begincodespacerange <0000> <FFFF> endcodespacerange\n'+'\n'.join(chunks)+
        '\nendcmap CMapName currentdict /CMap defineresource pop end end').encode('ascii')
    with fitz.open(stream=data,filetype='pdf') as doc:
        source_xref=show.get('xref')
        if not source_xref:raise FontError('No se puede aislar el recurso de fuente original.')
        original_program=doc.extract_font(source_xref)[3]
        new_font=_new_object(doc,doc.xref_object(source_xref))
        unicode_xref=_new_object(doc,'<<>>',unicode_stream)
        doc.xref_set_key(new_font,'ToUnicode',f'{unicode_xref} 0 R')
        resource=_attach_page_font(doc,page_number,new_font)
        updated=doc.tobytes(garbage=0,deflate=True)
    reader=PdfReader(BytesIO(updated),strict=True)
    font=reader.pages[page_number]['/Resources']['/Font'][resource].get_object()
    chosen={char:catalog[char] for char in dict.fromkeys(text)}
    ops=[]
    for char,codes in chosen.items():
        code=next(iter(codes)).to_bytes(2,'big')
        ops.extend([([],b'BT'),([NameObject(resource),FloatObject(12)],b'Tf'),
                    ([FloatObject(v) for v in (1,0,0,1,40,40)],b'Tm'),
                    ([ByteStringObject(code+code)],b'Tj'),([],b'ET')])
    with fitz.open(stream=updated,filetype='pdf') as probe:
        assert probe.extract_font(new_font)[3]==original_program
        page=probe[page_number];page.set_mediabox(fitz.Rect(0,0,300,300));page.set_rotation(0)
        stream=_new_object(probe,'<<>>',_serialize(ops));page.set_contents(stream)
        spans=page.get_texttrace();glyphs=[c for span in spans for c in span['chars']]
        if len(glyphs)!=len(chosen)*2:
            raise FontError('El catálogo Unicode no conserva el número de glifos reales.')
        for char,a,b in zip(chosen,glyphs[::2],glyphs[1::2]):
            if any(c[0]!=ord(char) or c[1]==0 for c in (a,b)):
                raise FontError('El código Unicode propuesto no corresponde a un glifo real del recurso original.')
            expected=_source_width(font,next(iter(chosen[char])),char)*.012
            if abs(b[2][0]-a[2][0]-expected)>.002:
                raise FontError('El nuevo código no reproduce el avance original de la fuente.')
        names={span['font'] for span in spans}
        if len(names)!=1:raise FontError('El catálogo requiere una sustitución de fuente no permitida.')
        raw=[c for b in page.get_text('rawdict')['blocks'] if b['type']==0 for l in b['lines'] for s in l['spans'] for c in s['chars']]
        ratios=(min((c['bbox'][1]-c['origin'][1])/12 for c in raw),max((c['bbox'][3]-c['origin'][1])/12 for c in raw))
    evidence={'source':'programa TrueType original; catálogo Unicode ampliado','explicit':False,'mapping_only':True,
              'original_resource_unchanged':True,'source_program_sha256':sha256(original_program).hexdigest(),
              'program_unchanged':True,'all_outlines_retained':True,'resource':resource,'characters':text,
              'unicode_mapping_evidence':proofs,
              'identity_basis':'Mismo programa de fuente y ajuste original; únicamente se asigna Unicode a glifos ya presentes con instrucciones, componentes y métricas exactos'}
    return NativeFontExtension(updated,resource,font,chosen,evidence,names.pop(),ratios,unit=2)
