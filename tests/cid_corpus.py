"""Original synthetic CFF programs; no proprietary fonts or pytest dependency."""
from io import BytesIO
import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.cffLib import FDArrayIndex, FDSelect, FontDict
from fontTools.pens.t2CharStringPen import T2CharStringPen

def _program(chars, *, changed=False, hints=False, matrix=False):
    names=['.notdef']+[f'cid{ord(c):05d}' for c in chars]
    fb=FontBuilder(1000,isTTF=False)
    fb.setupGlyphOrder(names);fb.setupCharacterMap({ord(c):f'cid{ord(c):05d}' for c in chars})
    strings={}
    for name in names:
        pen=T2CharStringPen(500,None)
        if name!='.notdef':
            x=65 if changed and name=='cid00053' else 40
            pen.moveTo((x,0));pen.lineTo((430,0));pen.lineTo((230,450+int(name[3:])));pen.closePath()
        strings[name]=pen.getCharString()
    fb.setupCFF('ABCDEF+PDFModderFixture-Regular',dict(FullName='PDF Modder Fixture Regular',
        FamilyName='PDF Modder Fixture',Weight='Regular',FontBBox=[0,0,500,700]),strings,
        dict(defaultWidthX=500,nominalWidthX=0,StdHW=60 if hints else 50))
    top=fb.font['CFF '].cff.topDictIndex[0]
    fd=FontDict();fd.FontName='PDFModderFixture-Regular';fd.Private=top.Private
    if matrix:fd.FontMatrix=[.0011,0,0,.001,0,0]
    fdarray=FDArrayIndex();fdarray.append(fd)
    top.FDArray=fdarray;top.FDSelect=FDSelect(format=0);top.FDSelect.gidArray=[0]*len(names)
    top.ROS=('Adobe','Identity',0);top.CIDCount=max([ord(c) for c in chars])+1
    del top.Private
    top.CharStrings.fdArray=fdarray;top.CharStrings.fdSelect=top.FDSelect
    fb.font.recalcBBoxes=False
    output=BytesIO();fb.font['CFF '].cff.compile(output,fb.font)
    return output.getvalue()


def document(*, changed=False,hints=False,matrix=False,absent=False):
    with fitz.open() as doc:
        p=doc.new_page(width=400,height=250)
        p.insert_text((20,150),'VECINO INTACTO',fontsize=10)
        control=doc.new_page(width=400,height=250);control.insert_text((20,50),'CONTROL',fontsize=10)
        p=doc[0]
        resources_xref=int(doc.xref_get_key(p.xref,'Resources')[1].split()[0])
        doc.xref_set_key(p.xref,'Resources',doc.xref_object(resources_xref,compressed=False))
        old=p.get_contents()
        def add(content,stream=None):
            x=doc.get_new_xref();doc.update_object(x,content)
            if stream is not None:doc.update_stream(x,stream)
            return x
        for resource,chars,opts in [('A','025',{}),('B','56',dict(changed=changed,hints=hints,matrix=matrix))]:
            content=_program(chars if not (absent and resource=='B') else '5',**opts)
            prog=add('<< /Subtype /CIDFontType0C >>',content)
            fd=add(f'<< /Type /FontDescriptor /FontName /ABCDEF+PDFModderFixture-Regular /Flags 4 /FontBBox [0 0 500 700] /Ascent 700 /Descent -200 /CapHeight 700 /StemV 50 /ItalicAngle 0 /FontFile3 {prog} 0 R >>')
            descendant=add(f'<< /Type /Font /Subtype /CIDFontType0 /BaseFont /ABCDEF+PDFModderFixture-Regular /FontDescriptor {fd} 0 R /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /DW 500 >>')
            mapping='\n'.join(f'<{ord(c):04X}> <{ord(c):04X}>' for c in chars)
            cmap=add('<<>>',f'/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /Adobe-Identity-UCS def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange {len(chars)} beginbfchar {mapping} endbfchar endcmap CMapName currentdict /CMap defineresource pop end end'.encode())
            font=add(f'<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+PDFModderFixture-Regular /Encoding /Identity-H /DescendantFonts [{descendant} 0 R] /ToUnicode {cmap} 0 R >>')
            doc.xref_set_key(p.xref,'Resources/Font/'+resource,f'{font} 0 R')
        stream=add('<<>>',b'BT /A 12 Tf 1 0 0 1 40 210 Tm <0032003000320035> Tj ET BT /B 12 Tf 1 0 0 1 40 170 Tm <0035> Tj ET')
        doc.xref_set_key(p.xref,'Contents','['+' '.join(f'{x} 0 R' for x in [*old,stream])+']')
        return doc.tobytes(no_new_id=True)

