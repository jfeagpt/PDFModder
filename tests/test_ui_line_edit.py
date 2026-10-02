"""Doble clic real, ajuste de línea y vista previa con un worker ocupado."""
from pathlib import Path
import re

import pymupdf
from pypdf import PdfReader
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage
import pytest

from pdfmodder.app import MainWindow
from pdfmodder.canvas import PdfCanvas
from pdfmodder.model import Glyph, PageModel, pt, union


@pytest.fixture
def line_canvas(qtbot):
    """Two independent columns; the first line has an unpainted word gap."""
    glyphs = []
    for line,text,x in ((0,"UNO",30.),(0,"DOS",95.),(1,"OTRO",235.)):
        for char in text:
            rect=(x,50.,x+10.,65.)
            glyphs.append(Glyph(len(glyphs),char,(x,62.),rect,rect,"Helvetica",12.,(0.,0.,0.),1.,line,line,line))
            x+=10.
    matrix=(1.,0.,0.,1.,0.,0.)
    model=PageModel(0,360.,180.,0,matrix,matrix,(0.,0.,360.,180.),glyphs,revision="fixture")
    image=QImage(360,180,QImage.Format_RGB32)
    image.fill(Qt.white)
    buffer=QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer,"PNG")
    canvas=PdfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(480,260)
    canvas.set_page(bytes(buffer.data()),model,1.)
    canvas.edit_requested.connect(lambda:canvas.start_editor(model.text(canvas.ids)))
    canvas.show()
    return canvas


def double_click_sequence(qtbot,canvas,pdf_point):
    point=canvas.viewport_point(pdf_point)
    # QTest.mouseDClick alone does not deliver the preceding mouse press that
    # used to clear the selection. Exercise the native event order explicitly.
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=point)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=point)
    qtbot.mouseDClick(canvas.viewport(),Qt.LeftButton,pos=point)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=point)


@pytest.mark.parametrize("point",[(45.,57.),(78.,57.)])
def test_double_click_keeps_selected_line_including_unpainted_gap(qtbot,line_canvas,point):
    canvas=line_canvas
    selected=[g.id for g in canvas.model.glyphs if g.line==0]
    canvas.set_selection(selected)
    double_click_sequence(qtbot,canvas,point)
    assert canvas.ids==selected
    assert canvas.editor.isVisible()
    assert canvas.editor.toPlainText()=="UNODOS"
    assert canvas.editor.hasFocus()


def test_double_click_without_selection_edits_word_and_never_other_column(qtbot,line_canvas):
    canvas=line_canvas
    double_click_sequence(qtbot,canvas,(105.,57.))
    assert canvas.editor.isVisible()
    assert canvas.editor.toPlainText()=="DOS"
    canvas.editor.hide()
    canvas.set_selection([g.id for g in canvas.model.glyphs if g.line==0])
    double_click_sequence(qtbot,canvas,(245.,57.))
    assert canvas.editor.toPlainText()=="OTRO"
    assert {g.line for g in canvas.model.selected(canvas.ids)}=={1}


def test_double_click_does_not_restore_disjoint_fragments(qtbot,line_canvas):
    canvas=line_canvas
    canvas.set_selection([0,2,3,4,5])
    double_click_sequence(qtbot,canvas,(45.,57.))
    assert canvas.editor.toPlainText()=="UNO"
    assert canvas.ids==[0,1,2]


@pytest.fixture
def line_window(qtbot,tmp_path):
    history=tmp_path/"history"
    history.mkdir()
    source=tmp_path/"line-original.pdf"
    with pymupdf.open() as doc:
        page=doc.new_page(width=420,height=300)
        page.draw_rect((40,50,370,105),color=(.2,.4,.6),fill=(.92,.96,.98),width=.5)
        # A justified sentence uses one real space per word boundary. Its
        # extra advance is geometric, unlike repeated spaces in table cells.
        x=60.
        for text in ("Inicio ","breve ","final"):
            page.insert_text((x,80),text,fontname="helv",fontsize=12)
            x+=pymupdf.get_text_length(text,fontname="helv",fontsize=12)+8.
        page.insert_text((60,145),"Vecino inmutable",fontname="helv",fontsize=12)
        other=doc.new_page(width=420,height=300)
        other.insert_text((60,80),"Pagina intacta",fontname="helv",fontsize=12)
        doc.save(source)
    window=MainWindow(config_path=tmp_path/"fonts.json",history_dir=history)
    window.thumbnail_timer.stop()
    qtbot.addWidget(window,before_close_func=lambda w:setattr(w,"_allow_close",True))
    window.show()
    window.open_document(source)
    settled(qtbot,window)
    yield window,source
    window._allow_close=True
    window.close()


def settled(qtbot,window):
    qtbot.waitUntil(lambda:not window.busy and not getattr(window,'_rich_loading',False)
                   and not getattr(window,'_rich_accept_pending',False)
                   and getattr(window,'_rich_pending',None) is None
                   and not (getattr(window,'_rich_active',False) and window._rich_timer.isActive()),timeout=30000)
    assert not window.last_error,window.last_error


def glyph_for(window,word):
    text="".join(g.text for g in window.model.glyphs)
    return window.model.glyphs[text.index(word)]


def center(glyph):
    return ((glyph.bbox[0]+glyph.bbox[2])/2,(glyph.bbox[1]+glyph.bbox[3])/2)


def test_line_adjustment_request_scope_and_explicit_full_line_area(qtbot,line_window):
    window,_=line_window
    glyph=glyph_for(window,"breve")
    window.canvas.set_selection(window.model.group(glyph,"word"))
    assert window.line_reflow_box.isChecked() and window.line_reflow_box.isEnabled()
    request=window._request(text="extenso",formatting=True,adjust_line=True)
    assert request.line_reflow
    assert request.width is request.height is request.size is None
    assert not window._request(dx=4.).line_reflow
    assert not window._request(text="extenso",formatting=True).line_reflow
    window.line_reflow_box.setChecked(False)
    assert not window._request(text="extenso",formatting=True,adjust_line=True).line_reflow
    window.line_reflow_box.setChecked(True)
    window.size_box.setValue(glyph.size+.25)
    assert not window._request(text="extenso",formatting=True,adjust_line=True).line_reflow
    window.size_box.setValue(glyph.size)
    window.reflow_box.setChecked(True)
    assert not window._request(text="extenso",formatting=True,adjust_line=True).line_reflow
    window.reflow_box.setChecked(False)
    assert not window._request(text="otra\nlínea",formatting=True,adjust_line=True).line_reflow

    whole_line=window.model.group(glyph,"line")
    window.canvas.set_selection(whole_line)
    window.width_box.setValue(window.width_box.value()+10.)
    request=window._request(text="Inicio extenso final",formatting=True,adjust_line=True)
    assert request.line_reflow and request.width==pytest.approx(pt(window.width_box.value()))
    assert request.height is not None
    window.canvas.set_selection([g.id for g in window.model.glyphs])
    assert not window.line_reflow_box.isEnabled()
    assert not window._request(text="otro texto",formatting=True,adjust_line=True).line_reflow


def test_legacy_line_preview_cancel_then_word_preview_during_thumbnail_commit_save(qtbot,line_window,tmp_path):
    window,source=line_window
    original=source.read_bytes()
    original_revision=window.model.revision
    first=glyph_for(window,"Inicio")
    line=window.model.group(first,"line")
    original_bounds=union(g.bbox for g in window.model.selected(line))
    window.canvas.set_selection(line)
    # The explicit legacy route retains justified-line redistribution and
    # its two-step preview. Rich editing is exercised by test_ui.py.
    window.start_legacy_edit()
    assert window.canvas.ids==line
    assert window.canvas.editor.isVisible()
    assert window.line_reflow_box.isEnabled()  # Can opt out while typing.
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,"Inicio amplio final")
    qtbot.keyClick(window.canvas.editor,Qt.Key_Return,modifier=Qt.ControlModifier)
    settled(qtbot,window)
    assert window.state["preview"] and window.state["history_index"]==0
    assert "amplio" in "".join(g.text for g in window.model.glyphs)
    qtbot.mouseClick(window.cancel_button,Qt.LeftButton)
    settled(qtbot,window)
    assert not window.state["preview"] and window.model.revision==original_revision
    assert "breve" in "".join(g.text for g in window.model.glyphs)

    # A real thumbnail request stays in flight from the controller's point of
    # view until polling resumes. No worker, result, or EditRequest is mocked.
    window.canvas.set_selection([])
    window.canvas._last_pointer_press=0.
    window._thumbnail_pages.clear()
    window.poller.stop()
    window._load_visible_thumbnail()
    assert window.busy and window._thumbnail_busy
    glyph=glyph_for(window,"breve")
    window.canvas.set_selection(window.model.group(glyph,'word'))
    window.start_legacy_edit()
    assert window.canvas.editor.isVisible()
    assert window.canvas.editor.toPlainText()=="breve"
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,"descartado")
    qtbot.keyClick(window.canvas.editor,Qt.Key_Return,modifier=Qt.ControlModifier)
    assert window._pending_text_preview is not None
    qtbot.keyClick(window.canvas.editor,Qt.Key_Escape)
    assert window._pending_text_preview is None
    assert not window.canvas.editor.isVisible()
    assert window.state["history_index"]==0

    window.start_legacy_edit()
    qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
    qtbot.keyClicks(window.canvas.editor,"extenso")
    qtbot.keyClick(window.canvas.editor,Qt.Key_Return,modifier=Qt.ControlModifier)
    assert window._pending_text_preview is not None
    assert window._pending_text_preview[0].line_reflow
    window.poller.start()
    settled(qtbot,window)
    assert window._pending_text_preview is None
    assert window.state["preview"] and window.state["history_index"]==0
    assert "extenso" in "".join(g.text for g in window.model.glyphs)
    qtbot.mouseClick(window.commit_button,Qt.LeftButton)
    settled(qtbot,window)
    assert window.state["history_index"]==1
    assert not window.state["preview"]
    output=tmp_path/"line-edited.pdf"
    window.save_as(output)
    settled(qtbot,window)
    assert source.read_bytes()==original
    reader=PdfReader(output,strict=True)
    extracted=re.sub(r"\s+"," ",reader.pages[0].extract_text())
    assert "Inicio extenso final" in extracted and "breve" not in extracted
    assert "Vecino inmutable" in extracted
    assert "Pagina intacta" in reader.pages[1].extract_text()
    with pymupdf.open(output) as doc,pymupdf.open(source) as before:
        assert doc[0].search_for("Inicio")[0].x0==pytest.approx(original_bounds[0],abs=.035)
        assert doc[0].search_for("final")[0].x1==pytest.approx(original_bounds[2],abs=.035)
        assert doc[1].get_pixmap().samples==before[1].get_pixmap().samples
    window.open_document(output)
    settled(qtbot,window)
    double_click_sequence(qtbot,window.canvas,center(glyph_for(window,"extenso")))
    qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=30000)
    assert window.canvas.editor.isVisible()
    assert window.canvas.editor.toPlainText()=="extenso"
    window.cancel()


def test_tagged_justified_word_can_be_edited_again_after_save_and_reopen(qtbot,line_window,tmp_path):
    """Wide justified gaps must not turn a word into the entire GUI line."""
    window,_=line_window
    source=Path(__file__).resolve().parents[1]/"examples"/"etiquetado.pdf"
    source_bytes=source.read_bytes()
    window.open_document(source)
    settled(qtbot,window)
    first=glyph_for(window,"PALABRA")
    original_line=window.model.selected(window.model.group(first,"line"))
    assert "".join(g.text for g in original_line)=="Mover PALABRA fin."
    original_bounds=union(g.bbox for g in original_line)
    saved_copies=[]

    # PALABRA -> VOZ creates substantially larger geometric spaces. Reopening
    # this first output previously left VOZ in a raw extraction line by itself,
    # so the GUI incorrectly sent its word width as the complete line width.
    for number,(old,new) in enumerate((("PALABRA","VOZ"),("VOZ","CANTO")),1):
        glyph=glyph_for(window,old)
        window.canvas.ensureVisible(window.canvas.scene_rect(glyph.bbox),20,20)
        point=window.canvas.viewport_point(center(glyph))
        window.mode_box.setCurrentIndex(window.mode_box.findData("line"))
        qtbot.mouseClick(window.canvas.viewport(),Qt.LeftButton,pos=point)
        assert window.model.text(window.canvas.ids)==f"Mover {old} fin."
        assert "10/09/2026" not in window.model.text(window.canvas.ids)

        window.mode_box.setCurrentIndex(window.mode_box.findData("word"))
        qtbot.mouseClick(window.canvas.viewport(),Qt.LeftButton,pos=window.canvas.viewport_point((10.,10.)))
        double_click_sequence(qtbot,window.canvas,center(glyph))
        qtbot.waitUntil(lambda:window.canvas.editor.isVisible(),timeout=30000)
        assert window.canvas.editor.isVisible()
        assert window.canvas.editor.toPlainText()==old
        assert window.model.text(window.canvas.ids)==old
        request=window._request(text=new,formatting=True,adjust_line=True)
        assert request.line_reflow and request.width is None and request.height is None
        qtbot.keyClick(window.canvas.editor,Qt.Key_A,modifier=Qt.ControlModifier)
        qtbot.keyClicks(window.canvas.editor,new)
        qtbot.keyClick(window.canvas.editor,Qt.Key_Return,modifier=Qt.ControlModifier)
        settled(qtbot,window)
        assert window.state["preview"] and window.state["history_index"]==0
        assert window.last_report["line_reflow"]
        assert window.last_report["accessibility"]["verified"]
        assert window.last_report["accessibility"]["logical_text_verified"]
        qtbot.mouseClick(window.commit_button,Qt.LeftButton)
        settled(qtbot,window)
        assert window.state["history_index"]==1 and not window.state["preview"]
        output=tmp_path/f"tagged-line-edit-{number}.pdf"
        window.save_as(output)
        settled(qtbot,window)
        assert source.read_bytes()==source_bytes
        assert all(path.read_bytes()==data for path,data in saved_copies)
        saved_copies.append((output,output.read_bytes()))

        independent=PdfReader(output,strict=True)
        assert f"Mover {new} fin." in re.sub(r"\s+"," ",independent.pages[0].extract_text())
        assert old not in independent.pages[0].extract_text()
        assert "10/09/2026" in independent.pages[1].extract_text()
        with pymupdf.open(output) as pdf,pymupdf.open(source) as before:
            assert pdf[0].search_for("Mover")[0].x0==pytest.approx(original_bounds[0],abs=.035)
            assert pdf[0].search_for("fin.")[0].x1==pytest.approx(original_bounds[2],abs=.035)
            assert pdf[0].search_for("10/09/2026")==before[0].search_for("10/09/2026")
            assert pdf[1].get_pixmap().samples==before[1].get_pixmap().samples
        window.open_document(output)
        settled(qtbot,window)
        assert not window.state.get("issues") and window.state["history_index"]==0
        updated=glyph_for(window,new)
        whole=window.model.group(updated,"line")
        assert window.model.text(whole)==f"Mover {new} fin."
        assert len({g.line for g in window.model.selected(whole)})==1
