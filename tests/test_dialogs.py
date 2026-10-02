"""Real Qt widgets and narrow controller hooks; no worker or full GUI session."""
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImageIOHandler
from PySide6.QtWidgets import QComboBox, QDialog, QCheckBox
import pytest

from pdfmodder.dialogs import FontPicker, TextDialog
from pdfmodder.editing_ui import ExtendedEditing


@pytest.fixture
def catalog():
    result = []
    for name,variant,bold,italic in [
        ('Helvetica','Regular',False,False),
        ('Helvetica-Bold','Bold',True,False),
        ('Helvetica-Oblique','Italic',False,True),
        ('Helvetica-BoldOblique','Bold Italic',True,True),
    ]:
        result.append(dict(name=name,family='Helvetica',variant=variant,bold=bold,italic=italic,path=None,source='Base14',editable=True))
    result.append(dict(name='Solo-Regular',family='Solo',variant='Regular',bold=False,italic=False,path=None,source='test',editable=True))
    return result


def test_picker_defaults_to_exact_helvetica_and_selects_real_style(qtbot,catalog):
    picker=FontPicker(catalog)
    qtbot.addWidget(picker)
    assert picker.choice()=={'font_name':'Helvetica','font_file':None}
    picker.bold_box.click()
    assert picker.choice()['font_name']=='Helvetica-Bold'
    picker.italic_box.click()
    assert picker.choice()['font_name']=='Helvetica-BoldOblique'
    picker.bold_box.click()
    assert picker.choice()['font_name']=='Helvetica-Oblique'


def test_picker_initial_name_preserves_exact_variant(qtbot,catalog):
    picker=FontPicker(catalog,initial_name='Helvetica-BoldOblique')
    qtbot.addWidget(picker)
    assert picker.choice()['font_name']=='Helvetica-BoldOblique'
    assert picker.bold_box.isChecked() and picker.italic_box.isChecked()


def test_missing_variant_reports_error_and_never_simulates_bold(qtbot,catalog):
    picker=FontPicker(catalog,initial_name='Solo-Regular')
    qtbot.addWidget(picker)
    picker.bold_box.click()
    assert 'Falta la variante negrita' in picker.status_label.text()
    assert not picker.bold_box.isChecked()
    assert picker.variant_box.currentData()['name']=='Solo-Regular'
    with pytest.raises(ValueError,match='Falta la variante negrita'):
        picker.choice()
    # Selecting the same available item again acknowledges the valid choice.
    picker.variant_box.activated.emit(picker.variant_box.currentIndex())
    assert picker.choice()['font_name']=='Solo-Regular'


def test_manual_import_stores_path_without_loading_font_in_gui(qtbot,catalog,monkeypatch):
    import pdfmodder.dialogs as dialogs
    picker=FontPicker(catalog)
    qtbot.addWidget(picker)
    selected='C:/manual/VarianteExacta.otf'
    monkeypatch.setattr(dialogs.QFileDialog,'getOpenFileName',lambda *args,**kwargs:(selected,''))
    def unexpected_read(*args,**kwargs):
        raise AssertionError('El selector GUI no debe leer una fuente')
    monkeypatch.setattr(Path,'read_bytes',unexpected_read)
    picker.import_button.click()
    assert picker.choice()['font_name']=='VarianteExacta'
    assert Path(picker.choice()['font_file']).as_posix()==selected
    assert not picker.bold_box.isEnabled() and not picker.italic_box.isEnabled()
    picker.use_catalog_button.click()
    assert picker.choice()=={'font_name':'Helvetica','font_file':None}
    assert picker.family_box.isEnabled()


def test_restricted_catalog_face_cannot_be_selected_for_preview(qtbot,catalog):
    catalog.append(dict(name='Restricted-Bold',family='Restricted',variant='Bold',bold=True,italic=False,path='restricted.ttf',source='test',editable=False,status='No permite incrustación editable'))
    picker=FontPicker(catalog,initial_name='Restricted-Bold')
    qtbot.addWidget(picker)
    with pytest.raises(ValueError,match='incrustación editable'):
        picker.choice()


def test_existing_dialog_preserves_source_font_colour_size_and_position(qtbot,catalog):
    dialog=TextDialog(catalog,text='Original ñ €',rect=(30,40,230,100),size=12.37542,
                      font_name='Helvetica-Bold',color=(.12,.34,.56),existing=True)
    qtbot.addWidget(dialog)
    values=dialog.values()
    assert not dialog.change_font.isChecked()
    assert values['font_name'] is None and values['font_file'] is None
    assert values['color'] is None
    assert values['size']==12.37542  # More precision than the visible 3 decimals.
    assert values['text']=='Original ñ €'
    assert not dialog.x_box.isEnabled() and not dialog.y_box.isEnabled()
    assert values['x']==pytest.approx(30,abs=.003) and values['y']==pytest.approx(40,abs=.003)
    assert values['width']==pytest.approx(200,abs=.003) and values['height']==pytest.approx(60,abs=.003)
    assert not values['reflow'] and not values['allow_overlap']
    dialog.change_font.click()
    assert dialog.values()['font_name']=='Helvetica-Bold'
    dialog.size_box.setValue(14.125)
    assert dialog.values()['size']==14.125


def test_mm_fields_return_pdf_points_and_insertion_has_safe_defaults(qtbot,catalog):
    dialog=TextDialog(catalog,text='Nuevo')
    qtbot.addWidget(dialog)
    dialog.x_box.setValue(25.4)
    dialog.y_box.setValue(50.8)
    dialog.width_box.setValue(76.2)
    dialog.height_box.setValue(25.4)
    values=dialog.values()
    assert (values['x'],values['y'],values['width'],values['height'])==pytest.approx((72,144,216,72))
    assert values['color']==(0,0,0) and values['reflow'] and not values['allow_overlap']
    assert values['font_name']=='Helvetica'
    assert dialog.preview_button.text()=='Previsualizar'
    dialog.preview_button.click()
    assert dialog.result()==QDialog.Accepted


def test_cancel_and_empty_text_leave_dialog_unaccepted(qtbot,catalog):
    dialog=TextDialog(catalog)
    qtbot.addWidget(dialog)
    dialog.preview_button.click()
    assert dialog.result()!=QDialog.Accepted and 'Escribe' in dialog.error_label.text()
    dialog.content.setPlainText('Borrador')
    dialog.reject()
    assert dialog.result()==QDialog.Rejected and dialog.content.toPlainText()=='Borrador'


def test_cmyk_colour_is_preserved_until_user_explicitly_picks_rgb(qtbot,catalog,monkeypatch):
    import pdfmodder.dialogs as dialogs
    original=(.1,.2,.3,.4)
    dialog=TextDialog(catalog,text='CMYK',color=original,existing=True)
    qtbot.addWidget(dialog)
    expected=QColor.fromCmykF(*original).toRgb()
    assert dialog._color==pytest.approx((expected.redF(),expected.greenF(),expected.blueF()))
    assert dialog.values()['color'] is None
    monkeypatch.setattr(dialogs.QColorDialog,'getColor',lambda *args,**kwargs:QColor())
    dialog.color_button.click()
    assert dialog.values()['color'] is None
    chosen=QColor.fromRgbF(.8,.2,.1)
    monkeypatch.setattr(dialogs.QColorDialog,'getColor',lambda *args,**kwargs:chosen)
    dialog.color_button.click()
    assert dialog.values()['color']==pytest.approx((.8,.2,.1),abs=.00003)


def test_modal_dialog_suspends_thumbnail_timer_and_restores_it(qtbot):
    timer=QTimer()
    timer.setInterval(60000)
    timer.start()
    harness=SimpleNamespace(thumbnail_timer=timer)
    class Dialog:
        def exec(self):
            assert not timer.isActive()
            return QDialog.Accepted
    try:
        assert ExtendedEditing._exec_edit_dialog(harness,Dialog())==QDialog.Accepted
        assert timer.isActive()
    finally:
        timer.stop()


def test_image_orientation_uses_qt_flag_value_without_invalid_int_conversion(qtbot,monkeypatch):
    import pdfmodder.editing_ui as editing
    monkeypatch.setattr(editing.QFileDialog,'getOpenFileName',lambda *args,**kwargs:('portrait.jpg',''))
    class File:
        def __init__(self,path): pass
        def stat(self): return SimpleNamespace(st_size=100)
        def read_bytes(self): return b'fixture'
    class Reader:
        def __init__(self,path): pass
        def size(self): return QSize(40,20)
        def canRead(self): return True
        def transformation(self): return QImageIOHandler.Transformation.TransformationRotate90
    monkeypatch.setattr(editing,'Path',File)
    monkeypatch.setattr(editing,'QImageReader',Reader)
    errors=[]
    canvas=SimpleNamespace(placement_mode=False,setCursor=lambda *_:None)
    harness=SimpleNamespace(canvas=canvas,_notice=lambda *_:None,_error=errors.append,_refresh_actions=lambda:None)
    ExtendedEditing.begin_image(harness)
    assert not errors
    assert harness._image_ratio==.5 and harness._placement=='image' and canvas.placement_mode


def test_format_dialog_keeps_existing_anchor_and_does_not_rewrite_colour(qtbot,monkeypatch,catalog):
    import pdfmodder.dialogs as dialogs
    captured=[]
    class Dialog:
        def __init__(self,*args,**kwargs):
            self.align_box=QComboBox()
            self.allow_overlap_box=QCheckBox()
            for value in ('left','center','right'):
                self.align_box.addItem(value,value)
        def values(self):
            return dict(text='Original',width=100,height=30,size=12.375,font_name=None,font_file=None,color=None,reflow=False,align=self.align_box.currentData(),allow_overlap=self.allow_overlap_box.isChecked())
    monkeypatch.setattr(dialogs,'TextDialog',Dialog)
    glyph=SimpleNamespace(font='Helvetica',size=12.375,color=(.1,.2,.3,.4),opacity=1,direction=(1,0),mode=0,bbox=(30,40,130,60))
    model=SimpleNamespace(revision='unchanged',selected=lambda ids:[glyph],text=lambda ids:'Original')
    anchor=QComboBox()
    anchor.addItem('Derecha','right')
    harness=SimpleNamespace(page_number=0,model=model,canvas=SimpleNamespace(ids=[0]),anchor_box=anchor,
        allow_overlap_box=QCheckBox(),auto_height_box=QCheckBox(),
        _catalog=lambda callback:callback(catalog),_exec_edit_dialog=lambda dialog:QDialog.Accepted,
        _request=lambda **kwargs:SimpleNamespace(**kwargs),_error=lambda msg:pytest.fail(msg),
        _submit=lambda cmd,payload,callback:captured.append(payload['request']),_previewed=lambda *_:None)
    ExtendedEditing.format_selection(harness)
    assert len(captured)==1 and captured[0].anchor=='right'
    assert captured[0].color is None and captured[0].font_name is None
