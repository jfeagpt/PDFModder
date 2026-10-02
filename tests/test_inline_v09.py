"""Real Qt input, range formatting and PDF-coordinate resize behaviour."""
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QTextCursor

from pdfmodder.canvas import PdfCanvas, resize_rect
from pdfmodder.model import Glyph, PageModel
from pdfmodder.rich_editor import PageEditor

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rich(qtbot):
    editor = PageEditor()
    qtbot.addWidget(editor)
    catalog = []
    for variant, bold, italic in [('Regular', False, False), ('Bold', True, False), ('Italic', False, True)]:
        catalog.append({'name': 'LiberationSans' + ('-' + variant if variant != 'Regular' else ''),
            'family': 'Liberation Sans', 'variant': variant, 'bold': bold, 'italic': italic,
            'path': str(ROOT / 'assets/fonts' / f'LiberationSans-{variant}.ttf'), 'editable': True})
    run = {'font_name': 'LiberationSans', 'font_xref': 7, 'font_resource': 'F1', 'size': 12.25,
           'color': (0.1, 0.2, 0.3), 'opacity': 1., 'char_spacing': 0., 'underline': False}
    editor.load_payload({'page': 0, 'ids': list(range(8)), 'rect': (10., 10., 180., 60.),
                         'runs': [{'text': 'UNO ', **run}, {'text': 'DOS', **run, 'size': 9.75}],
                         'font_previews': [{'font_name': entry['name'], 'font_xref':7 if not entry['bold'] and not entry['italic'] else None, **entry} for entry in catalog],
                         'catalog': catalog, 'revision': 'test'}, zoom=1.5)
    editor.resize(350, 100)
    editor.show()
    return editor


def choose(editor, start, end):
    c = editor.textCursor()
    c.setPosition(start)
    c.setPosition(end, QTextCursor.KeepAnchor)
    editor.setTextCursor(c)


def test_initial_caret_does_not_select_all_and_typing_is_local(qtbot, rich):
    assert not rich.textCursor().hasSelection()
    rich._original_carets = [{'index': i, 'bbox': (10+i*10, 10, 20+i*10, 24)} for i in range(7)]
    rich.place_caret_pdf((35, 15))
    assert rich.textCursor().position() == 2
    qtbot.keyClicks(rich, 'X')
    assert rich.toPlainText() == 'UNXO DOS'
    assert ''.join(r['text'] for r in rich.payload()['runs']) == 'UNXO DOS'


def test_dragging_letters_uses_real_qt_caret_and_preserves_selection(qtbot, rich):
    rich.setFocus()
    choose(rich, 1, 1)
    start=rich.cursorRect().center()
    choose(rich, 3, 3)
    end=rich.cursorRect().center()
    qtbot.mousePress(rich.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(rich.viewport(), pos=end)
    qtbot.mouseRelease(rich.viewport(), Qt.LeftButton, pos=end)
    assert rich.textCursor().selectedText()=='NO'
    qtbot.mouseClick(rich.toolbar.underline, Qt.LeftButton)
    assert rich.textCursor().selectedText()=='NO'
    parts=[(char,run.get('underline')) for run in rich.payload()['runs'] for char in run['text']]
    assert parts[:4]==[('U',False),('N',True),('O',True),(' ',False)]


def test_fragment_format_preserves_other_properties_and_styles(rich):
    choose(rich, 1, 6)
    rich.merge_style(underline=True, char_spacing=.35)
    runs = rich.payload()['runs']
    characters = [(c, run) for run in runs for c in run['text']]
    assert [r['underline'] for _, r in characters] == [False, True, True, True, True, True, False]
    assert [r['size'] for _, r in characters] == [12.25]*4 + [9.75]*3
    assert all(r['font_xref'] == 7 and r['color'] == (.1, .2, .3) for _, r in characters)
    rich.undo()
    assert all(not run['underline'] for run in rich.payload()['runs'])


def test_real_bold_changes_only_range_and_clears_original_resource(rich):
    choose(rich, 0, 3)
    rich.toolbar.toggle_variant('bold')
    runs = rich.payload()['runs']
    assert runs[0]['text'] == 'UNO'
    assert runs[0]['font_name'] == 'LiberationSans-Bold'
    assert runs[0]['font_file'].endswith('LiberationSans-Bold.ttf')
    assert runs[0]['font_xref'] is None and runs[0]['font_resource'] is None
    assert runs[1]['font_xref'] == 7
    choose(rich, 0, 3)
    rich.toolbar.toggle_variant('italic')
    assert 'Falta la variante' in rich.toolbar.status.text()
    assert rich.payload()['runs'][0]['font_name'] == 'LiberationSans-Bold'


def test_enter_soft_break_tab_and_paragraph_controls(qtbot, rich):
    choose(rich, 3, 3)
    qtbot.keyClick(rich, Qt.Key_Return, Qt.ShiftModifier)
    qtbot.keyClick(rich, Qt.Key_Return)
    qtbot.keyClick(rich, Qt.Key_Tab)
    raw = ''.join(r['text'] for r in rich.payload()['runs'])
    assert raw == 'UNO\u2028\n\t DOS'
    rich.merge_paragraph(left_indent=12.5, first_indent=-3., space_before=4., space_after=5., tab_stops=[36., 72.])
    values = rich.payload()['paragraphs'][1]
    assert values['left_indent'] == 12.5 and values['first_indent'] == -3.
    assert values['tab_stops'] == [36., 72.]
    assert rich.payload()['paragraphs'][0] == {'index': 0}


def test_invalid_tab_stops_prevent_accepting_stale_paragraph_values(qtbot, rich):
    accepted=[]
    rich.rich_accept.connect(accepted.append)
    rich.toolbar.paragraph_panel.show()
    rich.toolbar.tabs.setFocus()
    rich.toolbar.tabs.setText('72; 36')
    rich.toolbar.accept_draft()
    assert not accepted
    assert 'positivas crecientes' in rich.toolbar.status.text()
    rich.toolbar.tabs.setText('36; 72')
    rich.toolbar.accept_draft()
    assert len(accepted)==1
    assert accepted[0]['paragraphs'][0]['tab_stops']==[36.,72.]


def test_toolbar_numeric_edit_is_committed_before_accept(qtbot, rich):
    accepted=[]
    rich.rich_accept.connect(accepted.append)
    choose(rich,0,3)
    rich.toolbar.size_box.setFocus()
    rich.toolbar.size_box.lineEdit().setText('15,25 pt')
    # Use the widget's locale so this test also runs on an English machine.
    rich.toolbar.size_box.lineEdit().setText(rich.toolbar.size_box.locale().toString(15.25,'f',2)+' pt')
    rich.toolbar.accept_draft()
    assert accepted[0]['runs'][0]['size']==15.25
    assert ''.join(run['text'] for run in accepted[0]['runs'])=='UNO DOS'


def test_object_panel_preserves_manual_order_without_duplicate_group_members(qtbot):
    from pdfmodder.object_ui import ObjectDialog
    first={'kind':'text','ids':[0,1,2],'label':'UNO','rect':(10,10,40,20)}
    second={'kind':'text','ids':[3,4,5],'label':'DOS','rect':(10,30,40,40)}
    photo={'kind':'image','image_id':'image','label':'Foto','rect':(60,10,100,40)}
    info={'page':0,'revision':'r','items':[first,second,photo],
          'groups':[{'id':'group','name':'Conjunto','valid':True,'items':[first,photo]}]}
    dialog=ObjectDialog(info);qtbot.addWidget(dialog)
    moved=dialog.items.takeItem(1);dialog.items.insertItem(0,moved)
    for index in range(dialog.items.count()):dialog.items.item(index).setSelected(True)
    selection=dialog.selection()
    assert [item.get('ids') for item in selection if item['kind']=='text']==[[3,4,5],[0,1,2]]
    assert len([item for item in selection if item['kind']=='image'])==1


def test_visible_accept_cancel_and_shortcuts(qtbot, rich):
    accepted, cancelled = [], []
    rich.rich_accept.connect(accepted.append)
    rich.cancelled.connect(lambda: cancelled.append(True))
    assert rich.toolbar.isVisible()
    qtbot.mouseClick(rich.toolbar.accept, Qt.LeftButton)
    qtbot.keyClick(rich, Qt.Key_Return, Qt.ControlModifier)
    assert len(accepted) == 2
    qtbot.keyClick(rich, Qt.Key_Escape)
    assert cancelled == [True]


def test_real_pdf_toggle_preserves_draft_caret_and_toolbar(qtbot, rich):
    choose(rich, 1, 3)
    before=rich.payload()
    qtbot.mouseClick(rich.toolbar.pdf_button, Qt.LeftButton)
    assert rich.pdf_view and rich.isReadOnly() and rich.isVisible()
    assert rich._preview_effect.opacity()==0.
    assert rich.toolbar.isVisible()
    qtbot.mouseClick(rich.toolbar.pdf_button, Qt.LeftButton)
    assert not rich.pdf_view and not rich.isReadOnly()
    assert rich.textCursor().selectionStart()==1 and rich.textCursor().selectionEnd()==3
    assert rich.payload()==before


@pytest.mark.parametrize('handle,delta,expected', [
    ('nw', (-10, -5), (0, 15, 110, 70)), ('n', (0, -5), (10, 15, 110, 70)),
    ('ne', (10, -5), (10, 15, 120, 70)), ('e', (10, 0), (10, 20, 120, 70)),
    ('se', (10, 5), (10, 20, 120, 75)), ('s', (0, 5), (10, 20, 110, 75)),
    ('sw', (-10, 5), (0, 20, 110, 75)), ('w', (-10, 0), (0, 20, 110, 70)),
])
def test_all_resize_handles_anchor_opposite_side(handle, delta, expected):
    assert resize_rect((10., 20., 110., 70.), handle, delta) == expected


def test_aspect_lock_also_works_on_side_handle():
    value = resize_rect((10., 20., 110., 70.), 'e', (20., 0.), True)
    assert value == (10., 15., 130., 75.)
    assert (value[2]-value[0]) / (value[3]-value[1]) == 2.


@pytest.fixture
def canvas(qtbot):
    c = PdfCanvas()
    qtbot.addWidget(c)
    glyphs = [Glyph(i, ch, (20+i*15, 45), (20+i*15, 30, 35+i*15, 48),
                    (20+i*15, 30, 35+i*15, 48), 'Helvetica', 12., (0., 0., 0.), 1., 0, 0, 0)
              for i, ch in enumerate('PRUEBA')]
    image = QImage(300, 200, QImage.Format_RGB32)
    image.fill(Qt.white)
    b = QBuffer()
    b.open(QIODevice.WriteOnly)
    image.save(b, 'PNG')
    matrix = (1., 0., 0., 1., 0., 0.)
    c.set_page(bytes(b.data()), PageModel(0, 300, 200, 0, matrix, matrix, (0, 0, 300, 200), glyphs), 1.)
    c.resize(500, 320)
    c.show()
    return c


def test_canvas_text_resize_emits_rect_without_moving_glyphs(qtbot, canvas):
    canvas.set_selection(list(range(6)))
    before = [g.origin for g in canvas.model.glyphs]
    result = []
    canvas.text_resize_requested.connect(result.append)
    start, end = canvas.viewport_point((110, 48)), canvas.viewport_point((160, 80))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=end)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
    assert result == [(20., 30., 160., 80.)]
    assert [g.origin for g in canvas.model.glyphs] == before


def test_select_and_move_modes_have_distinct_drag_behaviour(qtbot, canvas):
    canvas.mode='character'
    moved=[]
    canvas.move_requested.connect(lambda dx,dy:moved.append((dx,dy)))
    first,last=canvas.viewport_point((27,39)),canvas.viewport_point((74,39))
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=first)
    qtbot.mouseMove(canvas.viewport(),pos=last)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=last)
    assert canvas.model.text(canvas.ids)=='PRUE'
    assert not moved
    canvas.set_interaction_mode('move')
    canvas.set_selection(list(range(6)))
    first,last=canvas.viewport_point((47,39)),canvas.viewport_point((67,39))
    qtbot.mousePress(canvas.viewport(),Qt.LeftButton,pos=first)
    qtbot.mouseMove(canvas.viewport(),pos=last)
    qtbot.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=last)
    assert moved==[(20.,0.)]


def test_new_text_editor_needs_no_existing_glyph_selection(canvas):
    payload={'page':0,'ids':[],'rect':(50.,70.,200.,120.),
             'runs':[{'text':'','font_name':'LiberationSans','size':10.,'color':(0,0,0)}]}
    canvas.start_rich_editor(payload)
    assert canvas.editor.isVisible()
    assert canvas.editor.payload()['ids']==[]
    assert not canvas.editor.textCursor().hasSelection()


def test_image_side_handle_resizes_with_rotated_page_coordinates(qtbot, canvas):
    canvas.model.rotation = 90
    canvas.model.rotation_matrix = (0., 1., -1., 0., 200., 0.)
    canvas.model.derotation_matrix = (0., -1., 1., 0., 0., 200.)
    canvas.set_images([{'id': 'image', 'rect': (30., 60., 130., 100.), 'editable': True}])
    canvas.image_mode = True
    canvas.lock_image_ratio = False
    canvas.select_image(canvas.images[0])
    result = []
    canvas.image_transform_requested.connect(lambda name, rect: result.append((name, rect)))
    start, end = canvas.viewport_point((30, 80)), canvas.viewport_point((20, 80))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=end)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
    assert result == [('image', (20., 60., 130., 100.))]


def test_rotated_editor_follows_page_and_survives_page_reset(canvas):
    canvas.model.rotation=90
    canvas.model.rotation_matrix=(0.,1.,-1.,0.,200.,0.)
    canvas.model.derotation_matrix=(0.,-1.,1.,0.,0.,200.)
    canvas.set_selection(list(range(6)))
    canvas._edit_click_pdf=(52.,40.)
    canvas.start_rich_editor({'page':0,'ids':list(range(6)),'rect':(20.,30.,110.,48.),
        'runs':[{'text':'PRUEBA','font_name':'Helvetica','size':12.,'color':(0,0,0)}],
        'carets':[{'index':i,'bbox':g.bbox,'origin':g.origin} for i,g in enumerate(canvas.model.glyphs)]})
    assert canvas._editor_proxy.rotation()==90
    assert canvas.editor.textCursor().position()==2
    assert canvas._editor_proxy.pos().x()==170.
    assert canvas._editor_proxy.pos().y()==20.
    buffer=QBuffer()
    buffer.open(QIODevice.WriteOnly)
    canvas._pixmap_item.pixmap().save(buffer,'PNG')
    canvas.set_page(bytes(buffer.data()),canvas.model,1.)
    assert canvas._editor_proxy is None
    canvas.set_selection(list(range(6)))
    canvas.start_editor('PRUEBA')
    assert canvas.editor.isVisible() and canvas.editor.toPlainText()=='PRUEBA'
