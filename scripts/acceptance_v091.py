"""Aceptación con PDFs privados aportados, sin copiarlos al corpus distribuido.

Uso: python scripts/acceptance_v091.py --anexo RUTA --mapa RUTA
Los resultados se guardan en tmp/compat-v091-private/acceptance.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pymupdf as fitz
from pypdf import PdfReader
from acceptance_v09 import _case, text_case, source_fingerprint
from acceptance_report import find_poppler, render_poppler, compare_poppler
from pdfmodder import __version__
from pdfmodder.engine import atomic_save
from pdfmodder.pageops import delete_pages_pdf,extract_pages_pdf,organize_pages_pdf
from pdfmodder.tagged import analyze


def pages_case(source,folder,poppler,name,assignment,operation):
    folder.mkdir(parents=True,exist_ok=True)
    data=source.read_bytes();digest=sha256(data).hexdigest()
    result=dict(name=name,verified=False,source_sha256=digest)
    try:
        output,report=operation(data)
        target=folder/'editado.pdf';atomic_save(output,target,source)
        assert target.read_bytes()==output
        before,after=PdfReader(BytesIO(data)),PdfReader(BytesIO(output))
        assert len(after.pages)==len(assignment)
        structure=analyze(output)
        assert structure is not None and report['tagged_structure']['verified']
        assert [p.extract_text() for p in after.pages]==[before.pages[n].extract_text() for n in assignment]
        render_poppler(poppler,source,folder/'antes');render_poppler(poppler,target,folder/'despues')
        comparisons=[]
        with fitz.open(source) as original:
            for new,old in enumerate(assignment):
                comparisons.append(compare_poppler(
                    folder/f'antes-{old+1:0{len(str(len(before.pages)))}d}.png',
                    folder/f'despues-{new+1:0{len(str(len(after.pages)))}d}.png',[],original[old].rotation_matrix))
        result.update(verified=True,engine=report,poppler_pages=comparisons,page_map=assignment,
                      output=str(target),output_sha256=sha256(output).hexdigest(),
                      accessible_nodes=len(structure.nodes),pypdf_pages_equal=True)
    except Exception as error:
        result.update(error=str(error),traceback=traceback.format_exc())
    result['source_unchanged']=sha256(source.read_bytes()).hexdigest()==digest
    result['verified'] &= result['source_unchanged']
    (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anexo',required=True,type=Path)
    parser.add_argument('--mapa',required=True,type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/compat-v091-private/acceptance')
    parser.add_argument('--only',nargs='+')
    parser.add_argument('--independent-python',type=Path,help='Python con pdfminer.six para contrastar fragmentos que pypdf separa heurísticamente.')
    args=parser.parse_args();poppler=find_poppler(None)
    args.output.mkdir(parents=True,exist_ok=True)
    cases=[]
    for name,source,old,new in [('anexo_direccion',args.anexo,'domicilio','dirección'),
                              ('anexo_titular',args.anexo,'responsable','titular'),
                              ('mapa_2026',args.mapa,'2025','2026')]:
        if args.only and name not in args.only:continue
        result=_case(source,args.output/name,poppler,name,text_case(old,new,uppermost=True),args.independent_python)
        cases.append(result);print(json.dumps({k:result.get(k) for k in ('name','verified','error')},ensure_ascii=True),flush=True)
    operations=[('anexo_eliminar_p2',[0,2],lambda d:delete_pages_pdf(d,[1])),
                ('anexo_extraer_p2',[1],lambda d:extract_pages_pdf(d,[1])),
                ('anexo_reordenar',[2,0,1],lambda d:organize_pages_pdf(d,[dict(source='current',page=n) for n in [2,0,1]]))]
    for name,assignment,operation in operations:
        if args.only and name not in args.only:continue
        result=pages_case(args.anexo,args.output/name,poppler,name,assignment,operation)
        cases.append(result);print(json.dumps({k:result.get(k) for k in ('name','verified','error')},ensure_ascii=True),flush=True)
    report=dict(verified=bool(cases) and all(c['verified'] for c in cases),application_version=__version__,cases=cases,
                app_source_sha256=source_fingerprint(),
                privacy='Documentos privados, no distribuir junto a la aplicación.',
                mask_policy=dict(dpi=144,margin_pt=.75,channel_tolerance=8,
                                 text='Sólo glifos de origen y destino; vecinos comprobados por contenido.',
                                 pages='Páginas copiadas y páginas no editadas: cero exclusiones y cero diferencias.'))
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['verified'] else 1


if __name__=='__main__':raise SystemExit(main())
