"""Signature placement uses the displayed CropBox without changing selections."""
import pymupdf as fitz
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtWidgets import QGraphicsView

from pdfmodder.canvas import PdfCanvas
from pdfmodder.engine import extract_page, full_write


def make_canvas(qtbot, zoom=1., rotation=0):
    with fitz.open() as doc:
        page=doc.new_page(width=420,height=350)
        page.insert_text((85,110),'PRUEBA FIRMA',fontsize=16)
        page.set_cropbox((20,30,400,330))
        page.set_rotation(rotation)
        data=full_write(doc)
    with fitz.open(stream=data,filetype='pdf') as doc:
        model=extract_page(doc,0,data)
        png=doc[0].get_pixmap(matrix=fitz.Matrix(zoom,zoom)).tobytes('png')
    canvas=PdfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(260,220)
    canvas.set_page(png,model,zoom)
    canvas.show()
    qtbot.waitUntil(canvas.isVisible)
    return canvas


def displayed_point(canvas, point):
    return canvas.mapFromScene(QPointF(point[0]*canvas.zoom,point[1]*canvas.zoom))


def drag(qtbot, canvas, first, last):
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=first)
    qtbot.mouseMove(canvas.viewport(),pos=last)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=last)


@pytest.mark.parametrize('zoom,rotation,first,last',[
    (.75,0,(80,100),(160,150)),
    (1.5,90,(160,150),(80,100)),
    (2.,180,(80,150),(160,100)),
    (.75,270,(160,100),(80,150)),
])
def test_rectangle_coordinates_follow_displayed_rotated_crop_at_zoom_and_scroll(qtbot,zoom,rotation,first,last):
    canvas=make_canvas(qtbot,zoom,rotation)
    canvas.centerOn(QPointF(120*zoom,125*zoom))
    if zoom>1:
        assert canvas.horizontalScrollBar().value()>0 and canvas.verticalScrollBar().value()>0
    selected=[]
    canvas.signature_rectangle_selected.connect(selected.append)
    canvas.begin_signature_rectangle()
    assert canvas.cursor().shape()==Qt.CrossCursor
    drag(qtbot,canvas,displayed_point(canvas,first),displayed_point(canvas,last))
    assert len(selected)==1
    assert selected[0]==pytest.approx([80,100,160,150],abs=1./zoom)
    assert canvas.signature_rectangle_mode
    # Preview geometry is already rotated display space; no second rotation.
    rect=canvas._signature_rectangle_item.rect()
    assert [rect.left(),rect.top(),rect.right(),rect.bottom()]==pytest.approx(
        [value*zoom for value in selected[0]])


def test_drag_clamps_to_page_edges_and_outside_press_cannot_start(qtbot):
    canvas=make_canvas(qtbot,.5,90)
    canvas.resize(600,500)
    selected=[]
    canvas.signature_rectangle_selected.connect(selected.append)
    canvas.begin_signature_rectangle()
    first=displayed_point(canvas,(90,100))
    outside=displayed_point(canvas,(canvas.model.width+40,canvas.model.height+40))
    drag(qtbot,canvas,first,outside)
    assert selected==[[90.,100.,canvas.model.width,canvas.model.height]]
    drag(qtbot,canvas,displayed_point(canvas,(-10,20)),first)
    assert len(selected)==1


@pytest.mark.parametrize('zoom',[.5,2.])
def test_click_and_less_than_three_screen_pixels_do_not_submit(qtbot,zoom):
    canvas=make_canvas(qtbot,zoom)
    canvas.centerOn(QPointF(100*zoom,100*zoom))
    selected=[]
    canvas.signature_rectangle_selected.connect(selected.append)
    previous=[40.,45.,150.,140.]
    canvas.begin_signature_rectangle(previous)
    first=displayed_point(canvas,(100,100))
    qtbot.mouseClick(canvas.viewport(),Qt.LeftButton,pos=first)
    drag(qtbot,canvas,first,first+QPoint(2,20))
    assert not selected
    assert canvas.signature_rectangle==previous
    drag(qtbot,canvas,first,first+QPoint(3,3))
    assert len(selected)==1


@pytest.mark.parametrize('mode',['text','image','zone','placement'])
def test_signature_mode_preserves_selections_and_blocks_other_canvas_actions(qtbot,mode):
    canvas=make_canvas(qtbot)
    canvas.set_selection([canvas.model.glyphs[0].id])
    if mode=='image':
        canvas.set_images([{'id':'image','rect':(40.,45.,180.,140.),'editable':True}])
        canvas.select_image(canvas.images[0])
        canvas.image_mode=True
    elif mode=='zone':
        canvas.zone_mode=True
        canvas.zone_rect=(30.,35.,190.,160.)
    elif mode=='placement':
        canvas.placement_mode=True
    before=(canvas.ids[:],canvas.image_id,canvas.zone_rect,[g.origin for g in canvas.model.glyphs])
    other=[]
    for signal in (canvas.selection_changed,canvas.image_selected,canvas.move_requested,
                   canvas.text_resize_requested,canvas.edit_requested,canvas.placement_clicked,
                   canvas.zone_selected,canvas.image_transform_requested,canvas.image_rotate_requested,
                   canvas.delete_requested,canvas.image_delete_requested,canvas.arrow_requested):
        signal.connect(lambda *args:other.append(args))
    canvas.setDragMode(QGraphicsView.ScrollHandDrag)
    canvas.setCursor(Qt.SizeAllCursor)
    canvas.begin_signature_rectangle([180,140,40,45])
    assert canvas.signature_rectangle==[40.,45.,180.,140.]
    drag(qtbot,canvas,displayed_point(canvas,(40,45)),displayed_point(canvas,(160,140)))
    qtbot.keyClick(canvas,Qt.Key_Delete)
    qtbot.keyClick(canvas,Qt.Key_Return)
    qtbot.keyClick(canvas,Qt.Key_Right)
    qtbot.mouseDClick(canvas.viewport(),Qt.LeftButton,pos=displayed_point(canvas,(90,80)))
    canvas.end_signature_rectangle()
    assert not other
    assert (canvas.ids,canvas.image_id,canvas.zone_rect,[g.origin for g in canvas.model.glyphs])==before
    assert canvas.dragMode()==QGraphicsView.ScrollHandDrag
    assert canvas.cursor().shape()==Qt.SizeAllCursor
    assert canvas._signature_rectangle_item is None and not canvas.signature_rectangle_mode


def test_escape_cancels_before_release_and_restores_viewer_controls(qtbot):
    canvas=make_canvas(qtbot)
    canvas.image_mode=True
    canvas.setDragMode(QGraphicsView.ScrollHandDrag)
    canvas.setCursor(Qt.SizeAllCursor)
    selected=[];cancelled=[];other=[]
    canvas.signature_rectangle_selected.connect(selected.append)
    canvas.signature_rectangle_cancelled.connect(lambda:cancelled.append(True))
    canvas.cancel_requested.connect(lambda:other.append(True))
    canvas.begin_signature_rectangle()
    first,last=displayed_point(canvas,(40,45)),displayed_point(canvas,(160,140))
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=first)
    qtbot.mouseMove(canvas.viewport(),pos=last)
    qtbot.keyClick(canvas,Qt.Key_Escape)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=last)
    assert cancelled==[True] and not selected and not other
    assert not canvas.signature_rectangle_mode and canvas._signature_rectangle_item is None
    assert canvas.dragMode()==QGraphicsView.ScrollHandDrag
    assert canvas.cursor().shape()==Qt.SizeAllCursor
