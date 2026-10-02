"""Primer hito ejecutable: reemplazo, movimiento, guardado, reapertura."""
from pathlib import Path
import io
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf as fitz
from pypdf import PdfReader
from pdfmodder.engine import edit_pdf,extract_page,atomic_save
from pdfmodder.model import EditRequest

def main():
    target=Path(__file__).resolve().parents[1]/'output'/'vertical'
    target.mkdir(parents=True,exist_ok=True)
    doc=fitz.open()
    page=doc.new_page()
    page.draw_rect((40,60,350,200),color=(.2,.4,.3),fill=(.85,.94,.87))
    page.draw_line((40,120),(350,120),color=(.2,.3,.4),width=.75)
    page.insert_text((60,100),'10/09/2026',fontsize=11.25,fontname='helv')
    page.insert_text((60,145),'Linea para mover',fontsize=11.25,fontname='helv')
    page.insert_text((260,100),'Vecino',fontsize=11.25,fontname='helv')
    page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(60,240,140,260),'uri':'https://example.org/'})
    doc.new_page().insert_text((60,80),'Pagina intacta')
    doc.set_toc([[1,'Primera',1],[1,'Segunda',2]])
    source=doc.tobytes(garbage=4,deflate=True)
    (target/'original.pdf').write_bytes(source)
    with fitz.open(stream=source,filetype='pdf') as check:
        model=extract_page(check,0)
    date=[g.id for g in model.glyphs if abs(g.origin[1]-100)<.1 and g.origin[0]<200]
    edited,r1=edit_pdf(source,EditRequest(0,date,text='11/09/2026'))
    with fitz.open(stream=edited,filetype='pdf') as check:
        model=extract_page(check,0)
    line=[g.id for g in model.glyphs if abs(g.origin[1]-145)<.1]
    moved,r2=edit_pdf(edited,EditRequest(0,line,dx=25,dy=30))
    atomic_save(moved,target/'modificado.pdf',target/'original.pdf')
    independent=PdfReader(target/'modificado.pdf')
    extracted=independent.pages[0].extract_text()
    assert '11/09/2026' in extracted and '10/09/2026' not in extracted
    assert extracted.count('Linea para mover')==1
    for name in ['original','modificado']:
        with fitz.open(target/f'{name}.pdf') as check:
            check[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(target/f'{name}.png')
            if name=='modificado':
                assert abs(check[0].search_for('Linea para mover')[0].x0-85)<.05
    report={'replacement':r1,'movement':r2,'independent_text':extracted,'verified':True}
    (target/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
    print(json.dumps({'verified':True,'replacement_seconds':r1['elapsed_seconds'],
                      'move_seconds':r2['elapsed_seconds'],'folder':str(target)},ensure_ascii=False))

if __name__=='__main__':
    main()
