"""Corpus sintético 0.8; no utiliza OCR ni archivos del usuario."""
from pathlib import Path
from io import BytesIO
import pymupdf as fitz
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]


def generate(output=None):
    output=Path(output or ROOT/'examples');output.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGB',(180,120),'#d9eef1');draw=ImageDraw.Draw(im)
    draw.rectangle((0,0,89,119),fill='#ce5946');draw.ellipse((105,20,165,80),fill='#387552')
    buf=BytesIO();im.save(buf,'PNG');image=buf.getvalue()
    with fitz.open() as doc:
        p=doc.new_page(width=595,height=842)
        p.insert_text((40,45),'PDF Modder 0.8 - herramientas de prueba',fontsize=18)
        p.insert_text((40,85),'Fecha: 10/09/2026',fontsize=12)
        p.insert_text((40,85),'Fecha: 10/09/2026',fontsize=12,render_mode=3)
        p.insert_text((40,110),'La fecha tiene texto visible y una copia OCR invisible.',fontsize=10)
        p.draw_rect((35,135,550,225),color=(.2,.4,.3),fill=(.92,.96,.9))
        p.insert_text((45,160),'Este parrafo se puede redistribuir.',fontsize=12)
        p.insert_text((40,255),'SOL',fontsize=12)
        p.insert_text((180,255),'SOL',fontsize=12)
        xref=p.insert_image((40,310,220,430),stream=image)
        p.insert_image((320,310,500,430),xref=xref)
        p.insert_text((40,455),'Dos instancias de la misma imagen: modifica solo una.',fontsize=10)
        p.insert_text((40,500),'Vecino que debe conservarse.',fontsize=12)
        p=doc.new_page(width=595,height=842)
        p.insert_text((40,45),'Pagina de control para organizar, duplicar y girar.',fontsize=15)
        p.insert_text((40,100),'SOL',fontsize=12)
        p.insert_image((60,160,240,280),xref=xref)
        doc.save(output/'herramientas-v08.pdf',garbage=4,deflate=True)
    with fitz.open() as appearance:
        p=appearance.new_page(width=400,height=200)
        p.draw_rect((15,15,385,180),fill=(.95,.95,.90),color=(.3,.4,.3))
        p.insert_text((30,70),'Fecha: 10/09/2026',fontsize=18)
        p.insert_text((30,110),'Documento escaneado de prueba',fontsize=14)
        png=p.get_pixmap(matrix=fitz.Matrix(2,2)).tobytes('png')
    with fitz.open() as doc:
        p=doc.new_page(width=400,height=200)
        p.insert_image(p.rect,stream=png)
        p.insert_text((30,70),'Fecha: 10/09/2026',fontsize=18,render_mode=3)
        p.insert_text((30,110),'Documento escaneado de prueba',fontsize=14,render_mode=3)
        doc.save(output/'ocr-capa-buscable.pdf',garbage=4,deflate=True)
    print('Generados herramientas-v08.pdf y ocr-capa-buscable.pdf (datos sintéticos).')


if __name__=='__main__':generate()
