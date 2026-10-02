"""Properties and protection dialogs. The PDF worker owns every PDF byte."""
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .document_ops_v170 import METADATA_FIELDS, validate_metadata
from .model import EditError


def _read_only(value, name):
    field = QLineEdit(str(value))
    field.setObjectName(name)
    field.setReadOnly(True)
    return field


class DocumentPropertiesDialog(QDialog):
    def __init__(self, properties, parent=None, *, edit_reason=''):
        super().__init__(parent)
        self.setWindowTitle('Propiedades del documento')
        self.setObjectName('documentPropertiesDialog')
        self.setMinimumWidth(590)
        self._original = dict(properties.get('metadata', {}))
        reason = edit_reason or properties.get('edit_reason', '')
        self.editable = bool(properties.get('editable', True) and not reason)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.path = _read_only(properties.get('path', ''), 'documentPropertyPath')
        self.size = _read_only(f"{properties.get('size_bytes', 0):,} bytes".replace(',', ' '), 'documentPropertySize')
        self.pages = _read_only(properties.get('page_count', 0), 'documentPropertyPages')
        form.addRow('Ruta', self.path)
        form.addRow('Tamaño del documento de trabajo', self.size)
        form.addRow('Páginas', self.pages)
        details = properties.get('format', 'PDF')
        details += ' · ' + (properties.get('encryption') or 'Sin cifrado')
        details += ' · ' + ('Contiene metadatos XMP' if properties.get('has_xmp') else 'Sin metadatos XMP')
        description = QLabel(details)
        description.setWordWrap(True)
        form.addRow('', description)
        self.fields = {}
        for key, label in METADATA_FIELDS.items():
            field = QLineEdit(self._original.get(key, ''))
            field.setObjectName('documentMetadata_' + key)
            field.setReadOnly(not self.editable)
            field.setMaxLength(8192)
            if key in ('creationDate', 'modDate'):
                field.setPlaceholderText('AAAA-MM-DD HH:MM:SS o fecha PDF D:…')
            form.addRow(label, field)
            self.fields[key] = field
        self.message = QLabel(reason or 'Las fechas admiten formato AAAA-MM-DD HH:MM:SS y zona horaria opcional. '
            'El cambio se revisa y se aplica al historial; «Guardar como…» crea la copia PDF.')
        self.message.setObjectName('documentMetadataMessage')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('Revisar cambios' if self.editable else 'Cerrar')
        self.buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        self.buttons.button(QDialogButtonBox.Cancel).setVisible(self.editable)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def metadata_values(self):
        changes = {key: field.text() for key, field in self.fields.items()
                   if field.text() != self._original.get(key, '')}
        return validate_metadata(changes)

    def accept(self):
        if self.editable:
            try:
                self.metadata_values()
            except EditError as exc:
                self.message.setText(str(exc))
                return
        super().accept()


class DocumentSecurityDialog(QDialog):
    def __init__(self, parent=None, certificates=None, store_error=''):
        super().__init__(parent)
        self.setWindowTitle('Guardar una copia protegida')
        self.setObjectName('documentSecurityDialog')
        self.setMinimumWidth(550)
        layout = QVBoxLayout(self)
        note = QLabel('Elige quién puede abrir la copia PDF. Se usa cifrado AES de 256 bits. '
                      'El documento de trabajo continúa disponible para editar.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('documentSecurityTabs')
        layout.addWidget(self.tabs)
        password_page = QWidget()
        password_form = QFormLayout(password_page)
        self.password = QLineEdit()
        self.password.setObjectName('documentSecurityPassword')
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('Contraseña para abrir la copia')
        self.confirm_password = QLineEdit()
        self.confirm_password.setObjectName('documentSecurityConfirmPassword')
        self.confirm_password.setEchoMode(QLineEdit.Password)
        password_form.addRow('Contraseña', self.password)
        password_form.addRow('Repetir contraseña', self.confirm_password)
        password_note = QLabel('No se guarda ni se recuerda. Usa hasta 40 bytes UTF-8; '
                               'las letras con acento pueden ocupar más de un byte.')
        password_note.setWordWrap(True)
        password_form.addRow(password_note)
        self.tabs.addTab(password_page, 'Contraseña')
        certificate_page = QWidget()
        certificate_form = QFormLayout(certificate_page)
        self.source = QComboBox()
        self.source.setObjectName('encryptionCertificateSource')
        self.source.addItem('Archivo público del destinatario (CER/CRT/PEM)', 'file')
        self.source.addItem('Certificado compatible instalado en Windows', 'windows')
        certificate_form.addRow('Origen', self.source)
        certificate_row = QWidget()
        row = QHBoxLayout(certificate_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.certificate = QLineEdit()
        self.certificate.setObjectName('encryptionCertificatePath')
        self.certificate.setPlaceholderText('Certificado público RSA del destinatario')
        row.addWidget(self.certificate)
        browse = QPushButton('Examinar…')
        browse.setObjectName('chooseEncryptionCertificate')
        row.addWidget(browse)
        def choose():
            selected, _ = QFileDialog.getOpenFileName(self, 'Elegir certificado público del destinatario', '',
                                                     'Certificados públicos (*.cer *.crt *.pem)')
            if selected:
                self.certificate.setText(selected)
        browse.clicked.connect(choose)
        certificate_form.addRow('Certificado', certificate_row)
        self.installed = QComboBox()
        self.installed.setObjectName('installedEncryptionCertificate')
        self.installed.setMinimumContentsLength(28)
        self.installed.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for entry in certificates or []:
            self.installed.addItem(entry['subject'] + ' · ' + entry.get('not_after', '')[:10], entry)
        if not self.installed.count():
            self.installed.addItem('No hay certificados RSA compatibles disponibles', None)
        certificate_form.addRow('Certificado instalado', self.installed)
        self.store_info = QLabel()
        self.store_info.setWordWrap(True)
        self.store_info.setObjectName('encryptionCertificateStoreInfo')
        certificate_form.addRow(self.store_info)
        def source_changed():
            windows = self.source.currentData() == 'windows'
            certificate_form.setRowVisible(certificate_row, not windows)
            certificate_form.setRowVisible(self.installed, windows)
            certificate_form.setRowVisible(self.store_info, windows)
            selected = self.installed.currentData()
            self.store_info.setText(('Emisor: ' + selected.get('issuer', '') + '\nHuella: ' + selected['thumbprint'])
                if selected else (store_error or 'Se muestran los certificados públicos compatibles disponibles en el almacén personal de Windows. '
                'También puedes importar el archivo CER o CRT del destinatario.'))
        self.source.currentIndexChanged.connect(source_changed)
        self.installed.currentIndexChanged.connect(source_changed)
        source_changed()
        certificate_note = QLabel('Sólo quien tenga la clave privada correspondiente podrá abrir la copia en un lector '
                                 'compatible con cifrado PDF por certificado. Este proceso usa la clave pública y '
                                 'no firma el documento. Se requiere RSA de al menos 2048 bits y permiso para cifrar claves.')
        certificate_note.setWordWrap(True)
        certificate_form.addRow(certificate_note)
        self.tabs.addTab(certificate_page, 'Certificado del destinatario')
        self.message = QLabel()
        self.message.setObjectName('documentSecurityMessage')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Elegir destino…')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def protection_options(self):
        if self.tabs.currentIndex() == 0:
            password = self.password.text()
            if not password or '\x00' in password:
                raise EditError('Introduce una contraseña para abrir la copia protegida.')
            if password != self.confirm_password.text():
                raise EditError('Las dos contraseñas no coinciden.')
            if len(password.encode('utf-8')) > 40:
                raise EditError('La contraseña supera el límite de 40 bytes UTF-8.')
            return {'mode': 'password', 'password': password}
        if self.source.currentData() == 'windows':
            selected = self.installed.currentData()
            if not selected:
                raise EditError('Selecciona un certificado instalado compatible o importa el certificado público del destinatario.')
            return {'mode': 'certificate', 'certificate_thumbprint': selected['thumbprint'], 'certificate_store': selected['store']}
        path = self.certificate.text().strip()
        if not path:
            raise EditError('Selecciona el certificado público del destinatario.')
        return {'mode': 'certificate', 'certificate_path': path}

    def accept(self):
        try:
            self.protection_options()
        except EditError as exc:
            self.message.setText(str(exc))
            return
        super().accept()


class DocumentUiV170Mixin:
    def _create_document_ui_v170(self):
        self.document_properties_action = QAction('Propiedades del documento…', self)
        self.document_properties_action.setObjectName('documentPropertiesAction')
        self.document_properties_action.setShortcut('Ctrl+D')
        self.document_properties_action.triggered.connect(self.choose_document_properties_v170)
        self.document_security_action = QAction('Guardar copia protegida…', self)
        self.document_security_action.setObjectName('documentSecurityAction')
        self.document_security_action.triggered.connect(self.choose_document_security_v170)
        self.document_security_action.setToolTip('Cifrar una copia por contraseña o por certificado público del destinatario')
        self._tool_button_v150(self.advanced_tools_section.body, self.document_properties_action, 'toolDocumentProperties')
        self._tool_button_v150(self.advanced_tools_section.body, self.document_security_action, 'toolDocumentSecurity')
        from .ui_icons_v170 import icon_v170
        self.document_properties_action.setIcon(icon_v170('document_properties'))
        self.document_security_action.setIcon(icon_v170('security'))

    def _refresh_document_v170(self):
        if not hasattr(self, 'document_properties_action'):
            return
        ready = bool(self.state) and not self.busy
        editing = getattr(self, '_rich_active', False) or bool(getattr(self, '_placement', None))
        self.document_properties_action.setEnabled(ready and not editing)
        self.document_security_action.setEnabled(ready and not editing and not self.state.get('preview')
                                                  and not self.compare_action.isChecked())

    def choose_document_properties_v170(self):
        if not self.state or self.busy:
            return
        self._submit('document_properties', callback=lambda info: QTimer.singleShot(
            0, lambda: self._show_document_properties_v170(info)))

    def _show_document_properties_v170(self, properties):
        reason = ''
        if self.state.get('preview'):
            reason = 'Aplica o cancela la vista previa antes de editar las propiedades.'
        elif self.compare_action.isChecked():
            reason = 'La comparación con el original se muestra sólo para lectura.'
        dialog = DocumentPropertiesDialog(properties, self, edit_reason=reason)
        if self._exec_edit_dialog(dialog) == QDialog.Accepted and dialog.editable:
            changes = dialog.metadata_values()
            if changes:
                self._submit('edit_document_metadata', {'metadata': changes}, self._document_metadata_preview_v170)
        dialog.deleteLater()

    def _document_metadata_preview_v170(self, result):
        self._previewed(result)
        self._notice('Metadatos revisados y validados. Pulsa «Aplicar cambio» para incluirlos en el historial; '
                     'después «Guardar como…» crea la copia PDF.')

    def choose_document_security_v170(self):
        if not self._v150_ready():
            return
        self._submit('list_encryption_certificates', callback=lambda listing: QTimer.singleShot(
            0, lambda: self._show_document_security_v170(listing)))

    def _show_document_security_v170(self, listing):
        dialog = DocumentSecurityDialog(self, listing.get('certificates', []), listing.get('error', ''))
        try:
            if self._exec_edit_dialog(dialog) != QDialog.Accepted:
                return
            options = dialog.protection_options()
            source = Path(self.state['path'])
            destination, _ = self._v150_file_dialog(lambda: QFileDialog.getSaveFileName(
                self, 'Guardar copia PDF protegida', str(source.with_name(source.stem + '-protegido.pdf')),
                'Documento PDF (*.pdf)'))
            if not destination:
                return
            if not destination.lower().endswith('.pdf'):
                destination += '.pdf'
            self._submit('export_secure_pdf', {'path': destination, **options}, self._document_security_saved_v170)
        finally:
            dialog.password.clear()
            dialog.confirm_password.clear()
            dialog.deleteLater()

    def _document_security_saved_v170(self, result):
        self._notice('Copia protegida guardada: ' + result['path'])
