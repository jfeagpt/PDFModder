"""Original scalable pictograms for the local editor; no external icon assets."""
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


# Drawings use a common 24-unit canvas and deliberately different silhouettes.
ICON_DRAWINGS_V170 = {
    'document': '<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6"/>',
    'open': '<path d="M3 19V6h7l2 3h9l-3 10zM3 19l4-8h14"/>',
    'save': '<path d="M4 3h14l3 3v15H3V3zM7 3v6h10V3M7 21v-8h10v8M14 5v2"/>',
    'sign': '<path d="M3 19c3-9 5-9 4-3s3-3 4-3-2 5 1 4l4-2M3 22h18M15 10l5-7 2 2-5 7-3 1z"/>',
    'undo': '<path d="M9 5L3 11l6 6M3 11h11c5 0 7 7 4 9"/>',
    'redo': '<path d="M15 5l6 6-6 6M21 11H10c-5 0-7 7-4 9"/>',
    'zoom_in': '<circle cx="10" cy="10" r="7"/><path d="M15 15l6 6M6 10h8M10 6v8"/>',
    'zoom_out': '<circle cx="10" cy="10" r="7"/><path d="M15 15l6 6M6 10h8"/>',
    'fit_page': '<path d="M8 4h8v16H8zM3 7V3h4M17 3h4v4M21 17v4h-4M7 21H3v-4"/>',
    'fit_width': '<path d="M5 3h14v18H5M1 12h22M1 12l3-3M1 12l3 3M23 12l-3-3M23 12l-3 3"/>',
    'search': '<circle cx="10" cy="10" r="7"/><path d="M15 15l7 7"/>',
    'find_replace': '<path d="M3 4h8M3 4l4 11M11 4L7 15M5 10h4M13 9h8l-3-3M21 9l-3 3M21 18h-8l3-3M13 18l3 3"/>',
    'select': '<path d="M5 2v18l5-5 4 7 3-2-4-7h7z"/>',
    'write': '<path d="M4 6V3h12v3M10 3v18M7 21h6M18 10v11M16 10h4M16 21h4"/>',
    'move': '<path d="M12 2v20M2 12h20M12 2L8 6M12 2l4 4M12 22l-4-4M12 22l4-4M2 12l4-4M2 12l4 4M22 12l-4-4M22 12l-4 4"/>',
    'copy': '<path d="M9 8h12v13H9zM16 8V3H3v13h6"/>',
    'cut': '<circle cx="5" cy="18" r="3"/><circle cx="18" cy="18" r="3"/><path d="M7 16L20 3M16 16L3 3"/>',
    'paste': '<path d="M8 5H4v17h16V5h-4M8 3h8v5H8zM8 13h8M8 17h6"/>',
    'delete': '<path d="M4 6h16M9 3h6M6 6l1 15h10l1-15M10 10v7M14 10v7"/>',
    'edit': '<path d="M3 7h11M3 11h7M3 15h4M10 20l1-5L19 3l3 3-8 12zM17 6l3 3"/>',
    'add_text': '<path d="M3 6V3h12v3M9 3v16M6 19h6M18 13v9M14 17h8"/>',
    'add_image': '<path d="M13 3H3v17h12M3 16l6-6 6 7M18 2v8M14 6h8"/><circle cx="9" cy="7" r="1"/>',
    'image': '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="16" cy="9" r="2"/><path d="M3 17l6-7 5 6 3-3 4 5"/>',
    'export': '<path d="M13 3H4v18h13v-6M11 9h11M18 5l4 4-4 4M8 15h3"/>',
    'pages': '<path d="M4 3h7v8H4zM14 3h7v8h-7zM4 14h7v8H4zM14 14h7v8h-7z"/>',
    'rotate_pages': '<path d="M9 8h9v13H9zM4 13a8 8 0 0 1 12-9M4 13V7M4 13h6"/>',
    'delete_pages': '<path d="M3 3h11v7M3 3v18h8M15 12h7M17 10h3M16 12v10h5V12"/>',
    'extract_pages': '<path d="M3 3h10v18H3M6 7h4M6 11h4M11 16h11M18 12l4 4-4 4"/>',
    'replace_pages': '<path d="M2 3h8v12H2M14 9h8v12h-8M12 4h9l-3-3M21 4l-3 3M12 20H3l3-3M3 20l3 3"/>',
    'crop_pages': '<path d="M3 2v17h18M2 6h16v16M8 10h5M8 13h5"/>',
    'split_pages': '<path d="M3 2h18v20H3M1 12h22M8 5v3M16 16v3M12 2v3M12 19v3" stroke-dasharray="3 2"/>',
    'insert_pages': '<path d="M3 2h10v20H3M6 6h4M6 10h4M18 8v12M14 14h8"/>',
    'merge': '<path d="M2 3h6v9H2M16 3h6v9h-6M5 14l7 6 7-6M12 8v12M9 22h6"/>',
    'organize': '<path d="M3 3h6v7H3zM15 14h6v7h-6zM13 5h8l-3-3M21 5l-3 3M11 18H3l3-3M3 18l3 3"/>',
    'objects': '<rect x="3" y="3" width="8" height="8"/><circle cx="17" cy="7" r="4"/><path d="M3 21l5-8 5 8zM16 15h5v6h-5z"/>',
    'copy_format': '<path d="M3 3h12v5H3zM7 8v7h4v7M18 4h4v8h-4zM18 12h4v8h-4z"/>',
    'paste_format': '<path d="M3 3h12v5H3zM7 8v7h4v7M19 10v12M15 16h8"/>',
    'compare': '<path d="M3 3h7v18H3zM14 3h7v18h-7zM6 8h1M6 12h1M17 8h1M17 12h1"/>',
    'highlight': '<path d="M5 16l10-13 6 5-10 13zM3 21h12M8 12l6 5M15 3l6 5"/>',
    'text_properties': '<path d="M3 5V3h10v2M8 3v16M5 19h6M15 9h7M15 14h7M15 19h7M18 7v4M20 12v4M17 17v4"/>',
    'format': '<path d="M3 21l7-18 7 18M6 14h8M19 4v17M17 4h5M17 21h5"/>',
    'tools': '<path d="M3 5h18M3 12h18M3 19h18M7 2v6M17 9v6M10 16v6"/>',
    'document_properties': '<path d="M3 2h12v20H3M6 6h5M6 10h5M6 14h3M16 13h6M19 10v6M16 20h6M17 17v6"/>',
    'security': '<path d="M12 2l9 4v6c0 5-5 9-9 11-4-2-9-6-9-11V6zM8 13v-3a4 4 0 0 1 8 0v3M7 13h10v6H7zM12 15v2"/>',
    'recent': '<path d="M8 3H3v18h11M7 7h3M7 11h2"/><circle cx="16" cy="13" r="7"/><path d="M16 9v5h4"/>',
    'updates': '<path d="M3 11a9 9 0 0 1 16-6M19 5V1M19 5h-4M21 13a9 9 0 0 1-16 6M5 19v4M5 19h4M12 7v10M8 13l4 4 4-4"/>',
    'download': '<path d="M12 2v14M7 11l5 5 5-5M3 16v6h18v-6"/>',
    'install': '<path d="M3 6l9-4 9 4v15H3zM3 6l9 4 9-4M12 10v11M7 15l3 3 6-7"/>',
    'flip_h': '<path d="M12 2v20M3 5v14l7-7zM21 5v14l-7-7z"/>',
    'flip_v': '<path d="M2 12h20M5 3h14l-7 7zM5 21h14l-7-7z"/>',
    'rotate_left': '<path d="M5 7a8 8 0 1 1-1 9M5 7V2M5 7h5"/><path d="M10 10h6v7h-6z"/>',
    'rotate_right': '<path d="M19 7a8 8 0 1 0 1 9M19 7V2M19 7h-5"/><path d="M8 10h6v7H8z"/>',
    'crop_image': '<path d="M6 2v16h16M2 6h16v16M10 14l3-4 3 4"/>',
    'replace_image': '<path d="M2 3h14v11H2M2 12l4-5 6 7M12 19h10M19 16l3 3-3 3"/><circle cx="11" cy="7" r="1"/>',
    'preview': '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    'apply': '<path d="M3 12l6 7L21 4"/>',
    'cancel': '<circle cx="12" cy="12" r="9"/><path d="M8 8l8 8M8 16l8-8"/>',
    'font': '<path d="M3 20L9 3l6 17M5 14h8M16 8h6M19 5v16M16 21h6"/>',
    'position': '<path d="M3 2v19h19M7 5h13v12H7zM10 8h7M10 11h4"/>',
    'zone': '<path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M8 8h8v8H8z"/>',
    'next_element': '<path d="M3 3h8v8H3zM13 14h8v8h-8zM5 17h5M7 14l3 3-3 3"/>',
    'whole_page': '<path d="M4 2h16v20H4zM7 5h10v14H7zM9 8h6M9 12h6M9 16h4"/>',
    'bold': '<path d="M6 3h8a5 5 0 0 1 0 9H6zM6 12h8a5 5 0 0 1 0 9H6z"/>',
    'italic': '<path d="M11 3h9M4 21h9M16 3L8 21"/>',
    'underline': '<path d="M6 3v9a6 6 0 0 0 12 0V3M4 21h16"/>',
    'color': '<path d="M3 17l5-14 5 14M5 12h6M2 21h20M18 4s-4 5-4 8a4 4 0 0 0 8 0c0-3-4-8-4-8z"/>',
}


class _SvgIconEngine(QIconEngine):
    def __init__(self, drawing):
        super().__init__()
        self.drawing = drawing

    def clone(self):
        return _SvgIconEngine(self.drawing)

    def paint(self, painter, rect, mode, state):
        color = '#88949e' if mode == QIcon.Disabled else '#345d7b'
        data = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                f'<g fill="none" stroke="{color}" stroke-width="1.65" '
                f'stroke-linecap="round" stroke-linejoin="round">{self.drawing}</g></svg>')
        QSvgRenderer(QByteArray(data.encode('utf-8'))).render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.)

    def scaledPixmap(self, size, mode, state, scale):
        output = QPixmap(QSize(max(1, round(size.width()*scale)), max(1, round(size.height()*scale))))
        output.fill(Qt.transparent)
        output.setDevicePixelRatio(scale)
        painter = QPainter(output)
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint(painter, QRectF(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return output


def icon_v170(kind):
    """Return an original vector icon which renders at the requested device DPI."""
    return QIcon(_SvgIconEngine(ICON_DRAWINGS_V170[kind]))


ACTION_ICONS_V170 = {
    'open_action': 'open', 'save_action': 'save', 'sign_action': 'sign',
    'undo_action': 'undo', 'redo_action': 'redo', 'zoom_out_action': 'zoom_out',
    'zoom_in_action': 'zoom_in', 'fit_page_action': 'fit_page', 'fit_width_action': 'fit_width',
    'search_action': 'search', 'edit_content_action': 'edit', 'add_text_action': 'add_text',
    'add_image_action': 'add_image', 'export_document_action': 'export',
    'thumbnail_action': 'pages', 'rotate_pages_action': 'rotate_pages',
    'delete_pages_action': 'delete_pages', 'extract_pages_action': 'extract_pages',
    'replace_pages_action': 'replace_pages', 'crop_pages_action': 'crop_pages',
    'split_document_action': 'split_pages', 'insert_pages_action': 'insert_pages',
    'merge_action': 'merge', 'organize_action': 'organize', 'replace_action': 'find_replace',
    'image_mode_action': 'image', 'objects_action': 'objects', 'copy_format_action': 'copy_format',
    'paste_format_action': 'paste_format', 'compare_action': 'compare', 'highlight_action': 'highlight',
    'add_text_properties_action': 'text_properties', 'format_action': 'format', 'tools_action': 'tools',
    'document_properties_action': 'document_properties', 'document_security_action': 'security',
    'copy_action_v170': 'copy', 'cut_action_v170': 'cut', 'paste_action_v170': 'paste',
    'delete_action_v170': 'delete', 'update_action_v170': 'updates',
}


def apply_action_icons_v170(window):
    for name, kind in ACTION_ICONS_V170.items():
        action = getattr(window, name, None)
        if action is not None:
            action.setIcon(icon_v170(kind))
    button_icons = {
        'preview_button': 'preview', 'move_button': 'move', 'edit_button': 'write',
        'commit_button': 'apply', 'cancel_button': 'cancel', 'font_button': 'font',
        'preview_step_button': 'preview', 'apply_step_button': 'apply', 'cancel_step_button': 'cancel',
        'image_props_button': 'position', 'image_remove_button': 'delete',
        'zone_button': 'zone', 'all_elements_button': 'whole_page',
        'image_export_button': 'export', 'image_edit_button': 'crop_image', 'side_color': 'color',
    }
    for name, kind in button_icons.items():
        button = getattr(window, name, None)
        if button is not None:
            button.setIcon(icon_v170(kind))
    for key, kind in {'flip_horizontal': 'flip_h', 'flip_vertical': 'flip_v',
                      'left': 'rotate_left', 'right': 'rotate_right',
                      'crop': 'crop_image', 'replace': 'replace_image'}.items():
        from PySide6.QtWidgets import QToolButton
        button = window.findChild(QToolButton, 'quickImage_' + key)
        if button is not None:
            button.setIcon(icon_v170(kind))
    for key, button in getattr(window, 'side_style_buttons', {}).items():
        button.setIcon(icon_v170(key))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
