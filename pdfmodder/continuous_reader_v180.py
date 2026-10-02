"""Bounded, page-continuous reading surface. It never edits PDF content."""
from collections import OrderedDict
from math import sqrt

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from .model import transform, transform_rect, union
from .reading_order_v180 import ordered_glyphs, ordered_lines, selection_text


class ContinuousReader(QGraphicsView):
    pages_requested = Signal(object)
    current_page_changed = Signal(int)
    selection_changed = Signal(object)
    copy_requested = Signal()
    context_requested = Signal(object)
    MAX_IMAGE_BYTES = 32 * 1024 * 1024
    MAX_IMAGE_PAGES = 8
    MAX_MODEL_PAGES = 10
    MAX_VISIBLE_PAGES = 256
    GUTTER = 24.
    MARGIN = 20.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("continuousPdfReader")
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#626b76"))
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.IBeamCursor)
        self.zoom = 1.25
        self._geometries = []
        self._rects = []
        self._placeholders = []
        self._images = OrderedDict()
        self._models = OrderedDict()
        self._loaded_zooms = {}
        self._overlays = []
        self._search_overlays = []
        self._search_matches = []
        self._pending_reveal = None
        self._anchor = self._focus = None
        self._gesture_anchor = None
        self._press_position = None
        self._dragging = False
        self._pointer = None
        self._current_page = 0
        self._last_requested = None
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._viewport_changed)
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(25)
        self._autoscroll.timeout.connect(self._scroll_selection)
        self.verticalScrollBar().valueChanged.connect(self._schedule_update)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_update)

    @property
    def models(self):
        return self._models

    @property
    def image_cache_bytes(self):
        return sum(value[2] for value in self._images.values())

    def reset_document(self, page_geometries, zoom=1.25):
        self._autoscroll.stop()
        self._anchor = self._focus = self._gesture_anchor = None
        self._press_position = self._pointer = None
        self._dragging = False
        self._images.clear()
        self._models.clear()
        self._loaded_zooms.clear()
        self._overlays.clear()
        self._search_overlays.clear()
        self._search_matches = []
        self._pending_reveal = None
        self.scene().clear()
        self._placeholders = []
        self._geometries = [(float(p["width"]), float(p["height"])) for p in page_geometries]
        if any(width <= 0 or height <= 0 for width, height in self._geometries):
            raise ValueError("Dimensiones de página no válidas.")
        self.zoom = max(.1, float(zoom))
        self._current_page = 0
        self._last_requested = None
        for number in range(len(self._geometries)):
            rectangle = self.scene().addRect(QRectF(), QPen(QColor("#bac1ca")), QColor("white"))
            rectangle.setZValue(-2)
            label = self.scene().addText(f"Página {number + 1}")
            label.setDefaultTextColor(QColor("#7b8795"))
            label.setZValue(-1)
            self._placeholders.append((rectangle, label))
        self._layout_pages()
        self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
        self.selection_changed.emit(None)
        self._schedule_update()

    def _layout_pages(self):
        self._rects = []
        largest = max((width for width, _ in self._geometries), default=0.) * self.zoom
        top = self.MARGIN
        for number, (width, height) in enumerate(self._geometries):
            rect = QRectF(self.MARGIN + (largest - width * self.zoom) / 2., top,
                          width * self.zoom, height * self.zoom)
            self._rects.append(rect)
            rectangle, label = self._placeholders[number]
            rectangle.setRect(rect)
            label.setPos(rect.left() + 12., rect.top() + 10.)
            top = rect.bottom() + self.GUTTER
            if number in self._images:
                self._place_image(number)
        self.setSceneRect(QRectF(0., 0., largest + 2. * self.MARGIN,
                                 max(0., top - self.GUTTER + self.MARGIN)))
        self._draw_selection()
        self._draw_search()

    def _place_image(self, number):
        pixmap, item, _ = self._images[number]
        rect = self._rects[number]
        item.setPos(rect.topLeft())
        # Rendering and display zoom may differ while a new render is pending.
        item.setScale(rect.width() / pixmap.width())

    def set_page(self, number, png, model, zoom):
        if number < 0 or number >= len(self._geometries):
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, "PNG"):
            raise ValueError("No se pudo mostrar la página renderizada.")
        cost = pixmap.width() * pixmap.height() * 4
        if cost > self.MAX_IMAGE_BYTES:
            ratio = sqrt(self.MAX_IMAGE_BYTES / cost) * .995
            pixmap = pixmap.scaled(max(1, int(pixmap.width() * ratio)),
                                   max(1, int(pixmap.height() * ratio)),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            cost = pixmap.width() * pixmap.height() * 4
        previous = self._images.pop(number, None)
        if previous:
            self.scene().removeItem(previous[1])
        item = self.scene().addPixmap(pixmap)
        item.setZValue(0)
        self._images[number] = (pixmap, item, cost)
        self._loaded_zooms[number] = self.zoom
        if model is not None:
            self._models.pop(number, None)
            self._models[number] = model
        self._place_image(number)
        self._prune_cache()
        if self._dragging and self._pointer is not None:
            self._extend_selection(self._pointer)
        self._draw_selection()
        self._draw_search()
        if self._pending_reveal and self._pending_reveal[0] == number:
            page, rect = self._pending_reveal
            self._pending_reveal = None
            self.reveal_rect(page, rect)

    def has_page(self, number, zoom=None):
        return (number in self._images and number in self._models and
                (zoom is None or abs(self._loaded_zooms.get(number, 0.) - zoom) < .0001))

    def loaded_page_numbers(self):
        return list(self._images)

    def model_for_page(self, number):
        return self._models.get(number)

    def current_page(self):
        return self._current_page

    def go_page(self, number):
        if not 0 <= number < len(self._rects):
            return
        rect = self._rects[number]
        point = self.mapFromScene(QPointF(rect.center().x(), rect.top()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + point.y())
        if self._current_page != number:
            self._current_page = number
            self.current_page_changed.emit(number)
        self._schedule_update()

    def set_zoom(self, zoom):
        zoom = max(.1, float(zoom))
        if zoom == self.zoom:
            return
        center = self.mapToScene(self.viewport().rect().center())
        page = self._page_at(center, nearest=True)
        if page is not None:
            rect = self._rects[page]
            anchor = ((center.x() - rect.left()) / self.zoom,
                      (center.y() - rect.top()) / self.zoom)
        else:
            anchor = None
        self.zoom = zoom
        self._layout_pages()
        if anchor is not None:
            rect = self._rects[page]
            self.centerOn(rect.left() + anchor[0] * zoom, rect.top() + anchor[1] * zoom)
        self._last_requested = None
        self._schedule_update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_update()

    def _schedule_update(self, *_):
        if not self._update_timer.isActive():
            self._update_timer.start(0)

    def visible_page_numbers(self):
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        return [number for number, rect in enumerate(self._rects) if rect.intersects(visible)]

    def _viewport_changed(self):
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        pages = self.visible_page_numbers()
        if pages:
            current = max(pages, key=lambda n: self._rects[n].intersected(visible).height())
            if current != self._current_page:
                self._current_page = current
                self.current_page_changed.emit(current)
            requested = list(range(max(0, min(pages) - 1), min(len(self._rects), max(pages) + 2)))
            signature = (tuple(requested), self.zoom)
            if signature != self._last_requested:
                self._last_requested = signature
                self.pages_requested.emit(requested)
        self._prune_cache()
        self._draw_selection()
        self._draw_search()

    def _prune_cache(self):
        visible = set(self.visible_page_numbers())
        def priority(number):
            return (number in visible, -abs(number - self._current_page))
        # Very small pages or a low zoom can show more than eight pages at
        # once. Keep those visible images instead of rendering/evicting them in
        # a loop. The absolute byte budget still applies to the whole cache.
        image_limit = max(self.MAX_IMAGE_PAGES, min(self.MAX_VISIBLE_PAGES, len(visible)) + 2)
        while len(self._images) > image_limit:
            number = min(self._images, key=priority)
            _, item, _ = self._images.pop(number)
            self._loaded_zooms.pop(number, None)
            self.scene().removeItem(item)
        while self._images and self.image_cache_bytes > self.MAX_IMAGE_BYTES:
            offscreen = [number for number in self._images if number not in visible]
            if offscreen:
                number = min(offscreen, key=priority)
                _, item, _ = self._images.pop(number)
                self._loaded_zooms.pop(number, None)
                self.scene().removeItem(item)
                continue
            # Preserve every visible page at a lower preview resolution if
            # their combined decoded pixmaps exceed the memory allowance.
            ratio = sqrt(self.MAX_IMAGE_BYTES / self.image_cache_bytes) * .995
            for number, (pixmap, item, _) in list(self._images.items()):
                reduced = pixmap.scaled(max(1, int(pixmap.width() * ratio)),
                                        max(1, int(pixmap.height() * ratio)),
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation)
                item.setPixmap(reduced)
                self._images[number] = (reduced, item, reduced.width() * reduced.height() * 4)
                self._place_image(number)
            break
        protected = {endpoint["page"] for endpoint in (self._anchor, self._focus) if endpoint}
        model_limit = max(self.MAX_MODEL_PAGES, min(self.MAX_VISIBLE_PAGES, len(visible)) + 2)
        while len(self._models) > model_limit:
            candidates = [number for number in self._models if number not in protected]
            if not candidates:
                break
            del self._models[min(candidates, key=priority)]

    def _page_at(self, point, nearest=False):
        for number, rect in enumerate(self._rects):
            if rect.contains(point):
                return number
        if nearest and self._rects:
            return min(range(len(self._rects)),
                       key=lambda n: max(self._rects[n].top() - point.y(), 0.,
                                         point.y() - self._rects[n].bottom()))
        return None

    def _endpoint_at(self, viewport_point, nearest=False):
        point = self.mapToScene(viewport_point)
        number = self._page_at(point, nearest)
        model = self._models.get(number)
        if number is None or model is None:
            if number is not None:
                self.pages_requested.emit([number])
            return None
        rect = self._rects[number]
        pdf = transform(((point.x() - rect.left()) / self.zoom,
                         (point.y() - rect.top()) / self.zoom), model.derotation_matrix)
        ordered = ordered_glyphs(model)
        hits = [g for g in ordered if g.bbox[0] <= pdf[0] <= g.bbox[2] and
                                     g.bbox[1] <= pdf[1] <= g.bbox[3]]
        if hits:
            glyph = min(hits, key=lambda g: abs((g.bbox[0] + g.bbox[2]) / 2. - pdf[0]))
        elif nearest and ordered:
            lines = ordered_lines(model)
            def distance(line):
                return min(max(g.bbox[1] - pdf[1], 0., pdf[1] - g.bbox[3]) for g in line)
            line = min(lines, key=distance)
            glyph = min(line, key=lambda g: (max(g.bbox[0] - pdf[0], 0., pdf[0] - g.bbox[2]),
                                             abs((g.bbox[0] + g.bbox[2]) / 2. - pdf[0])))
        else:
            return None
        return {"page": number, "id": glyph.id}

    def _endpoint_key(self, endpoint):
        model = self._models.get(endpoint["page"])
        order = {g.id: index for index, g in enumerate(ordered_glyphs(model))} if model else {}
        return endpoint["page"], order.get(endpoint["id"], 0)

    def selection_endpoints(self):
        if self._anchor is None or self._focus is None:
            return None
        start, end = sorted((self._anchor, self._focus), key=self._endpoint_key)
        return {"start": dict(start), "end": dict(end)}

    def selected_page_numbers(self):
        endpoints = self.selection_endpoints()
        return list(range(endpoints["start"]["page"], endpoints["end"]["page"] + 1)) if endpoints else []

    def selection_text(self):
        endpoints = self.selection_endpoints()
        if not endpoints:
            return ""
        result = []
        for page in self.selected_page_numbers():
            model = self._models.get(page)
            if model is None:
                # The caller must load the missing pages or ask its PDF worker;
                # never silently copy only part of a cross-page selection.
                raise ValueError("Faltan páginas de la selección por cargar.")
            first = endpoints["start"]["id"] if page == endpoints["start"]["page"] else None
            last = endpoints["end"]["id"] if page == endpoints["end"]["page"] else None
            result.append(selection_text(model, first, last))
        return "\n\n".join(result)

    def selected_ids(self, number):
        endpoints = self.selection_endpoints()
        model = self._models.get(number)
        if endpoints is None or model is None or number not in self.selected_page_numbers():
            return []
        glyphs = ordered_glyphs(model)
        positions = {g.id: i for i, g in enumerate(glyphs)}
        first = positions.get(endpoints["start"]["id"], 0) if number == endpoints["start"]["page"] else 0
        last = positions.get(endpoints["end"]["id"], len(glyphs) - 1) if number == endpoints["end"]["page"] else len(glyphs) - 1
        return [g.id for g in glyphs[first:last + 1]]

    def clear_selection(self):
        self._anchor = self._focus = self._gesture_anchor = None
        self._draw_selection()
        self.selection_changed.emit(None)

    def set_search_matches(self, matches):
        self._search_matches = list(matches or [])
        self._draw_search()

    def reveal_rect(self, number, rect):
        if not 0 <= number < len(self._rects):
            return
        model = self._models.get(number)
        if model is None:
            self._pending_reveal = (number, tuple(rect))
            self.go_page(number)
            self.pages_requested.emit([number])
            return
        x0, y0, x1, y1 = transform_rect(rect, model.rotation_matrix)
        page = self._rects[number]
        self.ensureVisible(QRectF(page.left() + x0 * self.zoom, page.top() + y0 * self.zoom,
                                  (x1 - x0) * self.zoom, (y1 - y0) * self.zoom), 20, 40)
        self._schedule_update()

    def _draw_search(self):
        for item in self._search_overlays:
            self.scene().removeItem(item)
        self._search_overlays = []
        visible = set(self.visible_page_numbers())
        for match in self._search_matches:
            number = match["page"]
            model = self._models.get(number)
            if number not in visible or model is None:
                continue
            x0, y0, x1, y1 = transform_rect(match["rect"], model.rotation_matrix)
            page = self._rects[number]
            item = self.scene().addRect(QRectF(page.left() + x0 * self.zoom,
                                               page.top() + y0 * self.zoom,
                                               (x1 - x0) * self.zoom,
                                               (y1 - y0) * self.zoom),
                                        QPen(Qt.NoPen), QColor(255, 193, 7, 100))
            item.setZValue(1)
            self._search_overlays.append(item)

    def _word(self, endpoint):
        model = self._models[endpoint["page"]]
        line = next((line for line in ordered_lines(model)
                     if any(g.id == endpoint["id"] for g in line)), [])
        index = next(i for i, g in enumerate(line) if g.id == endpoint["id"])
        left = right = index
        if not line[index].text.isspace():
            while left > 0 and not line[left - 1].text.isspace():
                left -= 1
            while right + 1 < len(line) and not line[right + 1].text.isspace():
                right += 1
        return ({"page": endpoint["page"], "id": line[left].id},
                {"page": endpoint["page"], "id": line[right].id})

    def _selection_updated(self):
        self._draw_selection()
        self.selection_changed.emit(self.selection_endpoints())

    def _extend_selection(self, point):
        endpoint = self._endpoint_at(point, nearest=True)
        if endpoint is not None and self._gesture_anchor is not None:
            self._anchor = dict(self._gesture_anchor)
            self._focus = endpoint
            self._selection_updated()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus(Qt.MouseFocusReason)
        point = event.position().toPoint()
        endpoint = self._endpoint_at(point)
        self._press_position = point
        self._pointer = point
        self._dragging = False
        if endpoint is None:
            self.clear_selection()
            event.accept()
            return
        if event.modifiers() & Qt.ShiftModifier and self._anchor is not None:
            self._gesture_anchor = dict(self._anchor)
            self._focus = endpoint
        else:
            self._gesture_anchor = endpoint
            self._anchor, self._focus = self._word(endpoint)
        self._selection_updated()
        event.accept()

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        if self._press_position is None or self._gesture_anchor is None:
            return super().mouseMoveEvent(event)
        self._pointer = point
        if (point - self._press_position).manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
        if self._dragging:
            self._extend_selection(point)
            if point.y() < 35 or point.y() > self.viewport().height() - 35:
                self._autoscroll.start()
            else:
                self._autoscroll.stop()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        if self._dragging:
            self._extend_selection(event.position().toPoint())
        self._press_position = None
        self._dragging = False
        self._autoscroll.stop()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        endpoint = self._endpoint_at(event.position().toPoint())
        if event.button() == Qt.LeftButton and endpoint:
            self._anchor, self._focus = self._word(endpoint)
            self._gesture_anchor = self._anchor
            self._selection_updated()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _scroll_selection(self):
        if not self._dragging or self._pointer is None:
            self._autoscroll.stop()
            return
        y = self._pointer.y()
        edge = 35
        if y < edge:
            delta = -max(5, min(45, edge - y))
        elif y > self.viewport().height() - edge:
            delta = max(5, min(45, y - self.viewport().height() + edge))
        else:
            self._autoscroll.stop()
            return
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta)
        self._extend_selection(self._pointer)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self.copy_requested.emit()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            self.clear_selection()
            event.accept()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        endpoint = self._endpoint_at(event.pos())
        if self.selection_endpoints() is None and endpoint:
            self._anchor, self._focus = self._word(endpoint)
            self._selection_updated()
        self.context_requested.emit(event.globalPos())
        event.accept()

    def _draw_selection(self):
        for item in self._overlays:
            self.scene().removeItem(item)
        self._overlays = []
        endpoints = self.selection_endpoints()
        if not endpoints:
            return
        for page in self.selected_page_numbers():
            model = self._models.get(page)
            if model is None or page not in self.visible_page_numbers():
                continue
            selected = set(self.selected_ids(page))
            rect = self._rects[page]
            for line in ordered_lines(model):
                boxes = [glyph.bbox for glyph in line if glyph.id in selected]
                if not boxes:
                    continue
                x0, y0, x1, y1 = transform_rect(union(boxes), model.rotation_matrix)
                item = self.scene().addRect(QRectF(rect.left() + x0 * self.zoom,
                                                   rect.top() + y0 * self.zoom,
                                                   (x1 - x0) * self.zoom,
                                                   (y1 - y0) * self.zoom),
                                            QPen(Qt.NoPen), QColor(52, 136, 232, 85))
                item.setZValue(2)
                self._overlays.append(item)
