"""Real PDF edits and conservative colour-state regression coverage."""
from io import BytesIO

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject,
                          DictionaryObject, NameObject, NumberObject, NullObject)

from pdfmodder.engine import edit_pdf, extract_page
from pdfmodder.graphics_state import COLOR_ISSUE, BLEND_ISSUE
from pdfmodder.model import EditError, EditRequest
from pdfmodder.richmodels import RichTextRequest
from pdfmodder.richtext import edit_rich_pdf, selection_payload
from pdfmodder.validation import page_issues, trace_chars


def _pdf(states=None, prefix=b'/GS gs\n', suffix=b'', *, indirect=False, form=None):
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.draw_rect((20,20,380,100),color=None,fill=(.92,.96,.99))
        page.insert_text((35,50),'Fecha 2025',fontsize=12)
        page.insert_text((35,85),'VECINO 2025',fontsize=12)
        page.draw_line((20,110),(380,110),color=(.2,.3,.8))
        other = doc.new_page(width=400, height=300)
        other.insert_text((35,50),'CONTROL 2025',fontsize=12)
        data = doc.tobytes()
    writer = PdfWriter(clone_from=BytesIO(data))
    page = writer.pages[0]
    resources = page['/Resources']
    states = states if states is not None else {'/GS': {'/OP': BooleanObject(False), '/op': BooleanObject(False)}}
    entries = DictionaryObject()
    for name, values in states.items():
        dictionary = DictionaryObject({NameObject(k): v for k,v in values.items()})
        entries[NameObject(name)] = writer._add_object(dictionary) if indirect else dictionary
    resources[NameObject('/ExtGState')] = writer._add_object(entries) if indirect else entries
    if form:
        obj = DecodedStreamObject()
        obj.set_data(form)
        obj.update({NameObject('/Type'): NameObject('/XObject'),NameObject('/Subtype'): NameObject('/Form'),
                    NameObject('/BBox'):ArrayObject([NumberObject(v) for v in (0,0,400,300)]),
                    NameObject('/Resources'): writer._add_object(DictionaryObject({NameObject('/ExtGState'):entries}))})
        resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Form'):writer._add_object(obj)})
    if indirect:
        page[NameObject('/Resources')] = writer._add_object(resources)
    content = DecodedStreamObject()
    content.set_data(prefix+page.get_contents().get_data()+suffix)
    page[NameObject('/Contents')] = writer._add_object(content)
    buffer=BytesIO();writer.write(buffer)
    return buffer.getvalue()


def _select(data, text='2025'):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    joined=''.join(g.text for g in model.glyphs);start=joined.index(text)
    return model,[g for g in model.glyphs[start:start+len(text)]]


def _function():
    return DictionaryObject({NameObject('/FunctionType'):NumberObject(2),
                             NameObject('/N'):NumberObject(2),
                             NameObject('/Domain'):ArrayObject([NumberObject(0),NumberObject(1)])})


@pytest.mark.parametrize('values',[
    {'/OP':BooleanObject(False)}, {'/op':BooleanObject(False)},
    {'/OP':BooleanObject(False),'/op':BooleanObject(False),'/OPM':NumberObject(1)},
    {'/TR':NameObject('/Identity')}, {'/TR2':NameObject('/Identity')},
    {'/TR2':NameObject('/Default')},
    {'/TR':_function(),'/TR2':NameObject('/Default')},
    {'/TR':ArrayObject([NameObject('/Identity')]*4)},
    {'/BM':NameObject('/Compatible'),'/SMask':NameObject('/None')},
    {'/BM':ArrayObject([NameObject('/Normal'),NameObject('/Compatible')])},
    {'/OP':NullObject(),'/TR2':NullObject()},
])
def test_neutral_states_are_not_incompatibilities(values):
    assert page_issues(_pdf({'/GS':values},indirect=True),0)==[]


@pytest.mark.parametrize('values,issue',[
    ({'/OP':BooleanObject(True)},COLOR_ISSUE),
    ({'/op':BooleanObject(True)},COLOR_ISSUE),
    ({'/OP':BooleanObject(True),'/op':BooleanObject(False)},COLOR_ISSUE),
    ({'/TR':_function()},COLOR_ISSUE),
    ({'/TR2':_function()},COLOR_ISSUE),
    ({'/TR':NameObject('/Default')},COLOR_ISSUE), # Default is only valid in TR2.
    ({'/TR':NameObject('/Identity'),'/TR2':_function()},COLOR_ISSUE),
    ({'/BM':NameObject('/Multiply')},BLEND_ISSUE),
    ({'/BM':ArrayObject([NameObject('/Multiply'),NameObject('/Normal')])},BLEND_ISSUE),
    ({'/SMask':DictionaryObject({NameObject('/S'):NameObject('/Alpha')})},BLEND_ISSUE),
])
def test_effective_special_colour_is_still_blocked(values,issue):
    data=_pdf({'/GS':values});assert issue in page_issues(data,0)
    model,chosen=_select(data)
    with pytest.raises(EditError,match='sobreimpresión|mezcla'):
        edit_pdf(data,EditRequest(0,[g.id for g in chosen],text='2026',revision=model.revision))
    payload=selection_payload(data,0,[g.id for g in chosen])
    with pytest.raises(EditError,match='sobreimpresión|mezcla'):
        edit_rich_pdf(data,RichTextRequest(0,[g.id for g in chosen],[dict(payload['runs'][0],text='2026')],rect=payload['rect']))


@pytest.mark.parametrize('prefix',[
    b'', b'/Danger gs /Safe gs\n', b'q /Danger gs Q\n',
    b'/Danger gs /Safe gs q /Danger gs Q\n',
])
def test_unused_and_restored_states_do_not_block(prefix):
    states={'/Danger':{'/OP':BooleanObject(True),'/TR2':_function(),'/BM':NameObject('/Multiply')},
            '/Safe':{'/OP':BooleanObject(False),'/TR2':NameObject('/Default'),'/BM':NameObject('/Normal')}}
    assert page_issues(_pdf(states,prefix=prefix,indirect=True),0)==[]


@pytest.mark.parametrize('prefix',[
    b'/Danger gs /Partial gs\n',
    b'q /Danger gs 0 0 5 5 re f Q\n',
    b'/Danger gs /Safe gs q /Danger gs Q /Partial gs\n',
])
def test_inherited_partial_and_saved_states_are_not_ignored(prefix):
    states={'/Danger':{'/OP':BooleanObject(True)},'/Partial':{'/op':BooleanObject(False)},
            '/Safe':{'/OP':BooleanObject(True)}}
    assert COLOR_ISSUE in page_issues(_pdf(states,prefix=prefix),0)


def test_trailing_unsafe_state_is_blocked_for_append_paths():
    assert COLOR_ISSUE in page_issues(_pdf({'/Danger':{'/OP':BooleanObject(True)}},prefix=b'',suffix=b'\n/Danger gs'),0)


def test_form_inherits_parent_state_and_uses_its_own_resources():
    states={'/Danger':{'/op':BooleanObject(True)},'/Safe':{'/OP':BooleanObject(False)}}
    assert COLOR_ISSUE in page_issues(_pdf(states,prefix=b'/Danger gs /Form Do /Safe gs\n',form=b'0 0 4 4 re f'),0)
    assert COLOR_ISSUE in page_issues(_pdf(states,prefix=b'/Form Do\n',form=b'/Danger gs 0 0 4 4 re f'),0)
    assert page_issues(_pdf(states,prefix=b'/Form Do\n',form=b'/Danger gs /Safe gs 0 0 4 4 re f'),0)==[]


@pytest.mark.parametrize('route',['legacy','rich'])
def test_change_move_and_reopen_keep_neighbours_control_page_and_real_text(route):
    states={'/GS':{'/OP':BooleanObject(False),'/op':BooleanObject(False),'/TR2':NameObject('/Default')},
            '/Unused':{'/OP':BooleanObject(True),'/TR':_function()}}
    data=_pdf(states,indirect=True);model,chosen=_select(data);ids=[g.id for g in chosen]
    if route=='legacy':
        changed,report=edit_pdf(data,EditRequest(0,ids,text='2026',revision=model.revision))
    else:
        payload=selection_payload(data,0,ids)
        changed,report=edit_rich_pdf(data,RichTextRequest(0,ids,[dict(payload['runs'][0],text='2026')],rect=payload['rect']))
    assert report['verified'] and all(p['pixels_above_8']==0 for p in report['pages'])
    model,moved=_select(changed,'2026')
    result,movement=edit_pdf(changed,EditRequest(0,[g.id for g in moved],dx=70,dy=15,revision=model.revision))
    assert movement['verified'] and all(p['pixels_above_8']==0 for p in movement['pages'])
    with fitz.open(stream=data,filetype='pdf') as old,fitz.open(stream=result,filetype='pdf') as new:
        assert len(new[0].search_for('2026'))==1 and len(new[0].search_for('2025'))==1
        assert new[1].get_pixmap().samples==old[1].get_pixmap().samples
        selected={(g.text,g.origin) for g in chosen}
        actual=trace_chars(new[0])
        for char,origin,font,size in trace_chars(old[0]):
            if (char,origin) not in selected:
                assert any(c==char and f==font and abs(s-size)<.001 and max(abs(a-b) for a,b in zip(o,origin))<.035 for c,o,f,s in actual)
        for g in moved:
            assert sum(c==g.text and abs(o[0]-g.origin[0]-70)<.035 and abs(o[1]-g.origin[1]-15)<.035 for c,o,_,_ in actual)==1
        assert new[0].get_text().count('VECINO 2025')==1
    reader=PdfReader(BytesIO(result))
    assert '2026' in reader.pages[0].extract_text()
    assert 'CONTROL 2025' in reader.pages[1].extract_text()
    assert page_issues(result,0)==[]


def test_malformed_overprint_is_not_treated_as_false():
    assert any('No se pudo analizar' in s for s in page_issues(_pdf({'/GS':{'/OP':NumberObject(0)}}),0))
