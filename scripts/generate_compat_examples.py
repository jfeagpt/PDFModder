"""Generate public v0.9.1/v0.9.2 compatibility PDFs without user documents."""
from __future__ import annotations

import argparse
import importlib.util
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, ContentStream, DictionaryObject, NameObject, NumberObject


ROOT = Path(__file__).resolve().parents[1]


def clipped_tagged_pdf():
    spec = importlib.util.spec_from_file_location('compat_tagged_corpus', ROOT / 'tests' / 'tagged_corpus.py')
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    source = corpus.make_tagged_pdf(named_properties=True, include_objr=True, actual_text=corpus.DATE_TEXT)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    page = writer.pages[0]
    contents = ContentStream(page.get_contents(), writer)
    contents.operations = [
        ([], b'q'), ([NumberObject(0), NumberObject(0), NumberObject(420), NumberObject(420)], b're'),
        ([], b'W'), ([], b'n'), *contents.operations, ([], b'Q'),
    ]
    page[NameObject('/Contents')] = writer._add_object(contents)
    result = BytesIO()
    writer.write(result)
    corpus.audit_tagged(result.getvalue())
    return result.getvalue()


def neutral_graphics_pdf():
    with fitz.open() as document:
        page = document.new_page(width=360, height=240)
        page.insert_text((40, 60), '10/09/2026', fontsize=12)
        page.insert_text((40, 130), 'VECINO INTACTO', fontsize=12)
        page.draw_line((30, 150), (325, 150), color=(.1, .3, .5), width=1)
        page = document.new_page(width=360, height=240)
        page.insert_text((40, 60), 'PAGINA CONTROL', fontsize=12)
        document.set_metadata({'title': 'PDF Modder: estados de color neutros', 'author': 'PDF Modder'})
        initial = document.tobytes(no_new_id=True)
    writer = PdfWriter(clone_from=PdfReader(BytesIO(initial)))
    state = DictionaryObject({
        NameObject('/OP'): writer._add_object(BooleanObject(False)),
        NameObject('/op'): writer._add_object(BooleanObject(False)),
        NameObject('/OPM'): NumberObject(0),
        NameObject('/TR'): writer._add_object(ArrayObject([NameObject('/Identity')] * 4)),
    })
    page = writer.pages[0]
    page['/Resources'][NameObject('/ExtGState')] = DictionaryObject({NameObject('/GS'): writer._add_object(state)})
    contents = ContentStream(page.get_contents(), writer)
    contents.operations.insert(0, ([NameObject('/GS')], b'gs'))
    page[NameObject('/Contents')] = writer._add_object(contents)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def complementary_cff_pdf():
    spec = importlib.util.spec_from_file_location('compat_cid_corpus', ROOT / 'tests' / 'cid_corpus.py')
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    return corpus.document()


def truetype_without_cmap_pdf():
    spec = importlib.util.spec_from_file_location('compat_cid_ttf_corpus', ROOT / 'tests' / 'cid_ttf_corpus.py')
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    return corpus.document()


def main():
    parser = argparse.ArgumentParser(description='Generar PDFs de compatibilidad 0.9.1 / 0.9.2')
    parser.add_argument('--output', type=Path, default=ROOT / 'examples')
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ('compat-etiquetado-v091.pdf', clipped_tagged_pdf()),
        ('compat-estado-neutro-v091.pdf', neutral_graphics_pdf()),
        ('compat-subconjuntos-v091.pdf', complementary_cff_pdf()),
        ('compat-truetype-v092.pdf', truetype_without_cmap_pdf()),
    ):
        path = output / name
        path.write_bytes(data)
        print(path)


if __name__ == '__main__':
    main()
