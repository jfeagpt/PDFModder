"""Un MCID anidado no pierde su cobertura semántica al reconstruir texto."""
from hashlib import sha256
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, FloatObject, NameObject, NumberObject, TextStringObject

from pdfmodder.engine import edit_pdf
from pdfmodder.model import EditError
from pdfmodder.tagged import analyze
from tagged_corpus import DATE_TEXT, dictionary, make_tagged_pdf
from test_engine import request_for, select


def nested_document(*, actual_text=False, parent_text=False):
    """ParentTree y /K son coherentes; el ámbito BDC3 contiene el BDC0."""
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    tree = writer._root_object['/StructTreeRoot']
    paragraph = tree['/K']['/K'][0].get_object()
    span = paragraph['/K']
    paragraph[NameObject('/K')] = ArrayObject([NumberObject(3), span.indirect_reference])
    tree['/ParentTree']['/Nums'][1].append(paragraph.indirect_reference)
    page = writer.pages[0]
    date = ContentStream(page['/Contents'][0], writer)
    properties = dictionary(MCID=NumberObject(3))
    if actual_text:
        properties[NameObject('/ActualText')] = TextStringObject(('PADRE' if parent_text else '') + DATE_TEXT)
    operations = [([NameObject('/Span'), properties], b'BDC')]
    if parent_text:
        font = next(key for key,value in page['/Resources']['/Font'].items()
                    if value.get_object().get('/BaseFont') == '/Helvetica')
        operations.extend([
            ([], b'BT'), ([font, NumberObject(10)], b'Tf'),
            ([NumberObject(1), NumberObject(0), NumberObject(0), NumberObject(1),
              NumberObject(48), FloatObject(float(page.mediabox.top)-80)], b'Tm'),
            ([TextStringObject('PADRE')], b'Tj'), ([], b'ET')])
    operations.extend(date.operations)
    operations.append(([], b'EMC'))
    date.operations = operations
    page['/Contents'][0] = writer._add_object(date)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize('actual_text', [False, True])
def test_nested_child_edit_blocks_with_or_without_ancestor_actualtext(actual_text):
    data = nested_document(actual_text=actual_text)
    before_hash = sha256(data).hexdigest()
    structure = analyze(data)
    assert structure.marks[0][3].nested_actual and structure.marks[0][0].nested_actual
    model, selected = select(data, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)anidad|inequívoca'):
        edit_pdf(data, request_for(model, selected, text='11/09/2026'))
    assert sha256(data).hexdigest() == before_hash


@pytest.mark.parametrize('actual_text', [False, True])
def test_nested_parent_with_visible_glyphs_cannot_be_reconstructed(actual_text):
    data = nested_document(actual_text=actual_text, parent_text=True)
    model, selected = select(data, 'PADRE', x=48, y=80)
    assert analyze(data).marks[0][3].nested_actual
    with pytest.raises(EditError, match=r'(?i)anidad|inequívoca'):
        edit_pdf(data, request_for(model, selected, dx=10, dy=5))


@pytest.mark.parametrize('actual_text', [False, True])
def test_nested_scope_does_not_block_unrelated_mcid_move(actual_text):
    data = nested_document(actual_text=actual_text, parent_text=True)
    before = analyze(data)
    model, selected = select(data, 'PALABRA', y=150)
    output, report = edit_pdf(data, request_for(model, selected, dx=10, dy=15))
    after = analyze(output)
    assert report['verified'] and before.semantic() == after.semantic()
    assert not after.marks[0][1].nested_actual
    assert after.marks[0][0].nested_actual and after.marks[0][3].nested_actual
    if actual_text:
        assert after.marks[0][3].resolved['/ActualText'] == 'PADRE'+DATE_TEXT
    _, moved = select(output, 'PALABRA', x=selected[0].origin[0]+10, y=165)
    assert len(moved) == len(selected)
    _, parent = select(output, 'PADRE', x=48, y=80)
    assert len(parent) == 5


@pytest.mark.parametrize('scope', ['outside', 'inside'])
@pytest.mark.parametrize('tag', ['/ReversedChars', '/CustomMeaning'])
def test_reversedchars_scope_blocks_affected_text_but_not_other_mcid(scope,tag):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_tagged_pdf())))
    page = writer.pages[0]
    stream = ContentStream(page['/Contents'][0], writer)
    start, end = ([NameObject(tag)], b'BMC'), ([], b'EMC')
    if scope == 'outside':
        stream.operations = [start, *stream.operations, end]
    else:
        stream.operations = [stream.operations[0], start, *stream.operations[1:-1], end, stream.operations[-1]]
    page['/Contents'][0] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    model, selected = select(data, '10/09/2026', x=100, y=100)
    with pytest.raises(EditError, match=r'(?i)anidad|inequívoca|ReversedChars'):
        edit_pdf(data, request_for(model, selected, text='11/09/2026'))
    model, selected = select(data, 'PALABRA', y=150)
    output, report = edit_pdf(data, request_for(model, selected, dx=10, dy=15))
    assert report['verified'] and analyze(data).semantic() == analyze(output).semantic()
    assert analyze(output).marks[0][0].nested_actual
    select(output, '10/09/2026', x=100, y=100)
