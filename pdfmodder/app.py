"""Interfaz española: el motor vive exclusivamente en un proceso serial."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import re
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QListView,
    QSplitter, QListWidget, QListWidgetItem, QPlainTextEdit, QLabel, QPushButton,
    QDoubleSpinBox, QComboBox, QCheckBox, QLineEdit, QToolBar, QFileDialog,
    QMessageBox, QDialog, QDialogButtonBox, QInputDialog, QGroupBox, QScrollArea,
)

from .canvas import PdfCanvas
from .model import EditRequest, mm, pt, union, transform
from .editing_ui import ExtendedEditing
from .advanced_ui import AdvancedEditing
from .rich_ui import RichEditing
from .object_ui import ObjectEditing
from .tools_ui_v150 import ToolsWorkspaceV150Mixin
from .page_actions_v150 import PageActionsV150Mixin
from .insertion_ui_v150 import InsertionUiV150Mixin
from .signing_ui import SigningUiMixin
from .workspace_ui_v170 import WorkspaceUiV170Mixin
from .document_ui_v170 import DocumentUiV170Mixin
from .clipboard_ui_v170 import ClipboardUiV170Mixin
from .reading_ui_v171 import ReadingUiV171Mixin
from . import __version__


def _application_icon():
    """Load the bundled icon both from the source tree and PyInstaller."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    for name in ("pdfmodder.ico", "pdfmodder.png"):
        path = root / "assets" / "icons" / name
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()


def _dispatch(command, payload):
    # This import occurs in the spawned worker. No PDF Document crosses IPC.
    from .worker import dispatch
    return dispatch(command, payload)


class MainWindow(ReadingUiV171Mixin,DocumentUiV170Mixin,ClipboardUiV170Mixin,WorkspaceUiV170Mixin,SigningUiMixin,ToolsWorkspaceV150Mixin,PageActionsV150Mixin,InsertionUiV150Mixin,RichEditing,ObjectEditing,AdvancedEditing,ExtendedEditing,QMainWindow):
    operation_finished = Signal(str, object)
    error_raised = Signal(str)
    page_ready = Signal()

    def __init__(self, initial_path=None, *, config_path=None, history_dir=None):
        super().__init__()
        self.setWindowTitle(f"PDF Modder {__version__}")
        self.resize(1420, 950)
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        self.future = None
        self._callback = None
        self._command = ""
        self._thumbnail_busy = False
        self._pending_text_preview = None
        self._closed = False
        self._allow_close = False
        self.state = {}
        self.model = None
        self.fonts = []
        self.page_number = 0
        self.zoom = 1.25
        self.config_path = config_path
        self.history_dir = history_dir
        self.last_error = ""
        self.last_report = None
        self._restore_regions = None
        self._restore_ids = None
        self._editing_context = None
        self._arrow_delta = [0.,0.]
        self._thumbnail_pages = set()
        self._thumbnail_order = []
        self._search_matches = []
        self._search_index = -1
        self._create_ui()
        self.poller = QTimer(self)
        self.poller.setInterval(30)
        self.poller.timeout.connect(self._poll)
        self.poller.start()
        self.arrow_timer = QTimer(self)
        self.arrow_timer.setSingleShot(True)
        self.arrow_timer.setInterval(180)
        self.arrow_timer.timeout.connect(self._flush_arrows)
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setInterval(500)
        self.thumbnail_timer.timeout.connect(self._load_visible_thumbnail)
        self.thumbnail_timer.start()
        self._refresh_actions()
        if initial_path:
            QTimer.singleShot(0, lambda:self.open_document(initial_path))

    @property
    def busy(self):
        return self.future is not None

    def _action(self, label, callback, shortcut=None, checkable=False):
        action = QAction(label, self)
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        self.toolbar.addAction(action)
        return action

    def _create_ui(self):
        self.toolbar = QToolBar("Documento", self)
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        self.open_action = self._action("Abrir…", self.choose_open, "Ctrl+O")
        self.save_action = self._action("Guardar como…", self.choose_save, "Ctrl+Shift+S")
        self.sign_action = self._action("Firmar…", self.choose_sign_document)
        self.sign_action.setObjectName('signDocumentAction')
        self.sign_action.setToolTip('Firmar con un certificado de Windows y sello visible opcional')
        self.toolbar.addSeparator()
        self.undo_action = self._action("Deshacer", lambda:self.history("undo"), "Ctrl+Z")
        self.redo_action = self._action("Rehacer", lambda:self.history("redo"), "Ctrl+Y")
        self.toolbar.addSeparator()
        self.toolbar.addWidget(QLabel(" Zoom "))
        self.zoom_out_action = self._action("Reducir zoom", lambda:self.step_zoom_v160(-1))
        self.zoom_out_action.setObjectName('zoomOutAction')
        self.zoom_box = QComboBox()
        self.zoom_box.setObjectName("zoomBox")
        for value in (50,75,100,125,150,200,300,400):
            self.zoom_box.addItem(f"{value}%", value/100)
        self.zoom_box.setCurrentIndex(3)
        self.zoom_box.currentIndexChanged.connect(lambda _:self.set_zoom(self.zoom_box.currentData()))
        self.toolbar.addWidget(self.zoom_box)
        self.zoom_in_action = self._action("Aumentar zoom", lambda:self.step_zoom_v160(1))
        self.zoom_in_action.setObjectName('zoomInAction')
        self.fit_page_action = self._action("Ajustar página", lambda:self.fit_page(False))
        self.fit_width_action = self._action("Ajustar anchura", lambda:self.fit_page(True))
        self.compare_action = self._action("Ver original", self.toggle_original, checkable=True)
        self.highlight_action = self._action("Resaltar cambios", self.toggle_highlights, checkable=True)
        self.highlight_action.setChecked(False)
        self.toolbar.addSeparator()
        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Buscar texto…")
        self.search_box.setMaximumWidth(190)
        self.search_box.returnPressed.connect(self.search)
        self.toolbar.addWidget(self.search_box)
        self.search_action = self._action("Buscar / siguiente", self.search, "F3")
        search_focus = QAction(self)
        search_focus.setShortcut(QKeySequence("Ctrl+F"))
        search_focus.triggered.connect(self.search_box.setFocus)
        self.addAction(search_focus)
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8,8,8,6)
        self.message = QLabel("Abre un PDF digital. Trabajarás sobre una copia y guardarás en otro archivo.")
        self.message.setWordWrap(True)
        self.message.setObjectName("messageLabel")
        self.message.setStyleSheet("padding: 8px; background: #e6eff5; color: #22384a;")
        outer.addWidget(self.message)
        self.edit_steps = QWidget()
        self.edit_steps.setObjectName('editSteps')
        steps_layout = QHBoxLayout(self.edit_steps)
        steps_layout.setContentsMargins(8,4,8,4)
        self.edit_step_label = QLabel()
        self.edit_step_label.setWordWrap(True)
        steps_layout.addWidget(self.edit_step_label,1)
        self.preview_step_button = QPushButton('1. Ver vista previa · Ctrl+Intro')
        self.preview_step_button.setObjectName('previewStepButton')
        self.preview_step_button.clicked.connect(lambda:self.preview_text(self.canvas.editor.toPlainText()))
        self.apply_step_button = QPushButton('2. Aplicar cambio')
        self.apply_step_button.setObjectName('applyStepButton')
        self.apply_step_button.clicked.connect(self.commit)
        self.cancel_step_button = QPushButton('Cancelar · Esc')
        self.cancel_step_button.setObjectName('cancelStepButton')
        self.cancel_step_button.clicked.connect(self.cancel)
        for button in (self.preview_step_button,self.apply_step_button,self.cancel_step_button):
            steps_layout.addWidget(button)
        self.edit_steps.setStyleSheet('QWidget#editSteps { background: #fff4c7; } QPushButton { padding: 6px 10px; }')
        self.edit_steps.hide()
        outer.addWidget(self.edit_steps)
        splitter = QSplitter()
        self.pages = QListWidget()
        self.pages.setObjectName("pageList")
        self.pages.setMinimumWidth(110)
        self.pages.setMaximumWidth(200)
        self.pages.setIconSize(QSize(100,135))
        self.pages.setSpacing(6)
        self.pages.setViewMode(QListView.IconMode)
        self.pages.setFlow(QListView.TopToBottom)
        self.pages.setWrapping(False)
        self.pages.setMovement(QListView.Static)
        self.pages.currentRowChanged.connect(self.go_page)
        splitter.addWidget(self.pages)
        self.canvas = PdfCanvas()
        self.canvas.selection_changed.connect(self.selection_changed)
        self.canvas.move_requested.connect(self.move_selection)
        self.canvas.edit_requested.connect(self.start_edit)
        self.canvas.preview_text.connect(self.preview_text)
        self.canvas.cancel_requested.connect(self.cancel)
        self.canvas.delete_requested.connect(lambda:self.preview_text(""))
        self.canvas.arrow_requested.connect(self.arrow_move)
        splitter.addWidget(self.canvas)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(290)
        scroll.setMaximumWidth(410)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        strict = QLabel("CONSERVACIÓN ESTRICTA\nSin sustitución de fuentes ni ajuste automático del tamaño.")
        strict.setWordWrap(True)
        strict.setStyleSheet("font-weight: 600; color: #245841; padding: 8px; background: #e3f1e7;")
        panel_layout.addWidget(strict)
        mode_layout = QFormLayout()
        self.mode_box = QComboBox()
        self.mode_box.setObjectName("selectionMode")
        for label,value in (("Carácter","character"),("Palabra","word"),("Línea","line"),("Bloque inferido","block")):
            self.mode_box.addItem(label,value)
        self.mode_box.setCurrentIndex(1)
        self.mode_box.currentIndexChanged.connect(lambda _:setattr(self.canvas,"mode",self.mode_box.currentData()))
        mode_layout.addRow("Seleccionar", self.mode_box)
        panel_layout.addLayout(mode_layout)
        hint = QLabel("Ctrl+clic: añadir/quitar fragmentos. Mayús+clic: rango en la línea. Doble clic: escribir sobre la página.")
        hint.setWordWrap(True)
        panel_layout.addWidget(hint)
        self.line_reflow_box = QCheckBox("Ajustar línea desde el panel lateral")
        self.line_reflow_box.setObjectName("lineReflowBox")
        self.line_reflow_box.setChecked(True)
        self.line_reflow_box.setToolTip("Se aplica al contenido del panel lateral y a la edición conservadora OCR/etiquetada. Conserva los extremos y reparte los espacios sin estirar letras. En el editor sobre la página se redistribuye sólo el cuadro elegido: selecciona la línea completa si quieres ajustarla entera. Los cambios explícitos de tamaño y la redistribución en varias líneas desactivan esta opción.")
        panel_layout.addWidget(self.line_reflow_box)
        self.property_box = QGroupBox("Selección")
        form = QFormLayout(self.property_box)
        self.selection_label = QLabel("Ningún texto seleccionado")
        self.selection_label.setWordWrap(True)
        form.addRow(self.selection_label)
        self.content = QPlainTextEdit()
        self.content.setObjectName("selectionText")
        self.content.setMaximumHeight(115)
        form.addRow("Contenido",self.content)
        self.font_label = QLabel("—")
        self.font_label.setWordWrap(True)
        self.font_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Fuente",self.font_label)
        self.size_box = self._spin("fontSize", 1,300, 3)
        self.size_box.setSuffix(" pt")
        form.addRow("Tamaño explícito",self.size_box)
        self.x_box = self._spin("positionX",-1000,3000)
        self.y_box = self._spin("positionY",-1000,3000)
        self.width_box = self._spin("areaWidth",.01,3000)
        self.height_box = self._spin("areaHeight",.01,3000)
        for label,box in (("X (borde izquierdo)",self.x_box),("Y (borde superior)",self.y_box),("Anchura de área",self.width_box),("Altura de área",self.height_box)):
            box.setSuffix(" mm")
            form.addRow(label,box)
        self.anchor_box = QComboBox()
        self.anchor_box.setObjectName("anchorBox")
        for label,value in (("Izquierda","left"),("Centro","center"),("Derecha","right"),("Separador decimal","decimal")):
            self.anchor_box.addItem(label,value)
        form.addRow("Anclaje del texto",self.anchor_box)
        self.decimal_box = QComboBox()
        self.decimal_box.addItems([",", "."])
        form.addRow("Separador explícito",self.decimal_box)
        self.reflow_box = QCheckBox("Redistribuir sólo esta selección")
        self.reflow_box.setObjectName("reflowBox")
        self.reflow_box.setToolTip("La anchura define el área; las letras conservan su tamaño. No redistribuye otras páginas.")
        self.reflow_box.toggled.connect(lambda _:self._refresh_actions())
        self.size_box.valueChanged.connect(lambda _:self._refresh_actions())
        form.addRow(self.reflow_box)
        self.preview_button = QPushButton("Previsualizar texto · Ctrl+Enter")
        self.preview_button.setObjectName("previewButton")
        self.preview_button.clicked.connect(lambda:self.preview_text(self.content.toPlainText()))
        form.addRow(self.preview_button)
        self.move_button = QPushButton("Mover a X / Y")
        self.move_button.setObjectName("moveButton")
        self.move_button.clicked.connect(self.move_numeric)
        form.addRow(self.move_button)
        self.edit_button = QPushButton("Editar sobre la página")
        self.edit_button.clicked.connect(self.start_edit)
        form.addRow(self.edit_button)
        panel_layout.addWidget(self.property_box)
        preview_layout = QHBoxLayout()
        self.commit_button = QPushButton("Aplicar vista previa")
        self.commit_button.setObjectName("commitButton")
        self.commit_button.clicked.connect(self.commit)
        self.cancel_button = QPushButton("Cancelar · Esc")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self.cancel)
        preview_layout.addWidget(self.commit_button)
        preview_layout.addWidget(self.cancel_button)
        panel_layout.addLayout(preview_layout)
        moving = QGroupBox("Movimiento")
        moving_form = QFormLayout(moving)
        self.step_box = self._spin("moveStep",.01,50)
        self.step_box.setValue(1.)
        self.step_box.setSuffix(" mm")
        moving_form.addRow("Paso de flechas",self.step_box)
        fine = QLabel("Mayús+flechas: 1/10 del paso. Las flechas sólo mueven cuando el documento tiene el foco.")
        fine.setWordWrap(True)
        moving_form.addRow(fine)
        self.snap_box = QCheckBox("Ajustar a bordes próximos (1 mm)")
        moving_form.addRow(self.snap_box)
        self.guides_box = QCheckBox("Mostrar guías de selección")
        self.guides_box.setChecked(True)
        self.guides_box.toggled.connect(self.toggle_guides)
        moving_form.addRow(self.guides_box)
        panel_layout.addWidget(moving)
        self.font_button = QPushButton("Inspector de fuentes / asociar TTF u OTF…")
        self.font_button.clicked.connect(self.font_inspector)
        panel_layout.addWidget(self.font_button)
        panel_layout.addStretch()
        scroll.setWidget(panel)
        splitter.addWidget(scroll)
        splitter.setSizes([140,950,320])
        splitter.setStretchFactor(1,1)
        outer.addWidget(splitter,1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Preparado · Sólo archivos locales")
        preview_action = QAction(self)
        preview_action.setShortcut(QKeySequence("Ctrl+Return"))
        preview_action.triggered.connect(lambda:self.preview_text(self.canvas.editor.toPlainText() if self.canvas.editor.isVisible() else self.content.toPlainText()))
        self.addAction(preview_action)
        escape = QAction(self)
        escape.setShortcut(QKeySequence("Escape"))
        escape.triggered.connect(self.cancel)
        self.addAction(escape)
        self._create_extended_ui(panel_layout)
        self._create_advanced_ui(panel_layout,form)
        self._init_rich(panel_layout)
        self._init_objects()
        self._create_tools_workspace_v150(splitter,scroll,panel)
        self._create_document_ui_v170()
        self._create_clipboard_ui_v170()
        self._create_workspace_v170()
        self.toolbar.insertAction(self.sign_action,self.document_properties_action)
        self.toolbar.insertAction(self.sign_action,self.document_security_action)
        toolbar_actions=self.toolbar.actions()
        clipboard_anchor=toolbar_actions[toolbar_actions.index(self.redo_action)+1]
        for action in (self.cut_action_v170,self.copy_action_v170,self.paste_action_v170,self.delete_action_v170):
            self.toolbar.removeAction(action)
            self.toolbar.insertAction(clipboard_anchor,action)
        self._create_reading_ui_v171()

    @staticmethod
    def _spin(name, low, high, decimals=3):
        box = QDoubleSpinBox()
        box.setObjectName(name)
        box.setRange(low, high)
        box.setDecimals(decimals)
        box.setKeyboardTracking(False)
        return box

    def _submit(self, command, payload=None, callback=None):
        if self.busy or self._closed:
            return False
        if not self._reading_command_allowed_v171(command):
            return False
        if getattr(self, '_signature_placement_dialog', None) is not None and command != 'page':
            return False
        self.last_error = ""
        self._command = command
        self._callback = callback
        self._thumbnail_busy = command == "page" and bool((payload or {}).get("thumbnail"))
        self.future = self.pool.submit(_dispatch,command,payload or {})
        self.statusBar().showMessage({"open":"Abriendo PDF…","page":"Renderizando página…","preview":"Validando y renderizando la modificación…","apply":"Validando movimiento…","save":"Validando y guardando copia…"}.get(command,"Procesando…"))
        self._refresh_actions()
        return True

    def _poll(self):
        if not self.future or not self.future.done():
            return
        future,command,callback = self.future,self._command,self._callback
        was_thumbnail = self._thumbnail_busy
        self.future = None
        self._callback = None
        self._thumbnail_busy = False
        try:
            result = future.result()
            if "state" in result:
                self.state = result["state"]
            self._refresh_actions()
            if callback:
                callback(result)
            self.operation_finished.emit(command,result)
        except Exception as exc:
            if command == 'prepare_editing':
                self._mode_preparing_v171 = False
                self._set_mode_v171('reading')
            if command in ('rich_preview','rich_prepare') and not self._rich_active:
                self._refresh_actions()
                return
            self._rich_failed(command,str(exc))
            if command == "open" and "PASSWORD_REQUIRED:" in str(exc):
                password, accepted = QInputDialog.getText(self,"PDF cifrado","Introduce una contraseña legítima del documento:",QLineEdit.Password)
                if accepted:
                    self.open_document(self._open_retry[0],password)
                else:
                    self._notice("Apertura cancelada. El documento de trabajo anterior se conserva.")
                    self._refresh_actions()
                return
            self._error(str(exc))
            self._refresh_actions()
        if was_thumbnail and self._pending_text_preview is not None:
            pending,self._pending_text_preview = self._pending_text_preview,None
            request,context = pending
            self.canvas.editor.setReadOnly(False)
            if context != (self.page_number,self.model.revision,tuple(self.canvas.ids)):
                self.content.setPlainText(request.text)
                self._error("La selección cambió antes de previsualizar. El borrador se conserva; selecciona de nuevo.")
                self._refresh_actions()
            else:
                self._send_text_preview(request)

    def _error(self, text):
        self.last_error = text
        self.message.setText(text)
        self.message.setStyleSheet("padding: 8px; color: #922a23; background: #ffebe7;")
        self.statusBar().showMessage("La operación no se ha aplicado. El trabajo anterior se conserva.")
        self.error_raised.emit(text)

    def _notice(self, text):
        self.message.setText(text)
        self.message.setStyleSheet("padding: 8px; color: #22384a; background: #e6eff5;")

    def _refresh_actions(self):
        self._sync_page_list()
        opened = bool(self.state)
        ready = opened and not self.busy
        preview = self.state.get("preview",False)
        original = self.compare_action.isChecked()
        selected = bool(self.canvas.ids) and not original and not preview
        permitted = not self.state.get("issues")
        writing = self.canvas.editor.isVisible() or getattr(self,'_rich_active',False) or getattr(self,'_rich_loading',False)
        self.open_action.setEnabled(not self.busy and not writing)
        self.save_action.setEnabled(ready and not preview and (permitted or self.state.get('metadata_only_save',False)) and not writing)
        self.sign_action.setEnabled(ready and not preview and permitted and not writing and not original)
        self.undo_action.setEnabled(ready and self.state.get("undo",False) and not writing)
        self.redo_action.setEnabled(ready and self.state.get("redo",False) and not writing)
        self.property_box.setEnabled(ready and selected and permitted and not writing)
        self.commit_button.setEnabled(ready and preview and not original)
        self.cancel_button.setEnabled(ready and (preview or self.canvas.editor.isVisible()))
        self.font_button.setEnabled(ready and not preview and not writing)
        self.pages.setEnabled(ready and not preview and not writing)
        for action in (self.fit_page_action,self.fit_width_action,self.compare_action,self.search_action):
            action.setEnabled(ready and not preview and not writing)
        self.search_box.setEnabled(ready and not writing)
        self.zoom_box.setEnabled(ready and not writing)
        self.zoom_out_action.setEnabled(ready and not writing and self.zoom > .100001)
        self.zoom_in_action.setEnabled(ready and not writing and self.zoom < 3.999999)
        self.canvas.read_only = not ready or original or preview or not permitted or writing
        self.canvas.allow_background_edit = bool(opened and self._thumbnail_busy and not original and not preview and permitted and not writing)
        self.line_reflow_box.setEnabled(bool(opened and selected and permitted and not (getattr(self,'_rich_active',False) or getattr(self,'_rich_loading',False)) and (ready or self._thumbnail_busy) and self._line_reflow_available() and self._pending_text_preview is None))
        if self._thumbnail_busy and writing:
            self.cancel_button.setEnabled(True)
        self.edit_steps.setVisible(bool(writing or preview or self._pending_text_preview))
        self.preview_step_button.setEnabled(bool(writing and (ready or self._thumbnail_busy) and not preview and self._pending_text_preview is None))
        self.apply_step_button.setEnabled(self.commit_button.isEnabled())
        self.cancel_step_button.setEnabled(self.cancel_button.isEnabled())
        self.edit_step_label.setText('Revisa el PDF modificado y pulsa «Aplicar cambio». Después, «Guardar como…».' if preview else
                                    'Primero genera la vista previa; después podrás aceptar la modificación con «Aplicar cambio».')
        title = Path(self.state.get("path","")).name if opened else "Sin documento"
        mark = " *" if self.state.get("dirty") else ""
        pending = " · VISTA PREVIA" if preview else ""
        original_label = " · ORIGINAL (sólo lectura)" if original else ""
        self.setWindowTitle(f"{title}{mark}{pending}{original_label} — PDF Modder {__version__}")
        origins=self.state.get('original_pages',[])
        if origins and origins[self.page_number] is None:
            self.compare_action.setEnabled(False)
        self._refresh_extended()
        self._refresh_advanced()
        if hasattr(self,'objects_action'):
            self.objects_action.setEnabled(ready and permitted and not writing and not preview and not original)
            self.copy_format_action.setEnabled(ready and selected and not writing and permitted)
            self.paste_format_action.setEnabled(ready and bool(self._format_copy) and not writing and permitted and not preview)
            self.interaction_box.setEnabled(ready and not writing and not preview)
        if getattr(self,'_rich_active',False):
            self.edit_step_label.setText('✓ Aceptar / Ctrl+Intro valida y aplica el borrador. × Cancelar / Esc lo descarta.')
            self.preview_step_button.setText('Aceptar ✓ · Ctrl+Intro')
            self.preview_step_button.setEnabled(not self._rich_accept_pending)
            self.apply_step_button.hide()
            self.cancel_step_button.setEnabled(not self._rich_accept_pending)
        else:
            self.preview_step_button.setText('1. Ver vista previa · Ctrl+Intro')
            self.preview_step_button.show()
            self.apply_step_button.show()
        self._refresh_document_v170()
        self._refresh_clipboard_v170()
        self._refresh_v170()
        self._restrict_signature_placement()
        self._refresh_reading_actions_v171()

    def _confirm_discard(self):
        if not (self.state.get("dirty") or self.state.get("preview") or self.canvas.editor.isVisible()):
            return True
        return QMessageBox.question(self,"Trabajo sin guardar","Hay cambios sin guardar. ¿Descartarlos y continuar?",QMessageBox.Discard | QMessageBox.Cancel,QMessageBox.Cancel) == QMessageBox.Discard

    def choose_open(self):
        if not self._confirm_discard():
            return
        path,_ = QFileDialog.getOpenFileName(self,"Abrir PDF digital","","Documentos PDF (*.pdf)")
        if path:
            self.open_document(path)

    def open_document(self,path,password=""):
        if self.canvas.editor.isVisible():
            self._error("Aplica o cancela la escritura antes de abrir otro documento.")
            return False
        payload = {"path":str(path),"password":password,"reading":True}
        if self.config_path:
            payload["config_path"] = str(self.config_path)
        if self.history_dir:
            payload["history_dir"] = str(self.history_dir)
        def opened(result):
            self.recent_open(self.state.get('path',path))
            self._set_mode_v171('reading')
            self.model = None
            self.page_number = 0
            self._thumbnail_pages.clear()
            self._thumbnail_order.clear()
            self.compare_action.setChecked(False)
            self._search_matches = []
            self.canvas.search_rects = []
            self.pages.blockSignals(True)
            self.pages.clear()
            for index in range(self.state["page_count"]):
                item = QListWidgetItem(f"Página {index+1}")
                item.setSizeHint(QSize(118,158))
                item.setTextAlignment(Qt.AlignHCenter)
                self.pages.addItem(item)
            self.pages.setCurrentRow(0)
            self.pages.blockSignals(False)
            if self.state.get('issues'):
                self._error('\n'.join(self.state['issues']))
            elif self.application_mode == 'reading':
                self._notice('Modo Lectura: selecciona y copia texto. Pulsa «Herramientas» para editar.')
            elif self.state.get('tagged'):
                pages=self.state.get('page_capabilities',{})
                page_notice=('Puedes eliminar o extraer páginas conservando sus etiquetas.' if pages.get('delete') and pages.get('extract')
                             else 'Páginas: '+(pages.get('reason') or 'la estructura requiere una comprobación específica.'))
                self._notice('PDF etiquetado: selecciona texto y haz doble clic para editarlo. '+page_notice+' El PDF original se conserva.')
            else:
                self._notice('Modo Lectura: selecciona y copia texto. Pulsa «Herramientas» para editar.')
            self.load_page()
        self._open_retry = (str(path),password)
        return self._submit("open",payload,opened)

    def load_page(self):
        if not self.state:
            return
        self._sync_page_list()
        origins=self.state.get('original_pages',[])
        if origins and origins[self.page_number] is None:
            self.compare_action.setChecked(False)
        self._submit("page",{"number":self.page_number,"zoom":self.zoom,"original":self.compare_action.isChecked(),"reading":self.application_mode=='reading'},self._loaded_page)

    def _loaded_page(self,result):
        self._page_png=result['png']
        self.model = result["model"]
        self.fonts = result["fonts"]
        pixmap = self.canvas.set_page(result["png"],self.model,result["zoom"],result["changes"])
        self.zoom = result["zoom"]
        self._sync_zoom_control()
        self.canvas.set_images(result.get('images',[]),self._restore_image_rect)
        self._restore_image_rect=None
        self._set_thumbnail(self.page_number,pixmap)
        if self._restore_regions is not None and not self.state.get("preview"):
            regions = self._restore_regions
            ids = [g.id for g in self.model.glyphs if any(r[0]-.2 <= (g.bbox[0]+g.bbox[2])/2 <= r[2]+.2 and r[1]-.2 <= (g.bbox[1]+g.bbox[3])/2 <= r[3]+.2 for r in regions)]
            self._restore_regions = None
            self.canvas.set_selection(ids)
        elif self._restore_ids is not None and not self.state.get("preview"):
            self.canvas.set_selection(self._restore_ids)
            self._restore_ids = None
        elif not self.state.get("preview"):
            self.selection_changed([])
        self._refresh_actions()
        focus_regions = ((self.last_report or {}).get('destination_regions', [])
                         if self.state.get('preview') else
                         [g.bbox for g in self.model.selected(self.canvas.ids)])
        if not focus_regions and self.canvas.selected_image():
            focus_regions = [self.canvas.selected_image()['rect']]
        if focus_regions:
            displayed_model = self.model
            def reveal_edit():
                if not self._closed and self.model is displayed_model:
                    self.canvas.ensureVisible(self.canvas.scene_rect(union(focus_regions)), 35, 35)
            # Wait for the edit toolbar and properties to finish their layout.
            QTimer.singleShot(0, reveal_edit)
        self.statusBar().showMessage(f"Página {self.page_number+1}/{self.state['page_count']} · Zoom {self.zoom*100:.1f}% · PDF real renderizado" + (" · PREVISUALIZACIÓN pendiente de aplicar" if self.state.get("preview") else ""))
        if result.get('comparison_warning') and self.compare_action.isChecked():
            self._notice(result['comparison_warning'])
        self._advanced_page()
        self._after_reading_page_loaded_v171()
        self.page_ready.emit()

    def go_page(self,index):
        if index < 0 or index >= self.state.get('page_count',0) or not self.state or self.busy or self.state.get("preview") or self.canvas.editor.isVisible():
            return
        self.page_number = index
        self._restore_ids = self._restore_regions = None
        self.canvas.search_rects = [m["rect"] for m in self._search_matches if m["page"] == index]
        self.load_page()

    def _sync_zoom_control(self):
        blocked = self.zoom_box.blockSignals(True)
        try:
            custom = self.zoom_box.findData('fit', Qt.UserRole + 1)
            if custom >= 0:
                self.zoom_box.removeItem(custom)
            index = next((i for i in range(self.zoom_box.count())
                          if abs(float(self.zoom_box.itemData(i)) - self.zoom) < 1e-8), -1)
            if index < 0:
                self.zoom_box.addItem(f'{self.zoom * 100:.1f}%', self.zoom)
                index = self.zoom_box.count() - 1
                self.zoom_box.setItemData(index, 'fit', Qt.UserRole + 1)
            self.zoom_box.setCurrentIndex(index)
        finally:
            self.zoom_box.blockSignals(blocked)

    def step_zoom_v160(self, direction):
        """Scale from the actual zoom, including a custom Fit page value."""
        self.set_zoom(self.zoom * (1.25 if direction > 0 else .8))

    def set_zoom(self,value):
        if not value or self.busy or self.canvas.editor.isVisible():
            return
        self.zoom = max(.1,min(float(value),4.))
        if self.model:
            self._restore_ids = self.canvas.ids[:]
            self.load_page()

    def fit_page(self,width_only=False):
        if not self.model:
            return
        viewport = self.canvas.viewport()
        ratio = (viewport.width()-35)/self.model.width
        if not width_only:
            ratio = min(ratio,(viewport.height()-35)/self.model.height)
        self.set_zoom(ratio)

    def toggle_original(self,checked):
        self.canvas.editor.hide()
        self._restore_ids = self._restore_regions = None
        self._notice("Comparación: documento original, sólo lectura. Los contornos naranjas indican zonas modificadas." if checked else "Documento de trabajo. La vista procede del PDF realmente modificado.")
        self.load_page()

    def toggle_highlights(self,checked):
        self.canvas.highlight_changes = checked
        self.canvas._draw_overlays()

    def toggle_guides(self,checked):
        self.canvas.show_guides = checked
        self.canvas._draw_overlays()

    def selection_changed(self,ids):
        if hasattr(self,"arrow_timer"):
            self.arrow_timer.stop()
            self._arrow_delta = [0.,0.]
        if not self.model or not ids:
            self.selection_label.setText("Ningún texto seleccionado")
            self.content.clear()
            self.font_label.setText("—")
            self._refresh_actions()
            return
        selected = self.model.selected(ids)
        if self.application_mode == 'reading':
            self.selection_label.setText(f'{len(selected)} caracteres · Lectura / Ctrl+C para copiar')
            self.content.setPlainText(self.canvas.reading_text())
            self._refresh_actions()
            return
        bounds = union(g.bbox for g in selected)
        styles = {(g.font,g.size,g.color,g.opacity,g.direction) for g in selected}
        self.selection_label.setText(f"{len(selected)} caracteres · {len(styles)} estilo(s)" + ("\nVarios formatos: edita por fragmentos sobre la página. Cada recurso se verifica antes de aplicar." if len(styles)>1 else ""))
        self.content.setPlainText(self.model.text(ids))
        def normalized(name):
            return re.sub(r"^[A-Z]{6}\+","",str(name).lstrip("/"))
        font_messages = []
        for name,xref,resource in sorted({(g.font,g.font_xref,g.font_resource) for g in selected},key=str):
            candidates = [item for item in self.fonts if str(item.get('resource','')).lstrip('/')==str(resource).lstrip('/') and (xref is None or item.get('xref')==xref)] if resource else [item for item in self.fonts if item.get('xref')==xref] if xref else [
                item for item in self.fonts if normalized(name) in {normalized(item.get(key,'')) for key in ('name','extracted_name','postscript_name','resource')}]
            info = candidates[0] if len(candidates)==1 else {}
            source = info.get("resolved_source")
            status = f"Resuelta: {source}" if source else info.get("status","Resolución pendiente de validación")
            if xref and info.get('embedded'):
                program=info.get('font_program') or info
                identity=f"{program.get('postscript_name') or name} · {info.get('variant') or 'variante no identificada'}"
                if program.get('version'): identity+=' · '+str(program['version'])
                status=f"Incrustada · /{str(resource).lstrip('/')} · objeto {xref}\nDetalles y cobertura en «Inspector de fuentes»."
                font_messages.append(identity+'\n'+status)
            elif len(candidates)>1:
                font_messages.append(f'{name}\nNombre ambiguo: {len(candidates)} recursos. Abre el inspector para comprobar la selección.')
            else:
                font_messages.append(f"{name}\n{status}")
        self.font_label.setText("\n".join(font_messages))
        self.font_label.setToolTip(self.font_label.text())
        self.size_box.setValue(selected[0].size)
        self.x_box.setValue(mm(bounds[0]))
        self.y_box.setValue(mm(bounds[1]))
        self.width_box.setValue(mm(bounds[2]-bounds[0]))
        self.height_box.setValue(mm(bounds[3]-bounds[1]))
        self.reflow_box.setChecked(False)
        self._refresh_actions()

    def start_edit(self):
        from .clipping import CLIP_ISSUE
        tagged_clipped = bool(self.state.get('tagged') and self.model and CLIP_ISSUE in self.model.issues)
        if (self.state.get('tagged') and not tagged_clipped) or (self.model and any(g.mode==3 for g in self.model.glyphs)):
            self.start_legacy_edit()
            self._notice('Esta selección utiliza la edición conservadora de etiquetas/OCR. Ctrl+Intro genera la vista previa y «Aplicar» confirma; el formato por fragmentos no se aplica a esta capa.')
            return
        return self.start_rich_edit()

    def start_legacy_edit(self):
        if (self.busy and not self._thumbnail_busy) or (self.canvas.read_only and not self.canvas.allow_background_edit) or not self.canvas.ids:
            return
        self.canvas.start_editor(self.content.toPlainText())
        self._editing_context=(self.page_number,self.model.revision,tuple(self.canvas.ids))
        self._notice('Escribe en el cuadro. Pulsa «1. Ver vista previa» arriba o Ctrl+Intro; después «2. Aplicar cambio». Escape cancela.')
        self._refresh_actions()

    def _line_reflow_available(self):
        selected = self.model.selected(self.canvas.ids) if self.model else []
        return bool(selected and len({(g.line,g.mode) for g in selected}) == 1
                    and not self.reflow_box.isChecked()
                    and abs(self.size_box.value()-selected[0].size) <= .0006)

    def _request(self,text=None,dx=0.,dy=0.,formatting=False,adjust_line=False):
        if not self.model or not self.canvas.ids:
            raise ValueError("Selecciona caracteres, una palabra, una línea o un bloque.")
        request = EditRequest(page=self.page_number,ids=self.canvas.ids[:],text=text,dx=dx,dy=dy,revision=self.model.revision)
        if formatting:
            request.anchor = self.anchor_box.currentData()
            request.width = pt(self.width_box.value())
            request.height = pt(self.height_box.value())
            original_size = self.model.selected(self.canvas.ids)[0].size
            request.size = self.size_box.value() if abs(self.size_box.value()-original_size)>.0006 else None
            request.reflow = self.reflow_box.isChecked()
            request.decimal_separator = self.decimal_box.currentText()
        request.line_reflow = bool(adjust_line and text is not None and "\n" not in text and "\r" not in text
                                   and not dx and not dy and self.line_reflow_box.isChecked()
                                   and self._line_reflow_available() and request.size is None)
        if request.line_reflow:
            selected = self.model.selected(self.canvas.ids)
            line_ids = {g.id for g in self.model.glyphs if g.line == selected[0].line and g.mode == selected[0].mode
                        and (g.opacity>0)==(selected[0].opacity>0)}
            if set(self.canvas.ids) != line_ids:
                # A word's visible bounds are not the available line area.
                # The engine takes the complete inferred line's endpoints.
                request.width = request.height = None
        return self._extend_request(request)

    def preview_text(self,text):
        if getattr(self,'_rich_active',False):
            self._rich_accept(self.canvas.editor.payload())
            return
        if (self.busy and not self._thumbnail_busy) or self.compare_action.isChecked() or self.state.get("preview") or self._pending_text_preview is not None:
            return
        try:
            if self._editing_context and self._editing_context!=(self.page_number,self.model.revision,tuple(self.canvas.ids)):
                raise ValueError("La selección cambió durante la escritura. Cancela el borrador y selecciona de nuevo.")
            request = self._request(text=text,formatting=True,adjust_line=True)
            if self._thumbnail_busy:
                self._pending_text_preview = (request,(self.page_number,self.model.revision,tuple(self.canvas.ids)))
                self.canvas.editor.setReadOnly(True)
                self._notice("La previsualización está pendiente de terminar la miniatura. Escape cancela la solicitud.")
                self._refresh_actions()
            else:
                self._send_text_preview(request)
        except ValueError as exc:
            self._error(str(exc))

    def _send_text_preview(self,request):
        self._restore_ids = self.canvas.ids[:]
        self.content.setPlainText(request.text)
        self.canvas.editor.hide()
        self._editing_context = None
        self._submit("preview",{"request":request},self._previewed)

    def _previewed(self,result):
        self.last_report = result.get("report")
        if (self.last_report or {}).get('operation')=='organize_pages':
            self.page_number=0
            self._restore_ids=self._restore_regions=None
            self._thumbnail_pages.clear();self._thumbnail_order.clear()
            for i in range(self.pages.count()):self.pages.item(i).setIcon(QIcon())
        if (self.last_report or {}).get('operation','').startswith('image_'):
            regions=self.last_report.get('destination_regions',[])
            self._restore_image_rect=regions[-1] if regions else None
            self._restore_ids=self._restore_regions=None
        notice="Vista previa del PDF modificado y validado. Aplica el cambio o cancélalo; aún no forma parte del historial."
        if (self.last_report or {}).get('warning'):notice+=' '+self.last_report['warning']
        if ((self.last_report or {}).get('line_reflow_requested') and not self.last_report.get('line_reflow')):
            notice += " En este campo se conserva la fuente y se compone el texto dentro del área; los vecinos permanecen fijos y no se justifica la línea."
        self._notice(notice)
        self.load_page()

    def commit(self):
        if self.state.get("preview"):
            self._submit("commit",callback=self._edited)

    def _edited(self,result):
        self.last_report = result.get("report")
        self._restore_regions = (self.last_report or {}).get("destination_regions",[])
        if (self.last_report or {}).get('operation','').startswith('image_'):
            self._restore_image_rect=self._restore_regions[-1] if self._restore_regions else None
            self._restore_regions=None
        self._restore_ids = None
        self._search_matches = []
        self._last_search = None
        self.canvas.search_rects = []
        self._thumbnail_pages.clear()
        self._thumbnail_order.clear()
        for index in range(self.pages.count()):
            self.pages.item(index).setIcon(QIcon())
        removed=(self.last_report or {}).get('removed_bookmarks',[])
        message="Cambio aplicado al PDF. Guardar como crea una copia validada."
        if (self.last_report or {}).get('warning'):
            message+=' '+self.last_report['warning']
        if removed:
            message+=f" Se retiraron {len(removed)} marcadores de páginas excluidas: "+', '.join(str(title) for title in removed)+'.'
        self._notice(message)
        self.load_page()

    def cancel(self):
        if self._cancel_signature_placement():return
        if self.cancel_rich():return
        if self.busy and not self._thumbnail_busy:
            return
        self._pending_text_preview = None
        self.canvas.editor.setReadOnly(False)
        self.canvas._press = self.canvas._drag = None
        self.canvas._image_drag_rect=None
        self.canvas._image_rotate=False
        self.canvas._image_rotate_angle=None
        self.canvas._text_resize=self.canvas._text_resize_rect=None
        self.canvas._image_resize=None
        if self._placement:
            self._cancel_placement()
            self._notice('Inserción cancelada. El PDF no se ha modificado.')
        self.canvas._draw_overlays()
        self.arrow_timer.stop()
        self._arrow_delta = [0.,0.]
        if self.canvas.editor.isVisible():
            self.canvas.editor.hide()
            self._editing_context=None
            if self.model:
                self.content.setPlainText(self.model.text(self.canvas.ids))
            self.canvas.setFocus()
            self._notice("Escritura cancelada. El PDF no se ha modificado.")
            self._refresh_actions()
        elif self.state.get("preview"):
            self._submit("cancel",callback=lambda _:self.load_page())
            self._notice("Previsualización cancelada. Se recuperó el estado anterior.")
        elif self.model and self.canvas.ids:
            self.content.setPlainText(self.model.text(self.canvas.ids))
            self._notice("Borrador cancelado. El PDF no se ha modificado.")

    def move_selection(self,dx,dy):
        if self.busy or self.canvas.read_only or not self.canvas.ids:
            return
        try:
            if self.snap_box.isChecked():
                dx,dy = self._snap(dx,dy)
            self._submit("apply",{"request":self._request(dx=dx,dy=dy)},self._edited)
        except ValueError as exc:
            self._error(str(exc))

    def move_numeric(self):
        if self.model and self.canvas.ids:
            bounds = union(g.bbox for g in self.model.selected(self.canvas.ids))
            self.move_selection(pt(self.x_box.value())-bounds[0],pt(self.y_box.value())-bounds[1])

    def _snap(self,dx,dy):
        bounds = union(g.bbox for g in self.model.selected(self.canvas.ids))
        others = [g for g in self.model.glyphs if g.id not in self.canvas.ids]
        for axis,delta in ((0,dx),(1,dy)):
            candidates = [g.bbox[side]-(bounds[edge]+delta) for g in others for edge in (axis,axis+2) for side in (axis,axis+2)]
            corrections = [value for value in candidates if abs(value)<=pt(1)]
            if corrections:
                correction = min(corrections,key=abs)
                if axis==0: dx += correction
                else: dy += correction
        return dx,dy

    def arrow_move(self,x,y,fine):
        if not self.model or self.busy or self.canvas.read_only:
            return
        step = pt(self.step_box.value())*(.1 if fine else 1.)
        origin = transform((0,0),self.model.derotation_matrix)
        target = transform((x*step,y*step),self.model.derotation_matrix)
        self._arrow_delta[0] += target[0]-origin[0]
        self._arrow_delta[1] += target[1]-origin[1]
        self.arrow_timer.start()

    def _flush_arrows(self):
        dx,dy = self._arrow_delta
        self._arrow_delta = [0.,0.]
        if dx or dy:
            item=self.canvas.selected_image() if self.canvas.image_mode else None
            if item and item.get('editable'):
                rect=item['rect']
                self.transform_image(item['id'],(rect[0]+dx,rect[1]+dy,rect[2]+dx,rect[3]+dy))
            else:
                self.move_selection(dx,dy)

    def history(self,command):
        self.canvas.editor.hide()
        self._restore_ids = self._restore_regions = None
        self._search_matches = []
        self._last_search = None
        self.canvas.search_rects = []
        self._thumbnail_pages.clear()
        self._thumbnail_order.clear()
        for index in range(self.pages.count()):
            self.pages.item(index).setIcon(QIcon())
        self._submit(command,callback=lambda _:self.load_page())

    def choose_save(self):
        source = Path(self.state.get("path","documento.pdf"))
        path,_ = QFileDialog.getSaveFileName(self,"Guardar copia PDF",str(source.with_name(source.stem+"_editado.pdf")),"Documento PDF (*.pdf)")
        if path:
            self.save_as(path)

    def save_as(self,path):
        def saved(result):
            self._notice(f"Copia validada y guardada: {result['path']}")
            self.statusBar().showMessage("Guardado completo. El archivo original se conserva.")
        return self._submit("save",{"path":str(path)},saved)

    def search(self):
        text = self.search_box.text()
        if not text or not self.state or self.busy:
            return
        if getattr(self,"_last_search",None) == text and self._search_matches:
            self._next_match()
            return
        self._last_search = text
        def found(result):
            self._search_matches = result["matches"]
            self._search_index = -1
            if not self._search_matches:
                self._notice(f"No se encuentra «{text}» en el documento de trabajo.")
                self.canvas.search_rects = []
                self.canvas._draw_overlays()
            else:
                self._next_match()
        self._submit("search",{"text":text},found)

    def _next_match(self):
        self._search_index = (self._search_index+1)%len(self._search_matches)
        match = self._search_matches[self._search_index]
        self._notice(f"Coincidencia {self._search_index+1} de {len(self._search_matches)} · Página {match['page']+1}")
        self.page_number = match["page"]
        self.pages.blockSignals(True)
        self.pages.setCurrentRow(self.page_number)
        self.pages.blockSignals(False)
        self.canvas.search_rects = [m["rect"] for m in self._search_matches if m["page"]==self.page_number]
        self.load_page()

    def _set_thumbnail(self,number,pixmap):
        if number >= self.pages.count():
            return
        self.pages.item(number).setIcon(QIcon(pixmap.scaled(100,135,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
        self._thumbnail_pages.add(number)
        if number in self._thumbnail_order:
            self._thumbnail_order.remove(number)
        self._thumbnail_order.append(number)
        while len(self._thumbnail_order)>30:
            old = self._thumbnail_order.pop(0)
            self.pages.item(old).setIcon(QIcon())
            self._thumbnail_pages.discard(old)

    def _load_visible_thumbnail(self):
        if (self.busy or not self.model or self.state.get("preview") or self._closed
                or self.canvas.editor.isVisible() or self.canvas.pointer_gesture_pending()
                or self._placement
                or QApplication.activeModalWidget() is not None):
            return
        for index in range(self.pages.count()):
            if index in self._thumbnail_pages:
                continue
            if not self.pages.visualItemRect(self.pages.item(index)).intersects(self.pages.viewport().rect()):
                continue
            def loaded(result):
                pixmap = QPixmap()
                pixmap.loadFromData(result["png"],"PNG")
                self._set_thumbnail(result["number"],pixmap)
                self.statusBar().showMessage(f"Página {self.page_number+1}/{self.state['page_count']} · Preparado")
            self._submit("page",{"number":index,"zoom":.18,"thumbnail":True,"original":self.compare_action.isChecked()},loaded)
            break

    def font_inspector(self):
        if self.canvas.ids and self.model:
            self._submit('font_evidence',{'page':self.page_number,'ids':self.canvas.ids[:],
                         'revision':self.model.revision,'original':self.compare_action.isChecked()},
                         lambda result:self._show_font_inspector(result['evidence']))
            return
        self._show_font_inspector()

    def _show_font_inspector(self,evidence=None):
        dialog = QDialog(self)
        dialog.setWindowTitle("Inspector de fuentes y asociaciones locales")
        dialog.setObjectName('fontInspectorDialog')
        dialog.resize(820,650)
        layout = QVBoxLayout(dialog)
        if evidence:
            summary=QLabel('La identificación se refiere al recurso usado por los caracteres seleccionados. Un archivo local con el mismo nombre o versión no acredita por sí solo identidad con el original.')
            summary.setWordWrap(True)
            layout.addWidget(summary)
        choice = QComboBox()
        choice.setObjectName('fontInspectorChoice')
        for index,item in enumerate(self.fonts):
            choice.addItem(f"{item.get('name',item.get('basefont',f'Fuente {index+1}'))} · /{str(item.get('resource','?')).lstrip('/')} · objeto {item.get('xref','?')}",index)
        selected_fonts={(g.font_xref,g.font_resource) for g in self.model.selected(self.canvas.ids)} if self.model and self.canvas.ids else set()
        preferred=next((i for i,item in enumerate(self.fonts) if any(
            (xref is None or item.get('xref')==xref) and
            (resource is None or str(item.get('resource','')).lstrip('/')==resource.lstrip('/'))
            for xref,resource in selected_fonts if xref is not None or resource is not None)),0)
        choice.setCurrentIndex(preferred)
        layout.addWidget(choice)
        details = QPlainTextEdit()
        details.setObjectName('fontInspectorDetails')
        details.setReadOnly(True)
        layout.addWidget(details)
        def show_font(index):
            if index<0: return
            info = dict(self.fonts[index])
            introduction = []
            if evidence:
                def same_resource(candidate):
                    return (candidate.get('xref')==info.get('xref') and
                            str(candidate.get('resource','')).lstrip('/')==str(info.get('resource','')).lstrip('/'))
                matching=[item for item in evidence if any(same_resource(candidate) for candidate in item.get('candidates',[]))]
                info['Evidencia de la selección']=matching or 'Este recurso no corresponde a los caracteres seleccionados.'
                for match in matching:
                    candidate=next(c for c in match['candidates'] if same_resource(c))
                    program=candidate.get('font_program') or candidate
                    introduction.extend([
                        match['certainty_label'],
                        f"Tipografía: {program.get('postscript_name') or candidate.get('name')} · {program.get('variant') or 'Variante desconocida'} · {program.get('version') or 'Versión desconocida'}",
                        f"Recurso de la selección: /{str(candidate.get('resource','?')).lstrip('/')} · objeto {candidate.get('xref','?')}",
                        'Vínculo con los caracteres: '+('operadores PDF verificados' if match['resource_match']=='explicit_resource' else 'por nombre; no se pudo verificar el operador exacto'),
                        match['certainty_detail'],
                        'Reinserción por Unicode: '+candidate['coverage']['detail'],
                    ])
                    if candidate['coverage'].get('status')=='encoding_not_reusable':
                        introduction.append('Los cambios que conservan códigos y avances PDF pueden reutilizar este recurso sin reinserción Unicode. La vista previa comprueba si el cambio concreto es compatible.')
                    for local in candidate.get('local_candidates',[]):
                        local_program=local.get('font_program') or {}
                        introduction.append(f"Archivo local candidato: {local.get('path')}\n{local_program.get('postscript_name','Nombre no disponible')} · {local_program.get('version','Versión no disponible')}\n{local.get('identity_detail') or local.get('status')}")
            characters = info.pop("available_characters",None)
            labels = {"name":"Nombre PDF","family":"Familia","variant":"Variante","version":"Versión","postscript_name":"Nombre PostScript","sha256":"Huella SHA-256","available_count":"Número de caracteres","fs_type":"Restricciones OS/2.fsType","os2_version":"Versión OS/2","embedding_permission":"Permiso de incrustación","license":"Licencia","license_url":"URL de licencia","manufacturer_url":"Web del fabricante","permissions_url":"Referencia oficial de permisos","identity_verified":"Identidad tipográfica verificada","variable":"Fuente variable","no_subsetting":"Prohíbe subconjuntos","embedded":"Incrustada","subset":"Subconjunto","resource":"Recurso PDF","xref":"Objeto PDF","source":"Origen detectado","resolved_source":"Origen resuelto","resolved_name":"Fuente resuelta","status":"Estado","association":"Asociación local","base14":"Recurso Base14","extracted_name":"Nombre extraído"}
            labels.update({'byte_length':'Tamaño del programa en bytes','glyph_count':'Número de glifos','unicode_cmap':'Tabla Unicode reutilizable','cmap_tables':'Tablas de caracteres','table_tags':'Tablas del programa','variant_source':'Origen de la variante','font_program':'Programa incrustado','identity_evidence':'Evidencia de identidad','coverage':'Cobertura para reinserción','local_candidates':'Candidatos instalados','local_candidates_checked':'Candidatos locales inspeccionados','resolved_program':'Programa resuelto','resolved_path':'Archivo resuelto','declared_name':'Nombre declarado','same_name_resources':'Recursos con el mismo nombre','type':'Tipo PDF','extension':'Formato de fuente','encoding':'Codificación'})
            text = ('\n\n'.join(introduction)+'\n\nDATOS TÉCNICOS\n\n' if introduction else '') + "\n\n".join(f"{labels.get(key,key)}: {('Sí' if value else 'No') if isinstance(value,bool) else 'No disponible' if value is None else json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)}" for key,value in info.items())
            if characters is not None:
                text += "\n\nCaracteres disponibles (Unicode):\n" + "".join(chr(cp) for cp in characters if cp>=32)
            details.setPlainText(text)
        choice.currentIndexChanged.connect(show_font)
        show_font(choice.currentIndex())
        note = QLabel("La coincidencia del nombre no demuestra identidad tipográfica. La asociación se valida con cada documento y con los caracteres escritos. Comprueba que la licencia de tu TTF/OTF permita la incrustación editable.")
        note.setWordWrap(True)
        layout.addWidget(note)
        associate = QPushButton("Asociar archivo TTF / OTF a esta fuente…")
        associate.setEnabled(bool(self.fonts))
        def import_font():
            path,_ = QFileDialog.getOpenFileName(dialog,"Elegir variante exacta de fuente","","Fuentes (*.ttf *.otf)")
            if path:
                name = self.fonts[choice.currentIndex()].get("name",choice.currentText())
                dialog.accept()
                self._submit("associate",{"name":name,"path":path},lambda _:self.load_page())
        associate.clicked.connect(import_font)
        layout.addWidget(associate)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('Cerrar')
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def closeEvent(self,event):
        if not self._allow_close and not self._confirm_discard():
            event.ignore()
            return
        if not self._closed:
            self._close_workspace_v170()
            self._finish_signature_placement(closing=True)
            self._closed = True
            self.poller.stop()
            self.thumbnail_timer.stop()
            self.arrow_timer.stop()
            if self.state:
                self.pool.submit(_dispatch,"close",{})
            self.pool.shutdown(wait=False,cancel_futures=False)
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="PDF Modder — editor local conservador")
    parser.add_argument("pdf",nargs="?")
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--smoke-test",metavar="REPORT_JSON",help="Probar apertura, edición, movimiento, guardado y reapertura; generar informe y cerrar")
    group.add_argument("--smoke-extended",metavar="REPORT_JSON",help="Probar también texto nuevo, imágenes, extracción, eliminación y unión de páginas")
    group.add_argument("--smoke-tagged",metavar="REPORT_JSON",help="Probar PDF etiquetado, doble clic, ajuste de línea, accesibilidad e historial")
    group.add_argument("--smoke-clipped",metavar="REPORT_JSON",help="Probar campos con recortes, cambios de longitud, historial y dos guardados")
    group.add_argument("--smoke-v08",metavar="REPORT_JSON",help="Probar OCR, reemplazos revisados, imágenes y organización de páginas")
    group.add_argument("--smoke-v09",metavar="REPORT_JSON",help="Probar edición rica, formato por fragmentos, historial y guardado")
    group.add_argument("--smoke-compat",metavar="REPORT_JSON",help="Probar etiquetas, recortes, páginas y estados gráficos neutros")
    group.add_argument("--smoke-v150",metavar="REPORT_JSON",help="Probar Herramientas 1.5.0: texto nuevo, recorte, exportación, división y reapertura")
    group.add_argument("--smoke-v160",metavar="REPORT_JSON",help="Prueba dirigida 1.6.0, incluida firma con certificado sintético efímero")
    group.add_argument("--smoke-v161",metavar="REPORT_JSON",help="Prueba dirigida de firma visible con certificado sintético efímero")
    group.add_argument("--smoke-v162",metavar="REPORT_JSON",help="Prueba de dibujo del recuadro y firma visible con certificado sintético")
    group.add_argument("--smoke-v170",metavar="REPORT_JSON",help="Prueba dirigida de edición, propiedades, seguridad y herramientas 1.7.0")
    group.add_argument("--smoke-v171",metavar="REPORT_JSON",help="Prueba de lectura, rueda, copia, herramientas y edición 1.7.1")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("PDF Modder")
    app.setOrganizationName("PDFModder")
    app.setStyle("Fusion")
    application_icon = _application_icon()
    if not application_icon.isNull():
        app.setWindowIcon(application_icon)
    initial = args.pdf
    smoke_report=args.smoke_test or args.smoke_extended or args.smoke_tagged or args.smoke_clipped or args.smoke_v08 or args.smoke_v09 or args.smoke_compat or args.smoke_v150 or args.smoke_v160 or args.smoke_v161 or args.smoke_v162 or args.smoke_v170 or args.smoke_v171
    if smoke_report and not initial:
        root = Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))
        initial = str(root/"examples"/("compat-etiquetado-v091.pdf" if args.smoke_compat else "herramientas-v08.pdf" if args.smoke_v08 else "recortado.pdf" if args.smoke_clipped else "etiquetado.pdf" if args.smoke_tagged else "digital.pdf"))
    window = MainWindow(initial)
    if not application_icon.isNull():
        window.setWindowIcon(application_icon)
    window.show()
    if smoke_report:
        if args.smoke_v171:
            from .smoke_v171 import SmokeV171 as Smoke
        elif args.smoke_v170:
            from .smoke_v170 import SmokeV170 as Smoke
        elif args.smoke_v162:
            from .smoke_v162 import SmokeV162 as Smoke
        elif args.smoke_v161:
            from .smoke_v161 import SmokeV161 as Smoke
        elif args.smoke_v160:
            from .smoke_v160 import SmokeV160 as Smoke
        elif args.smoke_v150:
            from .smoke_v150 import ToolsSmokeV150 as Smoke
        elif args.smoke_compat:
            from .smoke_compat import CompatibilitySmoke as Smoke
        elif args.smoke_v09:
            from .smoke_v09 import RichSmoke as Smoke
        elif args.smoke_v08:
            from .smoke_v08 import AdvancedSmoke as Smoke
        elif args.smoke_clipped:
            from .smoke_clipped import ClippedSmoke as Smoke
        elif args.smoke_tagged:
            from .smoke_tagged import TaggedSmoke as Smoke
        elif args.smoke_extended:
            from .smoke_extended import ExtendedSmoke as Smoke
        else:
            from .smoke import VerticalSmoke as Smoke
        window._smoke = Smoke(window,initial,smoke_report)
    return app.exec()
