"""Click-to-place text and images, using the existing validated PDF operations."""
from pathlib import Path
import sys

from PySide6.QtCore import Qt

from .model import pt


class InsertionUiV150Mixin:
    def begin_text(self):
        if not self.model or self.busy or self.state.get('preview') or self.state.get('issues'):
            return
        if self.state.get('tagged'):
            # New tagged content uses the explicit typography/area dialog;
            # its acceptance also asks for semantic reading placement.
            return self.begin_text_properties_v150()
        if self.canvas.image_mode:
            self.image_mode_action.setChecked(False)
            self.toggle_image_mode(False)
        self._placement = 'inline_text'
        self.canvas.placement_mode = True
        self.canvas.setCursor(Qt.CrossCursor)
        self._notice('Pulsa en la página y escribe. Texto nuevo: Liberation Sans, 12 pt; puedes cambiarlo en Formato. Escape cancela.')
        self._refresh_actions()

    def begin_text_properties_v150(self):
        """The original dialog remains available for explicit numeric insertion."""
        return super().begin_text()

    def placed(self, x, y):
        kind = self._placement
        if kind not in ('inline_text', 'image'):
            return super().placed(x, y)
        if not self.model:
            self._cancel_placement()
            return
        page_width = self.model.cropbox[2]-self.model.cropbox[0]
        page_height = self.model.cropbox[3]-self.model.cropbox[1]
        if not (0 <= x < page_width and 0 <= y < page_height):
            self._error('Pulsa dentro del área visible de la página. Escape cancela la colocación.')
            return
        self._cancel_placement()
        if kind == 'image':
            width = min(pt(60), page_width-x, (page_height-y)*self._image_ratio)
            self.add_image(self._image_data, (x, y, x+width, y+width/self._image_ratio))
            return
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        entries = []
        for suffix, name, bold, italic in (
                ('Regular', 'LiberationSans', False, False),
                ('Bold', 'LiberationSans-Bold', True, False),
                ('Italic', 'LiberationSans-Italic', False, True),
                ('BoldItalic', 'LiberationSans-BoldItalic', True, True)):
            path = root / 'assets/fonts' / f'LiberationSans-{suffix}.ttf'
            if path.is_file():
                entries.append({'name': name, 'family': 'Liberation Sans', 'variant': suffix,
                                'path': str(path), 'bold': bold, 'italic': italic, 'editable': True,
                                'source': 'Fuente incluida para texto nuevo'})
        regular = next((entry for entry in entries if entry['name'] == 'LiberationSans'), None)
        if regular is None:
            self._error('Falta LiberationSans-Regular.ttf en la instalación. Usa Agregar texto con propiedades para elegir una fuente explícita.')
            return
        self._rich_loading = True
        self._inline_text_loading = True
        self._rich_generation += 1
        generation = self._rich_generation
        context = (self.page_number, self.model.revision)
        def loaded(catalog):
            if generation != self._rich_generation or not self.model or context != (self.page_number, self.model.revision):
                return
            self._rich_loading = False
            self._inline_text_loading = False
            available = entries + [entry for entry in catalog if entry.get('name') not in {face['name'] for face in entries}]
            width, height = min(pt(40), page_width-x), min(pt(12), page_height-y)
            style = {'text': '', 'font_name': regular['name'], 'font_file': regular['path'],
                     'font_xref': None, 'font_resource': None, 'size': 12., 'color': (0., 0., 0.),
                     'opacity': 1., 'char_spacing': 0., 'underline': False}
            payload = {'page': self.page_number, 'ids': [], 'rect': (x, y, x+width, y+height),
                       'width': width, 'height': height, 'runs': [style],
                       'paragraphs': [{'index': 0}], 'revision': self.model.revision,
                       'auto_width': True, 'auto_height': True,
                       'allow_overlap': self.allow_overlap_box.isChecked(), 'carets': [],
                       'font_previews': entries, 'catalog': available}
            self.canvas.set_selection([])
            self._open_rich_payload(payload)
        self._catalog(loaded)
        self._refresh_actions()

    def _rich_failed(self, command, message):
        if command == 'font_catalog' and getattr(self, '_inline_text_loading', False):
            self._inline_text_loading = False
            self._rich_loading = False
        return super()._rich_failed(command, message)
