"""Aceptación por interfaz con el MAPA privado aportado; nunca se distribuye.

Ejemplo: python scripts/acceptance_v092.py --pdf RUTA --routes pagina panel
Los casos usan selecciones concretas y guardan siempre copias dentro de tmp.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication
from pdfmodder.app import MainWindow
from pdfmodder import __version__


# Occurrence is explicit: the two 9,15 cells are independent selections.
CASES = [
    ('ha_naturales', '5,8177', '6,1250', 0),
    ('ha_franjas', '3,3363', '4,2363', 0),
    ('ha_total_superior', '9,15', '9,25', 0),
    ('ha_agricultor', '68,48', '63,48', 0),
    ('ha_porcentaje', '13,36', '14,36', 0),
    ('ha_total_inferior', '9,15', '10,25', 1),
    ('ha_ampliar', '68,48', '66,4488', 0),
    ('ha_acortar', '68,48', '8,4', 0),
    ('nombre_acortar', 'BARTOLOME PARRA ZURANO S.A', 'BARTOLOME PARRA ZURANO', 0),
    # A whole-line selection includes the trailing original space. Leaving it
    # outside the selection would invade an unselected character on expansion.
    ('nombre_ampliar', 'BARTOLOME PARRA ZURANO S.A ', 'BARTOLOME PARRA ZURANO S.A.U. ', 0),
    ('fecha_regresion', '2025', '2026', 0),
]
REJECTED_CASES = [('ha_glifos_ausentes', '68,48', '70,48', 0)]


class GuiAcceptance(QObject):
    def __init__(self, window, source, output, jobs):
        super().__init__(window)
        self.window, self.source, self.output, self.jobs = window, source, output, jobs
        self.source_hash = sha256(source.read_bytes()).hexdigest()
        self.case_index = 0
        self.stage = 'opening'
        self.results = []
        self.finished = False
        self.started = time.perf_counter()
        self.selected = {}
        self.current = {}
        window.thumbnail_timer.stop()
        window.operation_finished.connect(self.operation)
        window.error_raised.connect(self.case_failed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.case_failed(f'Tiempo límite en {self.stage}.'))
        self.timer.start(90000)

    def require(self, condition, message):
        if not condition:
            raise AssertionError(message)

    def operation(self, command, result):
        if self.finished or self.stage == 'next':
            return
        try:
            self.advance(command, result)
        except Exception as exc:
            self.case_failed(str(exc), traceback.format_exc())

    def select(self, text, occurrence):
        glyphs = self.window.model.glyphs
        content = ''.join(g.text for g in glyphs)
        indices = []
        offset = 0
        while (index := content.find(text, offset)) >= 0:
            indices.append(index)
            offset = index + len(text)
        self.require(len(indices) > occurrence, f'No se encuentra aparición {occurrence + 1} de {text!r}.')
        start = indices[occurrence]
        part = glyphs[start:start + len(text)]
        self.require(''.join(g.text for g in part) == text, 'La selección abarca caracteres inesperados.')
        self.window.canvas.set_selection([g.id for g in part])
        return part

    def advance(self, command, result):
        (name, old, new, occurrence), route, expected_block = self.jobs[self.case_index]
        is_page = command == 'page' and result.get('model') is not None
        if self.stage == 'opening' and is_page and result['number'] == 0:
            self.current = {'name': name + '_' + route, 'route': route, 'old': old, 'new': new,
                            'occurrence': occurrence, 'verified': False, 'source_sha256': self.source_hash,
                            'expected_rejection': expected_block,
                            'phase': 'edit', 'started': time.perf_counter()}
            part = self.select(old, occurrence)
            self.selected[self.current['name']] = part
            self.current.update(selected_characters=len(part), source_font=part[0].font,
                                source_font_xref=part[0].font_xref, source_origin=list(part[0].origin))
            self.initial_revision = self.window.model.revision
            self.initial_render_hash = sha256(result['png']).hexdigest()
            if route == 'pagina':
                self.stage = 'selection'
                self.window.start_edit()
            else:
                self.window.content.setPlainText(new)
                self.require(self.window.preview_button.isEnabled(), 'El panel lateral no permite previsualizar.')
                self.stage = 'panel_preview'
                self.window.preview_button.click()
        elif self.stage == 'selection' and command == 'rich_selection':
            editor = self.window.canvas.editor
            self.require(editor.isVisible() and editor.rich_mode, 'No se abrió el editor sobre la página.')
            self.require(editor.toPlainText() == old, 'El editor alteró el alcance seleccionado.')
            cursor = editor.textCursor()
            cursor.select(QTextCursor.Document)
            editor.setTextCursor(cursor)
            cursor.insertText(new)
            self.stage = 'rich_preview'
        elif self.stage == 'rich_preview' and command == 'rich_preview':
            self.require(not expected_block, 'La fuente incompleta aceptó caracteres ausentes sin rechazarlos.')
            self.require(result['report'].get('verified'), 'No se validó el PDF de la vista previa.')
            self.preview_hash = sha256(result['png']).hexdigest()
            self.current['engine'] = result['report']
            self.stage = 'accepted'
            self.window.canvas.editor.toolbar.accept.click()
        elif self.stage == 'panel_preview' and is_page and result['number'] == 0:
            self.require(not expected_block, 'La fuente incompleta aceptó caracteres ausentes sin rechazarlos.')
            self.require(self.window.state['preview'] and self.window.state['history_index'] == 0,
                         'El panel no dejó una vista previa pendiente de aceptación.')
            self.require(self.window.last_report.get('verified'), 'El panel no validó el PDF previsualizado.')
            self.preview_hash = sha256(result['png']).hexdigest()
            self.current['engine'] = self.window.last_report
            self.stage = 'accepted'
            self.window.commit_button.click()
        elif self.stage == 'accepted' and is_page and result['number'] == 0:
            self.require(self.window.state['history_index'] == 1, 'La edición no produjo una sola operación.')
            self.require(sha256(result['png']).hexdigest() == self.preview_hash, 'Vista previa y aplicación difieren.')
            self.edited_text = ''.join(g.text for g in self.window.model.glyphs)
            self.require(new in self.edited_text, 'El PDF no contiene el texto esperado.')
            self.current['preview_matches_saved_pdf'] = True
            self.case_dir = self.output / self.current['name']
            self.case_dir.mkdir(parents=True, exist_ok=True)
            self.target = self.case_dir / 'editado.pdf'
            self.current['output'] = str(self.target)
            self.stage = 'saved'
            self.window.save_as(self.target)
        elif self.stage == 'saved' and command == 'save':
            self.current['output_sha256'] = sha256(self.target.read_bytes()).hexdigest()
            self.stage = 'undo'
            self.window.history('undo')
        elif self.stage == 'undo' and is_page and result['number'] == 0:
            self.require(self.window.model.revision == self.initial_revision, 'Deshacer no recuperó exactamente el documento.')
            self.current['undo_exact'] = True
            self.stage = 'reopened'
            self.window.open_document(self.target)
        elif self.stage == 'reopened' and is_page and result['number'] == 0:
            self.require(''.join(g.text for g in self.window.model.glyphs) == self.edited_text, 'Guardar y reabrir cambió el texto.')
            self.require(sha256(result['png']).hexdigest() == self.preview_hash, 'Guardar y reabrir cambió la apariencia.')
            self.current.update(gui_verified=True, gui_render_reopened_equal=True, phase='independent_validation')
            screenshot = self.case_dir / 'reabierto.png'
            self.window.grab().save(str(screenshot))
            self.current['screenshot'] = str(screenshot)
            self.finish_case()
        elif self.stage == 'reject_verify' and is_page and result['number'] == 0:
            self.require(self.window.state['history_index'] == 0 and not self.window.state['dirty']
                         and not self.window.state['preview'], 'El rechazo alteró el historial o dejó un cambio pendiente.')
            self.require(self.window.model.revision == self.initial_revision, 'El rechazo alteró los bytes del documento de trabajo.')
            self.require(sha256(result['png']).hexdigest() == self.initial_render_hash, 'El rechazo alteró la apariencia del documento.')
            self.current.update(verified=True, rejection_verified=True, history_unchanged=True,
                                working_pdf_unchanged=True, render_unchanged=True, phase='expected_rejection')
            self.finish_case()

    def case_failed(self, message, trace=None):
        if self.finished or self.stage == 'next':
            return
        if not self.current:
            (name, old, new, occurrence), route, expected_block = self.jobs[self.case_index]
            self.current = {'name': name + '_' + route, 'route': route, 'old': old, 'new': new,
                            'occurrence': occurrence, 'source_sha256': self.source_hash,
                            'expected_rejection': expected_block}
        if self.current.get('expected_rejection') and self.stage in ('selection', 'rich_preview', 'panel_preview'):
            concrete = (any(word in message.lower() for word in ('glifo', 'carácter', 'caracter', 'contiene', 'faltan'))
                        and any(char in message for char in ('«0»', '«7»', 'U+0030', 'U+0037'))
                        and 'requiere contornos TrueType' not in message)
            if concrete:
                self.current['blocked_reason'] = message
                self.stage = 'reject_verify'
                self.window.cancel()
                self.window.load_page()
                return
        self.current.update(verified=False, error=message, phase=self.stage)
        if trace:
            self.current['traceback'] = trace
        self.finish_case()

    def finish_case(self):
        self.current['elapsed_gui_seconds'] = round(time.perf_counter() - self.current.pop('started', self.started), 3)
        self.current['source_unchanged'] = sha256(self.source.read_bytes()).hexdigest() == self.source_hash
        self.results.append(self.current)
        print(json.dumps({key: self.current.get(key) for key in ('name', 'gui_verified', 'error')}, ensure_ascii=True), flush=True)
        self.stage = 'next'
        self.timer.stop()
        self.window.cancel()
        self.case_index += 1
        if self.case_index >= len(self.jobs):
            self.finished = True
            self.window._allow_close = True
            self.window.close()
            QApplication.instance().exit(0)
        else:
            def advance():
                if self.window.busy:
                    QTimer.singleShot(50, advance)
                    return
                self.current = {}
                self.stage = 'opening'
                self.timer.start(90000)
                self.window.open_document(self.source)
            QTimer.singleShot(50, advance)


def audit_outputs(source, output, results, selected, independent_python=None):
    """Run after the GUI closes, with independent extraction and rendering."""
    import pymupdf as fitz
    from pypdf import PdfReader
    from acceptance_report import find_poppler, render_poppler, compare_poppler, glyph_records
    from acceptance_v09 import _plain, _unchanged_glyphs
    original = source.read_bytes()
    before = PdfReader(BytesIO(original), strict=True)
    poppler = find_poppler(None)
    source_prefix = output / 'original'
    if any(case.get('gui_verified') for case in results):
        render_poppler(poppler, source, source_prefix)
    for case in results:
        folder = output / case['name']
        folder.mkdir(parents=True, exist_ok=True)
        if case.get('gui_verified'):
            try:
                target = Path(case['output'])
                saved = target.read_bytes()
                case['unchanged_glyphs_checked'] = _unchanged_glyphs(original, saved, selected[case['name']])
                expected_count = len(glyph_records(original)) - len(selected[case['name']]) + len(case['new'])
                assert len(glyph_records(saved)) == expected_count, 'Quedaron caracteres antiguos o duplicados, o faltan caracteres nuevos.'
                case['exact_replacement_character_count'] = True
                after = PdfReader(BytesIO(saved), strict=True)
                assert len(after.pages) == len(before.pages)
                extracted = {mode: _plain(after.pages[0].extract_text(extraction_mode=mode)) for mode in ('plain', 'layout')}
                if not any(_plain(case['new']) in text for text in extracted.values()) and independent_python:
                    code = 'import json,sys; from pdfminer.high_level import extract_text; print(json.dumps(extract_text(sys.argv[1],page_numbers=[0]),ensure_ascii=True))'
                    result = subprocess.run([str(independent_python), '-c', code, str(target)], capture_output=True,
                                            text=True, check=True, timeout=60)
                    extracted['pdfminer.six'] = _plain(json.loads(result.stdout))
                    case['additional_extractor'] = {'name': 'pdfminer.six',
                        'reason': 'pypdf separa algunos fragmentos del texto editado heurísticamente.'}
                matches = [mode for mode, text in extracted.items() if _plain(case['new']) in text]
                assert matches, f'El extractor independiente no encuentra {case["new"]!r}.'
                case['independent_matching_modes'] = matches
                with fitz.open(stream=original, filetype='pdf') as original_doc, fitz.open(target) as result_doc:
                    for number in range(1, len(before.pages)):
                        assert before.pages[number].extract_text() == after.pages[number].extract_text()
                        assert original_doc[number].get_pixmap().samples == result_doc[number].get_pixmap().samples
                    case['control_pages_equal'] = True
                    engine = case['engine']
                    exclusions = engine.get('source_regions', []) + engine.get('destination_regions', [])
                    if engine.get('pages'):
                        exclusions += engine['pages'][0].get('ink_exclusion_regions', [])
                        exclusions += engine['pages'][0].get('verified_ink_regions', [])
                    assert exclusions, 'Faltan regiones mínimas de cambio para comparar.'
                    render_poppler(poppler, target, folder / 'despues')
                    digits = len(str(len(before.pages)))
                    case['poppler_pages'] = [compare_poppler(
                        output / f'original-{number+1:0{digits}d}.png', folder / f'despues-{number+1:0{digits}d}.png',
                        exclusions if number == 0 else [], page.rotation_matrix,
                    ) for number, page in enumerate(original_doc)]
                case.update(verified=True, phase='complete')
            except Exception as exc:
                case.update(verified=False, error=str(exc), traceback=traceback.format_exc(), phase='independent_validation')
        case['verified'] = bool(case.get('verified') and case.get('source_unchanged'))
        (folder / 'report.json').write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


def main():
    from acceptance_v09 import source_fingerprint
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'tmp/compat-v092-private/acceptance')
    parser.add_argument('--routes', nargs='+', choices=['pagina', 'panel'], default=['pagina', 'panel'])
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--independent-python', type=Path)
    args = parser.parse_args()
    source = args.pdf.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    jobs = [(case, route, expected_block) for definitions, expected_block in ((CASES, False), (REJECTED_CASES, True))
            for case in definitions for route in args.routes
            if not args.only or case[0] in args.only or case[0] + '_' + route in args.only]
    if not jobs:
        parser.error('Ningún caso coincide con --only.')
    fingerprint = source_fingerprint()
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    history = output / 'history'
    history.mkdir(exist_ok=True)
    window = MainWindow(source, config_path=output / 'fonts.json', history_dir=history)
    window.show()
    driver = GuiAcceptance(window, source, output, jobs)
    window._acceptance_v092 = driver
    app.exec()
    cases = audit_outputs(source, output, [case for case in driver.results if not case.get('expected_rejection')],
                          driver.selected, args.independent_python)
    rejected = [case for case in driver.results if case.get('expected_rejection')]
    for case in rejected:
        folder = output / case['name']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'report.json').write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding='utf-8')
    report = dict(verified=len(cases) + len(rejected) == len(jobs) and all(case['verified'] for case in cases + rejected),
                  application_version=__version__, app_source_sha256=fingerprint,
                  source_fingerprint_unchanged=source_fingerprint() == fingerprint,
                  privacy='Pruebas privadas del PDF aportado; no distribuir documentos, resultados ni capturas.',
                  cases=cases, rejected_cases=rejected)
    report['verified'] &= report['source_fingerprint_unchanged']
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
