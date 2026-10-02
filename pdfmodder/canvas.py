"""Superficie de selección; sólo consume geometría y un PNG del proceso PDF."""
from time import monotonic
import math

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QPixmap, QKeyEvent, QPolygonF
from PySide6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene

from .model import transform, transform_rect, union
from .rich_editor import PageEditor


def resize_rect(rect, handle, delta, keep_ratio=False):
    """Resize in unrotated PDF coordinates, anchoring the opposite edge."""
    x0, y0, x1, y1 = rect
    dx, dy = delta
    width, height = x1-x0, y1-y0
    left, right = 'w' in handle, 'e' in handle
    top, bottom = 'n' in handle, 's' in handle
    new_width = max(1., width + (dx if right else -dx if left else 0.))
    new_height = max(1., height + (dy if bottom else -dy if top else 0.))
    if keep_ratio:
        sx, sy = new_width / width, new_height / height
        # Use the axis with the larger fractional user displacement for
        # corners. Side handles resize symmetrically around the other axis.
        scale = (sx if abs(sx-1.) >= abs(sy-1.) else sy) if (left or right) and (top or bottom) else sx if left or right else sy
        scale = max(scale, 1./min(width, height))
        new_width, new_height = width*scale, height*scale
    if left:
        x0 = x1-new_width
    elif right:
        x1 = x0+new_width
    elif keep_ratio:
        center = (x0+x1)/2
        x0, x1 = center-new_width/2, center+new_width/2
    if top:
        y0 = y1-new_height
    elif bottom:
        y1 = y0+new_height
    elif keep_ratio:
        center = (y0+y1)/2
        y0, y1 = center-new_height/2, center+new_height/2
    return x0, y0, x1, y1


class PdfCanvas(QGraphicsView):
    selection_changed = Signal(object)
    wheel_page_requested = Signal(int)
    move_requested = Signal(float, float)
    edit_requested = Signal()
    preview_text = Signal(str)
    cancel_requested = Signal()
    delete_requested = Signal()
    arrow_requested = Signal(int, int, bool)
    placement_clicked = Signal(float,float)
    image_selected = Signal(object)
    image_transform_requested = Signal(str,object)
    image_rotate_requested = Signal(str,float)
    image_delete_requested = Signal(str)
    zone_selected = Signal(object)
    image_context_requested = Signal(str,object)
    text_context_requested = Signal(object)
    rich_changed = Signal(object)
    rich_accept = Signal(object)
    text_resize_requested = Signal(object)
    signature_rectangle_selected = Signal(object)
    signature_rectangle_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pdfCanvas")
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#626b76"))
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.model = None
        self.zoom = 1.
        self.ids = []
        self.mode = "word"
        self._reading_mode = False
        self.page_navigation_enabled = False
        self._reading_anchor = None
        self._reading_press_pos = None
        self._reading_dragging = False
        self.image_mode=False
        self.zone_mode=False
        self.zone_rect=None
        self._zone_start=None
        self.placement_mode=False
        self.signature_rectangle_mode=False
        self.signature_rectangle=None
        self._signature_rectangle_item=None
        self._signature_rectangle_start=None
        self._signature_rectangle_before_drag=None
        self._signature_rectangle_view_state=None
        self._signature_rectangle_pointer_down=False
        self._signature_rectangle_ignore_release=False
        self.images=[]
        self.image_id=None
        self.lock_image_ratio=True
        self._image_drag_rect=None
        self._image_resize=False
        self._image_rotate=False
        self._image_rotate_angle=None
        self._text_resize=None
        self._text_resize_rect=None
        self._edit_click_pdf=None
        self._editor_bounds=None
        self._pixmap_item=None
        self._editor_proxy=None
        self.interaction_mode='select'
        self.read_only = False
        # A thumbnail may be rendering in the PDF process while this local
        # typing session starts. It never replaces the displayed PageModel.
        self.allow_background_edit = False
        self.show_guides = True
        self.changes = []
        self.highlight_changes = False
        self.search_rects = []
        self.overlays = []
        self._press = None
        self._press_scene = None
        self._drag = None
        self._border_move = False
        self._anchor_id = None
        self._selection_drag_anchor = None
        self._click_selection_before = None
        self._click_revision = None
        self._last_pointer_press = 0.
        self.editor = PageEditor(self.viewport())
        self.editor.setObjectName("onPageEditor")
        self.editor.setToolTip("Escribir · Ctrl+Intro: aceptar · Escape: cancelar · Mayús+Intro: salto de línea")
        self.editor.preview.connect(self.preview_text)
        self.editor.cancelled.connect(self.cancel_requested)
        self.editor.rich_changed.connect(self.rich_changed)
        self.editor.rich_changed.connect(lambda _: self._place_editor())
        self.editor.rich_accept.connect(self.rich_accept)
        self.editor.hide()
        self.horizontalScrollBar().valueChanged.connect(self._place_editor)
        self.verticalScrollBar().valueChanged.connect(self._place_editor)

    def set_page(self, png, model, zoom, changes=None):
        self.end_signature_rectangle()
        self._press = self._press_scene = self._drag = None
        self._reading_anchor = self._reading_press_pos = None
        self._reading_dragging = False
        self._border_move = False
        self._text_resize = self._text_resize_rect = None
        self._image_resize = self._image_rotate = False
        self._image_drag_rect = self._image_rotate_angle = None
        self.zone_rect=None
        self._zone_start=None
        self.editor.hide()
        self._release_editor_proxy()
        self.scene().clear()
        self.overlays = []
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, "PNG"):
            raise ValueError("No se pudo mostrar la página renderizada.")
        self._pixmap_item=self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.model, self.zoom = model, zoom
        self.ids = []
        self._anchor_id = None
        self._click_selection_before = None
        self._click_revision = None
        self._last_pointer_press = 0.
        self._editor_bounds=None
        self.changes = changes or []
        self._draw_overlays()
        return pixmap

    def _release_editor_proxy(self):
        if self._editor_proxy is not None:
            proxy=self._editor_proxy
            self._editor_proxy=None
            proxy.setWidget(None)
            self.editor.setParent(self.viewport())
            self.scene().removeItem(proxy)
            proxy.deleteLater()

    def _event_in_proxy(self, point):
        return self._editor_proxy is not None and self._editor_proxy.contains(
            self._editor_proxy.mapFromScene(self.mapToScene(point)))

    def set_live_preview(self, png, status=None):
        """Update the worker-rendered PDF behind the active typing session."""
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, 'PNG'):
            raise ValueError('No se pudo mostrar la previsualización del PDF.')
        if self._pixmap_item is not None:
            self._pixmap_item.setPixmap(pixmap)
        if status is not None:
            self.editor.toolbar.status.setText('\n'.join(x for x in (self.editor.font_warning, status) if x))

    def set_interaction_mode(self, mode):
        if mode not in ('select', 'write', 'move'):
            raise ValueError('Modo de interacción desconocido.')
        self.interaction_mode=mode
        self._border_move=False
        self.setCursor(Qt.IBeamCursor if self.reading_mode or mode=='write' else Qt.SizeAllCursor if mode=='move' else Qt.ArrowCursor)
        self.setToolTip({'select':'Seleccionar · arrastra letras dentro del texto · arrastra el borde para mover · doble clic para escribir',
                         'write':'Escribir · pulsa el texto para situar el cursor',
                         'move':'Mover · arrastra la selección o usa las flechas'}[mode])

    @property
    def reading_mode(self):
        return self._reading_mode

    @reading_mode.setter
    def reading_mode(self, enabled):
        self._reading_mode = bool(enabled)
        # Switching workspaces cannot finish a gesture begun in the other one.
        self._reading_anchor = self._reading_press_pos = None
        self._reading_dragging = False
        self._press = self._press_scene = self._drag = None
        self._border_move = False
        self._text_resize = self._text_resize_rect = None
        self._image_resize = self._image_rotate = False
        self._image_drag_rect = self._image_rotate_angle = None
        if hasattr(self,'interaction_mode'):
            self.setCursor(Qt.IBeamCursor if enabled else Qt.SizeAllCursor if self.interaction_mode=='move'
                           else Qt.IBeamCursor if self.interaction_mode=='write' else Qt.ArrowCursor)
        if hasattr(self,'overlays'):
            self._draw_overlays()

    def _reading_lines(self, block=None):
        """Visible reading segments, splitting wide gaps inside one PDF line.

        Extraction/painting order is not reading order. A generator can also
        put two table columns in one line, so block identity alone is not a
        sufficient boundary for a dragged range.
        """
        if not self.model:
            return []
        groups={}
        for glyph in self.model.glyphs:
            if glyph.mode==3 or glyph.opacity<=0 or block is not None and glyph.block!=block:
                continue
            groups.setdefault((glyph.block,glyph.line,glyph.mode),[]).append(glyph)
        lines=[]
        for group in groups.values():
            group.sort(key=lambda glyph:(glyph.bbox[0],glyph.origin[0],glyph.id))
            part=[]
            for glyph in group:
                if part and glyph.bbox[0]-part[-1].bbox[2]>max(12.,2.5*max(glyph.size,part[-1].size)):
                    lines.append(part);part=[]
                part.append(glyph)
            if part:lines.append(part)
        return sorted(lines,key=lambda line:(min(g.bbox[1] for g in line),min(g.bbox[0] for g in line),line[0].id))

    def _reading_column(self, anchor):
        lines=self._reading_lines(anchor.block)
        initial=next((line for line in lines if any(g.id==anchor.id for g in line)),None)
        if initial is None:return []
        bounds=union(g.bbox for g in initial)
        column=[]
        for line in lines:
            if line[0].mode!=anchor.mode:continue
            rect=union(g.bbox for g in line)
            overlap=min(bounds[2],rect[2])-max(bounds[0],rect[0])
            if overlap>0 or abs(rect[0]-bounds[0])<=max(1.,anchor.size*.5):
                column.append(line)
        return column

    def _reading_word(self, hit):
        line=next((line for line in self._reading_lines(hit.block) if any(g.id==hit.id for g in line)),[])
        if not line:return []
        index=next(i for i,g in enumerate(line) if g.id==hit.id)
        if hit.text.isspace():return [hit.id]
        left=right=index
        while left>0 and not line[left-1].text.isspace():
            if line[left].bbox[0]-line[left-1].bbox[2]>hit.size*.65:break
            left-=1
        while right+1<len(line) and not line[right+1].text.isspace():
            if line[right+1].bbox[0]-line[right].bbox[2]>hit.size*.65:break
            right+=1
        return [g.id for g in line[left:right+1]]

    def _reading_range(self, point):
        anchor=next((g for g in self.model.glyphs if g.id==self._reading_anchor),None)
        if anchor is None:return []
        lines=self._reading_column(anchor)
        if not lines:return []
        # A drag into whitespace or a neighbouring column stops at the nearest
        # character of the starting column instead of sweeping that neighbour.
        x,y=point
        def line_distance(line):
            rect=union(g.bbox for g in line)
            return max(rect[1]-y,0.,y-rect[3]),abs((rect[1]+rect[3])/2-y)
        target_line=min(lines,key=line_distance)
        target=min(target_line,key=lambda g:(max(g.bbox[0]-x,0.,x-g.bbox[2]),abs((g.bbox[0]+g.bbox[2])/2-x)))
        ordered=[g for line in lines for g in line]
        first=next(i for i,g in enumerate(ordered) if g.id==anchor.id)
        last=next(i for i,g in enumerate(ordered) if g.id==target.id)
        lo,hi=sorted((first,last))
        return [g.id for g in ordered[lo:hi+1]]

    def reading_text(self):
        """Extract a selection locally without font resolution or a PDF edit."""
        chosen=set(self.ids)
        parts=[]
        for line in self._reading_lines():
            text=''.join(g.text for g in line if g.id in chosen)
            if text:parts.append(text)
        return '\n'.join(parts)

    def pdf_point(self, viewport_point):
        scene = self.mapToScene(viewport_point)
        return transform((scene.x()/self.zoom, scene.y()/self.zoom), self.model.derotation_matrix)

    def viewport_point(self, pdf_point):
        x, y = transform(pdf_point, self.model.rotation_matrix)
        return self.mapFromScene(QPointF(x*self.zoom, y*self.zoom))

    def scene_rect(self, rect):
        x0, y0, x1, y1 = transform_rect(rect, self.model.rotation_matrix)
        return QRectF(x0*self.zoom, y0*self.zoom, (x1-x0)*self.zoom, (y1-y0)*self.zoom)

    def begin_signature_rectangle(self, rect=None):
        """Draw in displayed, rotated CropBox-local points, with a top-left origin."""
        if not self.signature_rectangle_mode:
            self._signature_rectangle_view_state=(self.dragMode(),self.cursor())
        self.signature_rectangle_mode=True
        self._signature_rectangle_start=None
        self._signature_rectangle_before_drag=None
        self._signature_rectangle_pointer_down=False
        self._signature_rectangle_ignore_release=False
        self._press=self._press_scene=self._drag=None
        self._border_move=False
        self._text_resize=self._text_resize_rect=None
        self._image_resize=self._image_rotate=False
        self._image_drag_rect=self._image_rotate_angle=None
        self._zone_start=None
        self.signature_rectangle=self._normalized_signature_rectangle(rect) if rect is not None and self.model else None
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.CrossCursor)
        self.setFocus()
        self._draw_overlays()
        self._draw_signature_rectangle()

    def end_signature_rectangle(self):
        """Remove the signature preview and restore the previous viewer controls."""
        if self.signature_rectangle_mode and self._signature_rectangle_pointer_down:
            self._signature_rectangle_ignore_release=True
        if self._signature_rectangle_item is not None:
            self.scene().removeItem(self._signature_rectangle_item)
            self._signature_rectangle_item=None
        self.signature_rectangle_mode=False
        self.signature_rectangle=None
        self._signature_rectangle_start=None
        self._signature_rectangle_before_drag=None
        self._signature_rectangle_pointer_down=False
        if self._signature_rectangle_view_state is not None:
            drag_mode,cursor=self._signature_rectangle_view_state
            self._signature_rectangle_view_state=None
            self.setDragMode(drag_mode)
            self.setCursor(cursor)

    def _signature_display_point(self, viewport_point, clamp=False):
        scene=self.mapToScene(viewport_point)
        x,y=scene.x()/self.zoom,scene.y()/self.zoom
        if clamp:
            x=max(0.,min(self.model.width,x))
            y=max(0.,min(self.model.height,y))
        return x,y

    def _normalized_signature_rectangle(self, rect):
        x0,y0,x1,y1=map(float,rect)
        x0,x1=sorted((max(0.,min(self.model.width,x0)),max(0.,min(self.model.width,x1))))
        y0,y1=sorted((max(0.,min(self.model.height,y0)),max(0.,min(self.model.height,y1))))
        return [x0,y0,x1,y1]

    def _draw_signature_rectangle(self):
        if self.signature_rectangle is None:
            if self._signature_rectangle_item is not None:
                self.scene().removeItem(self._signature_rectangle_item)
                self._signature_rectangle_item=None
            return
        x0,y0,x1,y1=self.signature_rectangle
        scene_rect=QRectF(x0*self.zoom,y0*self.zoom,(x1-x0)*self.zoom,(y1-y0)*self.zoom)
        if self._signature_rectangle_item is None:
            pen=QPen(QColor('#007cc2'),1.5,Qt.DashLine)
            pen.setCosmetic(True)
            self._signature_rectangle_item=self.scene().addRect(scene_rect,pen,QBrush(QColor('#330099dd')))
            self._signature_rectangle_item.setZValue(20)
        else:
            self._signature_rectangle_item.setRect(scene_rect)

    def _update_signature_rectangle(self, viewport_point):
        point=self._signature_display_point(viewport_point,clamp=True)
        self.signature_rectangle=self._normalized_signature_rectangle((*self._signature_rectangle_start,*point))
        self._draw_signature_rectangle()

    def _signature_rectangle_large_enough(self):
        x0,y0,x1,y1=self.signature_rectangle
        first=self.viewportTransform().map(QPointF(x0*self.zoom,y0*self.zoom))
        last=self.viewportTransform().map(QPointF(x1*self.zoom,y1*self.zoom))
        return abs(last.x()-first.x())>=3. and abs(last.y()-first.y())>=3.

    def set_selection(self, ids, notify=True):
        allowed = {g.id for g in self.model.glyphs} if self.model else set()
        self.ids = sorted(set(ids) & allowed)
        if self.ids:
            self.image_id=None
            self.image_selected.emit(None)
        self._draw_overlays()
        if notify:
            self.selection_changed.emit(self.ids)

    def set_images(self,items,restore_rect=None):
        self.images=items
        self.image_id=None
        if restore_rect:
            item=next((im for im in reversed(items) if all(abs(a-b)<.06 for a,b in zip(im['rect'],restore_rect))),None)
            if item:
                self.image_id=item['id']
        self.image_selected.emit(self.selected_image())
        self._draw_overlays()

    def selected_image(self):
        return next((im for im in self.images if im['id']==self.image_id),None)

    def select_image(self,item):
        self.set_selection([])
        self.image_id=item['id'] if item else None
        self.image_selected.emit(item)
        self._draw_overlays()

    def _rect_item(self, rect, color, fill=None, dashed=False):
        pen = QPen(QColor(color), 1.)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.DashLine)
        item = self.scene().addRect(self.scene_rect(rect), pen, QBrush(QColor(fill)) if fill else QBrush(Qt.NoBrush))
        item.setZValue(2)
        self.overlays.append(item)

    @staticmethod
    def handle_points(rect):
        x0,y0,x1,y1=rect
        cx,cy=(x0+x1)/2,(y0+y1)/2
        return {'nw':(x0,y0),'n':(cx,y0),'ne':(x1,y0),'e':(x1,cy),
                'se':(x1,y1),'s':(cx,y1),'sw':(x0,y1),'w':(x0,cy)}

    def _handle_at(self, rect, viewport_point):
        matches=[]
        for name,point in self.handle_points(rect).items():
            distance=(viewport_point-self.viewport_point(point)).manhattanLength()
            if distance<=6:
                matches.append((distance,name))
        return min(matches)[1] if matches else None

    def _border_at(self, rect, viewport_point, tolerance=3.5):
        """Hit a selected frame in viewport pixels, independent of zoom/rotation.

        Handles take precedence at the caller. Measuring segment distance also
        works for transformed page coordinates without growing the PDF region
        as the user zooms out. The frame interior remains text selection space.
        """
        x0,y0,x1,y1=rect
        corners=[self.viewport_point(point) for point in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
        px,py=viewport_point.x(),viewport_point.y()
        for first,last in zip(corners,corners[1:]+corners[:1]):
            vx,vy=last.x()-first.x(),last.y()-first.y()
            length_squared=vx*vx+vy*vy
            position=max(0.,min(1.,((px-first.x())*vx+(py-first.y())*vy)/length_squared)) if length_squared else 0.
            dx,dy=px-(first.x()+position*vx),py-(first.y()+position*vy)
            if dx*dx+dy*dy<=tolerance*tolerance:
                return True
        return False

    def _rotation_handle_position(self, rect):
        """Keep the circular rotation grip 24 screen pixels above the frame."""
        cx, cy = (rect[0]+rect[2])/2, (rect[1]+rect[3])/2
        anchor = QPointF(self.viewport_point((cx, rect[1])))
        center = QPointF(self.viewport_point((cx, cy)))
        dx, dy = anchor.x()-center.x(), anchor.y()-center.y()
        length = math.hypot(dx, dy) or 1.
        return anchor + QPointF(dx/length*24., dy/length*24.)

    def _rotation_handle_at(self, rect, viewport_point):
        delta = QPointF(viewport_point)-self._rotation_handle_position(rect)
        return delta.x()*delta.x()+delta.y()*delta.y() <= 81.

    def _draw_rotation_handle(self, rect):
        anchor = self.mapToScene(self.viewport_point(((rect[0]+rect[2])/2, rect[1])))
        grip = self.mapToScene(self._rotation_handle_position(rect).toPoint())
        pen = QPen(QColor('#007cc2'), 1.5)
        line = self.scene().addLine(anchor.x(), anchor.y(), grip.x(), grip.y(), pen)
        circle = self.scene().addEllipse(grip.x()-5., grip.y()-5., 10., 10.,
                                        QPen(QColor('white')), QBrush(QColor('#007cc2')))
        circle.setToolTip('Girar imagen · arrastra · Mayús: pasos de 15° · Escape: cancelar')
        for item in (line, circle):
            item.setZValue(4)
            self.overlays.append(item)

    def _draw_rotation_gesture(self, rect, angle):
        cx, cy = (rect[0]+rect[2])/2, (rect[1]+rect[3])/2
        cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        points = []
        for x, y in ((rect[0],rect[1]),(rect[2],rect[1]),(rect[2],rect[3]),(rect[0],rect[3])):
            point = (cx+(x-cx)*cosine-(y-cy)*sine, cy+(x-cx)*sine+(y-cy)*cosine)
            points.append(self.mapToScene(self.viewport_point(point)))
        item = self.scene().addPolygon(QPolygonF(points), QPen(QColor('#21ba82'), 1.5, Qt.DashLine))
        item.setZValue(4)
        label = self.scene().addText(f'{angle:+.1f}°')
        label.setDefaultTextColor(QColor('#006945'))
        label.setPos(points[0])
        label.setZValue(4)
        self.overlays.extend((item, label))

    def _draw_handles(self, rect, color='#007cc2'):
        for point in self.handle_points(rect).values():
            x,y=transform(point,self.model.rotation_matrix)
            item=self.scene().addRect(x*self.zoom-3.5,y*self.zoom-3.5,7,7,
                                     QPen(QColor('#ffffff')),QBrush(QColor(color)))
            item.setZValue(3)
            self.overlays.append(item)

    def _draw_overlays(self):
        if self._press is None:
            self._border_move=False
        for item in self.overlays:
            self.scene().removeItem(item)
        self.overlays = []
        if not self.model:
            return
        if self.zone_rect:self._rect_item(self.zone_rect,'#aa44bb','#11aa44bb',True)
        if self.highlight_changes:
            for rect in self.changes:
                self._rect_item(rect, "#e08b00", "#22ffba30", True)
        for rect in self.search_rects:
            self._rect_item(rect, "#a88500", "#55ffdb00")
        selected = self.model.selected(self.ids)
        for glyph in selected:
            self._rect_item(glyph.bbox, "#007cc2", "#440099dd")
        if selected and self.show_guides and not self.reading_mode:
            bounds = self._text_resize_rect or union(g.bbox for g in selected)
            self._rect_item(bounds, "#007cc2", None, True)
            if not self.read_only and not self.editor.isVisible():
                self._draw_handles(bounds)
            r = self.scene_rect(bounds)
            pen = QPen(QColor("#55c3d5e1"), 1., Qt.DashLine)
            for x in (r.left(), r.right()):
                item = self.scene().addLine(x, 0, x, self.scene().height(), pen)
                self.overlays.append(item)
        if self._drag and selected:
            dx,dy = self._drag
            bounds = union(g.bbox for g in selected)
            moved = (bounds[0]+dx,bounds[1]+dy,bounds[2]+dx,bounds[3]+dy)
            self._rect_item(moved, "#21ba82", "#3321ba82", True)
        selected_image=self.selected_image()
        if selected_image:
            rect=self._image_drag_rect or selected_image['rect']
            self._rect_item(rect,'#007cc2',None,True)
            if not self.reading_mode and not self.read_only and selected_image.get('editable'):
                self._draw_handles(rect)
                self._draw_rotation_handle(rect)
            if self._image_rotate_angle is not None:
                self._draw_rotation_gesture(rect, self._image_rotate_angle)

    def mousePressEvent(self, event):
        self._signature_rectangle_ignore_release=False
        if self.signature_rectangle_mode:
            if event.button()==Qt.LeftButton:
                self._signature_rectangle_pointer_down=True
            if self.model and event.button()==Qt.LeftButton:
                point=self._signature_display_point(event.position().toPoint())
                if 0.<=point[0]<=self.model.width and 0.<=point[1]<=self.model.height:
                    self._signature_rectangle_before_drag=self.signature_rectangle
                    self._signature_rectangle_start=point
                    self.signature_rectangle=[*point,*point]
                    self._draw_signature_rectangle()
                    self.setFocus()
            event.accept()
            return
        self._border_move=False
        if self.editor.isVisible():
            if self._event_in_proxy(event.position().toPoint()):
                return super().mousePressEvent(event)
            # The typing session is bound to its initial selection until
            # preview/cancel. An outside click must never retarget its draft.
            event.accept()
            return
        if not self.model or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        point = self.pdf_point(event.position().toPoint())
        if self.reading_mode:
            hit=self.model.hit(point)
            self._reading_anchor=hit.id if hit else None
            self._reading_press_pos=event.position().toPoint() if hit else None
            self._reading_dragging=False
            self._press=self._drag=None
            self._selection_drag_anchor=None
            self.set_selection(self._reading_word(hit) if hit else [])
            self._anchor_id=hit.id if hit else None
            self.setCursor(Qt.IBeamCursor)
            event.accept()
            return
        if self.zone_mode:
            self._zone_start=point
            self.zone_rect=(*point,*point)
            event.accept()
            return
        self._click_selection_before = self.ids[:]
        self._click_revision = self.model.revision
        self._last_pointer_press = monotonic()
        if self.placement_mode and not self.read_only:
            self.placement_clicked.emit(*point)
            event.accept()
            return
        if self.image_mode:
            self._press_scene=event.position().toPoint()
            item=self.selected_image()
            self._image_resize=False
            self._image_rotate=False
            self._image_rotate_angle=None
            if item:
                self._image_rotate=self._rotation_handle_at(item['rect'],event.position().toPoint())
                if not self._image_rotate:
                    self._image_resize=self._handle_at(item['rect'],event.position().toPoint())
            if not self._image_resize and not self._image_rotate:
                item=next((im for im in reversed(self.images) if im['rect'][0]<=point[0]<=im['rect'][2] and im['rect'][1]<=point[1]<=im['rect'][3]),None)
                self.select_image(item)
            self._press=point if item and item.get('editable') and not self.read_only else None
            self._image_drag_rect=None
            if self._press and self._image_rotate:
                self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if self.ids and not self.read_only:
            bounds=union(g.bbox for g in self.model.selected(self.ids))
            handle=self._handle_at(bounds,event.position().toPoint())
            if handle:
                self._text_resize=handle
                self._press=point
                self._press_scene=event.position().toPoint()
                self._text_resize_rect=None
                event.accept()
                return
            if self.interaction_mode=='select' and self._border_at(bounds,event.position().toPoint()):
                self._border_move=True
                self._press=point
                self._press_scene=event.position().toPoint()
                self._selection_drag_anchor=None
                self._drag=None
                self.setCursor(Qt.SizeAllCursor)
                event.accept()
                return
        hit = self.model.hit(point)
        self._press_scene = event.position().toPoint()
        if not hit:
            self.set_selection([])
            self._press = None
            return
        self._selection_drag_anchor=hit.id
        group = self.model.group(hit, self.mode)
        if event.modifiers() & Qt.ControlModifier:
            selected = set(self.ids)
            selected.difference_update(group) if set(group).issubset(selected) else selected.update(group)
            self.set_selection(selected)
        elif event.modifiers() & Qt.ShiftModifier and self._anchor_id is not None:
            anchor = next((g for g in self.model.glyphs if g.id == self._anchor_id), None)
            # A range never silently sweeps a different extraction line/column.
            if anchor and anchor.line == hit.line and anchor.mode == hit.mode and (anchor.opacity>0)==(hit.opacity>0):
                lo,hi = sorted((anchor.id, hit.id))
                self.set_selection([g.id for g in self.model.glyphs if g.line == hit.line and g.mode == hit.mode
                                    and (g.opacity>0)==(hit.opacity>0) and lo <= g.id <= hi])
            else:
                self.set_selection(set(self.ids) | set(group))
        elif hit.id not in self.ids:
            self.set_selection(group)
            self._anchor_id = hit.id
        self._press = point if not self.read_only else None
        if self.interaction_mode=='write' and self.ids and not self.read_only:
            self._edit_click_pdf=point
            self._press=None
            self.edit_requested.emit()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.signature_rectangle_mode:
            if self._signature_rectangle_start is not None:
                self._update_signature_rectangle(event.position().toPoint())
            event.accept()
            return
        if self.editor.isVisible() and self._editor_proxy is not None:
            return super().mouseMoveEvent(event)
        if self.reading_mode:
            position=event.position().toPoint()
            if self.model and self._reading_anchor is not None and self._reading_press_pos is not None:
                if self._reading_dragging or (position-self._reading_press_pos).manhattanLength()>4:
                    self._reading_dragging=True
                    self.set_selection(self._reading_range(self.pdf_point(position)))
            self.setCursor(Qt.IBeamCursor if self.model and self.model.hit(self.pdf_point(position)) else Qt.ArrowCursor)
            event.accept()
            return
        if self._zone_start:
            point=self.pdf_point(event.position().toPoint())
            x,y=self._zone_start
            self.zone_rect=(min(x,point[0]),min(y,point[1]),max(x,point[0]),max(y,point[1]))
            self._draw_overlays();event.accept();return
        if self.image_mode and self._press and self.selected_image():
            if (event.position().toPoint()-self._press_scene).manhattanLength()>4:
                rect=self.selected_image()['rect']
                point=self.pdf_point(event.position().toPoint())
                dx,dy=point[0]-self._press[0],point[1]-self._press[1]
                if self._image_rotate:
                    cx,cy=(rect[0]+rect[2])/2,(rect[1]+rect[3])/2
                    start=math.atan2(self._press[1]-cy,self._press[0]-cx)
                    end=math.atan2(point[1]-cy,point[0]-cx)
                    angle=(math.degrees(end-start)+180.)%360.-180.
                    if event.modifiers() & Qt.ShiftModifier:
                        angle=round(angle/15.)*15.
                    self._image_rotate_angle=angle
                elif self._image_resize:
                    self._image_drag_rect=resize_rect(rect,self._image_resize,(dx,dy),self.lock_image_ratio)
                else:
                    self._image_drag_rect=(rect[0]+dx,rect[1]+dy,rect[2]+dx,rect[3]+dy)
                self._draw_overlays()
            event.accept()
            return
        if self.image_mode and not self._press:
            item=self.selected_image()
            if item and item.get('editable') and not self.read_only:
                position=event.position().toPoint()
                if self._rotation_handle_at(item['rect'], position):
                    self.setCursor(Qt.OpenHandCursor)
                else:
                    handle=self._handle_at(item['rect'], position)
                    cursors={'nw':Qt.SizeFDiagCursor,'se':Qt.SizeFDiagCursor,
                             'ne':Qt.SizeBDiagCursor,'sw':Qt.SizeBDiagCursor,
                             'n':Qt.SizeVerCursor,'s':Qt.SizeVerCursor,
                             'e':Qt.SizeHorCursor,'w':Qt.SizeHorCursor}
                    self.setCursor(cursors.get(handle, Qt.SizeAllCursor if self._border_at(item['rect'],position) else Qt.ArrowCursor))
                event.accept()
                return
        if self._text_resize and self._press and self.ids:
            point=self.pdf_point(event.position().toPoint())
            bounds=union(g.bbox for g in self.model.selected(self.ids))
            self._text_resize_rect=resize_rect(bounds,self._text_resize,
                (point[0]-self._press[0],point[1]-self._press[1]))
            self._draw_overlays()
            event.accept()
            return
        if self._press and self.ids and (event.position().toPoint()-self._press_scene).manhattanLength() > 4:
            point = self.pdf_point(event.position().toPoint())
            if self.interaction_mode=='select' and not self._border_move:
                hit=self.model.hit(point)
                anchor=next((g for g in self.model.glyphs if g.id==self._selection_drag_anchor),None)
                if hit and anchor and hit.line==anchor.line and hit.mode==anchor.mode and (hit.opacity>0)==(anchor.opacity>0):
                    endpoints=self.model.group(anchor,self.mode)+self.model.group(hit,self.mode)
                    lo,hi=min(endpoints),max(endpoints)
                    self.set_selection([g.id for g in self.model.glyphs if g.line==anchor.line and lo<=g.id<=hi
                                        and g.mode==anchor.mode and (g.opacity>0)==(anchor.opacity>0)])
                event.accept()
                return
            self._drag = (point[0]-self._press[0], point[1]-self._press[1])
            self._draw_overlays()
            event.accept()
            return
        if self.interaction_mode=='select' and not self._press:
            selected=self.model.selected(self.ids) if self.model else []
            bounds=union(g.bbox for g in selected) if selected else None
            on_border=bool(bounds and not self.read_only and not self._handle_at(bounds,event.position().toPoint())
                           and self._border_at(bounds,event.position().toPoint()))
            self.setCursor(Qt.SizeAllCursor if on_border else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._signature_rectangle_ignore_release and event.button()==Qt.LeftButton:
            self._signature_rectangle_ignore_release=False
            event.accept()
            return
        if self.signature_rectangle_mode:
            if event.button()==Qt.LeftButton:
                self._signature_rectangle_pointer_down=False
            if event.button()==Qt.LeftButton and self._signature_rectangle_start is not None:
                self._update_signature_rectangle(event.position().toPoint())
                self._signature_rectangle_start=None
                if self._signature_rectangle_large_enough():
                    self._signature_rectangle_before_drag=None
                    self.signature_rectangle_selected.emit(self.signature_rectangle[:])
                else:
                    self.signature_rectangle=self._signature_rectangle_before_drag
                    self._signature_rectangle_before_drag=None
                    self._draw_signature_rectangle()
            event.accept()
            return
        if self.reading_mode:
            if event.button()==Qt.LeftButton:
                if self.model and self._reading_anchor is not None and self._reading_press_pos is not None:
                    position=event.position().toPoint()
                    if self._reading_dragging or (position-self._reading_press_pos).manhattanLength()>4:
                        self.set_selection(self._reading_range(self.pdf_point(position)))
                self._reading_anchor=self._reading_press_pos=None
                self._reading_dragging=False
                self._press=self._press_scene=self._drag=None
                self._border_move=False
            event.accept()
            return
        was_border_move=self._border_move
        self._border_move=False
        if was_border_move:self.setCursor(Qt.ArrowCursor)
        if self.editor.isVisible() and self._editor_proxy is not None:
            return super().mouseReleaseEvent(event)
        if self._text_resize:
            rect=self._text_resize_rect
            self._text_resize=self._text_resize_rect=self._press=None
            self._draw_overlays()
            if rect and not self.read_only:
                self.text_resize_requested.emit(rect)
            event.accept()
            return
        if self._zone_start:
            self._zone_start=None
            if self.zone_rect and self.zone_rect[2]-self.zone_rect[0]>.1 and self.zone_rect[3]-self.zone_rect[1]>.1:
                self.zone_selected.emit(self.zone_rect)
            event.accept();return
        if self.image_mode:
            rect=self._image_drag_rect
            image_id=self.image_id
            angle=self._image_rotate_angle
            rotated=self._image_rotate
            self._press=self._drag=self._image_drag_rect=None
            self._image_resize=self._image_rotate=False
            self._image_rotate_angle=None
            self.setCursor(Qt.ArrowCursor)
            self._draw_overlays()
            if rotated and angle is not None and abs(angle)>.01 and image_id and not self.read_only:
                self.image_rotate_requested.emit(image_id,angle)
            elif rect and image_id and not self.read_only:
                self.image_transform_requested.emit(image_id,rect)
            event.accept()
            return
        delta = self._drag
        self._press = self._drag = None
        if delta and not self.read_only:
            self._draw_overlays()
            self.move_requested.emit(*delta)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self,event):
        if self.signature_rectangle_mode:
            event.accept()
            return
        if self.model and not self.editor.isVisible():
            point=self.pdf_point(event.pos())
            hits=[item for item in self.images if item['rect'][0]<=point[0]<=item['rect'][2] and item['rect'][1]<=point[1]<=item['rect'][3]]
            if hits:
                chosen=next((item for item in hits if item['id']==self.image_id),hits[-1])
                self.select_image(chosen)
                self.image_context_requested.emit(chosen['id'],event.globalPos())
                event.accept();return
            hit=self.model.hit(point)
            if hit:
                if hit.id not in self.ids:
                    self.set_selection(self._reading_word(hit) if self.reading_mode else self.model.group(hit,self.mode))
                self.text_context_requested.emit(event.globalPos())
                event.accept();return
            if self.ids:
                self.text_context_requested.emit(event.globalPos())
                event.accept();return
        super().contextMenuEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.signature_rectangle_mode:
            event.accept()
            return
        self._press = self._drag = None
        self._border_move=False
        self._text_resize=self._text_resize_rect=None
        if self.reading_mode:
            self._reading_anchor=self._reading_press_pos=None
            self._reading_dragging=False
            if self.model and event.button()==Qt.LeftButton:
                hit=self.model.hit(self.pdf_point(event.position().toPoint()))
                self.set_selection(self._reading_word(hit) if hit else [])
                self._anchor_id=hit.id if hit else None
            event.accept()
            return
        if self.editor.isVisible() or self.image_mode or self.placement_mode or self.zone_mode:
            if self.editor.isVisible() and self._event_in_proxy(event.position().toPoint()):
                return super().mouseDoubleClickEvent(event)
            event.accept()
            return
        if self.model and event.button() == Qt.LeftButton and (not self.read_only or self.allow_background_edit):
            point = self.pdf_point(event.position().toPoint())
            # The first press can clear a line selection when the pointer is
            # in a gap between words. Restore only a contiguous selection on
            # the same line, inside its bounds, and from this page revision.
            previous = self.ids
            if self._click_revision == self.model.revision and self.pointer_gesture_pending():
                previous = self._click_selection_before or []
            self._click_selection_before = None
            self._click_revision = None
            keep = self._coherent_selection_at(previous, point)
            hit = self.model.hit(point)
            if keep:
                if self.ids != keep:
                    self.set_selection(keep)
            elif hit:
                self.set_selection(self.model.group(hit, "word"))
                self._anchor_id = hit.id
            else:
                self.set_selection([])
            if self.ids:
                self._edit_click_pdf=point
                self.edit_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def pointer_gesture_pending(self):
        """Keep background scheduling out of a possible second click."""
        interval = QApplication.doubleClickInterval() / 1000.
        return self._press is not None or monotonic() - self._last_pointer_press <= interval

    def _coherent_selection_at(self, ids, point):
        selected = self.model.selected(ids)
        if not selected or len({(g.line,g.mode,g.opacity>0) for g in selected}) != 1:
            return []
        line = [g.id for g in self.model.glyphs if g.line == selected[0].line and g.mode == selected[0].mode
                and (g.opacity>0)==(selected[0].opacity>0)]
        positions = [line.index(g.id) for g in selected]
        if max(positions) - min(positions) + 1 != len(positions):
            return []
        x0,y0,x1,y1 = union(g.bbox for g in selected)
        return [g.id for g in selected] if x0 <= point[0] <= x1 and y0 <= point[1] <= y1 else []

    def start_editor(self, text):
        if not self.ids or (self.read_only and not self.allow_background_edit):
            return
        self.editor.setReadOnly(False)
        self.editor.set_pdf_view(False)
        self.editor.rich_mode=False
        self.editor.setPlainText(text)
        selected = self.model.selected(self.ids)
        font = self.editor.font()
        font.setPointSizeF(selected[0].size*self.zoom*72/self.editor.logicalDpiY())
        self.editor.setFont(font)
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        cursor=self.editor.textCursor()
        cursor.setPosition(0)
        if self._edit_click_pdf:
            x,y=self._edit_click_pdf
            index=0
            for glyph in selected:
                if y>=glyph.bbox[1] and (y>glyph.bbox[3] or x>(glyph.bbox[0]+glyph.bbox[2])/2):
                    index+=len(glyph.text)
            cursor.setPosition(min(index,len(text)))
        self.editor.setTextCursor(cursor)
        self._edit_click_pdf=None

    def start_rich_editor(self, payload, catalog=None):
        if (not self.ids and not payload.get('rect')) or (self.read_only and not self.allow_background_edit):
            return
        self.editor.setReadOnly(False)
        self.editor.load_payload(payload,catalog,self.zoom)
        self._editor_bounds=payload.get('rect') or union(g.bbox for g in self.model.selected(self.ids))
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        if self._edit_click_pdf:
            self.editor.place_caret_pdf(self._edit_click_pdf)
        self._edit_click_pdf=None
        self.editor.toolbar.raise_()

    def _place_editor(self):
        if self.model and (self.ids or self._editor_bounds):
            bounds=self._editor_bounds or union(g.bbox for g in self.model.selected(self.ids))
            rect = self.scene_rect(bounds)
            start = self.mapFromScene(rect.topLeft())
            width = max(14,int((bounds[2]-bounds[0])*self.zoom+3))
            height = max(25,int((bounds[3]-bounds[1])*self.zoom+6))
            if self.editor.rich_mode:
                if self.editor._payload.get('auto_width'):
                    width=max(width,int(self.editor.document().idealWidth()+3))
                if self.editor._payload.get('auto_height'):
                    height=max(height,int(self.editor.document().size().height()+4))
            x,y=start.x(),start.y()
            if self.model.rotation:
                if self._editor_proxy is None:
                    self.editor.setParent(None)
                    self._editor_proxy=self.scene().addWidget(self.editor)
                    self._editor_proxy.setZValue(10)
                sx,sy=transform(bounds[:2],self.model.rotation_matrix)
                self.editor.resize(width,height)
                self._editor_proxy.setPos(sx*self.zoom,sy*self.zoom)
                self._editor_proxy.setRotation(self.model.rotation)
            else:
                self._release_editor_proxy()
                self.editor.setGeometry(x,y,width,height)
            toolbar=self.editor.toolbar
            toolbar.adjustSize()
            toolbar_width=min(toolbar.sizeHint().width(),self.viewport().width()-8)
            toolbar_height=toolbar.sizeHint().height()
            toolbar_x=max(4,min(x,self.viewport().width()-toolbar_width-4))
            toolbar_y=y-toolbar_height-7 if y>toolbar_height+10 else y+height+7
            toolbar.setGeometry(toolbar_x,toolbar_y,toolbar_width,toolbar_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'editor'):
            self._place_editor()

    def wheelEvent(self, event):
        # Let this wheel event reach the boundary first. Only a later event
        # that starts at the boundary may request another page.
        delta=event.pixelDelta() if not event.pixelDelta().isNull() else event.angleDelta()
        vertical=delta.y()
        navigation=(self.page_navigation_enabled and self.model is not None and vertical
                    and abs(vertical)>abs(delta.x()) and not event.modifiers()&Qt.ControlModifier
                    and not self.editor.isVisible() and not self.placement_mode and not self.signature_rectangle_mode)
        if navigation:
            bar=self.verticalScrollBar()
            at_boundary=(vertical<0 and bar.value()>=bar.maximum()) or (vertical>0 and bar.value()<=bar.minimum())
            if at_boundary:
                self.wheel_page_requested.emit(1 if vertical<0 else -1)
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if self.signature_rectangle_mode:
            if event.key()==Qt.Key_Escape:
                self.end_signature_rectangle()
                self.signature_rectangle_cancelled.emit()
                event.accept()
                return
            return super().keyPressEvent(event)
        if event.key() == Qt.Key_Escape:
            self._press = self._drag = None
            self._border_move=False
            self.setCursor(Qt.IBeamCursor if self.interaction_mode=='write' else Qt.SizeAllCursor if self.interaction_mode=='move' else Qt.ArrowCursor)
            self._image_drag_rect=None
            self._image_resize=self._image_rotate=False
            self._image_rotate_angle=None
            self._text_resize=self._text_resize_rect=None
            self._reading_anchor=self._reading_press_pos=None
            self._reading_dragging=False
            self._draw_overlays()
            self.editor.hide()
            self.cancel_requested.emit()
            return
        if self.reading_mode:
            # QGraphicsView keeps ordinary scrolling/navigation keys. Keys
            # which the edit workspace interprets as mutations never emit its
            # edit, image, delete or move signals in the reading workspace.
            if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_F2,Qt.Key_Delete,Qt.Key_Backspace):
                event.accept()
                return
            return super().keyPressEvent(event)
        if self.image_mode and self.image_id and not self.read_only:
            directions={Qt.Key_Left:(-1,0),Qt.Key_Right:(1,0),Qt.Key_Up:(0,-1),Qt.Key_Down:(0,1)}
            if event.key() in directions:
                self.arrow_requested.emit(*directions[event.key()],bool(event.modifiers()&Qt.ShiftModifier))
                return
            if event.key() in (Qt.Key_Delete,Qt.Key_Backspace):
                self.image_delete_requested.emit(self.image_id)
                return
        if self.ids and not self.read_only:
            directions = {Qt.Key_Left:(-1,0),Qt.Key_Right:(1,0),Qt.Key_Up:(0,-1),Qt.Key_Down:(0,1)}
            if event.key() in directions:
                self.arrow_requested.emit(*directions[event.key()], bool(event.modifiers() & Qt.ShiftModifier))
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
                self.edit_requested.emit()
                return
            if event.key() in (Qt.Key_Delete,Qt.Key_Backspace):
                self.delete_requested.emit()
                return
        super().keyPressEvent(event)
