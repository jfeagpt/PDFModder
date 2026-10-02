"""Original geometric glyphs for a reproducible CID TrueType corpus (CC0)."""
from io import BytesIO
import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


def program(*,missing='',changed='',revision=1.):
    chars=',0123456789';names=['.notdef']+[f'uni{ord(c):04X}' for c in chars]
    fb=FontBuilder(1000,isTTF=True);fb.setupGlyphOrder(names)
    fb.setupCharacterMap({ord(c):names[i+1] for i,c in enumerate(chars)})
    glyphs={}
    for i,name in enumerate(names):
        pen=TTGlyphPen(None);char=chars[i-1] if i else ''
        if i and char not in missing:
            x=75 if char in changed else 45
            pen.moveTo((x,0));pen.lineTo((440,0));pen.lineTo((220,450+i*11));pen.closePath()
        glyphs[name]=pen.glyph()
    fb.setupGlyf(glyphs);fb.setupHorizontalMetrics({name:(500,45) for name in names})
    fb.setupHorizontalHeader(ascent=800,descent=-200)
    fb.setupNameTable(dict(familyName='PDF Modder CID Fixture',styleName='Regular',
        uniqueFontIdentifier='PDFModder-CID-Test',fullName='PDFModderCIDFixture-Regular',
        psName='PDFModderCIDFixture-Regular',version=f'Version {revision}',licenseDescription='CC0 original test glyphs'))
    fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200,fsType=0)
    fb.setupPost();fb.setupMaxp();fb.font['head'].fontRevision=revision
    del fb.font['cmap'];out=BytesIO();fb.font.save(out)
    return out.getvalue(),{c:i+1 for i,c in enumerate(chars)}


def document(*,missing='',changed='',same_revision=False,indirect_map=False,ambiguous=False):
    """68,48→70,48: target contains the shapes, source ToUnicode omits 0/7.

    The reference has another version, so it can supply Unicode evidence but
    cannot be used as an automatic replacement of the target font.
    """
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=250)
        page.insert_text((30,125),'VECINO INTACTO',fontsize=10)
        other=doc.new_page(width=400,height=250);other.insert_text((30,50),'CONTROL',fontsize=10)
        page=doc[0];old=page.get_contents()
        def add(text,stream=None):
            x=doc.get_new_xref();doc.update_object(x,text)
            if stream is not None:doc.update_stream(x,stream)
            return x
        for name,chars,kwargs in [('A',',468',dict(missing=missing)),('B',',04678',dict(changed=changed,revision=1. if same_revision else 2.))]:
            font_bytes,codes=program(**kwargs);fontfile=add('<<>>',font_bytes)
            base=('ABCDEF+' if name=='A' else 'GHIJKL+')+'PDFModderCIDFixture-Regular'
            descriptor=add(f'<< /Type /FontDescriptor /FontName /{base} /Flags 4 /FontBBox [0 -200 500 800] /Ascent 800 /Descent -200 /CapHeight 700 /StemV 50 /ItalicAngle 0 /FontFile2 {fontfile} 0 R >>')
            mapping='/Identity'
            if indirect_map:
                m=add('<<>>',b''.join(i.to_bytes(2,'big') for i in range(12)));mapping=f'{m} 0 R'
            descendant=add(f'<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{base} /FontDescriptor {descriptor} 0 R /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /CIDToGIDMap {mapping} /DW 500 >>')
            pairs=[(codes[c],c) for c in chars]
            if ambiguous and name=='B':pairs=[(codes[c],'7' if c=='0' else c) for c in chars]
            rows='\n'.join(f'<{code:04X}> <{ord(c):04X}>' for code,c in pairs)
            cmap=add('<<>>',f'/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /ExistingCID def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange {len(pairs)} beginbfchar {rows} endbfchar endcmap CMapName currentdict /CMap defineresource pop end end'.encode())
            font=add(f'<< /Type /Font /Subtype /Type0 /BaseFont /{base} /Encoding /Identity-H /DescendantFonts [{descendant} 0 R] /ToUnicode {cmap} 0 R >>')
            resources=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
            doc.xref_set_key(resources,'Font/'+name,f'{font} 0 R')
        encoded=lambda text:''.join(f'{codes[c]:04X}' for c in text)
        stream=add('<<>>',f'q BT /A 12 Tf 1 0 0 1 40 210 Tm <{encoded("68,48")}> Tj ET Q q BT /B 12 Tf 1 0 0 1 40 170 Tm <{encoded("4")}> Tj ET Q 0.3 0.5 0.7 RG 30 195 80 28 re S'.encode())
        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in [*old,stream])+']')
        return doc.tobytes()
