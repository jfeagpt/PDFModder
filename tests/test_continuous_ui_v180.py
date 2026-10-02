import pytest
from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from pdfmodder.model import Glyph, PageModel
from test_tools_ui_v150 import NoPdfPool


@pytest.fixture
def reader_window(qtbot,monkeypatch):
    import pdfmodder.app as application
    monkeypatch.setattr(application,'ProcessPoolExecutor',NoPdfPool)
    window=application.MainWindow()
    qtbot.addWidget(window)
    for timer in (window.poller,window.thumbnail_timer,window.reader_timer_v180):timer.stop()
    window.show()
    yield window
    window.state={};window._allow_close=True;window.close()


def populate(window):
    image=QImage(500,700,QImage.Format_RGB32);image.fill(Qt.white)
    buffer=QBuffer();buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG')
    png=bytes(buffer.data());models=[]
    for page in range(2):
        glyphs=[]
        for block,text,y in ((0,'Primer parrafo',80),(1,'Segundo parrafo',170)):
            for i,char in enumerate(text):
                box=(50+i*10.,y,60+i*10.,y+15.)
                glyphs.append(Glyph(len(glyphs),char,(box[0],y+12.),box,box,'Helvetica',12.,(0.,0.,0.),1.,block,block,0))
        matrix=(1.,0.,0.,1.,0.,0.)
        models.append(PageModel(page,500.,700.,0,matrix,matrix,(0.,0.,500.,700.),glyphs,revision='fixture'))
    window.state={'path':'synthetic.pdf','page_count':2,'document_revision':'fixture','copy_allowed':True,
                  'issues':[],'validation_pending':True,'editing_prepared':False}
    window._reader_key_v180=('fixture',False)
    window.reader.reset_document([{'width':500.,'height':700.}]*2,zoom=1.)
    for number,model in enumerate(models):window.reader.set_page(number,png,model,1.)
    window.model=models[0]
    window.zoom=1.
    window._refresh_actions()
    QApplication.processEvents()
    return models


def point(reader,page,glyph):
    rect=reader._rects[page]
    return reader.mapFromScene(QPointF(rect.left()+(glyph.bbox[0]+glyph.bbox[2])/2,
                                     rect.top()+(glyph.bbox[1]+glyph.bbox[3])/2))


def test_reader_startup_stack_and_copy_range_between_pages(reader_window,qtbot,monkeypatch):
    window=reader_window;models=populate(window)
    assert window.document_views.currentWidget() is window.reader
    requests=[]
    monkeypatch.setattr(window,'_submit',lambda command,payload=None,callback=None:requests.append((command,payload,callback)) or True)
    window.reader.go_page(0)
    qtbot.mouseClick(window.reader.viewport(),Qt.LeftButton,pos=point(window.reader,0,models[0].glyphs[0]))
    window.reader.go_page(1)
    qtbot.mouseClick(window.reader.viewport(),Qt.LeftButton,Qt.ShiftModifier,pos=point(window.reader,1,models[1].glyphs[-1]))
    window.reader.setFocus()
    qtbot.keyClick(window.reader.viewport(),Qt.Key_C,Qt.ControlModifier)
    assert requests[-1][0]=='reading_copy_range'
    payload=requests[-1][1]
    assert payload['start']['page']==0 and payload['end']['page']==1 and payload['revision']=='fixture'
    requests[-1][2]({'text':'Primer parrafo\n\nSegundo parrafo\n\nPagina dos'})
    assert 'Pagina dos' in QApplication.clipboard().text()
    assert not window.canvas.editor.isVisible() and not window._rich_active
    assert window.copy_action_v170.isEnabled() and not window.delete_action_v170.isEnabled()


def test_tag_button_asks_then_uses_preview_and_stays_disabled_in_reading(reader_window,monkeypatch):
    window=reader_window
    window.state={'page_count':1,'tagged':True,'issues':[],'path':'synthetic.pdf'}
    window._refresh_actions()
    assert not window.remove_tags_action.isEnabled()
    window._set_mode_v171('editing')
    assert window.remove_tags_action.isEnabled()
    requests=[]
    monkeypatch.setattr(window,'_submit',lambda command,payload=None,callback=None:requests.append(command) or True)
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:QMessageBox.Cancel)
    window.remove_tags_v180();assert requests==[]
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:QMessageBox.Yes)
    window.remove_tags_v180();assert requests==['remove_tags']
