"""Public movement routes must retain real rich content after save and undo."""
from io import BytesIO

import pymupdf as fitz
from PIL import Image
import pytest

from pdfmodder.engine import atomic_save, edit_pdf, extract_page
from pdfmodder.history import History
from pdfmodder.model import EditRequest
from pdfmodder.objects import group_pdf, object_info, transform_objects_pdf
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload


def _model(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return extract_page(doc, 0, data)


def _ids(data, text):
    glyphs = _model(data).glyphs
    start = ''.join(g.text for g in glyphs).index(text)
    return [g.id for g in glyphs[start:start+len(text)]]


def _document():
    image = BytesIO()
    Image.new('RGB', (20, 10), (40, 110, 200)).save(image, format='PNG')
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_text((35, 50), 'Subrayado', fontsize=12)
        page.insert_text((35, 140), 'VECINO', fontsize=10)
        page.insert_image((230, 40, 290, 70), stream=image.getvalue())
        doc.new_page(width=400, height=300).insert_text((35, 50), 'CONTROL')
        data = doc.tobytes()
    ids = _ids(data, 'Subrayado')
    payload = selection_payload(data, 0, ids)
    return edit_rich_pdf(data, RichTextRequest(0, ids,
        [dict(run, underline=True, char_spacing=.4) for run in payload['runs']],
        rect=(35, payload['rect'][1], 200, 100)))[0]


def _assert_displacement(before, after, selected, dx, dy):
    original, current = _model(before), _model(after)
    assert len(original.glyphs) == len(current.glyphs)
    for first, second in zip(original.glyphs, current.glyphs):
        assert (second.text, second.font, second.size, second.color) == (first.text, first.font, first.size, first.color)
        delta = (dx, dy) if first.id in selected else (0, 0)
        assert second.origin == pytest.approx(tuple(a+b for a,b in zip(first.origin, delta)), abs=.002)
    with fitz.open(stream=before, filetype='pdf') as a, fitz.open(stream=after, filetype='pdf') as b:
        assert a[1].get_pixmap().samples == b[1].get_pixmap().samples


def test_edit_pdf_moves_underlined_fragment_with_exact_undo_save_and_reedit(tmp_path):
    data = _document()
    ids = _ids(data, 'ray')
    moved, report = edit_pdf(data, EditRequest(0, ids, dx=8, dy=20))
    assert report['rich_text_move'] and report['underlines_moved'] == 3
    _assert_displacement(data, moved, set(ids), 8, 20)
    history = History(data, directory=tmp_path)
    try:
        history.push(moved, report)
        assert history.undo() == data
        assert history.redo() == moved
        path = tmp_path/'fragmento.pdf'
        atomic_save(history.current, path)
    finally:
        history.close()
    reopened = path.read_bytes()
    _assert_displacement(data, reopened, set(ids), 8, 20)
    payload = selection_payload(reopened, 0, _ids(reopened, 'ray'))
    assert payload['text'] == 'ray'
    assert all(run['underline'] and run['char_spacing'] == .4 for run in payload['runs'])
    edited, _ = edit_rich_pdf(reopened, RichTextRequest(0, payload['ids'],
        [dict(run, underline=False) for run in payload['runs']], rect=payload['rect']))
    with fitz.open(stream=edited, filetype='pdf') as doc:
        assert len(doc[0].get_drawings()) == len('Subrayado')-len('ray')


def test_object_group_moves_image_then_underlined_text_and_reopens(tmp_path):
    data = _document()
    image = next(item for item in object_info(data, 0)['items'] if item['kind'] == 'image')
    text = dict(kind='text', ids=_ids(data, 'Subrayado'))
    # Image first changes the content stream before the rich text route runs.
    data, _ = group_pdf(data, 0, [image, text], name='Texto e imagen')
    group = object_info(data, 0)['groups'][0]
    moved, report = transform_objects_pdf(data, 0, group['items'], 'move', dx=9, dy=14)
    assert any(edit.get('rich_text_move') for edit in report['edits'])
    _assert_displacement(data, moved, set(text['ids']), 9, 14)
    path = tmp_path/'grupo.pdf'
    atomic_save(moved, path)
    reopened = path.read_bytes()
    group_after = object_info(reopened, 0)['groups'][0]
    assert group_after['valid']
    assert group_after['rect'] == pytest.approx(tuple(v+(9 if i%2 == 0 else 14)
                                                    for i,v in enumerate(group['rect'])), abs=.002)
    payload = selection_payload(reopened, 0, _ids(reopened, 'Subrayado'))
    assert all(run['underline'] and run['char_spacing'] == .4 for run in payload['runs'])
    with fitz.open(stream=data, filetype='pdf') as a, fitz.open(stream=reopened, filetype='pdf') as b:
        before, after = a[0].get_image_info(hashes=True)[0], b[0].get_image_info(hashes=True)[0]
        assert before['digest'] == after['digest']
        assert after['bbox'] == pytest.approx(tuple(v+(9 if i%2 == 0 else 14)
                                                   for i,v in enumerate(before['bbox'])), abs=.002)
