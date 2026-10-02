"""Organizador Qt: planes y miniaturas recibidas, sin abrir documentos PDF."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, QSize, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .model import mm, pt


class PageOrganizerDialog(QDialog):
    import_requested = Signal(object, int)  # list[str] paths, final insertion index
    thumbnail_requested = Signal(str, int)  # source id, source page index

    def __init__(self, pages, parent=None, *, capabilities=None):
        super().__init__(parent)
        self._capabilities = dict(capabilities or {})
        self.setWindowTitle("Organizar páginas")
        self.resize(830, 690)
        self._busy = False
        self._next_id = 0
        self._pixmaps = {}
        self._pending_thumbnails = set()
        self._labels = {"current": "Documento actual"}
        self._initial = []
        layout = QVBoxLayout(self)
        instruction = QLabel("Arrastra las miniaturas para cambiar el orden. El número de cada fila indica su posición final. El PDF se modifica al previsualizar y aplicar.")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        middle = QHBoxLayout()
        self.page_list = QListWidget()
        self.page_list.setObjectName("organizerPages")
        self.page_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.page_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.page_list.setDefaultDropAction(Qt.MoveAction)
        self.page_list.setDropIndicatorShown(True)
        self.page_list.setDragEnabled(True)
        self.page_list.setAcceptDrops(True)
        self.page_list.setIconSize(QSize(105, 135))
        self.page_list.setSpacing(4)
        self.page_list.setMinimumWidth(420)
        middle.addWidget(self.page_list, 1)
        controls = QWidget()
        side = QVBoxLayout(controls)
        self.selection_label = QLabel("Selecciona páginas")
        self.selection_label.setWordWrap(True)
        side.addWidget(self.selection_label)
        self.up_button = self._button(side, "Subir", "organizerUp", lambda:self.move_selected(-1))
        self.down_button = self._button(side, "Bajar", "organizerDown", lambda:self.move_selected(1))
        self.rotate_button = self._button(side, "Girar 90° a la derecha", "organizerRotate", self.rotate_selected)
        self.duplicate_button = self._button(side, "Duplicar selección", "organizerDuplicate", self.duplicate_selected)
        self.remove_button = self._button(side, "Quitar del orden", "organizerRemove", self.remove_selected)
        form = QFormLayout()
        self.position_box = QSpinBox()
        self.position_box.setObjectName("organizerInsertPosition")
        self.position_box.setMinimum(1)
        form.addRow("Insertar antes de posición", self.position_box)
        self.width_box = self._dimension("organizerBlankWidth", 210.)
        self.height_box = self._dimension("organizerBlankHeight", 297.)
        form.addRow("Blanca: anchura", self.width_box)
        form.addRow("Blanca: altura", self.height_box)
        side.addLayout(form)
        self.blank_button = self._button(side, "Insertar página en blanco", "organizerBlank", self.insert_blank)
        self.import_button = self._button(side, "Insertar páginas de PDF…", "organizerImport", self.choose_pdf)
        self.reset_button = self._button(side, "Restablecer documento original", "organizerReset", self.reset_order)
        note = QLabel("Los enlaces y marcadores apuntarán a la primera copia final de su destino. Un enlace a su propia página se mantiene en esa copia. Las estructuras no compatibles se rechazan antes de aplicar.")
        note.setWordWrap(True)
        side.addWidget(note)
        side.addStretch()
        middle.addWidget(controls)
        layout.addLayout(middle, 1)
        self.order_label = QLabel()
        self.order_label.setObjectName("organizerFinalOrder")
        self.order_label.setWordWrap(True)
        layout.addWidget(self.order_label)
        self.status_label = QLabel()
        self.status_label.setObjectName("organizerStatus")
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.Ok)
        self.apply_button.setObjectName("organizerPreview")
        self.apply_button.setText("Previsualizar orden final")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self.request_visible_thumbnails)
        self.page_list.model().rowsMoved.connect(self._changed)
        self.page_list.itemSelectionChanged.connect(self._selection_changed)
        self.page_list.verticalScrollBar().valueChanged.connect(lambda _:self.thumbnail_timer.start(80))
        for number, metadata in enumerate(pages):
            entry = self._entry("current", metadata, number)
            self._initial.append(entry.copy())
            self._append_entry(entry)
            if metadata.get("png"):
                self.set_thumbnail("current", entry["page"], metadata["png"])
        self._initial_plan = self.plan()
        self._changed()
        self.position_box.setValue(self.page_list.count()+1)
        self.thumbnail_timer.start(0)

    @staticmethod
    def _button(layout, label, name, slot):
        button = QPushButton(label)
        button.setObjectName(name)
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    @staticmethod
    def _dimension(name, value):
        box = QDoubleSpinBox()
        box.setObjectName(name)
        box.setRange(mm(1), mm(14400))
        box.setDecimals(3)
        box.setSuffix(" mm")
        box.setValue(value)
        return box

    def _entry(self, source, metadata, fallback):
        return {"source": source, "page": int(metadata.get("page", fallback)), "rotation": 0,
                "_width": float(metadata["width"]), "_height": float(metadata["height"]),
                "_base_rotation": int(metadata.get("rotation", 0)), "_copy": False}

    def _append_entry(self, entry, position=None):
        item = QListWidgetItem()
        data = dict(entry)
        self._next_id += 1
        data["_id"] = self._next_id
        item.setData(Qt.UserRole, data)
        item.setSizeHint(QSize(390, 145))
        if position is None:
            self.page_list.addItem(item)
        else:
            self.page_list.insertItem(position, item)
        self._refresh_item(item)
        return item

    def _refresh_item(self, item):
        data = item.data(Qt.UserRole)
        source, delta = data["source"], data["rotation"]
        if source == "blank":
            width, height = data["width"], data["height"]
            origin = "Página en blanco"
            pixmap = QPixmap(95, max(25, min(125, round(95*height/width))))
            pixmap.fill(Qt.white)
            painter = QPainter(pixmap)
            painter.setPen(QColor("#8c969f"))
            painter.drawRect(0, 0, pixmap.width()-1, pixmap.height()-1)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "En blanco")
            painter.end()
            base_rotation = 0
        else:
            width, height = data["_width"], data["_height"]
            origin = f"{self._labels.get(source, source)} · página {data['page']+1}"
            pixmap = self._pixmaps.get((source, data["page"]))
            base_rotation = data["_base_rotation"]
        if delta % 180:
            width, height = height, width
        item.setText(f"{self.page_list.row(item)+1} · {origin}" + (" · copia" if data.get("_copy") else "")
                     + f"\n{mm(width):.1f} × {mm(height):.1f} mm · giro final {(base_rotation+delta)%360}°")
        item.setToolTip(origin + "\nArrastra esta fila para cambiar su posición final.")
        item.setIcon(QIcon(pixmap.transformed(QTransform().rotate(delta), Qt.SmoothTransformation)) if pixmap is not None else QIcon())

    def _changed(self, *_):
        count = self.page_list.count()
        for index in range(count):
            self._refresh_item(self.page_list.item(index))
        self.position_box.setMaximum(count+1)
        self.order_label.setText(f"Orden final visible de arriba abajo: {count} página(s).")
        self._update_buttons()
        self.thumbnail_timer.start(0)

    def _selection_changed(self):
        rows = sorted(self.page_list.row(item) for item in self.page_list.selectedItems())
        self.selection_label.setText(f"{len(rows)} página(s) seleccionada(s)" if rows else "Selecciona páginas")
        if rows:
            self.position_box.setValue(rows[0]+1)
        self._update_buttons()

    def _update_buttons(self):
        selected = bool(self.page_list.selectedItems())
        for button, capability in ((self.up_button, 'reorder'), (self.down_button, 'reorder'),
                (self.rotate_button, 'rotate'), (self.duplicate_button, 'duplicate'), (self.remove_button, 'delete')):
            button.setEnabled(selected and self._allowed(capability))
            button.setToolTip('' if self._capabilities.get(capability, True) else
                self._capabilities.get('reason') or 'Esta operación no conserva todavía la estructura accesible.')
        for button, capability in ((self.blank_button, 'insert_blank'), (self.import_button, 'insert_pdf')):
            button.setEnabled(self._allowed(capability))
            button.setToolTip('' if self._capabilities.get(capability, True) else
                self._capabilities.get('reason') or 'Esta operación no conserva todavía la estructura accesible.')
        self.reset_button.setEnabled(not self._busy)
        self.apply_button.setEnabled(not self._busy and self.page_list.count()>0 and self.plan()!=getattr(self,"_initial_plan",self.plan()))
        self.page_list.setDragEnabled(self._allowed('reorder'))
        self.page_list.setAcceptDrops(self._allowed('reorder'))

    def _allowed(self, capability):
        return not self._busy and self._capabilities.get(capability, True)

    def plan(self):
        result = []
        for index in range(self.page_list.count()):
            data = self.page_list.item(index).data(Qt.UserRole)
            keys = ("source", "width", "height", "rotation") if data["source"] == "blank" else ("source", "page", "rotation")
            result.append({key: data[key] for key in keys})
        return result

    def rotate_selected(self):
        if not self._allowed('rotate'):
            return
        for item in self.page_list.selectedItems():
            data = item.data(Qt.UserRole)
            data["rotation"] = (data["rotation"]+90) % 360
            item.setData(Qt.UserRole, data)
        self._changed()

    def duplicate_selected(self):
        if not self._allowed('duplicate'):
            return
        selected = sorted(self.page_list.selectedItems(), key=self.page_list.row)
        if not selected:
            return
        position = self.page_list.row(selected[-1])+1
        copies = []
        for offset, item in enumerate(selected):
            data = dict(item.data(Qt.UserRole))
            data["_copy"] = True
            copies.append(self._append_entry(data, position+offset))
        self.page_list.clearSelection()
        for item in copies:
            item.setSelected(True)
        self._changed()

    def move_selected(self, delta):
        if not self._allowed('reorder') or delta not in (-1, 1):
            return
        items = sorted(self.page_list.selectedItems(), key=self.page_list.row, reverse=delta>0)
        selected_ids = {item.data(Qt.UserRole)["_id"] for item in items}
        for item in items:
            old = self.page_list.row(item)
            target = old+delta
            if 0 <= target < self.page_list.count() and self.page_list.item(target).data(Qt.UserRole)["_id"] not in selected_ids:
                self.page_list.takeItem(old)
                self.page_list.insertItem(target, item)
                item.setSelected(True)
        self._changed()

    def remove_selected(self):
        if not self._allowed('delete'):
            return
        items = self.page_list.selectedItems()
        if len(items) == self.page_list.count():
            self.set_error("El PDF debe conservar al menos una página. Inserta primero una página si quieres reemplazar todas.")
            return
        for row in sorted((self.page_list.row(item) for item in items), reverse=True):
            self.page_list.takeItem(row)
        self._changed()

    def insert_blank(self):
        if not self._allowed('insert_blank'):
            return
        entry = {"source": "blank", "width": pt(self.width_box.value()), "height": pt(self.height_box.value()), "rotation": 0}
        item = self._append_entry(entry, self.position_box.value()-1)
        self.page_list.clearSelection()
        item.setSelected(True)
        self._changed()

    def choose_pdf(self):
        if not self._allowed('insert_pdf'):
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Insertar páginas de PDF", "", "Documentos PDF (*.pdf)")
        if paths:
            self.set_busy(True)
            self.import_requested.emit(paths, self.position_box.value()-1)

    def add_source(self, source_id, pages, label=None, position=None):
        if not isinstance(source_id, str) or not source_id or source_id in ("current", "blank"):
            raise ValueError("El PDF añadido necesita un identificador propio.")
        self._labels[source_id] = label or Path(source_id).name
        position = self.page_list.count() if position is None else max(0, min(position, self.page_list.count()))
        for offset, metadata in enumerate(pages):
            entry = self._entry(source_id, metadata, offset)
            self._append_entry(entry, position+offset)
            if metadata.get("png"):
                self.set_thumbnail(source_id, entry["page"], metadata["png"])
        self.set_busy(False)
        self._changed()

    def set_thumbnail(self, source_id, page, png):
        pixmap = QPixmap()
        if not pixmap.loadFromData(png, "PNG"):
            self.set_error("No se pudo mostrar una miniatura recibida.")
            return
        key = (source_id, page)
        self._pixmaps.pop(key, None)
        self._pixmaps[key] = pixmap.scaled(140, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._pending_thumbnails.discard(key)
        while len(self._pixmaps)>64:
            self._pixmaps.pop(next(iter(self._pixmaps)))
        for index in range(self.page_list.count()):
            self._refresh_item(self.page_list.item(index))
        self.thumbnail_timer.start(0)

    def request_visible_thumbnails(self):
        if self._busy or self._pending_thumbnails or not self.isVisible():
            return
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            data = item.data(Qt.UserRole)
            if data["source"] == "blank" or not self.page_list.visualItemRect(item).intersects(self.page_list.viewport().rect()):
                continue
            key = (data["source"], data["page"])
            if key not in self._pixmaps and key not in self._pending_thumbnails:
                self._pending_thumbnails.add(key)
                self.thumbnail_requested.emit(*key)
                return  # Serial worker: request the next after set_thumbnail.

    def set_busy(self, busy):
        self._busy = bool(busy)
        self.page_list.setEnabled(not self._busy)
        self.status_label.setText("Cargando páginas…" if self._busy else "")
        self._update_buttons()
        if not self._busy:
            self.thumbnail_timer.start(0)

    def set_error(self, message):
        self._busy = False
        self._pending_thumbnails.clear()
        self.page_list.setEnabled(True)
        self.status_label.setText(str(message))
        self._update_buttons()

    def reset_order(self):
        if self._busy:
            return
        with QSignalBlocker(self.page_list):
            self.page_list.clear()
            for entry in self._initial:
                self._append_entry(entry)
        self.status_label.clear()
        self._changed()
