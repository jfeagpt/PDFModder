"""Viewport border gestures: move frames, select inside, preserve resize handles."""
import pymupdf as fitz
import pytest
from PySide6.QtCore import QPoint, Qt

from pdfmodder.canvas import PdfCanvas
from pdfmodder.engine import extract_page, full_write
from pdfmodder.model import union


def make_canvas(qtbot, zoom=1., rotation=0):
    with fitz.open() as doc:
        page=doc.new_page(width=420,height=350)
        page.insert_text((85,110),'PRUEBA MOVIMIENTO TEXTO',fontsize=16)
        page.set_cropbox((20,30,400,330))
        page.set_rotation(rotation)
        data=full_write(doc)
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
        png=doc[0].get_pixmap(matrix=fitz.Matrix(zoom,zoom)).tobytes('png')
    canvas=PdfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(700,700)
    canvas.set_page(png,model,zoom)
    canvas.show()
    canvas.set_selection([g.id for g in model.glyphs])
    return canvas,png


def border_position(canvas):
    x0,y0,x1,y1=union(g.bbox for g in canvas.model.selected(canvas.ids))
    return (x0+(x1-x0)*.25,y0)


@pytest.mark.parametrize('zoom',[.75,1.5])
@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_selected_text_border_moves_in_pdf_coordinates_with_rotation_crop_and_zoom(qtbot,zoom,rotation):
    canvas,_=make_canvas(qtbot,zoom,rotation)
    selected=canvas.ids[:]
    origins=[g.origin for g in canvas.model.glyphs]
    moved=[];resized=[]
    canvas.move_requested.connect(lambda dx,dy:moved.append((dx,dy)))
    canvas.text_resize_requested.connect(resized.append)
    x,y=border_position(canvas)
    first,last=canvas.viewport_point((x,y)),canvas.viewport_point((x+24,y+16))
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=first)
    assert canvas._border_move and not canvas._text_resize
    qtbot.mouseMove(canvas.viewport(),pos=last)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=last)
    assert len(moved)==1 and moved[0]==pytest.approx((24,16),abs=1.4)
    assert not resized and canvas.ids==selected
    assert [g.origin for g in canvas.model.glyphs]==origins
    assert not canvas._border_move and canvas._press is None


@pytest.mark.parametrize('zoom',[.75,1.5])
def test_border_tolerance_is_viewport_pixels_and_handles_keep_priority(qtbot,zoom):
    canvas,_=make_canvas(qtbot,zoom)
    rect=union(g.bbox for g in canvas.model.selected(canvas.ids))
    start=canvas.viewport_point(border_position(canvas))
    assert canvas._border_at(rect,start+QPoint(0,3))
    assert not canvas._border_at(rect,start-QPoint(0,5))
    handle=canvas.viewport_point((rect[2],rect[3]))
    moved=[];resized=[]
    canvas.move_requested.connect(lambda *value:moved.append(value))
    canvas.text_resize_requested.connect(resized.append)
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=handle)
    assert canvas._text_resize=='se' and not canvas._border_move
    end=canvas.viewport_point((rect[2]+20,rect[3]+10))
    qtbot.mouseMove(canvas.viewport(),pos=end)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=end)
    assert not moved and len(resized)==1
    assert resized[0][2:]==pytest.approx((rect[2]+20,rect[3]+10),abs=1.4)


def test_drag_inside_selected_text_still_selects_characters(qtbot):
    canvas,_=make_canvas(qtbot,1.5)
    canvas.mode='character'
    moved=[]
    canvas.move_requested.connect(lambda *value:moved.append(value))
    first,last=[canvas.model.glyphs[n] for n in (1,4)]
    center=lambda glyph:canvas.viewport_point(((glyph.bbox[0]+glyph.bbox[2])/2,(glyph.bbox[1]+glyph.bbox[3])/2))
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=center(first))
    assert not canvas._border_move
    qtbot.mouseMove(canvas.viewport(),pos=center(last))
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=center(last))
    assert not moved
    assert canvas.ids==[g.id for g in canvas.model.glyphs[1:5]]


@pytest.mark.parametrize('cancel',['escape','page','application_cancel'])
def test_cancelled_border_gesture_never_emits_move_on_release(qtbot,cancel):
    canvas,png=make_canvas(qtbot)
    moved=[]
    canvas.move_requested.connect(lambda *value:moved.append(value))
    x,y=border_position(canvas)
    first,last=canvas.viewport_point((x,y)),canvas.viewport_point((x+30,y+20))
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=first)
    qtbot.mouseMove(canvas.viewport(),pos=last)
    assert canvas._border_move and canvas._drag
    if cancel=='escape':
        qtbot.keyClick(canvas,Qt.Key_Escape)
    elif cancel=='page':
        canvas.set_page(png,canvas.model,canvas.zoom)
    else:
        # Existing MainWindow.cancel clears pointers then redraws overlays.
        canvas._press=canvas._drag=None
        canvas._draw_overlays()
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=last)
    assert not moved and not canvas._border_move


def test_read_only_selection_cannot_start_border_move(qtbot):
    canvas,_=make_canvas(qtbot)
    canvas.read_only=True
    moved=[]
    canvas.move_requested.connect(lambda *value:moved.append(value))
    x,y=border_position(canvas)
    first,last=canvas.viewport_point((x,y)),canvas.viewport_point((x+30,y+20))
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=first)
    qtbot.mouseMove(canvas.viewport(),pos=last)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=last)
    assert not moved and not canvas._border_move
