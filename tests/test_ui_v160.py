"""Focused checks for 1.6 controls and a real instance-preserving image gesture."""
import math

import pymupdf as fitz
import pytest
from PySide6.QtCore import Qt

from pdfmodder.canvas import PdfCanvas
from pdfmodder.engine import extract_page
from pdfmodder.image_transform_v160 import transform_image_instance_pdf
from pdfmodder.media import edit_image_pdf, image_items, export_image_pdf
from test_image_tools import sample, rgba
from test_tools_ui_v150 import tools_window, _canvas_document


def test_startup_defaults_and_zoom_from_actual_fit_value(tools_window, monkeypatch):
    window = tools_window
    assert not window.highlight_action.isChecked() and not window.canvas.highlight_changes
    for section in (window.content_tools_section, window.format_tools_section, window.page_tools_section):
        assert not section.header.isChecked() and not section.content.isVisible()
        section.header.click()
        assert section.content.isVisible()
    _canvas_document(window)
    window.state = {'page_count': 1}
    def reload_page():
        window._sync_zoom_control()
        window._refresh_actions()
    monkeypatch.setattr(window, 'load_page', reload_page)
    window.zoom = .937
    window._refresh_actions()
    actions = window.toolbar.actions()
    combo_action = next(action for action in actions if window.toolbar.widgetForAction(action) is window.zoom_box)
    assert actions.index(window.zoom_out_action)+1 == actions.index(combo_action)
    assert actions.index(combo_action)+1 == actions.index(window.zoom_in_action)
    window.zoom_in_action.trigger()
    assert window.zoom == pytest.approx(.937*1.25)
    assert window.zoom_box.currentData() == window.zoom
    window.zoom_out_action.trigger()
    assert window.zoom == pytest.approx(.937)
    window.zoom = 3.9
    window.zoom_in_action.trigger()
    assert window.zoom == 4. and not window.zoom_in_action.isEnabled()


def _image_canvas(qtbot, rotation=0, zoom=1.):
    data = sample(rotation=rotation, crop=True)
    with fitz.open(stream=data, filetype='pdf') as doc:
        model = extract_page(doc, 0, data)
        png = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes('png')
        images = image_items(doc, 0)
    canvas = PdfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(650, 650)
    canvas.set_page(png, model, zoom)
    canvas.set_images(images)
    canvas.show()
    canvas.image_mode = True
    canvas.select_image(images[0])
    return canvas, data


@pytest.mark.parametrize('rotation,zoom', [(0, 1.), (90, 1.5), (270, .75)])
def test_rotation_grip_emits_one_delta_and_keeps_page_geometry(qtbot, rotation, zoom):
    canvas, data = _image_canvas(qtbot, rotation, zoom)
    image = canvas.selected_image()
    rect = image['rect']
    cx, cy = (rect[0]+rect[2])/2, (rect[1]+rect[3])/2
    start = canvas._rotation_handle_position(rect).toPoint()
    start_pdf = canvas.pdf_point(start)
    radius = math.hypot(start_pdf[0]-cx, start_pdf[1]-cy)
    finish = canvas.viewport_point((cx+radius, cy))
    rotations, moves = [], []
    canvas.image_rotate_requested.connect(lambda image_id, angle: rotations.append((image_id, angle)))
    canvas.image_transform_requested.connect(lambda *args: moves.append(args))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    assert canvas._image_rotate and not canvas._image_resize
    qtbot.mouseMove(canvas.viewport(), pos=finish)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=finish)
    assert len(rotations) == 1 and not moves
    assert rotations[0][1] == pytest.approx(90., abs=1.)
    output, report = transform_image_instance_pdf(data, 0, rotations[0][0], rotation=rotations[0][1])
    assert report['verified'] and report['physical_size_preserved']
    with fitz.open(stream=output, filetype='pdf') as doc:
        assert doc[0].rotation == rotation
        transformed = image_items(doc, 0)[0]
        assert transformed['editable']
        assert (transformed['rect'][0]+transformed['rect'][2])/2 == pytest.approx(cx, abs=.01)
        assert (transformed['rect'][1]+transformed['rect'][3])/2 == pytest.approx(cy, abs=.01)


def test_image_gesture_cancel_and_eight_resize_handles(qtbot):
    canvas, _ = _image_canvas(qtbot)
    rect = canvas.selected_image()['rect']
    assert len(canvas.handle_points(rect)) == 8
    requests = []
    canvas.image_rotate_requested.connect(lambda *args: requests.append(args))
    start = canvas._rotation_handle_position(rect).toPoint()
    finish = canvas.viewport_point((rect[2]+20, (rect[1]+rect[3])/2))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=finish)
    qtbot.keyClick(canvas, Qt.Key_Escape)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=finish)
    assert not requests and canvas._image_rotate_angle is None
    sizes = []
    canvas.image_transform_requested.connect(lambda *args: sizes.append(args))
    for name, point in canvas.handle_points(rect).items():
        start = canvas.viewport_point(point)
        assert canvas._handle_at(rect, start) == name
    start = canvas.viewport_point((rect[2], rect[3]))
    finish = canvas.viewport_point((rect[2]+24, rect[3]+12))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=finish)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=finish)
    assert len(sizes) == 1
    assert sizes[0][1] == pytest.approx((rect[0], rect[1], rect[2]+24, rect[3]+12), abs=.01)


@pytest.mark.parametrize('framed', [False, True])
def test_free_rotation_size_pixels_shared_instances_and_reopen(tmp_path, framed):
    data = sample()
    if framed:
        data, _ = edit_image_pdf(data, 0, '0', crop=(.1,.1,.9,.9), rotation=13., fit_mode='fill')
    with fitz.open(stream=data, filetype='pdf') as doc:
        original = image_items(doc, 0)[0]
        untouched = doc[1].get_pixmap().samples
    output, report = transform_image_instance_pdf(data, 0, '0', rotation=37.25)
    assert report['verified'] and report['physical_size_preserved']
    saved = tmp_path/'rotated.pdf'
    saved.write_bytes(output)
    with fitz.open(saved) as doc:
        current = image_items(doc, 0)[0]
        assert current['editable']
        assert doc[1].get_pixmap().samples == untouched
        for offset in (0, 2):
            a = original['matrix_pdf'][offset:offset+2]
            b = current['matrix_pdf'][offset:offset+2]
            assert math.hypot(*a) == pytest.approx(math.hypot(*b), abs=.001)
    assert rgba(export_image_pdf(output, 0, '0')['image_bytes']) == rgba(export_image_pdf(data, 0, '0')['image_bytes'])
    rect = current['rect']
    destination = (rect[0]+10, rect[1]+100, rect[2]+10, rect[3]+100)
    moved, _ = transform_image_instance_pdf(output, 0, '0', destination)
    with fitz.open(stream=moved, filetype='pdf') as doc:
        assert image_items(doc, 0)[0]['rect'] == pytest.approx(destination, abs=.001)
        assert doc[1].get_pixmap().samples == untouched


def test_combined_tool_keeps_rotation_handle_and_submits_one_history_operation(tools_window, monkeypatch, qtbot):
    window = tools_window
    _canvas_document(window)
    canvas = window.canvas
    canvas.image_mode = True
    canvas.select_image(canvas.images[0])
    window.state = {'page_count': 1}
    window._refresh_actions()
    submitted = []
    monkeypatch.setattr(window, '_submit', lambda *args, **kwargs: submitted.append((args, kwargs)))
    rect = canvas.selected_image()['rect']
    start = canvas._rotation_handle_position(rect).toPoint()
    finish = canvas.viewport_point((190, 95))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    assert canvas.image_mode and canvas._image_rotate
    qtbot.mouseMove(canvas.viewport(), pos=finish)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=finish)
    assert len(submitted) == 1
    args, _ = submitted[0]
    assert args[0] == 'image_apply' and args[1]['operation'] == 'rotate'


@pytest.mark.parametrize('decorative', [False, True])
def test_new_tagged_image_rotates_and_resizes_without_losing_accessibility(decorative):
    from pdfmodder.media import add_image_pdf
    from pdfmodder.tagged import analyze
    from tagged_corpus import make_tagged_pdf, audit_tagged
    from test_tagged_v160 import image_bytes
    source, _ = add_image_pdf(make_tagged_pdf(), 0, image_bytes(), (160, 260, 200, 284),
                              accessibility_order=None if decorative else 'page_end',
                              alt_text=None if decorative else 'Figura de prueba', decorative=decorative)
    expected = analyze(source).semantic()
    reading_order = audit_tagged(source)['reading_order']
    with fitz.open(stream=source, filetype='pdf') as doc:
        item = image_items(doc, 0)[-1]
        assert item['editable']
    output, report = transform_image_instance_pdf(source, 0, item['id'], rotation=27.5)
    assert report['accessibility']['structure_preserved']
    assert report['accessibility']['artifact_preserved'] == decorative
    with fitz.open(stream=output, filetype='pdf') as doc:
        rotated = image_items(doc, 0)[-1]
        assert rotated['editable']
        x0, y0, x1, y1 = rotated['rect']
    resized, report = transform_image_instance_pdf(output, 0, item['id'],
                                                  (x0+10, y0+20, x0+10+(x1-x0)*1.2, y0+20+(y1-y0)*1.2))
    assert report['verified'] and report['accessibility']['reading_order_preserved']
    assert analyze(resized).semantic() == expected
    assert audit_tagged(resized)['reading_order'] == reading_order
