"""Adversarial checks for the transaction boundaries, independent of the corpus."""
import io
from pathlib import Path
import hashlib
import pymupdf as fitz
import pytest
from pypdf import PdfReader
from pdfmodder.engine import edit_pdf, extract_page, atomic_save
from pdfmodder.model import EditRequest, EditError
from pdfmodder.history import History
from pdfmodder.validation import assert_characters, trace_chars


def sample():
    doc=fitz.open()
    p=doc.new_page()
    p.insert_text((50,100),'10/09/2026',fontsize=11.25)
    p.insert_text((220,100),'VECINO',fontsize=11.25)
    p.insert_text((50,180),'OTRO OTRO',fontsize=11.25)
    data=doc.tobytes()
    doc.close()
    return data


def ids_at(data,y,xmax=200):
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
    return model,[g.id for g in model.glyphs if abs(g.origin[1]-y)<.01 and g.origin[0]<xmax]


def test_stale_revision_rejected():
    original=sample()
    model,ids=ids_at(original,100)
    changed,_=edit_pdf(original,EditRequest(0,ids,text='11/09/2026',revision=model.revision))
    with pytest.raises(EditError,match='cambió desde'):
        edit_pdf(changed,EditRequest(0,ids,text='12/09/2026',revision=model.revision))


def test_redaction_never_runs_pending_annotations():
    doc=fitz.open(stream=sample(),filetype='pdf')
    doc[0].add_redact_annot((215,80,300,110))
    data=doc.tobytes()
    _,ids=ids_at(data,100)
    with pytest.raises(EditError,match='redacciones pendientes'):
        edit_pdf(data,EditRequest(0,ids,text='11/09/2026'))
    assert 'VECINO' in doc[0].get_text()


def test_shared_form_instances_are_explicitly_blocked():
    source=fitz.open(stream=sample(),filetype='pdf')
    target=fitz.open()
    for _ in range(2):
        page=target.new_page()
        page.show_pdf_page(page.rect,source,0)
    data=target.tobytes()
    model,ids=ids_at(data,100)
    with pytest.raises(EditError,match='Form XObjects'):
        edit_pdf(data,EditRequest(0,ids,text='11/09/2026'))


def test_neighbours_verified_even_inside_changed_envelope():
    before=fitz.open(stream=sample(),filetype='pdf')
    expected=trace_chars(before[0])
    altered=fitz.open()
    p=altered.new_page()
    p.insert_text((50,100),'10/09/2026',fontsize=11.25)
    p.insert_text((220,100),'VECINA',fontsize=11.25)
    p.insert_text((50,180),'OTRO OTRO',fontsize=11.25)
    with pytest.raises(EditError,match='carácter'):
        assert_characters(expected,p)


def test_exact_history_and_redo_branch_survive_disk_error(tmp_path,monkeypatch):
    hist=History(b'original',directory=tmp_path)
    hist.push(b'second',{'page':0})
    hist.push(b'third',{'page':0})
    hist.undo()
    original_write=Path.write_bytes
    def fail(path,data):
        if path.parent==hist.root:
            raise OSError('disk full')
        return original_write(path,data)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'write_bytes',fail)
        with pytest.raises(OSError): hist.push(b'fourth',None)
    assert hist.current==b'second'
    assert hist.redo()==b'third'
    assert hist.undo()==b'second'
    assert hist.undo()==b'original'
    hist.close()


def test_atomic_save_failure_preserves_existing_destination(tmp_path,monkeypatch):
    import pdfmodder.engine as engine
    data=sample()
    origin=tmp_path/'original.pdf'
    output=tmp_path/'output.pdf'
    origin.write_bytes(data)
    output.write_bytes(b'PREVIOUS DESTINATION')
    def fail(*args): raise PermissionError('locked target')
    monkeypatch.setattr(engine.os,'replace',fail)
    with pytest.raises(PermissionError): atomic_save(data,output,origin)
    assert origin.read_bytes()==data
    assert output.read_bytes()==b'PREVIOUS DESTINATION'
    assert not list(tmp_path.glob('.pdfmodder-*.pdf'))


def test_full_write_has_no_incremental_revision_and_reedits(tmp_path):
    data=sample()
    _,ids=ids_at(data,100)
    changed,_=edit_pdf(data,EditRequest(0,ids,text='11/09/2026'))
    path=tmp_path/'copy.pdf'
    atomic_save(changed,path)
    reader=PdfReader(path)
    assert '/Prev' not in reader.trailer
    assert '11/09/2026' in reader.pages[0].extract_text()
    reopened=path.read_bytes()
    _,ids=ids_at(reopened,100)
    again,_=edit_pdf(reopened,EditRequest(0,ids,text='12/09/2026'))
    text=PdfReader(io.BytesIO(again)).pages[0].extract_text()
    assert '12/09/2026' in text and '11/09/2026' not in text
    assert text.count('OTRO')==2


def test_single_character_deletion_keeps_neighbours():
    data=sample()
    model,ids=ids_at(data,100)
    changed,_=edit_pdf(data,EditRequest(0,[ids[1]],text=''))
    with fitz.open(stream=changed,filetype='pdf') as doc:
        actual=trace_chars(doc[0])
        assert len(actual)==len(model.glyphs)-1
        neighbours=[g for g in model.glyphs if g.id!=ids[1]]
        assert_characters([(g.text,g.origin,g.font,g.size) for g in neighbours],doc[0])


def test_character_selection_does_not_merge_columns():
    doc=fitz.open()
    p=doc.new_page()
    p.insert_text((40,70),'IZQUIERDA')
    p.insert_text((340,70),'DERECHA')
    model=extract_page(doc,0)
    ids=model.group(model.glyphs[0],'block')
    assert model.text(ids)=='IZQUIERDA'


def test_typographic_opacity_and_fractional_size_preserved():
    doc=fitz.open()
    p=doc.new_page()
    p.draw_rect((20,20,350,200),fill=(.3,.4,.2),color=None)
    p.insert_text((50,100),'10/09/2026',fontsize=11.375,color=(.7,.1,.2),fill_opacity=.6)
    data=doc.tobytes()
    model,ids=ids_at(data,100)
    changed,_=edit_pdf(data,EditRequest(0,ids,text='11/09/2026'))
    with fitz.open(stream=changed,filetype='pdf') as final:
        trace=final[0].get_texttrace()
        assert all(abs(s['opacity']-.6)<.001 and abs(s['size']-11.375)<.001 for s in trace)


def test_negative_permission_mask_and_empty_user_password_are_not_bypassed():
    from pdfmodder.validation import document_issues
    doc=fitz.open(stream=sample(),filetype='pdf')
    restricted=doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='owner-test',
                          user_pw='',permissions=fitz.PDF_PERM_PRINT)
    with fitz.open(stream=restricted,filetype='pdf') as opened:
        assert opened.permissions<0 and not opened.needs_pass
        issues=document_issues(restricted,opened)
    assert any('permiso' in message for message in issues)
    with pytest.raises(EditError,match='cifrado'):
        edit_pdf(restricted,EditRequest(0,[0],text='2'))
