"""Explicit semantics for content added to an already tagged PDF."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QComboBox, QLineEdit,
    QCheckBox, QDialogButtonBox,
)


class AccessibilityDialog(QDialog):
    def __init__(self, parent=None, *, image=False):
        super().__init__(parent)
        self.setWindowTitle('Accesibilidad del contenido nuevo')
        self.setObjectName('accessibilityInsertionDialog')
        self.setMinimumWidth(450)
        self.is_image = image
        layout = QVBoxLayout(self)
        note = QLabel(
            'Este PDF tiene un orden de lectura. Indica dónde debe leerse el contenido '
            'nuevo, independientemente de su posición visual. '
            + ('Una imagen informativa necesita una descripción.' if image else
               'El texto se añadirá como párrafo.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.order = QComboBox()
        self.order.setObjectName('accessibilityReadingOrder')
        self.order.addItem('Elige su posición de lectura…', None)
        self.order.addItem('Al principio de la página', 'page_start')
        self.order.addItem('Al final de la página', 'page_end')
        form.addRow('Orden de lectura', self.order)
        self.alt = QLineEdit()
        self.alt.setObjectName('accessibilityAltText')
        self.alt.setMaxLength(2000)
        self.alt.setPlaceholderText('Describe la información que aporta la imagen')
        self.decorative = QCheckBox('Imagen sólo decorativa; excluir del orden de lectura')
        self.decorative.setObjectName('accessibilityDecorativeImage')
        if image:
            form.addRow('Descripción', self.alt)
            form.addRow(self.decorative)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('Previsualizar')
        self.buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.order.currentIndexChanged.connect(self._refresh)
        self.alt.textChanged.connect(self._refresh)
        self.decorative.toggled.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_):
        decorative = self.is_image and self.decorative.isChecked()
        self.order.setEnabled(not decorative)
        self.alt.setEnabled(not decorative)
        valid = decorative or (self.order.currentData() is not None and
                               (not self.is_image or bool(self.alt.text().strip())))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(valid)

    def values(self):
        result = {'accessibility_order': self.order.currentData()}
        if self.is_image:
            decorative = self.decorative.isChecked()
            result.update(alt_text=None if decorative else self.alt.text().strip(),
                          decorative=decorative)
            if decorative:
                result['accessibility_order'] = None
        return result
