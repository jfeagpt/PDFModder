"""Aceptación 0.9: motor rico, PDF reabierto, pypdf y render independiente.

Por defecto prueba digital.pdf y la factura local aportada por el usuario. Los
PDF y renderizados privados se escriben únicamente bajo tmp/ (no distribuir).
Cada caso parte del original y conserva un informe separado, incluso si falla.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import fields
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import platform
import re
import sys
import subprocess
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import pymupdf as fitz
from pypdf import PdfReader

from acceptance_report import find_poppler, render_poppler, compare_poppler, glyph_records
from pdfmodder import __version__
from pdfmodder.engine import extract_page, atomic_save
from pdfmodder.richmodels import RichTextRequest


def source_fingerprint():
    digest=sha256()
    paths=[*ROOT.joinpath('pdfmodder').rglob('*.py'),ROOT/'run_pdfmodder.py']
    for path in sorted(paths,key=lambda p:p.relative_to(ROOT).as_posix()):
        digest.update(path.relative_to(ROOT).as_posix().encode('utf-8')+b'\0'+sha256(path.read_bytes()).digest()+b'\n')
    return digest.hexdigest()


def _model(data):
    with fitz.open(stream=data,filetype='pdf') as doc:
        return extract_page(doc,0,data)


def _selection(model,text,uppermost=False):
    glyphs=[g for g in model.glyphs if g.mode==0 and g.opacity>0]
    joined=''.join(g.text for g in glyphs)
    matches=[]
    offset=0
    while (index:=joined.find(text,offset))>=0:
        part=glyphs[index:index+len(text)]
        if ''.join(g.text for g in part)==text:
            matches.append(part)
        offset=index+len(text)
    if not matches:
        raise AssertionError(f'No se encuentra el texto de prueba {text!r}.')
    if len(matches)>1 and not uppermost:
        raise AssertionError(f'La selección de {text!r} es ambigua; especifica una ubicación.')
    return min(matches,key=lambda part:part[0].origin[1]) if uppermost else matches[0]


def _characters(runs):
    return [dict(run,text=char) for run in runs for char in run['text']]


def _request(data,selected):
    from pdfmodder.richtext import selection_payload
    payload=selection_payload(data,0,[g.id for g in selected])
    allowed={f.name for f in fields(RichTextRequest)}
    values={key:deepcopy(value) for key,value in payload.items() if key in allowed}
    values.update(auto_width=True,auto_height=True)
    return RichTextRequest(**values)


def _replace(request,text):
    chars=_characters(request.runs)
    request.runs=[dict(chars[min(i,len(chars)-1)],text=char) for i,char in enumerate(text)]
    return request


def _style(request):
    chars=_characters(request.runs)
    for item in chars[:2]:
        item.update(underline=True,char_spacing=.15,color=(.8,0.,0.))
    request.runs=chars
    return request


def _unchanged_glyphs(before,after,selected):
    selected_ids={g.id for g in selected}
    expected=[r for index,r in enumerate(glyph_records(before)) if index not in selected_ids]
    actual=glyph_records(after)
    for item in expected:
        index=next((i for i,candidate in enumerate(actual)
            if candidate['text']==item['text'] and candidate['font']==item['font']
            and candidate['mode']==item['mode'] and candidate['color']==item['color']
            and candidate['direction']==item['direction']
            and abs(candidate['size']-item['size'])<.002
            and abs(candidate['opacity']-item['opacity'])<.001
            and all(abs(a-b)<.035 for a,b in zip(candidate['origin'],item['origin']))),None)
        if index is None:
            raise AssertionError(f"Cambió un glifo ajeno a la selección en {item['origin']}.")
        actual.pop(index)
    return len(expected)


def _plain(text):
    return re.sub(r'\s+',' ',text).strip()


def _case(source,folder,poppler,name,recipe,independent_python=None):
    from pdfmodder.richtext import edit_rich_pdf
    started=time.perf_counter()
    folder.mkdir(parents=True,exist_ok=True)
    data=source.read_bytes();digest=sha256(data).hexdigest()
    report={'name':name,'verified':False,'source_sha256':digest,'phase':'prepare'}
    try:
        request,selected,expected=recipe(data)
        report['selected_characters']=len(selected)
        report['phase']='edit'
        output,engine=edit_rich_pdf(data,request)
        assert engine.get('verified'),'El motor no confirmó la transacción.'
        report['engine']=engine
        report['unchanged_glyphs_checked']=_unchanged_glyphs(data,output,selected)
        report['phase']='save_reopen'
        target=folder/'editado.pdf'
        atomic_save(output,target,source)
        saved=target.read_bytes()
        with fitz.open(stream=output,filetype='pdf') as preview,fitz.open(target) as reopened:
            assert len(preview)==len(reopened),'Número de páginas alterado al guardar.'
            for number in range(len(preview)):
                assert preview[number].get_pixmap().samples==reopened[number].get_pixmap().samples
                assert glyph_records(output,number)==glyph_records(saved,number)
        report['preview_matches_saved_pdf']=True
        report['phase']='independent_extractor'
        independent=PdfReader(BytesIO(saved),strict=True)
        before=PdfReader(BytesIO(data),strict=True)
        assert len(independent.pages)==len(before.pages)
        # pypdf's plain extractor inserts a heuristic space at some PDF style
        # boundaries. Cross-check its independent layout extractor without
        # deleting real spaces from either result or the expected content.
        extracted={mode:_plain(independent.pages[0].extract_text(extraction_mode=mode))
                   for mode in ('plain','layout')}
        if independent_python and any(not any(_plain(value) in text for text in extracted.values()) for value in expected):
            code=('import json,sys,pdfminer; from pdfminer.high_level import extract_text; '
                  'print(json.dumps({"version":pdfminer.__version__,"text":extract_text(sys.argv[1],page_numbers=[0])},ensure_ascii=True))')
            process=subprocess.run([str(independent_python),'-c',code,str(target)],capture_output=True,
                                   text=True,check=True,timeout=60)
            extra=json.loads(process.stdout)
            extracted['pdfminer.six']=_plain(extra['text'])
            report['additional_extractor']={'name':'pdfminer.six','version':extra['version'],
                'reason':'pypdf no reúne todos los fragmentos esperados al cambiar de recurso de fuente.'}
        matches=[]
        for value in expected:
            modes=[mode for mode,text in extracted.items() if _plain(value) in text]
            assert modes,f'Los extractores no encuentran el texto esperado {value!r}.'
            matches.append(dict(fragment=value,modes=modes))
        for number in range(1,len(before.pages)):
            assert before.pages[number].extract_text()==independent.pages[number].extract_text()
        report['independent_expected_fragments']=expected
        report['independent_matching_modes']=matches
        report['pypdf_control_pages_equal']=True
        report['phase']='independent_renderer'
        exclusions=engine.get('source_regions',[])+engine.get('destination_regions',[])
        # The engine also reports glyph-outline bounds (e.g. an Ñ accent
        # outside an inaccurate font metric box), independently of any pixel
        # difference. Retain the narrow per-glyph mask and fixed .75pt margin.
        if engine.get('pages'):
            exclusions+=engine['pages'][0].get('ink_exclusion_regions',[])
            exclusions+=engine['pages'][0].get('verified_ink_regions',[])
        assert exclusions,'Faltan regiones de glifos para el contraste visual independiente.'
        render_poppler(poppler,source,folder/'antes')
        render_poppler(poppler,target,folder/'despues')
        comparisons=[]
        with fitz.open(source) as original:
            digits=len(str(len(original)))
            for number,page in enumerate(original):
                comparisons.append(compare_poppler(folder/f'antes-{number+1:0{digits}d}.png',folder/f'despues-{number+1:0{digits}d}.png',
                                                    exclusions if number==0 else [],page.rotation_matrix))
        report.update(verified=True,phase='complete',poppler_pages=comparisons,
                      output=str(target),output_sha256=sha256(saved).hexdigest())
    except Exception as error:
        report.update(error=str(error),traceback=traceback.format_exc())
    finally:
        report['source_unchanged']=sha256(source.read_bytes()).hexdigest()==digest
        if not report['source_unchanged']:
            report.update(verified=False,error='Se alteró el archivo original.')
        report['elapsed_seconds']=round(time.perf_counter()-started,3)
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def text_case(original,replacement=None,*,uppermost=False,style=False):
    def recipe(data):
        selected=_selection(_model(data),original,uppermost)
        request=_request(data,selected)
        if replacement is not None:_replace(request,replacement)
        if style:_style(request)
        return request,selected,[(replacement or original)]
    return recipe


def new_paragraph_case(data):
    font=ROOT/'assets/fonts/LiberationSans-Regular.ttf'
    request=RichTextRequest(page=0,ids=[],rect=(48,670,430,765),auto_width=False,auto_height=False,
        runs=[dict(text='Primera línea\u2028Salto suave\nNuevo párrafo\tImporte',font_name='LiberationSans',
                   font_file=str(font),size=11.25,color=(0.,0.,0.),opacity=1.,char_spacing=.1,underline=False)],
        paragraphs=[dict(index=0,line_spacing=18.,left_indent=6.,space_before=2.,space_after=6.),
                    dict(index=1,line_spacing=18.,left_indent=6.,first_indent=10.,space_before=3.,
                         space_after=4.,tab_stops=[120.],tab_interval=36.)],
        revision=sha256(data).hexdigest())
    return request,[],['Primera línea','Salto suave','Nuevo párrafo','Importe']


def execute(output,poppler,invoice=None,only=None):
    output.mkdir(parents=True,exist_ok=True)
    cases=[('digital_fecha',ROOT/'examples/digital.pdf',text_case('10/09/2026','11/09/2026')),
           ('digital_fragmento',ROOT/'examples/digital.pdf',text_case('10/09/2026','11/09/2026',style=True)),
           ('digital_parrafos',ROOT/'examples/digital.pdf',new_paragraph_case)]
    if invoice is not None:
        cases += [('factura_espana',invoice,text_case('ESPAÑA','ESPAÑA PRUEBA',uppermost=True)),
                  ('factura_fecha',invoice,text_case('30/10/2025','31/10/2025')),
                  ('factura_nueva_linea',invoice,text_case('ESPAÑA','ESPAÑA\nPRUEBA',uppermost=True)),
                  ('factura_fragmento',invoice,text_case('ESPAÑA',uppermost=True,style=True)),
                  ('factura_concepto',invoice,text_case('SANDIA MINI BLANCA ','SANDIA MINI BLANCA ECO'))]
    results=[]
    for name,source,recipe in cases:
        if only and name not in only:continue
        try:
            result=_case(source,output/name,poppler,name,recipe)
        except Exception as error:
            result={'name':name,'verified':False,'phase':'setup','error':str(error),'traceback':traceback.format_exc()}
            folder=output/name;folder.mkdir(parents=True,exist_ok=True)
            (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        results.append(result)
        print(json.dumps({key:result.get(key) for key in ('name','verified','phase','error','elapsed_seconds')},ensure_ascii=True),flush=True)
    return {'verified':bool(results) and all(r['verified'] for r in results),'application_version':__version__,
            'app_source_sha256':source_fingerprint(),
            'platform':platform.platform(),'pymupdf':fitz.VersionBind,'cases':results,
            'private_invoice_used':invoice is not None,
            'privacy':'Los documentos y capturas de la factura son privados y no deben distribuirse.',
            'mask_policy':{'rectangles':'Glifos de origen/destino y contornos de tinta verificables informados por cada transacción.',
                           'margin_pt':.75,'dpi':144,'channel_tolerance':8,
                           'control_pages':'Cero exclusiones; identidad exacta de píxeles.'}}


def main():
    parser=argparse.ArgumentParser(description='Aceptación rica 0.9 con corpus público y factura privada local')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/acceptance-v09-private')
    parser.add_argument('--poppler')
    parser.add_argument('--invoice',type=Path,default=Path.home()/'OneDrive - S.A.T. AGROLEVANTE/Escritorio/FACTURA F25-1 BARTOLOME PARRA ZURANO_SANDIA.pdf')
    parser.add_argument('--skip-private',action='store_true')
    parser.add_argument('--only',nargs='+')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    try:
        report=execute(output,find_poppler(args.poppler),None if args.skip_private else args.invoice,args.only)
    except Exception as error:
        report={'verified':False,'error':str(error),'traceback':traceback.format_exc()}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'verified':report['verified'],'report':str(output/'report.json')},ensure_ascii=True))
    return 0 if report['verified'] else 1


if __name__=='__main__':
    raise SystemExit(main())
