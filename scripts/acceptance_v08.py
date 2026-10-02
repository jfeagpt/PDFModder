"""Aceptación reproducible 0.8: OCR, coincidencias, imagen y páginas, con Poppler.

No lee archivos del usuario. Usa exclusivamente los dos ejemplos públicos 0.8.
Ejecutar: .venv/Scripts/python.exe scripts/acceptance_v08.py
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import pymupdf as fitz
from pypdf import PdfReader
from PIL import Image

from acceptance_report import find_poppler,render_poppler,compare_poppler,glyph_records
from pdfmodder import __version__
from pdfmodder.engine import extract_page,atomic_save,full_write
from pdfmodder.media import image_items,edit_image_pdf,export_image_pdf
from pdfmodder.model import EditRequest
from pdfmodder.pageops import organize_pages_pdf
from pdfmodder.search_replace import find_matches,replace_matches
from pdfmodder.textlayout import edit_with_layout


def model_for(data,page=0):
    with fitz.open(stream=data,filetype='pdf') as doc:
        return extract_page(doc,page,data)


def field(model,text,mode=0):
    candidates=[g for g in model.glyphs if g.mode==mode and g.opacity>0]
    joined=''.join(g.text for g in candidates)
    offset=joined.index(text)
    chosen=candidates[offset:offset+len(text)]
    assert ''.join(g.text for g in chosen)==text
    assert len({g.line for g in chosen})==1
    return chosen


def check_glyphs(expected,data,page=0):
    """Independently match every retained glyph, including inside image masks."""
    remaining=glyph_records(data,page)
    for glyph in expected:
        possibilities=[(index,r) for index,r in enumerate(remaining) if r['text']==glyph.text and
                       r['mode']==glyph.mode and r['font']==glyph.font and
                       abs(r['origin'][0]-glyph.origin[0])<.035 and abs(r['origin'][1]-glyph.origin[1])<.035]
        assert len(possibilities)==1, f'Un carácter ajeno se perdió o duplicó: {glyph.text!r}, {glyph.origin}'
        index,actual=possibilities[0]
        assert abs(actual['size']-glyph.size)<.001 and abs(actual['opacity']-glyph.opacity)<.001
        assert tuple(actual['color'])==glyph.color and tuple(actual['direction'])==glyph.direction
        remaining.pop(index)
    return len(expected)


def png_difference(tool,source,destination,output,rectangles):
    render_poppler(tool,source,output/'antes')
    render_poppler(tool,destination,output/'despues')
    pages=[]
    with fitz.open(source) as doc:
        for number,page in enumerate(doc):
            pages.append(compare_poppler(output/f'antes-{number+1}.png',output/f'despues-{number+1}.png',
                                         rectangles if number==0 else [],page.rotation_matrix))
    return pages


def execute(output,poppler):
    started=time.perf_counter()
    output.mkdir(parents=True,exist_ok=True)
    source=ROOT/'examples/herramientas-v08.pdf'
    searchable_source=ROOT/'examples/ocr-capa-buscable.pdf'
    originals={source.name:source.read_bytes(),searchable_source.name:searchable_source.read_bytes()}
    data=originals[source.name]
    original_model=model_for(data)
    original_second=model_for(data,1)
    old_date='Fecha: 10/09/2026'
    new_date='Fecha: 11/09/2026'
    selected=field(original_model,old_date)
    changed_ids={g.id for g,new in zip(selected,new_date) if g.text!=new}
    untouched_ids={g.id for g in original_model.glyphs}-changed_ids
    operations=[]
    excluded=[]

    data,date_report=edit_with_layout(data,EditRequest(0,[g.id for g in selected],text=new_date,
                                                      revision=original_model.revision,line_reflow=True,auto_width=True))
    assert date_report['verified'] and date_report['ocr_cleanup']['verified']
    assert date_report['ocr_cleanup']['removed_characters']==len(old_date)
    assert all(p['max_channel_delta']==0 for p in date_report['ocr_cleanup']['pages'])
    untouched_ids.difference_update(date_report['ocr_cleanup']['removed_ids'])
    excluded.extend(date_report['source_regions']+date_report['destination_regions'])
    operations.append({'name':'fecha_visible_con_ocr','report':date_report})

    matches=find_matches(data,'SOL',whole_word=True)
    assert len(matches)==3
    reviewed=[m for m in matches if m['page']==0]
    assert len(reviewed)==2 and len([m for m in matches if m['page']==1])==1
    original_matches=find_matches(originals[source.name],'SOL',whole_word=True,pages='1')
    untouched_ids.difference_update(i for match in original_matches for i in match['ids'])
    data,search_report=replace_matches(data,reviewed,'LUNA',auto_width=True)
    assert search_report['verified'] and search_report['match_count']==2
    for edit in search_report['edits']:
        excluded.extend(edit['source_regions']+edit['destination_regions'])
    operations.append({'name':'reemplazar_dos_coincidencias_de_tres','report':search_report})

    with fitz.open(stream=data,filetype='pdf') as doc:
        images=image_items(doc,0)
        control_images=image_items(doc,1)
        assert len(images)==2 and len(control_images)==1
        target=images[0]
        retained_box=tuple(images[1]['rect'])
    untouched_image=export_image_pdf(data,0,images[1]['id'])
    untouched_page_image=export_image_pdf(data,1,control_images[0]['id'])
    original_image=export_image_pdf(data,0,target['id'])
    (output/'imagen-original.png').write_bytes(original_image['image_bytes'])
    data,image_report=edit_image_pdf(data,0,target['id'],crop=(0,0,.75,1),rotation=90,
                                    revision=sha256(data).hexdigest())
    assert image_report['verified'] and image_report['instance_only'] and image_report['original_box_preserved']
    excluded.append(target['rect'])
    operations.append({'name':'recortar_y_girar_una_instancia','report':image_report})
    changed_asset=export_image_pdf(data,0,'0')
    assert (changed_asset['width_px'],changed_asset['height_px'])==(120,135)
    with Image.open(BytesIO(original_image['image_bytes'])) as original_bitmap:
        expected_pixels=original_bitmap.convert('RGBA').crop((0,0,135,120)).transpose(Image.Transpose.ROTATE_270)
    with Image.open(BytesIO(changed_asset['image_bytes'])) as changed_bitmap:
        assert expected_pixels.tobytes()==changed_bitmap.convert('RGBA').tobytes()
    (output/'imagen-recortada-girada.png').write_bytes(changed_asset['image_bytes'])
    assert export_image_pdf(data,0,'1')['image_bytes']==untouched_image['image_bytes']
    assert export_image_pdf(data,1,'0')['image_bytes']==untouched_page_image['image_bytes']
    with fitz.open(stream=data,filetype='pdf') as doc:
        actual_images=image_items(doc,0)
        assert tuple(actual_images[0]['rect'])==tuple(target['rect'])
        assert tuple(actual_images[1]['rect'])==retained_box

    final=output/'final.pdf'
    atomic_save(data,final,source)
    reopened=final.read_bytes()
    for number in (0,1):
        assert glyph_records(data,number)==glyph_records(reopened,number)
    retained=check_glyphs([g for g in original_model.glyphs if g.id in untouched_ids],reopened)
    retained_second=check_glyphs(original_second.glyphs,reopened,1)
    before_reader=PdfReader(BytesIO(originals[source.name]),strict=True)
    independent=PdfReader(BytesIO(reopened),strict=True)
    texts=[page.extract_text() for page in independent.pages]
    assert len(independent.pages)==2
    assert texts[0].count(new_date)==1 and old_date not in texts[0]
    assert texts[0].count('LUNA')==2 and 'SOL' not in texts[0]
    assert texts[1]==before_reader.pages[1].extract_text() and texts[1].count('SOL')==1
    (output/'texto-extraido-pypdf.txt').write_text('\n\n'.join(texts),encoding='utf-8')
    main_pixels=png_difference(poppler,source,final,output,excluded)

    # Organizing is audited separately, with an explicit page mapping and no
    # exclusions. The unedited second source page occurs twice, once rotated.
    plan=[{'source':'current','page':1,'rotation':0},
          {'source':'current','page':0,'rotation':0},
          {'source':'blank','width':300,'height':200,'rotation':0},
          {'source':'current','page':1,'rotation':90}]
    organized,page_report=organize_pages_pdf(reopened,plan)
    organized_path=output/'organizado.pdf'
    atomic_save(organized,organized_path,source)
    organized_reader=PdfReader(organized_path,strict=True)
    assert [p.extract_text() for p in organized_reader.pages]==[texts[1],texts[0],'',texts[1]]
    assert [p.rotation for p in organized_reader.pages]==[0,0,0,90]
    render_poppler(poppler,organized_path,output/'organizado')
    page_pixels=[compare_poppler(output/'despues-2.png',output/'organizado-1.png',[],fitz.Matrix(1,1)),
                 compare_poppler(output/'despues-1.png',output/'organizado-2.png',[],fitz.Matrix(1,1))]
    reference_rotation=output/'referencia-giro.pdf'
    with fitz.open(stream=reopened,filetype='pdf') as doc:
        doc[1].set_rotation(90)
        reference_rotation.write_bytes(full_write(doc))
    render_poppler(poppler,reference_rotation,output/'referencia-giro')
    page_pixels.append(compare_poppler(output/'referencia-giro-2.png',output/'organizado-4.png',[],fitz.Matrix(1,1)))
    with Image.open(output/'organizado-3.png') as blank:
        assert blank.size==(600,400) and blank.convert('RGB').getextrema()==((255,255),(255,255),(255,255))

    # OCR-only correction: the complete raster appearance must remain identical.
    ocr_data=originals[searchable_source.name]
    ocr_model=model_for(ocr_data)
    ocr_selected=field(ocr_model,old_date,mode=3)
    ocr_result,ocr_report=edit_with_layout(ocr_data,EditRequest(0,[g.id for g in ocr_selected],text=new_date,
                                                              ocr_mode='searchable',auto_width=True,revision=ocr_model.revision))
    assert ocr_report['appearance_unchanged'] and ocr_report['ocr_mode']=='searchable'
    ocr_path=output/'ocr-capa-buscable-editada.pdf'
    atomic_save(ocr_result,ocr_path,searchable_source)
    ocr_text=PdfReader(ocr_path,strict=True).pages[0].extract_text()
    assert new_date in ocr_text and old_date not in ocr_text
    ocr_output=output/'comparacion-ocr'
    ocr_output.mkdir(exist_ok=True)
    ocr_pixels=png_difference(poppler,searchable_source,ocr_path,ocr_output,[])
    assert all(p['max_channel_delta_outside_mask']==0 for p in ocr_pixels)
    assert source.read_bytes()==originals[source.name]
    assert searchable_source.read_bytes()==originals[searchable_source.name]
    version=subprocess.run([str(poppler),'-v'],capture_output=True,text=True,errors='replace').stderr.strip()
    return {'verified':True,'application_version':__version__,'source_unchanged':True,
            'scope':'Sólo corpus sintético público; no archivos del usuario.',
            'platform':platform.platform(),'python':platform.python_version(),'pymupdf':fitz.VersionBind,'poppler':version,
            'elapsed_seconds':round(time.perf_counter()-started,3),
            'source_sha256':{name:sha256(payload).hexdigest() for name,payload in originals.items()},
            'outputs':{'final':str(final),'organized':str(organized_path),'searchable_ocr':str(ocr_path)},
            'output_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in (final,organized_path,ocr_path)},
            'saved_preview_identical_characters':True,'unchanged_characters_checked':retained,
            'control_page_characters_checked':retained_second,'unselected_image_instances_unchanged':2,
            'operations':operations,'independent_text_checks_passed':True,'independent_text':texts,
            'poppler_pages':main_pixels,'organizer':{'engine':page_report,'poppler_pages':page_pixels,'blank_white_verified':True},
            'searchable_ocr':{'engine':ocr_report,'poppler_pages':ocr_pixels,'independent_text':ocr_text},
            'mask_policy':{'text':'Cajas individuales de los caracteres modificados, nunca líneas o bloques completos.',
                           'images':'Únicamente la caja de la instancia recortada y girada.',
                           'rectangles_pt':excluded,'margin_pt':.75,'tolerance_channel':8,
                           'control_and_ocr':'Página 2, organizador y OCR buscable: cero exclusiones y píxeles idénticos.'}}


def main():
    parser=argparse.ArgumentParser(description='Aceptación reproducible de las herramientas PDF Modder 0.8')
    parser.add_argument('--output',type=Path,default=ROOT/'output/acceptance-v08')
    parser.add_argument('--poppler')
    args=parser.parse_args()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    try:
        report=execute(output,find_poppler(args.poppler))
    except Exception as error:
        report={'verified':False,'application_version':__version__,'error':str(error),'traceback':traceback.format_exc()}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'verified':report['verified'],'report':str(output/'report.json'),
                      'elapsed_seconds':report.get('elapsed_seconds'),'error':report.get('error')},ensure_ascii=True))
    if not report['verified']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
