"""Acceptance on caller-supplied PDFs; originals remain immutable.

Usage: python scripts/acceptance_v150.py --out tmp/acceptance-v150-private FILE.pdf ...
No private input path or test document belongs in source control. Each operation
starts from original bytes unless its name explicitly refers to an added image.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import subprocess
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf as fitz
from PIL import Image, ImageDraw
from pypdf import PdfReader

from pdfmodder.composition import AddTextRequest, insert_text_pdf
from pdfmodder.engine import atomic_save, edit_pdf, extract_page
from pdfmodder.export_v150 import export_document
from pdfmodder.fonts import FontResolver
from pdfmodder.media import add_image_pdf, edit_image_pdf, image_items, transform_image_pdf
from pdfmodder.model import EditError, EditRequest, intersects, union
from pdfmodder.page_tools_v150 import crop_pages_pdf, replace_pages_pdf, split_pdf
from pdfmodder.pageops import delete_pages_pdf, extract_pages_pdf, merge_pdfs, organize_pages_pdf
from pdfmodder import __version__
from package_v09 import source_fingerprint


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image_bytes():
    asset = Image.new('RGB', (100, 60), 'white')
    drawing = ImageDraw.Draw(asset)
    drawing.rectangle((0, 0, 49, 59), fill=(10, 85, 170))
    drawing.polygon([(50, 0), (99, 59), (50, 59)], fill=(255, 145, 30))
    stream = BytesIO()
    asset.save(stream, format='PNG')
    return stream.getvalue()


def auxiliary_pdf():
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=220)
        page.insert_text((30, 60), 'PDFMODDER AUXILIAR 1.5.0')
        page.draw_rect((30, 100, 160, 170), color=(0, .3, .8))
        return doc.tobytes()


def free_area(page, model, width, height, excluded=()):
    """Deterministic visible empty area; no automatic permission to overlap."""
    obstacles = [fitz.Rect(g.bbox) for g in model.glyphs if g.id not in excluded]
    obstacles.extend(fitz.Rect(info['bbox']) for info in page.get_image_info())
    obstacles.extend(fitz.Rect(link['from']) for link in page.get_links())
    obstacles.extend(annot.rect for annot in page.annots() or [])
    # Thin strokes are obstacles; a full-page background fill is not an object
    # that would obscure a later addition. The engine still performs its checks.
    for drawing in page.get_drawings():
        if drawing['type'] in ('s', 'fs') and drawing['rect'].width < page.rect.width * .95:
            obstacles.append(drawing['rect'])
    bounds = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
    for y in range(int(bounds.height-height-12), 12, -14):
        for x in range(12, int(bounds.width-width-12), 14):
            rect = fitz.Rect(x, y, x+width, y+height)
            expanded = rect + (-2, -2, 2, 2)
            if not any(intersects(expanded, obstacle) for obstacle in obstacles):
                return tuple(rect)
    raise EditError('No se encontró un área vacía suficiente para este caso de aceptación, sin permitir solapamientos.')


def selected_number(model):
    groups = {}
    for glyph in model.glyphs:
        if glyph.mode != 3 and glyph.opacity > 0:
            groups.setdefault(glyph.line, []).append(glyph)
    candidates = []
    for glyphs in groups.values():
        text = ''.join(g.text for g in glyphs)
        for match in re.finditer(r'2025|2026|\d{2}/\d{2}/\d{4}|\d{2,4}', text):
            selected = glyphs[match.start():match.end()]
            candidates.append((0 if match.group() in ('2025', '2026') or '/' in match.group() else 1,
                               len(match.group()), selected))
    if not candidates:
        raise EditError('No hay cifra visible adecuada en la primera página para este caso.')
    selected = sorted(candidates, key=lambda item: item[:2])[0][2]
    return selected


def compact_report(report):
    keys = ('verified', 'operation', 'page_count', 'part_count', 'non_destructive',
            'instance_only', 'independent_parser', 'warnings', 'named_destinations')
    summary = {key: report[key] for key in keys if key in report}
    if isinstance(report.get('pages'), list):
        summary['validated_pages'] = len(report['pages'])
    return summary


def run_document(source, output, cases=None, poppler=None):
    data = source.read_bytes()
    original_hash = digest(data)
    output.mkdir(parents=True, exist_ok=False)
    resolver = FontResolver(config_path=output/'fonts.json')
    with fitz.open(stream=data, filetype='pdf') as document:
        count = document.page_count
        model = extract_page(document, 0, data)
        original_text = document[0].get_text()
        original_images = len(document[0].get_image_info())
    results = []
    state = {}
    report = {'document': source.name, 'source_sha256': original_hash, 'page_count': count,
              'page1_characters': len(original_text), 'operations': results,
              'scope': 'Motor PDF en archivos de disco; no acredita pruebas de Acrobat ni interfaz.'}
    def checkpoint():
        report['original_unchanged'] = digest(source.read_bytes()) == original_hash
        report['counts'] = dict(Counter(item['status'] for item in results))
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def record(name, operation):
        if cases and name not in cases:
            return
        started = time.perf_counter()
        try:
            detail = operation()
            result = {'case': name, 'status': 'passed', **(detail or {})}
        except EditError as exc:
            result = {'case': name, 'status': 'blocked', 'reason': str(exc)}
        except Exception as exc:
            result = {'case': name, 'status': 'failed', 'reason': str(exc), 'type': type(exc).__name__}
        result['seconds'] = round(time.perf_counter()-started, 3)
        results.append(result)
        checkpoint()
        print(json.dumps({'document': source.name, **result}, ensure_ascii=True), flush=True)
    def saved(name, value, expected_count=count, verify=None):
        candidate, evidence = value
        target = output/(name+'.pdf')
        atomic_save(candidate, str(target), str(source))
        reopened = target.read_bytes()
        # atomic_save performs another full write and validates that transition;
        # stream compression / discarded unreachable objects may change bytes.
        with fitz.open(stream=reopened, filetype='pdf') as doc:
            assert doc.page_count == expected_count, 'Número de páginas inesperado.'
            assert len(PdfReader(BytesIO(reopened)).pages) == expected_count
            if verify:
                verify(doc)
        visual = {}
        if poppler and name in ('move_text', 'edit_text'):
            from acceptance_report import compare_poppler
            def render_first(path, prefix):
                result = subprocess.run([str(poppler), '-cropbox', '-f', '1', '-l', '1',
                    '-singlefile', '-r', '144', '-png', str(path), str(prefix)],
                    capture_output=True, text=True, errors='replace', check=True, timeout=60)
                return result.stderr.strip()
            original_png = output / 'poppler-original.png'
            if not original_png.exists():
                render_first(source, original_png.with_suffix(''))
            destination_png = output / ('poppler-' + name + '.png')
            stderr = render_first(target, destination_png.with_suffix(''))
            regions = evidence.get('source_regions', []) + evidence.get('destination_regions', [])
            assert regions, 'Faltan regiones de los caracteres modificados para Poppler.'
            if evidence.get('pages'):
                regions += evidence['pages'][0].get('ink_exclusion_regions', [])
                regions += evidence['pages'][0].get('verified_ink_regions', [])
            with fitz.open(stream=data, filetype='pdf') as original:
                pixels = compare_poppler(original_png, destination_png, regions, original[0].rotation_matrix)
            visual = {'poppler_page_1': pixels, 'poppler_stderr': stderr}
        state[name] = reopened
        return {'output': target.name, 'sha256': digest(reopened), 'reopened': True,
                'independent_page_count': True, 'full_write_changed_bytes':reopened != candidate,
                'validation': compact_report(evidence), **visual}
    def move_text():
        chosen = selected_number(model)
        box = union(g.bbox for g in chosen)
        with fitz.open(stream=data, filetype='pdf') as doc:
            # Small horizontal move when free, otherwise a deterministically
            # selected empty area. No validation rule is disabled.
            proposed = fitz.Rect(box) + (30, 0, 30, 0)
            neighbors = [g for g in model.glyphs if g.id not in {c.id for c in chosen}]
            if doc[0].rect.contains(proposed) and not any(intersects(proposed, g.bbox) for g in neighbors):
                dx, dy = 30, 0
            else:
                target = free_area(doc[0], model, box[2]-box[0], box[3]-box[1], {g.id for g in chosen})
                dx, dy = target[0]-box[0], target[1]-box[1]
        candidate = edit_pdf(data, EditRequest(0, [g.id for g in chosen], dx=dx, dy=dy), resolver)
        cleanup = candidate[1].get('ocr_cleanup', {})
        removed_ids = set(cleanup.get('removed_ids', []))
        assert len(removed_ids) == cleanup.get('removed_characters', 0), 'El informe de limpieza OCR no coincide con sus identificadores.'
        removed = [g for g in model.glyphs if g.id in removed_ids]
        assert len(removed) == len(removed_ids) and all(g.mode == 3 for g in removed), 'La limpieza declarada no corresponde exclusivamente a caracteres OCR invisibles originales.'
        def verify(doc):
            after = extract_page(doc, 0)
            for glyph in chosen:
                assert any(g.text == glyph.text and abs(g.origin[0]-glyph.origin[0]-dx)<.05
                           and abs(g.origin[1]-glyph.origin[1]-dy)<.05 for g in after.glyphs), 'No se encuentra un carácter en el destino previsto.'
            assert Counter(g.text for g in model.glyphs if g.id not in removed_ids) == Counter(g.text for g in after.glyphs), 'Cambió el contenido fuera de la limpieza OCR declarada.'
        details = saved('move_text', candidate, verify=verify)
        details.update(text=''.join(g.text for g in chosen), dx=dx, dy=dy)
        if removed_ids:
            details['ocr_cleanup'] = {'removed_invisible_characters':len(removed_ids),
                                      'warning':cleanup.get('warning', '')}
        return details
    def change_text():
        chosen = selected_number(model)
        old = ''.join(g.text for g in chosen)
        new = old[:-1] + ('6' if old[-1] != '6' else '5')
        def verify(doc):
            assert new in doc[0].get_text(), 'No se encuentra la nueva cifra extraíble.'
            independent = PdfReader(BytesIO(state_for_extract[0])).pages[0].extract_text()
            assert new in re.sub(r'\s', '', independent), 'Extractor independiente no encuentra los dígitos nuevos.'
        candidate = edit_pdf(data, EditRequest(0, [g.id for g in chosen], text=new), resolver)
        state_for_extract = [candidate[0]]
        result = saved('edit_text', candidate, verify=verify)
        result.update(old_text=old, new_text=new)
        result['independent_text_contiguous'] = new in PdfReader(BytesIO(candidate[0])).pages[0].extract_text()
        if not result['independent_text_contiguous']:
            result['extractor_divergence'] = 'PyMuPDF extrae la cifra contigua; pypdf introduce espacios entre operadores. Los dígitos coinciden al quitar únicamente espacios; no se normalizan otros caracteres.'
        return result
    def add_text():
        with fitz.open(stream=data, filetype='pdf') as doc:
            box = free_area(doc[0], model, 110, 20)
        text = 'PDF Modder 1.5 TEST'
        value = insert_text_pdf(data, AddTextRequest(0, box[0], box[1], 110, 20, text,
                                                    font_name='Helvetica', size=8), resolver)
        def verify(doc):
            assert text in doc[0].get_text()
            assert text in PdfReader(BytesIO(value[0])).pages[0].extract_text()
        return saved('add_text', value, verify=verify)
    def add_image():
        with fitz.open(stream=data, filetype='pdf') as doc:
            box = free_area(doc[0], model, 70, 42)
        state['image_box'] = box
        def verify(doc):
            assert len(doc[0].get_image_info()) == original_images+1
        return saved('add_image', add_image_pdf(data, 0, image_bytes(), box), verify=verify)
    def added_image():
        if 'add_image' not in state:
            raise EditError('Caso dependiente: no se pudo insertar la imagen de prueba.')
        image_data = state['add_image']
        with fitz.open(stream=image_data, filetype='pdf') as doc:
            items = image_items(doc, 0)
        selected = min(items, key=lambda item: sum(abs(a-b) for a,b in zip(item['rect'], state['image_box'])))
        return image_data, selected
    def move_image():
        image_data, item = added_image()
        box = item['rect']
        # Same image instance; translation and enlargement performed together.
        rect = (box[0]+3, box[1]-5, box[2]+8, box[3]-2)
        return saved('move_resize_image', transform_image_pdf(image_data, 0, item['id'], rect))
    def rotate_image():
        image_data, item = added_image()
        return saved('rotate_image', edit_image_pdf(image_data, 0, item['id'], rotation=90))
    def export(fmt):
        target = output/('export.txt' if fmt == 'txt' else 'export-png')
        result = export_document(data, str(target), fmt, [0], dpi=96)
        if fmt == 'txt':
            assert target.read_text(encoding='utf-8').strip()
        else:
            assert fitz.Pixmap(result['files'][0]['path']).width > 0
        return {'files': [Path(item['path']).name for item in result['files']], 'warnings': result['warnings']}
    def rotation():
        plan = [{'source':'current', 'page':n, 'rotation':90 if n == 0 else 0} for n in range(count)]
        def verify(doc):
            assert doc[0].rotation == (model.rotation+90)%360
        return saved('rotate_page', organize_pages_pdf(data, plan), verify=verify)
    def split():
        parts, evidence = split_pdf(data, pages_per_part=max(1, count//2))
        details = []
        for index, (part, group) in enumerate(zip(parts, evidence['page_groups'])):
            details.append(saved(f'split-{index+1:02d}', (part, evidence['parts'][index]), len(group)))
        return {'parts':details, 'part_count':len(parts)}
    auxiliary = auxiliary_pdf()
    def insert():
        plan = [{'source':'aux', 'page':0}] + [{'source':'current', 'page':n} for n in range(count)]
        return saved('insert_page', organize_pages_pdf(data, plan, {'aux':auxiliary}), count+1)
    operations = [
        ('move_text', move_text), ('edit_text', change_text), ('add_text', add_text),
        ('add_image', add_image), ('move_resize_image', move_image), ('rotate_image', rotate_image),
        ('export_txt', lambda:export('txt')), ('export_png', lambda:export('png')),
        ('crop_page', lambda:saved('crop_page', crop_pages_pdf(data, [0], [4, 4, 4, 4]))),
        ('delete_page', lambda:saved('delete_page', delete_pages_pdf(data, [count-1]), count-1)),
        ('extract_page', lambda:saved('extract_page', extract_pages_pdf(data, [0]), 1)),
        ('rotate_page', rotation), ('split', split),
        ('replace_page', lambda:saved('replace_page', replace_pages_pdf(data, [0], auxiliary, [0]))),
        ('insert_page', insert), ('merge', lambda:saved('merge', merge_pdfs(data, [auxiliary]), count+1)),
    ]
    for name, operation in operations:
        record(name, operation)
    checkpoint()
    assert report['original_unchanged'], 'El archivo de origen cambió durante las pruebas.'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdfs', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, default=Path('tmp/acceptance-v150-private'))
    parser.add_argument('--cases', help='Comma-separated case names; omitted runs all cases.')
    parser.add_argument('--poppler', action='store_true', help='Contrasta con Poppler la página editada/movida a 144 ppp.')
    args = parser.parse_args()
    source_before = source_fingerprint()
    root = args.out/datetime.now().strftime('%Y%m%d-%H%M%S')
    root.mkdir(parents=True, exist_ok=False)
    reports = []
    cases = set(args.cases.split(',')) if args.cases else None
    poppler = None
    if args.poppler:
        from acceptance_report import find_poppler
        poppler = find_poppler()
    for index, source in enumerate(args.pdfs):
        if source_fingerprint() != source_before:
            break
        reports.append(run_document(source.resolve(), root/f'document-{index+1}', cases, poppler))
    source_after = source_fingerprint()
    code_unchanged = source_after == source_before
    summary = {'documents':reports, 'originals_unchanged':all(r['original_unchanged'] for r in reports),
               'counts':dict(Counter(op['status'] for report in reports for op in report['operations'])),
               'application_version':__version__, 'app_source_sha256':source_before,
               'app_source_sha256_before':source_before, 'app_source_sha256_after':source_after,
               'app_sources_unchanged':code_unchanged, 'completed_documents':len(reports),
               'requested_documents':len(args.pdfs), 'aborted':not code_unchanged}
    if not code_unchanged:
        summary['abort_reason'] = 'El código productivo cambió durante la aceptación; estos resultados no acreditan una versión estable.'
    (root/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report':str(root/'summary.json'), 'counts':summary['counts'],
                      'originals_unchanged':summary['originals_unchanged'],
                      'app_sources_unchanged':code_unchanged}, ensure_ascii=True), flush=True)
    if not code_unchanged:
        return 2
    return 1 if summary['counts'].get('failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
