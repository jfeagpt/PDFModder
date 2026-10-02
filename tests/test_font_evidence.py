"""Font identity evidence from original synthetic fonts, never a private PDF.

The simple generated outlines and name tables in this file are dedicated to
the public domain (CC0). No installed or user-provided fonts are copied here.
"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
import pymupdf
import pytest

from pdfmodder.fonts import FontResolver


def synthetic_font(*, name="Evidence-Regular", version="Version 1.0", height=650, text=" AB012/", symbol=False, stripped=False):
    points=sorted({ord(char) for char in text})
    names=[".notdef"]+[f"uni{cp:04X}" for cp in points]
    builder=FontBuilder(1000,isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({cp:f"uni{cp:04X}" for cp in points})
    glyphs={}
    for name_ in names:
        pen=TTGlyphPen(None)
        if name_!="uni0020":
            pen.moveTo((50,0))
            pen.lineTo((500,0))
            pen.lineTo((500,height))
            pen.lineTo((50,height))
            pen.closePath()
        glyphs[name_]=pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name_:(600,50) for name_ in names})
    builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupNameTable({"familyName":"Evidence family","styleName":"Regular",
                           "fullName":name,"psName":name,"version":version,
                           "uniqueFontIdentifier":name+version,
                           "licenseDescription":"Original test font; CC0 public domain."})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200,fsType=8)
    builder.setupPost()
    builder.setupMaxp()
    builder.font["head"].created=builder.font["head"].modified=2082844800
    if symbol:
        table=CmapSubtable.newSubtable(4)
        table.platformID,table.platEncID,table.language=3,0,0
        table.cmap={0xF000+cp:f"uni{cp:04X}" for cp in points}
        builder.font["cmap"].tables=[table]
    if stripped:
        for table in ("name","OS/2","cmap"):
            del builder.font[table]
    output=BytesIO()
    builder.save(output)
    return output.getvalue()


class FontDocument:
    """Controlled PDF resources, backed by actual font programs for MuPDF."""
    def __init__(self,*items):
        self.items=items

    def get_page_fonts(self,page_number,full=True):
        assert page_number==0 and full
        return [(xref,"ttf" if data else "n/a","TrueType" if data else "Type1",name,resource,"WinAnsiEncoding",0)
                for xref,name,resource,data in self.items]

    def extract_font(self,xref):
        _,name,_,data=next(item for item in self.items if item[0]==xref)
        return name,"ttf" if data else "n/a","TrueType" if data else "Type1",data


@pytest.fixture
def resolver():
    # This test fixture only reads the path; neither inspect method writes it.
    return FontResolver(Path(__file__).with_name("unused-font-evidence-mapping.json"),installed_dirs=[])


def test_embedded_program_evidence_separates_pdf_name_and_internal_name(resolver):
    data=synthetic_font()
    with pymupdf.open() as doc:
        page=doc.new_page()
        page.insert_font(fontname="Factual",fontbuffer=data)
        page.insert_text((60,80),"AB012/",fontname="Factual",fontsize=12)
        info=resolver.inspect(doc,0,text="AB012/")[0]
    assert info["declared_name"]==info["name"]
    assert info["font_program"]["postscript_name"]=="Evidence-Regular"
    assert info["font_program"]["sha256"]==sha256(data).hexdigest()
    assert info["font_program"]["byte_length"]==len(data)
    assert info["font_program"]["version"]=="Version 1.0"
    assert info["font_program"]["fs_type"]==8
    assert info["font_program"]["unicode_cmap"] is True
    assert info["font_program"]["glyph_count"]==8
    assert info["identity_evidence"]["kind"]=="embedded_program"
    assert info["identity_evidence"]["program_identified"]
    assert info["identity_evidence"]["requires_reproduction_validation"]
    assert not info["identity_verified"]  # No universal typography guarantee.
    assert info["coverage"]["addressable"] is True
    assert not info["local_candidates_checked"]


def test_page_inventory_does_not_scan_local_candidate_evidence(resolver,monkeypatch):
    def unexpected(*args):
        raise AssertionError("A page render must not collect local candidates")
    monkeypatch.setattr(resolver,"_local_evidence",unexpected)
    info=resolver.inspect(FontDocument((5,"Evidence-Regular","F1",synthetic_font())),0)[0]
    assert info["local_candidates"]==[]
    assert info["local_candidates_checked"] is False
    assert info["coverage"]["checked"] is False
    assert info["coverage"]["addressable"] is None


def test_equal_declared_names_are_ambiguous_until_actual_resource_is_supplied(resolver):
    first=synthetic_font(height=650)
    second=synthetic_font(height=710)
    doc=FontDocument((5,"ABCDEF+Evidence","R7",first),(7,"GHIJKL+Evidence","R17",second))
    ambiguous=resolver.inspect_selection(doc,0,"Evidence","AB")
    assert ambiguous["certainty"]=="ambiguous_resource"
    assert ambiguous["resource_match"]=="ambiguous_name"
    assert ambiguous["candidate_count"]==2
    assert {item["font_program"]["sha256"] for item in ambiguous["candidates"]}=={sha256(first).hexdigest(),sha256(second).hexdigest()}
    exact=resolver.inspect_selection(doc,0,"Evidence","AB",font_xref=5,resource="/R7")
    assert exact["resource_match"]=="explicit_resource"
    assert exact["certainty"]=="embedded_program"
    assert exact["candidate_count"]==1
    assert exact["candidates"][0]["font_program"]["sha256"]==sha256(first).hexdigest()
    wrong=resolver.inspect_selection(doc,0,"Evidence","AB",font_xref=5,resource="R17")
    assert wrong["resource_match"]=="not_found" and wrong["candidates"]==[]


def test_symbol_subset_identification_does_not_claim_unicode_reusability(resolver):
    data=synthetic_font(text=" 012/",symbol=True)
    info=resolver.inspect_selection(FontDocument((5,"ABCDEF+Evidence-Regular","R7",data)),0,"Evidence-Regular","01/02",font_xref=5)["candidates"][0]
    assert info["identity_evidence"]["program_identified"]
    assert info["font_program"]["unicode_cmap"] is False
    assert info["font_program"]["glyph_count"]==6
    assert info["font_program"]["available_count"] is None
    assert info["coverage"]["addressable"] is False
    assert info["coverage"]["status"]=="encoding_not_reusable"
    assert 0x30 in info["coverage"]["missing_codepoints"]
    assert info["resolved_source"] is None


def test_stripped_program_has_fingerprint_without_inventing_family_version_or_permissions(resolver):
    data=synthetic_font(stripped=True)
    info=resolver.inspect(FontDocument((5,"ABCDEF+Evidence-Bold","R1",data)),0)[0]
    program=info["font_program"]
    assert program["sha256"]==sha256(data).hexdigest()
    assert program["family"] is program["version"] is program["fs_type"] is None
    assert program["postscript_name"] is None
    assert program["variant_source"]=="nombre declarado en el PDF"
    assert program["cmap_tables"]==[] and program["unicode_cmap"] is False
    assert info["identity_evidence"]["program_identified"]
    assert info["resolved_source"] is None


def test_base14_nominal_and_missing_character_are_not_font_identity_proofs(resolver):
    standard=resolver.inspect_selection(FontDocument((5,"Helvetica","F1",b"")),0,"Helvetica","niño €")["candidates"][0]
    assert standard["font_program"] is None
    assert standard["identity_evidence"]["kind"]=="base14_nominal"
    assert not standard["identity_evidence"]["program_identified"]
    assert standard["coverage"]["addressable"] is True
    partial=resolver.inspect(FontDocument((5,"Evidence-Regular","F1",synthetic_font(text=" AB"))),0,text="A€")[0]
    assert partial["coverage"]["status"]=="missing_characters"
    assert partial["coverage"]["missing_codepoints"]==[0x20AC]
    assert partial["resolved_source"] is None


@pytest.mark.parametrize("same_bytes,version",[(True,"Version 1.0"),(False,"Version 1.0"),(False,"Version 2.0")])
def test_local_postscript_candidate_distinguishes_binary_identity_and_name_version_match(tmp_path,same_bytes,version):
    original=synthetic_font()
    local=original if same_bytes else synthetic_font(height=710,version=version)
    (tmp_path/"exact.ttf").write_bytes(local)
    # Same family, different PS name: this is never an identity candidate.
    (tmp_path/"similar.ttf").write_bytes(synthetic_font(name="Other-Regular"))
    resolver=FontResolver(tmp_path/"mapping.json",installed_dirs=[tmp_path])
    doc=FontDocument((5,"ABCDEF+PDFDeclaredAlias","R7",original))
    info=resolver.inspect_selection(doc,0,"PDFDeclaredAlias","AB",font_xref=5)["candidates"][0]
    assert info["declared_name"]=="ABCDEF+PDFDeclaredAlias"
    assert info["font_program"]["postscript_name"]=="Evidence-Regular"
    assert len(info["local_candidates"])==1
    candidate=info["local_candidates"][0]
    assert candidate["match_basis"]=="program_postscript_name"
    assert candidate["postscript_match"] and candidate["variant_match"]
    assert candidate["version_match"]==(version=="Version 1.0")
    assert candidate["program_bytes_match"] is same_bytes
    assert candidate["identity_verified"] is same_bytes
    assert not candidate["automatic_substitution"]
    assert candidate["coverage"]["addressable"]
    # Evidence gathering does not change the actual resolver's resource order.
    assert resolver.resolve(doc,0,"R7","AB").buffer==original
    assert not (tmp_path/"mapping.json").exists()


def test_local_evidence_cache_refreshes_after_font_file_changes(tmp_path,monkeypatch):
    path=tmp_path/"exact.ttf"
    original=synthetic_font()
    path.write_bytes(original)
    resolver=FontResolver(tmp_path/"mapping.json",installed_dirs=[tmp_path])
    doc=FontDocument((5,"Evidence-Regular","F1",original))
    before=resolver.inspect_selection(doc,0,"Evidence-Regular","AB")["candidates"][0]["local_candidates"][0]
    original_stat=path.stat()
    stat_method=Path.stat
    path.write_bytes(synthetic_font(version="Version 2.1",height=730))
    # Model a replacement with unchanged file timestamps/size deterministically.
    monkeypatch.setattr(Path,'stat',lambda self,*args,**kwargs:original_stat if self==path else stat_method(self,*args,**kwargs))
    after=resolver.inspect_selection(doc,0,"Evidence-Regular","AB")["candidates"][0]["local_candidates"][0]
    assert before["program_bytes_match"] is True
    assert after["program_bytes_match"] is False
    assert after["font_program"]["version"]=="Version 2.1"
    assert after["version_match"] is False
