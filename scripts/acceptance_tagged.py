"""Reproducible tagged-text audit with logical-order and independent pixel checks."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import pymupdf as fitz
import pypdf
from pypdf import PdfReader

from acceptance_report import (
    CHANNEL_TOLERANCE, DPI, MARGIN_PT, ORIGIN_TOLERANCE,
    compare_poppler, find_poppler, glyph_records, render_poppler,
    same_origin, select, verify_neighbours,
)
from pdfmodder.engine import atomic_save, edit_pdf, extract_page
from pdfmodder.model import EditRequest
from tagged_corpus import DATE_TEXT, MOVE_TEXT, audit_tagged, make_tagged_pdf


def sha(data):
    return hashlib.sha256(data).hexdigest()


def model_for(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return extract_page(doc, 0, data)


def jsonable(value):
    if isinstance(value, dict):
        return {':'.join(map(str, key)) if isinstance(key, tuple) else key: jsonable(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def changed_character_boxes(before, after, allowed_ids, engine_report):
    """Keep only actual changed-character boxes within the operation's regions.

    Unchanged neighbours are checked separately even inside these exclusions.
    No mask is based on the page, paragraph, line or inferred text selection box.
    """
    old, new = model_for(before).glyphs, model_for(after).glyphs
    unused = set(range(len(new)))
    changed_old = []
    for glyph in old:
        index = next((i for i in unused if new[i].text == glyph.text
                      and same_origin(new[i].origin, glyph.origin)
                      and new[i].font == glyph.font and abs(new[i].size-glyph.size)<.001
                      and new[i].color == glyph.color and abs(new[i].opacity-glyph.opacity)<.0001), None)
        if index is None:
            changed_old.append(glyph)
        else:
            unused.remove(index)
    changed_new = [new[i] for i in sorted(unused)]
    assert all(g.id in allowed_ids for g in changed_old), 'Cambió un vecino ajeno a la operación'
    for glyphs, key in ((changed_old, 'source_regions'), (changed_new, 'destination_regions')):
        regions = [fitz.Rect(r)+(-.05,-.05,.05,.05) for r in engine_report[key]]
        assert all(any(region.contains(fitz.Rect(g.bbox)) for region in regions) for g in glyphs), 'Cambio fuera de las regiones registradas por el motor'
    return [list(g.bbox) for g in changed_old+changed_new], {
        'source_changed_characters': len(changed_old), 'destination_changed_characters': len(changed_new),
        'original_unchanged_characters': len(old)-len(changed_old),
    }


def same_structure(before, after):
    for key in ('lang', 'marked', 'rolemap', 'structure', 'struct_parents',
                'parent_tree_next_key', 'parent_tree', 'objrs'):
        assert before[key] == after[key], f'Estructura lógica alterada: {key}'


def verify_word_style(before, after, word, y):
    _, old = select(before, word, y)
    _, new = select(after, word, y)
    for a, b in zip(old, new):
        assert (a.text, a.font, a.size, a.color, a.opacity) == (b.text, b.font, b.size, b.color, b.opacity)
        assert abs(a.origin[1]-b.origin[1]) < ORIGIN_TOLERANCE
        assert abs((a.origin[0]-old[0].origin[0])-(b.origin[0]-new[0].origin[0])) < ORIGIN_TOLERANCE


def generate_examples():
    targets = {
        ROOT / 'examples/etiquetado.pdf': make_tagged_pdf(),
        ROOT / 'examples/etiquetado_actualtext.pdf': make_tagged_pdf(named_properties=True, actual_text=DATE_TEXT),
    }
    for path, data in targets.items():
        audit_tagged(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return [str(path) for path in targets]


def execute(source, output, poppler):
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    source_hash = sha(source_bytes)
    original_audit = audit_tagged(source_bytes)
    assert original_audit['actual_text'] == {(0, 0): DATE_TEXT}, 'Usa el ejemplo con ActualText coincidente'
    original_path = output / 'original.pdf'
    assert original_path.resolve() != source.resolve(), 'El original debe quedar fuera de la carpeta de resultados'
    original_path.write_bytes(source_bytes)
    state, excluded, operations = source_bytes, [], []
    recipes = [
        ('fecha_actualtext', '10/09/2026', 100, {'text': '11/09/2026'}),
        ('ajuste_linea', 'PALABRA', 150, {'text': 'VOZ', 'line_reflow': True}),
        ('mover_palabra', 'VOZ', 150, {'dx': 0, 'dy': 20}),
    ]
    for index, (name, label, baseline, parameters) in enumerate(recipes):
        model, chosen = select(state, label, baseline)
        allowed = [g for g in model.glyphs if abs(g.origin[1]-baseline)<.035] if parameters.get('line_reflow') else chosen
        before = state
        state, report = edit_pdf(state, EditRequest(0, [g.id for g in chosen], revision=model.revision, **parameters))
        assert report['verified'] and report['accessibility']['verified']
        neighbours = verify_neighbours(before, state, allowed)
        boxes, checks = changed_character_boxes(before, state, {g.id for g in allowed}, report)
        excluded.extend(boxes)
        checks['unaffected_neighbours_verified'] = neighbours
        old_audit, audit = audit_tagged(before), audit_tagged(state)
        same_structure(original_audit, audit)
        expected_reading = original_audit['reading_order'].replace(DATE_TEXT, 'Fecha: 11/09/2026', 1)
        if index >= 1:
            expected_reading = expected_reading.replace(MOVE_TEXT, 'Mover VOZ fin.')
        assert audit['reading_order'] == expected_reading
        assert audit['actual_text'] == {(0, 0): 'Fecha: 11/09/2026'}
        assert audit['content'][(0, 0)] == 'Fecha: 11/09/2026'
        if index >= 1:
            assert audit['content'][(0, 1)] == 'Mover VOZ fin.'
        if name == 'ajuste_linea':
            verify_word_style(before, state, 'Mover', 150)
            verify_word_style(before, state, 'fin.', 150)
            checks['neighbour_words_preserve_style_and_internal_positions'] = True
        if name == 'mover_palabra':
            records = glyph_records(state)
            for glyph in chosen:
                assert not any(r['text']==glyph.text and same_origin(r['origin'],glyph.origin) for r in records)
                destination = (glyph.origin[0], glyph.origin[1]+20)
                assert sum(r['text']==glyph.text and same_origin(r['origin'],destination) for r in records) == 1
            assert audit['reading_order'] == old_audit['reading_order']
            checks['moved_characters_have_one_destination_and_no_source'] = len(chosen)
        operations.append({'operation': name, 'parameters': parameters,
                           'checks': checks, 'mask_rectangles_pt': boxes, 'engine_report': report})

    destination = output / 'editado.pdf'
    atomic_save(state, destination, source)
    saved = destination.read_bytes()
    final_audit = audit_tagged(saved)
    assert final_audit == audit_tagged(state)
    for number in (0, 1):
        assert glyph_records(saved, number) == glyph_records(state, number)
    assert glyph_records(saved, 1) == glyph_records(source_bytes, 1)
    reader, original_reader = PdfReader(BytesIO(saved), strict=True), PdfReader(BytesIO(source_bytes), strict=True)
    texts = [page.extract_text() for page in reader.pages]
    assert len(reader.pages) == len(original_reader.pages) == 2
    assert texts[0].count('11/09/2026') == 1 and '10/09/2026' not in texts[0]
    assert texts[0].count('VOZ') == 1 and 'PALABRA' not in texts[0]
    assert texts[1] == original_reader.pages[1].extract_text()
    properties = reader.pages[0]['/Resources'].get('/Properties', {})
    properties = properties.get_object() if hasattr(properties, 'get_object') else properties
    assert all(value.get_object().get('/ActualText') != DATE_TEXT for value in properties.values())
    assert sha(source.read_bytes()) == source_hash

    stderr = [render_poppler(poppler, original_path, output / 'antes'),
              render_poppler(poppler, destination, output / 'despues')]
    with fitz.open(stream=source_bytes, filetype='pdf') as original:
        comparisons = [compare_poppler(output / f'antes-{n+1}.png', output / f'despues-{n+1}.png',
                                       excluded if n == 0 else [], original[n].rotation_matrix)
                       for n in (0, 1)]
    version = subprocess.run([str(poppler), '-v'], capture_output=True, text=True,
                             errors='replace', check=True).stderr.strip()
    return jsonable({
        'verified': True, 'scope': 'Corpus etiquetado sintético; no certificación PDF/UA ni archivos reales del usuario.',
        'source': str(source), 'destination': str(destination),
        'source_sha256': source_hash, 'destination_sha256': sha(saved), 'source_unchanged': True,
        'platform': platform.platform(), 'python': platform.python_version(),
        'pymupdf': fitz.VersionBind, 'pypdf': pypdf.__version__, 'poppler': version,
        'elapsed_seconds': round(time.perf_counter()-started, 3), 'operations': operations,
        'logical_before': original_audit, 'logical_after': final_audit,
        'logical_order_verified': True, 'actualtext_updated': True,
        'stale_unused_actualtext_resource_absent': True, 'saved_preview_identical_characters': True,
        'pypdf_text': texts, 'pypdf_text_checks_passed': True,
        'poppler_stderr': stderr, 'poppler_pages': comparisons,
        'mask_policy': {'rectangles': 'Sólo caracteres realmente sustituidos o desplazados, origen y destino de las tres operaciones; ninguno de los vecinos que mantienen texto, formato y posición.',
                        'rectangles_pt': excluded, 'margin_pt': MARGIN_PT, 'dpi': DPI,
                        'channel_tolerance_255': CHANNEL_TOLERANCE,
                        'justification': '0,75 pt = 1,5 px a 144 ppp para antialias. Ningún píxel exterior supera 8/255; página 2 exige igualdad exacta sin máscaras.'},
        'independence': 'El auditor de prueba usa pypdf sin tagged.py para contrastar estructura y orden; pypdf también participa en el parser de producción. Poppler renderiza independientemente toda la salida.',
    })


def main():
    parser = argparse.ArgumentParser(description='Aceptación de PDF etiquetado y ajuste de línea con Poppler')
    parser.add_argument('--source', type=Path, default=ROOT / 'examples/etiquetado_actualtext.pdf')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/acceptance-tagged')
    parser.add_argument('--poppler')
    parser.add_argument('--generate-examples', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        if args.generate_examples:
            generate_examples()
        report = execute(args.source.resolve(), args.output.resolve(), find_poppler(args.poppler))
    except Exception as error:
        report = {'verified': False, 'error': str(error), 'traceback': traceback.format_exc(),
                  'elapsed_seconds': round(time.perf_counter()-started, 3)}
    report_path = args.output / 'report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'verified': report['verified'], 'report': str(report_path),
                      'elapsed_seconds': report['elapsed_seconds'], 'error': report.get('error')}, ensure_ascii=True))
    if not report['verified']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
