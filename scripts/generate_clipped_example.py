"""Regenera el corpus público de campos recortados, sin pytest ni datos privados.

Uso: .venv/Scripts/python.exe scripts/generate_clipped_example.py [--output ruta.pdf]
Requiere las versiones fijadas de PyMuPDF y pypdf del proyecto. El contenido,
geometría, recursos y operadores son reproducibles; el identificador PDF puede
variar entre ejecuciones. No incorpora programas de fuente: usa Base14.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, FloatObject, NumberObject


def generate() -> bytes:
    with fitz.open() as doc:
        page = doc.new_page(width=450, height=400)
        page.draw_rect((30, 45, 420, 100), color=(.2, .4, .5), fill=(.83, .94, .92))
        page.insert_text((40, 80), 'SOL', fontname='cour', fontsize=10)
        page.insert_text((40, 250), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ', fontname='cour', fontsize=10)
        doc.new_page(width=450, height=400).insert_text((40, 80), 'PAGINA INTACTA')
        initial = doc.tobytes()

    writer = PdfWriter(clone_from=PdfReader(BytesIO(initial)))
    page = writer.pages[0]
    stream = ContentStream(page['/Contents'][1], writer)
    middle = []
    for args, operator in stream.operations:
        if operator == b'TJ':
            # Internal adjustment exercises nonuniform source spacing. The
            # large gap leaves room while the following Tj tests cursor state.
            word = ArrayObject([ByteStringObject(b'S'), FloatObject(18.25),
                                ByteStringObject(b'OL'), NumberObject(-8000),
                                ByteStringObject(b' LUNA')])
            middle.extend([([FloatObject(0)], b'Tc'), ([FloatObject(0)], b'Tw'),
                           ([FloatObject(100)], b'Tz'), ([word], b'TJ'),
                           ([ByteStringObject(b' FIN')], b'Tj')])
        else:
            middle.append((args, operator))

    def numbers(*values):
        return [FloatObject(value) for value in values]

    stream.operations = [([], b'q'), (numbers(.1, 0, 0, .1, 0, 0), b'cm'),
                         (numbers(300, 3000, 3900, 550), b're'), ([], b'W'), ([], b'n'),
                         (numbers(10, 0, 0, 10, 0, 0), b'cm'), *middle, ([], b'Q')]
    page['/Contents'][1] = writer._add_object(stream)
    intermediate = BytesIO()
    writer.write(intermediate)

    with fitz.open(stream=intermediate.getvalue(), filetype='pdf') as doc:
        page = doc[0]
        page.insert_text((40, 145), '10/09/2026', fontname='cour', fontsize=10)
        page.insert_text((40, 28), 'PDF Modder: campo recortado', fontname='helv', fontsize=13)
        page.insert_text((40, 177), 'Seleccione la palabra situada en el campo verde.', fontname='helv', fontsize=10)
        page.insert_text((40, 192), 'Desactive ajustar la linea y amplie el area a 28,222 mm.', fontname='helv', fontsize=10)
        doc.set_metadata({'title': 'PDF Modder - campo recortado reproducible',
                          'author': 'PDF Modder - corpus sintetico'})
        return doc.tobytes(garbage=4, deflate=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'examples' / 'recortado.pdf')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(generate())
    print(args.output.resolve())


if __name__ == '__main__':
    main()
