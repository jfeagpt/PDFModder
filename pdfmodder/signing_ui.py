"""Certificate picker only; private-key work runs in the existing PDF worker."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .signing import SIGNING_NOTICE


class SignatureDialog(QDialog):
    preview_requested = Signal(dict, int)
    POINTS_PER_MM = 72. / 25.4
    DrawRectangleResult = 2

    def __init__(self, parent=None, certificates=None, store_error='', *, pages=None, current_page=0,
                 visible_signature_error=''):
        super().__init__(parent)
        self.setWindowTitle('Firmar digitalmente una copia')
        self.setObjectName('digitalSignatureDialog')
        self.setMinimumWidth(530)
        layout = QVBoxLayout(self)
        note = QLabel(SIGNING_NOTICE)
        note.setWordWrap(True)
        layout.addWidget(note)
        body = QHBoxLayout()
        layout.addLayout(body)
        credentials_widget = QWidget()
        form = QFormLayout(credentials_widget)
        form.setContentsMargins(0, 0, 0, 0)
        body.addWidget(credentials_widget, 1)
        self.source = QComboBox()
        self.source.setObjectName('signingCertificateSource')
        self.source.addItem('Certificados instalados en Windows', 'windows')
        self.source.addItem('Archivo PFX/P12 (avanzado)', 'pfx')
        form.addRow('Origen', self.source)
        self.installed = QComboBox()
        self.installed.setObjectName('installedSigningCertificate')
        self.installed.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.installed.setMinimumContentsLength(30)
        for cert in certificates or []:
            self.installed.addItem(cert['subject'] + ' · ' + cert.get('not_after', '')[:10], cert)
        if not self.installed.count():
            self.installed.addItem('No hay certificados compatibles con clave privada RSA', None)
        form.addRow('Certificado instalado', self.installed)
        self.store_info = QLabel()
        self.store_info.setWordWrap(True)
        def show_certificate():
            cert = self.installed.currentData()
            self.store_info.setText(('Emisor: ' + cert.get('issuer', '') + '\nHuella: ' + cert['thumbprint']
                + '\nWindows puede pedirte el PIN o permiso para usar la clave privada.') if cert else
                (store_error or 'Instala tu certificado personal con clave privada en Windows o selecciona un archivo PFX/P12.'))
        self.installed.currentIndexChanged.connect(show_certificate)
        show_certificate()
        form.addRow('', self.store_info)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.certificate = QLineEdit()
        self.certificate.setObjectName('signingCertificatePath')
        self.certificate.setPlaceholderText('Certificado con clave privada (*.pfx, *.p12)')
        row_layout.addWidget(self.certificate)
        browse = QPushButton('Examinar…')
        browse.setObjectName('chooseSigningCertificate')
        row_layout.addWidget(browse)
        def choose():
            selected, _ = QFileDialog.getOpenFileName(
                self, 'Elegir certificado personal', '', 'Certificados PKCS#12 (*.pfx *.p12)')
            if selected:
                self.certificate.setText(selected)
        browse.clicked.connect(choose)
        form.addRow('Certificado', row)
        self.password = QLineEdit()
        self.password.setObjectName('signingCertificatePassword')
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('No se guarda ni se recuerda')
        form.addRow('Contraseña', self.password)
        def source_changed():
            windows = self.source.currentData() == 'windows'
            form.setRowVisible(self.installed, windows)
            form.setRowVisible(self.store_info, windows)
            form.setRowVisible(row, not windows)
            form.setRowVisible(self.password, not windows)
            if windows:
                self.password.clear()
        self.source.currentIndexChanged.connect(source_changed)
        source_changed()
        self.reason = QLineEdit()
        self.reason.setObjectName('signingReason')
        self.reason.setMaxLength(512)
        form.addRow('Motivo (opcional)', self.reason)
        self.location = QLineEdit()
        self.location.setObjectName('signingLocation')
        self.location.setMaxLength(256)
        form.addRow('Lugar (opcional)', self.location)
        self.visible_signature = QCheckBox('Mostrar firma en la página')
        self.visible_signature.setObjectName('visibleSigningAppearance')
        form.addRow(self.visible_signature)
        self.visible_signature.setEnabled(not visible_signature_error)
        if visible_signature_error:
            restriction = QLabel(visible_signature_error)
            restriction.setObjectName('visibleSigningRestriction')
            restriction.setWordWrap(True)
            form.addRow(restriction)
        appearance = QLabel('El sello muestra el titular, los datos del certificado y la fecha. '
                            'La validez de la firma se consulta en el panel de firmas del lector PDF.')
        appearance.setWordWrap(True)
        form.addRow(appearance)
        self._preview_revision = 0
        self._preview_pending = False
        self._preview_result = None
        self._finished = False
        self.appearance_options = QWidget()
        self.appearance_options.setMinimumWidth(390)
        options = QVBoxLayout(self.appearance_options)
        options.setContentsMargins(12, 0, 0, 0)
        body.addWidget(self.appearance_options, 1)
        self.signature_page = QComboBox()
        self.signature_page.setObjectName('signingAppearancePage')
        for page in pages or []:
            self.signature_page.addItem('Página ' + str(page['page'] + 1), dict(page))
        selected_page = next((index for index in range(self.signature_page.count())
            if self.signature_page.itemData(index)['page'] == current_page), 0)
        self.signature_page.setCurrentIndex(selected_page)
        page_form = QFormLayout()
        page_form.addRow('Página del sello', self.signature_page)
        options.addLayout(page_form)
        geometry = QGridLayout()
        self.signature_x = self._millimetres('signingAppearanceX')
        self.signature_y = self._millimetres('signingAppearanceY')
        self.signature_width = self._millimetres('signingAppearanceWidth')
        self.signature_height = self._millimetres('signingAppearanceHeight')
        for row_index, values in enumerate((
                ('Desde la izquierda', self.signature_x, 'Desde arriba', self.signature_y),
                ('Anchura', self.signature_width, 'Altura', self.signature_height))):
            for column, (label, control) in enumerate(((values[0], values[1]), (values[2], values[3]))):
                geometry.addWidget(QLabel(label), row_index * 2, column)
                geometry.addWidget(control, row_index * 2 + 1, column)
        options.addLayout(geometry)
        self.draw_button = QPushButton('Dibujar recuadro en la página…')
        self.draw_button.setObjectName('drawSigningRectangle')
        self.draw_button.setToolTip('Arrastra sobre el documento para elegir la posición y tamaño del sello. Escape cancela.')
        options.addWidget(self.draw_button)
        self.preview_button = QPushButton('Previsualizar firma y posición')
        self.preview_button.setObjectName('previewSigningAppearance')
        options.addWidget(self.preview_button)
        self.preview_tabs = QTabWidget()
        self.preview_label = QLabel()
        self.preview_label.setObjectName('signingAppearancePreview')
        self.preview_detail = QLabel()
        self.preview_detail.setObjectName('signingAppearanceDetail')
        for preview in (self.preview_label, self.preview_detail):
            preview.setAlignment(Qt.AlignCenter)
            preview.setWordWrap(True)
            preview.setMinimumSize(360, 265)
            preview.setStyleSheet('background: #eef1f4; padding: 5px; color: #34495e;')
        self.preview_tabs.addTab(self.preview_label, 'En la página')
        self.preview_tabs.addTab(self.preview_detail, 'Detalle de la firma')
        options.addWidget(self.preview_tabs)
        timing = QLabel('Vista previa sin usar la clave privada ni firmar. La fecha se actualiza al firmar. '
                        'Elige un espacio libre para que el sello no tape contenido.')
        timing.setWordWrap(True)
        options.addWidget(timing)
        self.message = QLabel()
        self.message.setObjectName('signingAppearanceMessage')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('Elegir destino y firmar…')
        self.buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.finished.connect(self._mark_finished)
        self.signature_page.currentIndexChanged.connect(self._page_changed)
        self.visible_signature.toggled.connect(self._appearance_changed)
        self.preview_button.clicked.connect(self._request_preview)
        self.draw_button.clicked.connect(self._request_rectangle)
        for control in (self.source, self.installed):
            control.currentIndexChanged.connect(self._invalidate_preview)
        for control in (self.certificate, self.password, self.reason, self.location):
            control.textChanged.connect(self._invalidate_preview)
        for control in (self.signature_x, self.signature_y, self.signature_width, self.signature_height):
            control.valueChanged.connect(self._invalidate_preview)
        self._page_changed()
        self._appearance_changed(False)

    @staticmethod
    def _millimetres(name):
        control = QDoubleSpinBox()
        control.setObjectName(name)
        control.setDecimals(2)
        control.setRange(0., 10000.)
        control.setSuffix(' mm')
        control.setKeyboardTracking(False)
        return control

    def _page_changed(self, *_):
        page = self.signature_page.currentData()
        if page:
            width, height = page['width'] / self.POINTS_PER_MM, page['height'] / self.POINTS_PER_MM
            self.signature_x.setMaximum(width)
            self.signature_y.setMaximum(height)
            self.signature_width.setMaximum(width)
            self.signature_height.setMaximum(height)
            stamp_width, stamp_height = min(150., width), min(50., height)
            self.signature_width.setValue(stamp_width)
            self.signature_height.setValue(stamp_height)
            self.signature_x.setValue(max(0., width - stamp_width - 12.))
            self.signature_y.setValue(max(0., height - stamp_height - 12.))
        self._invalidate_preview()

    def _appearance_changed(self, enabled):
        self.appearance_options.setVisible(enabled)
        self._invalidate_preview()
        self.adjustSize()

    def _invalidate_preview(self, *_):
        self._preview_revision += 1
        self._preview_result = None
        for preview in (self.preview_label, self.preview_detail):
            preview.clear()
            preview.setText('Pulsa Previsualizar para ver el sello real sobre el PDF.')
        self.message.clear()

    def _mark_finished(self, *_):
        self._finished = True

    def _request_rectangle(self):
        if self._preview_pending or not self.visible_signature.isEnabled():
            return
        if not self.signature_page.currentData():
            self.message.setText('Elige una página antes de dibujar el sello.')
            return
        self.done(self.DrawRectangleResult)

    def set_drawn_rectangle(self, rectangle):
        x0, y0, x1, y1 = rectangle
        for control, value in ((self.signature_x, x0), (self.signature_y, y0),
                               (self.signature_width, x1-x0), (self.signature_height, y1-y0)):
            control.setValue(value / self.POINTS_PER_MM)
        self.visible_signature.setChecked(True)
        self._invalidate_preview()
        try:
            self.appearance()
            self.message.setText('Recuadro seleccionado. Pulsa Previsualizar para comprobar el sello.')
        except ValueError as exc:
            self.message.setText(str(exc))

    def credentials(self):
        if self.source.currentData() == 'windows':
            certificate = self.installed.currentData()
            if not certificate:
                raise ValueError('Selecciona un certificado instalado compatible o cambia a Archivo PFX/P12.')
            return {'certificate_thumbprint': certificate['thumbprint'], 'certificate_store': certificate['store']}
        path = self.certificate.text().strip()
        if not path:
            raise ValueError('Selecciona tu certificado PFX/P12 con clave privada.')
        return {'certificate_path': path, 'password': self.password.text()}

    def appearance(self):
        if not self.visible_signature.isChecked():
            return None
        page = self.signature_page.currentData()
        if not page:
            raise ValueError('No se han recibido las dimensiones de la página. Cierra este diálogo y vuelve a Firmar.')
        x, y, width, height = [control.value() * self.POINTS_PER_MM for control in (
            self.signature_x, self.signature_y, self.signature_width, self.signature_height)]
        if width < 210. or height < 70.:
            raise ValueError('El sello necesita al menos 74,09 mm de anchura y 24,70 mm de altura para que se lea.')
        if x + width > page['width'] + .015 or y + height > page['height'] + .015:
            raise ValueError('El sello supera el borde de la página. Reduce su tamaño o cambia su posición.')
        return {'page': page['page'], 'rect': [x, y, min(x + width, page['width']), min(y + height, page['height'])]}

    def signing_options(self):
        return {**self.credentials(), 'reason': self.reason.text(), 'location': self.location.text(),
                'visible_signature': self.appearance()}

    def _request_preview(self):
        if self._preview_pending or not self.visible_signature.isChecked():
            return
        try:
            payload = self.signing_options()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self._preview_pending = True
        self._preview_result = None
        self.preview_button.setEnabled(False)
        self.draw_button.setEnabled(False)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.message.setText('Generando la apariencia PDF del sello…')
        self.preview_requested.emit(payload, self._preview_revision)

    def receive_preview(self, result, revision):
        if self._finished:
            return
        self._end_preview()
        if revision != self._preview_revision:
            self.message.setText('Los datos cambiaron. Previsualiza otra vez antes de firmar.')
            return
        for label, data in ((self.preview_label, result.get('png')),
                            (self.preview_detail, result.get('appearance_png', result.get('png')))):
            pixmap = QPixmap()
            if not data or not pixmap.loadFromData(data):
                self.message.setText('No se pudo mostrar la previsualización del sello.')
                self._preview_result = None
                return
            label.setPixmap(pixmap.scaled(390, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._preview_result = result
        self.message.setText('Vista previa del PDF. La firma criptográfica se aplica al guardar la copia.')

    def preview_failed(self, error):
        if self._finished or not self._preview_pending:
            return
        self._end_preview()
        self.message.setText(str(error))

    def _end_preview(self):
        self._preview_pending = False
        self.preview_button.setEnabled(True)
        self.draw_button.setEnabled(True)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        if self._preview_pending:
            return
        try:
            self.signing_options()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        super().accept()


class SigningUiMixin:
    def choose_sign_document(self):
        if not self._v150_ready():
            return
        if getattr(self, '_rich_active', False):
            self._error('Acepta o cancela la edición de texto antes de firmar la copia.')
            return
        if self.state.get('issues'):
            self._error('\n'.join(self.state['issues']))
            return
        self._submit('list_signing_certificates', callback=lambda result: QTimer.singleShot(
            0, lambda: self._choose_signature_certificate(result)))

    def _choose_signature_certificate(self, listing):
        dialog = SignatureDialog(self, listing.get('certificates', []), listing.get('error', ''),
                                 pages=listing.get('pages', []), current_page=self.page_number,
                                 visible_signature_error=listing.get('visible_signature_error', ''))
        def preview(payload, revision):
            if not self._submit('signature_preview', payload,
                                lambda result: dialog.receive_preview(result, revision)):
                dialog.preview_failed('Espera a que termine la operación actual y vuelve a previsualizar.')
        dialog.preview_requested.connect(preview)
        self._show_signature_dialog(dialog)

    def _show_signature_dialog(self, dialog):
        dialog._finished = False
        self.error_raised.connect(dialog.preview_failed)
        drawing = False
        try:
            result = self._exec_edit_dialog(dialog)
            if result == SignatureDialog.DrawRectangleResult:
                drawing = True
                self._signature_thumbnail_before_draw = self.thumbnail_timer.isActive()
                self.thumbnail_timer.stop()
                QTimer.singleShot(0, lambda: self._begin_signature_placement(dialog))
                return
            if result != QDialog.Accepted:
                return
            options = dialog.signing_options()
            source = Path(self.state['path'])
            destination, _ = self._v150_file_dialog(lambda: QFileDialog.getSaveFileName(
                self, 'Guardar copia firmada', str(source.with_name(source.stem + '-firmado.pdf')),
                'Documento PDF (*.pdf)'))
            if not destination:
                return
            if not destination.lower().endswith('.pdf'):
                destination += '.pdf'
            self._submit('sign_pdf', {
                'path': destination, **options,
            }, self._signed_document)
        finally:
            self.error_raised.disconnect(dialog.preview_failed)
            if not drawing:
                dialog.password.clear()
                dialog.deleteLater()

    def _begin_signature_placement(self, dialog):
        if self._closed:
            dialog.password.clear()
            dialog.deleteLater()
            return
        self._signature_placement_dialog = dialog
        self._signature_loading = False
        self._signature_cancel_after_load = False
        self._signature_thumbnail_active = getattr(self, '_signature_thumbnail_before_draw',
                                                    self.thumbnail_timer.isActive())
        self.thumbnail_timer.stop()
        self._placement = 'signature_rectangle'
        self._signature_actions = [(action, action.isEnabled()) for action in self.findChildren(QAction)]
        self._signature_widgets = [(widget, widget.isEnabled()) for widget in
            [*self.findChildren(QToolBar), self.pages, self.tools_scroll]]
        self.canvas.signature_rectangle_selected.connect(self._signature_rectangle_chosen)
        self.canvas.signature_rectangle_cancelled.connect(self._cancel_signature_placement)
        self.page_ready.connect(self._signature_page_ready)
        self.error_raised.connect(self._signature_loading_failed)
        page = dialog.signature_page.currentData()['page']
        if page != self.page_number:
            self._signature_loading = True
            self.page_number = page
            self.pages.blockSignals(True)
            self.pages.setCurrentRow(page)
            self.pages.blockSignals(False)
            self.load_page()
        else:
            self._signature_page_ready()
        self._refresh_actions()

    def _signature_page_ready(self):
        if getattr(self, '_signature_placement_dialog', None) is None:
            return
        self._signature_loading = False
        if self._signature_cancel_after_load:
            self._finish_signature_placement()
            return
        self.canvas.begin_signature_rectangle()
        self.canvas.setFocus()
        self._notice('Firma visible: arrastra para dibujar el recuadro. Escape o «Cancelar» vuelve al diálogo de firma.')
        self._refresh_actions()

    def _signature_rectangle_chosen(self, rectangle):
        dialog = getattr(self, '_signature_placement_dialog', None)
        if dialog is None:
            return
        dialog.set_drawn_rectangle(rectangle)
        self._finish_signature_placement()

    def _cancel_signature_placement(self):
        if getattr(self, '_signature_placement_dialog', None) is None:
            return False
        if self._signature_loading and self.busy:
            self._signature_cancel_after_load = True
            self.statusBar().showMessage('Cancelando la selección del sello…')
        else:
            self._finish_signature_placement()
        return True

    def _signature_loading_failed(self, error):
        if getattr(self, '_signature_placement_dialog', None) is not None and self._signature_loading:
            self._signature_placement_dialog.message.setText(str(error))
            self._finish_signature_placement()

    def _finish_signature_placement(self, *, closing=False):
        dialog = getattr(self, '_signature_placement_dialog', None)
        if dialog is None:
            return
        self._signature_placement_dialog = None
        self.canvas.end_signature_rectangle()
        self.canvas.signature_rectangle_selected.disconnect(self._signature_rectangle_chosen)
        self.canvas.signature_rectangle_cancelled.disconnect(self._cancel_signature_placement)
        self.page_ready.disconnect(self._signature_page_ready)
        self.error_raised.disconnect(self._signature_loading_failed)
        self._placement = None
        for action, enabled in self._signature_actions:
            action.setEnabled(enabled)
        for widget, enabled in self._signature_widgets:
            widget.setEnabled(enabled)
        if not closing:
            self._refresh_actions()
            if self._signature_thumbnail_active:
                self.thumbnail_timer.start()
            QTimer.singleShot(0, lambda: self._show_signature_dialog(dialog))
        else:
            dialog.password.clear()
            dialog.deleteLater()

    def _restrict_signature_placement(self):
        if getattr(self, '_signature_placement_dialog', None) is None:
            return
        for action, _ in self._signature_actions:
            if action.shortcut() != QKeySequence('Escape'):
                action.setEnabled(False)
        for widget, _ in self._signature_widgets:
            widget.setEnabled(False)
        self.canvas.read_only = bool(self._signature_loading)
        self.edit_steps.show()
        self.edit_step_label.setText('Arrastra para dibujar el sello de firma · Escape: volver al diálogo')
        self.preview_step_button.hide()
        self.apply_step_button.hide()
        self.cancel_step_button.setEnabled(True)

    def _signed_document(self, result):
        self._notice('Copia firmada: ' + result['path'] + '\n'
                     'Integridad criptográfica comprobada. Confianza y revocación del certificado '
                     'no comprobadas; sin sello de tiempo. El trabajo abierto sigue sin firmar.')
        self.statusBar().showMessage('Copia firmada guardada. El documento de trabajo se conserva.', 15000)
