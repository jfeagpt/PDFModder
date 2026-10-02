"""Códigos simples del recurso PDF existente, comprobados sin exportar el sondeo.

Una aparición previa no es un catálogo completo: Encoding / ToUnicode pueden
declarar caracteres todavía no usados. Se consulta ese mapa y se exige un glifo
real en el mismo recurso. Nunca se toma un código de otra fuente por su nombre.
"""
from collections import defaultdict
from io import BytesIO
from hashlib import sha256

import pymupdf as fitz
from pypdf._cmap import get_encoding
from pypdf._codecs import charset_encoding
from pypdf.generic import ByteStringObject, FloatObject, NameObject


def verified_catalog(data, page_number, show, observed, needed):
    from .clipping import _advance, _serialize

    catalog = {char: set(codes) for char, codes in observed.items()}
    missing = set(needed) - catalog.keys()
    font = show['font']
    if not missing:
        return catalog
    if font.get('/Subtype') == '/Type0':
        return _verified_cid_catalog(data, page_number, show, catalog, missing)
    if font.get('/Subtype') not in ('/TrueType', '/Type1'):
        return catalog
    # pypdf's fallback "charmap" is not evidence of a PDF encoding. Accept
    # only a declared map, or a standard font with its published encoding.
    enc = font.get('/Encoding')
    if hasattr(enc, 'get_object'):
        enc = enc.get_object()
    explicit = bool(font.get('/ToUnicode'))
    if isinstance(enc, str):
        explicit |= enc in charset_encoding
    elif isinstance(enc, dict):
        explicit |= enc.get('/BaseEncoding') in charset_encoding or bool(enc.get('/Differences'))
    explicit |= str(font.get('/BaseFont', '')) in charset_encoding
    if not explicit:
        return catalog
    try:
        encoding, unicode_map = get_encoding(font)
    except Exception:
        return catalog
    candidates = defaultdict(set)
    for code in range(256):
        try:
            key = encoding.get(code) if isinstance(encoding, dict) else bytes([code]).decode(encoding)
            char = unicode_map.get(key, key)
            # Without Encoding, charmap entries not explicitly in ToUnicode
            # are defaults invented by the extractor, not font declarations.
            if enc is None and str(font.get('/BaseFont', '')) not in charset_encoding and key not in unicode_map:
                continue
            if char in missing and len(char) == 1 and _advance(font, code, char) > 0:
                candidates[char].add(code)
        except (ValueError, LookupError, TypeError):
            continue
    if not candidates:
        return catalog
    # One isolated SHOW per candidate makes missing .notdef glyphs and
    # extraction aliases observable. All font resources are original.
    entries = [(char, code) for char, codes in candidates.items() for code in sorted(codes)]
    ops = []
    for _, code in entries:
        ops.extend([([], b'BT'), ([NameObject(show['resource']), FloatObject(12)], b'Tf'),
                    ([FloatObject(v) for v in (1, 0, 0, 1, 40, 40)], b'Tm'),
                    ([ByteStringObject(bytes([code]))], b'Tj'), ([], b'ET')])
    with fitz.open(stream=data, filetype='pdf') as probe:
        stream = probe.get_new_xref()
        probe.update_object(stream, '<<>>')
        probe.update_stream(stream, _serialize(ops))
        probe[page_number].set_contents(stream)
        traces = [c for span in probe[page_number].get_texttrace() for c in span['chars']]
    if len(traces) != len(entries):
        return catalog
    for (char, code), trace in zip(entries, traces):
        if trace[0] == ord(char) and trace[1] != 0:
            catalog.setdefault(char, set()).add(code)
    return catalog


def _verified_cid_catalog(data, page_number, show, catalog, missing):
    """Only explicit two-byte Identity-H ToUnicode entries, never inferred CIDs."""
    from .clipping import _serialize
    from .richtext import _source_width
    font = show['font']
    if font.get('/Encoding') != '/Identity-H' or not font.get('/ToUnicode'):
        return catalog
    try:
        encoding, unicode_map = get_encoding(font)
        if encoding != 'utf-16-be' or unicode_map.get(-1) != 2:
            return catalog
        entries=[]
        for key, char in unicode_map.items():
            if (isinstance(key,str) and len(key)==1 and char in missing
                    and len(char)==1 and ord(key)>0 and _source_width(font,ord(key),char)>0):
                entries.append((char,ord(key)))
        if not entries:
            return catalog
        ops=[]
        for _,code in entries:
            ops.extend([([],b'BT'),([NameObject(show['resource']),FloatObject(12)],b'Tf'),
                        ([FloatObject(v) for v in (1,0,0,1,40,40)],b'Tm'),
                        ([ByteStringObject(code.to_bytes(2,'big'))],b'Tj'),([],b'ET')])
        with fitz.open(stream=data,filetype='pdf') as probe:
            stream=probe.get_new_xref();probe.update_object(stream,'<<>>')
            probe.update_stream(stream,_serialize(ops));probe[page_number].set_contents(stream)
            traces=[c for span in probe[page_number].get_texttrace() for c in span['chars']]
        if len(traces)==len(entries):
            for (char,code),trace in zip(entries,traces):
                if trace[0]==ord(char) and trace[1]!=0:
                    catalog.setdefault(char,set()).add(code)
    except Exception:
        # Failure to prove an extra glyph never changes the caller's catalog.
        return catalog
    return catalog


def _cff_identity(show):
    """Inspect existing CID CFF programs without modifying or embedding them."""
    from fontTools.cffLib import CFFFontSet
    from fontTools.cffLib.transforms import desubroutinize
    from .fonts import normalized_name
    font=show['font']
    if font.get('/Subtype')!='/Type0' or font.get('/Encoding')!='/Identity-H':
        return None
    descendant=font['/DescendantFonts'][0].get_object()
    if descendant.get('/Subtype')!='/CIDFontType0':
        return None
    descriptor=descendant['/FontDescriptor'].get_object()
    program=descriptor.get('/FontFile3')
    if program is None:
        return None
    program=program.get_object()
    if program.get('/Subtype')!='/CIDFontType0C':
        return None
    cff=CFFFontSet();cff.decompile(BytesIO(program.get_data()),None)
    if len(cff.fontNames)!=1:
        return None
    desubroutinize(cff)
    top=cff[cff.fontNames[0]]
    # Offsets, cardinality and width encodings naturally differ between subsets.
    structural={'charset','CharStrings','FDArray','FDSelect','CIDCount'}
    metadata={k:v for k,v in top.rawDict.items() if k not in structural}
    metadata['base_name']=normalized_name(str(font['/BaseFont']).lstrip('/'))
    if metadata['base_name']!=normalized_name(cff.fontNames[0]):
        return None
    programs={}
    for glyph in top.charset:
        if glyph=='.notdef':
            continue
        if not glyph.startswith('cid'):
            return None
        string,selector=top.CharStrings.getItemAndSelector(glyph)
        fd=top.FDArray[selector or 0]
        fd_metadata={k:v for k,v in fd.rawDict.items() if k!='Private'}
        if 'FontName' in fd_metadata:
            fd_metadata['FontName']=normalized_name(fd_metadata['FontName'])
        string.decompile();code=list(string.program)
        first=next((i for i,v in enumerate(code) if isinstance(v,str)),None)
        if first is None or not all(isinstance(v,(int,float)) for v in code[:first]):
            return None
        op=code[first]
        if op in ('hstem','vstem','hstemhm','vstemhm','hintmask','cntrmask'):
            width_arg=first%2==1
        elif op in ('hmoveto','vmoveto'):
            width_arg=first==2
        elif op=='rmoveto':
            width_arg=first==3
        elif op=='endchar':
            width_arg=first in (1,5)
        else:
            return None
        width=code.pop(0)+string.private.nominalWidthX if width_arg else string.private.defaultWidthX
        private={k:v for k,v in string.private.rawDict.items()
                 if k not in ('Subrs','defaultWidthX','nominalWidthX')}
        # Keep the decoded Type2 hint instructions and masks, not only outlines.
        visible=any(v in ('rmoveto','hmoveto','vmoveto') for v in code if isinstance(v,str))
        programs[int(glyph[3:])]=(width,private,code,visible,fd_metadata)
    return metadata,programs


def verified_cid_fallbacks(data, page_number, source, shows, operations, needed):
    """Complementary original CFF subsets with matched programs and hinting.

    A PostScript name alone never qualifies. Every common CID must have the
    same decoded Type2 program, width and private hint parameters; at least one
    common visible glyph and equal font-level metadata are required. An
    ambiguous differing candidate remains unavailable. No font is substituted
    by family name and none is re-embedded or modified.
    """
    from .richtext import _catalog, _source_width
    try:
        original=_cid_identity(source)
        if original is None:
            return {}
        metadata,programs=original
        accepted={};identities={};ambiguous=set();visited=set()
        for candidate in shows:
            resource=candidate['resource']
            if resource==source['resource'] or resource in visited:
                continue
            visited.add(resource)
            other=_cid_identity(candidate)
            if other is None or other[0]!=metadata:
                continue
            shared=programs.keys() & other[1].keys()
            if (not any(programs[cid][3] for cid in shared)
                    or any(programs[cid]!=other[1][cid] for cid in shared)):
                continue
            width_tolerance=.51 if metadata.get('kind')=='TrueType' else .001
            if any(abs(_source_width(source['font'],cid,'')-programs[cid][0])>width_tolerance or
                   abs(_source_width(candidate['font'],cid,'')-programs[cid][0])>width_tolerance for cid in shared):
                continue
            catalog=verified_catalog(data,page_number,candidate,
                                     _catalog(shows,operations,resource),needed)
            for char in needed:
                codes=catalog.get(char,set())
                if len(codes)!=1:
                    continue
                cid=next(iter(codes));identity=other[1].get(cid)
                if identity is None or not identity[3]:
                    continue
                if abs(_source_width(candidate['font'],cid,char)-identity[0])>width_tolerance:
                    continue
                if char in identities and identity!=identities[char]:
                    ambiguous.add(char)
                else:
                    identities[char]=identity;accepted.setdefault(char,resource)
        return {char:resource for char,resource in accepted.items() if char not in ambiguous}
    except Exception:
        return {}


def _tt_font(show):
    """Return only CIDToGID Identity TrueType programs; never guess a mapping."""
    from fontTools.ttLib import TTFont
    font=show['font']
    if font.get('/Subtype')!='/Type0' or font.get('/Encoding')!='/Identity-H':
        return None
    descendant=font['/DescendantFonts'][0].get_object()
    if descendant.get('/Subtype')!='/CIDFontType2' or descendant.get('/CIDToGIDMap')!='/Identity':
        return None
    descriptor=descendant['/FontDescriptor'].get_object()
    stream=descriptor.get('/FontFile2')
    if stream is None:
        return None
    font=TTFont(BytesIO(stream.get_object().get_data()),lazy=False)
    if not all(key in font for key in ('glyf','hmtx','head','name')) or 'fvar' in font:
        font.close();return None
    return font


def _tt_glyphs(font):
    """Exact glyph programs, local metrics and recursively verified components."""
    names=font.getGlyphOrder();cache={};busy=set()
    def proof(name):
        if name in cache:return cache[name]
        if name in busy:raise ValueError('Glifo compuesto cíclico.')
        busy.add(name);glyph=font['glyf'][name]
        children=tuple(proof(component.glyphName) for component in getattr(glyph,'components',()))
        result=(font['hmtx'].metrics[name],bytes(glyph.compile(font['glyf'])),children)
        busy.remove(name);cache[name]=result
        return result
    result={}
    for gid,name in enumerate(names):
        glyph=font['glyf'][name]
        if gid and glyph.numberOfContours:
            result[gid]=proof(name)
    return result


def _tt_identity(show):
    from .fonts import normalized_name
    font=_tt_font(show)
    if font is None:return None
    with font:
        base=normalized_name(str(show['font']['/BaseFont']).lstrip('/'))
        if normalized_name(font['name'].getDebugName(6) or '')!=base:return None
        metadata={'kind':'TrueType','base_name':base,'units':font['head'].unitsPerEm,
                  'revision':font['head'].fontRevision,'mac_style':font['head'].macStyle,
                  'lowest_ppem':font['head'].lowestRecPPEM,
                  'names':tuple(normalized_name(font['name'].getDebugName(i) or '') for i in (1,2,5)),
                  'global_hinting':tuple((tag,sha256(font.getTableData(tag)).hexdigest())
                                        for tag in ('fpgm','prep','cvt ','gasp') if tag in font)}
        for table,keys in [('OS/2',('fsType','usWeightClass','usWidthClass','fsSelection','sTypoAscender','sTypoDescender','sTypoLineGap')),
                           ('hhea',('ascent','descent','lineGap','caretSlopeRise','caretSlopeRun'))]:
            metadata[table]=tuple((key,getattr(font[table],key,None)) for key in keys) if table in font else None
        glyphs=_tt_glyphs(font)
        programs={gid:(value[0][0]*1000/font['head'].unitsPerEm,value,None,True) for gid,value in glyphs.items()}
        return metadata,programs


def _cid_identity(show):
    return _tt_identity(show) or _cff_identity(show)


def existing_tt_unicode(data, page_number, source, needed):
    """Resolve Unicode for glyphs already inside the selected TrueType subset.

    Reference fonts may have another version: only the character label is
    borrowed after an exact match of that glyph's program, component programs
    and hmtx metrics. The selected font program and global hinting remain
    untouched. This is evidence of a character mapping, not font identity.
    """
    from .fonts import normalized_name
    from pypdf import PdfReader
    target=_tt_font(source)
    if target is None:return {},{}
    with target:
        units=target['head'].unitsPerEm
        name=normalized_name(str(source['font']['/BaseFont']).lstrip('/'))
        if normalized_name(target['name'].getDebugName(6) or '')!=name:return {},{}
        proofs=_tt_glyphs(target)
    by_proof=defaultdict(set)
    for gid,proof in proofs.items():by_proof[proof].add(gid)
    found=defaultdict(set);evidence=defaultdict(list)
    reader=PdfReader(BytesIO(data));fonts=reader.pages[page_number]['/Resources']['/Font'].get_object()
    for resource,value in fonts.items():
        font=value.get_object()
        if normalized_name(str(font.get('/BaseFont','')).lstrip('/'))!=name or not font.get('/ToUnicode'):continue
        try:
            reference=_tt_font({'font':font})
        except Exception:
            # A broken unrelated resource cannot establish a mapping, and
            # should not hide evidence supplied by a different valid donor.
            continue
        if reference is None:continue
        with reference:
            if reference['head'].unitsPerEm!=units:continue
            if normalized_name(reference['name'].getDebugName(6) or '')!=name:continue
            try:
                encoding,cmap=get_encoding(font)
                reference_proofs=_tt_glyphs(reference)
            except Exception:
                continue
            if encoding!='utf-16-be' or cmap.get(-1)!=2:continue
            for key,char in cmap.items():
                if not isinstance(key,str) or len(key)!=1 or char not in needed:continue
                proof=reference_proofs.get(ord(key))
                if proof not in by_proof:continue
                for gid in by_proof[proof]:
                    found[char].add(gid)
                    evidence[char].append({'reference_resource':str(resource),'reference_cid':ord(key),'source_cid':gid,
                                          'glyph_program_sha256':sha256(proof[1]).hexdigest()})
    return {char:codes for char,codes in found.items() if len(codes)==1},dict(evidence)
