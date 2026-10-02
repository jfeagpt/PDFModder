"""Visual image crop / rotation dialog. PDF mutation stays in the worker."""
import math
from pathlib import Path

from PySide6.QtCore import Qt,QByteArray,QBuffer,QIODevice,QRectF,Signal,QSignalBlocker
from PySide6.QtGui import QColor,QImage,QImageReader,QPainter,QPen,QPixmap,QTransform
from PySide6.QtWidgets import (QDialog,QDialogButtonBox,QDoubleSpinBox,QFileDialog,
    QGridLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QVBoxLayout,QWidget,QCheckBox)


class CropCanvas(QWidget):
    cropChanged=Signal(tuple)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('imageCropCanvas')
        self.setMinimumSize(400,280)
        self.image=QImage()
        self.crop=(0.,0.,1.,1.)
        self._drag=None
        self.setMouseTracking(True)

    def set_image(self,image):
        # Keep the drawing surface bounded; full-resolution bytes are used by
        # the worker for the real edit, not by paintEvent or pointer movement.
        self.image=image.scaled(1200,900,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        self.crop=(0.,0.,1.,1.)
        self.update()

    def set_crop(self,crop):
        self.crop=tuple(crop)
        self.update()

    def image_rect(self):
        if self.image.isNull():
            return QRectF()
        available=QRectF(self.rect()).adjusted(12,12,-12,-12)
        ratio=min(available.width()/self.image.width(),available.height()/self.image.height())
        width,height=self.image.width()*ratio,self.image.height()*ratio
        return QRectF(available.center().x()-width/2,available.center().y()-height/2,width,height)

    def crop_rect(self):
        r=self.image_rect()
        x0,y0,x1,y1=self.crop
        return QRectF(r.left()+x0*r.width(),r.top()+y0*r.height(),(x1-x0)*r.width(),(y1-y0)*r.height())

    def _normalized(self,position):
        r=self.image_rect()
        return (max(0.,min(1.,(position.x()-r.left())/r.width())),
                max(0.,min(1.,(position.y()-r.top())/r.height())))

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('#e5e7eb'))
        if self.image.isNull():
            return
        r=self.image_rect()
        painter.drawImage(r,self.image)
        c=self.crop_rect()
        shade=QColor(10,20,30,135)
        for area in (QRectF(r.left(),r.top(),r.width(),c.top()-r.top()),
                     QRectF(r.left(),c.bottom(),r.width(),r.bottom()-c.bottom()),
                     QRectF(r.left(),c.top(),c.left()-r.left(),c.height()),
                     QRectF(c.right(),c.top(),r.right()-c.right(),c.height())):
            painter.fillRect(area,shade)
        painter.setPen(QPen(QColor('#0097c7'),2))
        painter.drawRect(c)
        painter.setBrush(QColor('white'))
        for point in (c.topLeft(),c.topRight(),c.bottomLeft(),c.bottomRight()):
            painter.drawRect(QRectF(point.x()-4,point.y()-4,8,8))

    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton or not self.image_rect().contains(event.position()):
            return
        r=self.crop_rect()
        corners=(r.topLeft(),r.topRight(),r.bottomLeft(),r.bottomRight())
        corner=next((i for i,p in enumerate(corners) if (p-event.position()).manhattanLength()<14),None)
        mode=('corner',corner) if corner is not None else ('move',None) if event.modifiers() & Qt.ControlModifier else ('new',None)
        self._drag=(mode,self._normalized(event.position()),self.crop)
        event.accept()

    def mouseMoveEvent(self,event):
        if self._drag is None:
            return
        (mode,corner),start,old=self._drag
        x,y=self._normalized(event.position())
        if mode=='new':
            crop=(min(start[0],x),min(start[1],y),max(start[0],x),max(start[1],y))
        elif mode=='move':
            dx=max(-old[0],min(1-old[2],x-start[0]))
            dy=max(-old[1],min(1-old[3],y-start[1]))
            crop=(old[0]+dx,old[1]+dy,old[2]+dx,old[3]+dy)
        else:
            values=list(old)
            values[0 if corner in (0,2) else 2]=x
            values[1 if corner in (0,1) else 3]=y
            crop=(min(values[0],values[2]),min(values[1],values[3]),max(values[0],values[2]),max(values[1],values[3]))
        if crop[2]-crop[0]>=.002 and crop[3]-crop[1]>=.002:
            self.crop=crop
            self.cropChanged.emit(crop)
            self.update()
        event.accept()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:
            self._drag=None
            event.accept()


class ImageEditorDialog(QDialog):
    """Returns an operation, not a PDF or a simulated successful edit.

    operation(): replacement_bytes is None until a file is explicitly chosen;
    crop is normalized in the original asset before a clockwise arbitrary turn.
    Caller must preview the resulting PDF and obtain the normal Apply action.
    """
    def __init__(self,image_bytes,parent=None,*,frame_rect=None,initial_operation=None):
        super().__init__(parent)
        self.setWindowTitle('Recortar, girar o reemplazar imagen')
        self.setObjectName('imageEditorDialog')
        self.resize(850,630)
        self.replacement_bytes=None
        self._image=self._read_image(image_bytes)
        self._frame_ratio=((frame_rect[2]-frame_rect[0])/(frame_rect[3]-frame_rect[1])
                           if frame_rect is not None and frame_rect[3]>frame_rect[1]
                           else self._image.width()/self._image.height())
        self._proxy=self._image.scaled(1200,900,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        self._error=''
        self._invalid_crop=False
        self.canvas=CropCanvas()
        self.preview_label=QLabel()
        self.preview_label.setObjectName('imageOperationPreview')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(230,220)
        self.preview_label.setMaximumWidth(280)
        self.preview_label.setStyleSheet('background:#e5e7eb;border:1px solid #c7cdd3')
        self.size_label=QLabel()
        self.size_label.setWordWrap(True)
        self.status_label=QLabel()
        self.status_label.setObjectName('imageOperationStatus')
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        self.notice=QLabel('Encajar y Rellenar conservan las proporciones. El marco mantiene su posición y dimensiones; el recorte conserva los píxeles originales y puede recuperarse. El giro se guarda como transformación PDF, sin remuestrear la foto. Revisa después el resultado en el PDF.')
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet('background:#fff4ce;padding:8px')
        self.rotation_box=QComboBox()
        self.rotation_box.setObjectName('imageRotation')
        for value in (0,90,180,270):
            self.rotation_box.addItem(f'{value}° horario',value)
        self.rotation_spin=QDoubleSpinBox()
        self.rotation_spin.setObjectName('imageFreeRotation')
        self.rotation_spin.setRange(-360,360)
        self.rotation_spin.setDecimals(2)
        self.rotation_spin.setSuffix('°')
        self.rotation_spin.setToolTip('Giro libre en sentido horario, conservando los píxeles.')
        self.fit_box=QComboBox()
        self.fit_box.setObjectName('imageFitMode')
        for label,value in (('Encajar — imagen completa','fit'),('Rellenar recortando','fill'),('Estirar — cambia proporciones','stretch')):
            self.fit_box.addItem(label,value)
        self.flip_horizontal=QCheckBox('Voltear horizontal')
        self.flip_horizontal.setObjectName('imageFlipHorizontal')
        self.flip_vertical=QCheckBox('Voltear vertical')
        self.flip_vertical.setObjectName('imageFlipVertical')
        self.replace_button=QPushButton('Elegir otra imagen…')
        self.replace_button.setObjectName('imageReplaceFile')
        self.reset_button=QPushButton('Restablecer recorte y giro')
        self.reset_button.setObjectName('imageResetCrop')
        self.crop_spins=[]
        grid=QGridLayout()
        for column,(label,value) in enumerate(zip(('Izquierda','Arriba','Derecha','Abajo'),(0,0,100,100))):
            spin=QDoubleSpinBox()
            spin.setObjectName('imageCrop'+('Left','Top','Right','Bottom')[column])
            spin.setRange(0,100)
            spin.setDecimals(2)
            spin.setSuffix(' %')
            spin.setValue(value)
            spin.valueChanged.connect(self._numbers_changed)
            self.crop_spins.append(spin)
            grid.addWidget(QLabel(label),0,column)
            grid.addWidget(spin,1,column)
        tools=QHBoxLayout()
        tools.addWidget(QLabel('Giro'))
        tools.addWidget(self.rotation_box)
        tools.addWidget(self.rotation_spin)
        tools.addStretch()
        tools.addWidget(self.reset_button)
        tools.addWidget(self.replace_button)
        arrangement=QHBoxLayout()
        arrangement.addWidget(QLabel('Ajuste al marco'))
        arrangement.addWidget(self.fit_box,1)
        arrangement.addWidget(self.flip_horizontal)
        arrangement.addWidget(self.flip_vertical)
        images=QHBoxLayout()
        images.addWidget(self.canvas,1)
        right=QVBoxLayout()
        right.addWidget(QLabel('Resultado de la imagen'))
        right.addWidget(self.preview_label,1)
        right.addWidget(self.size_label)
        images.addLayout(right)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.preview_button=self.buttons.button(QDialogButtonBox.Ok)
        self.preview_button.setText('Ver en el PDF')
        self.preview_button.setObjectName('imageEditorPreview')
        self.buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        layout=QVBoxLayout(self)
        tip=QLabel('Dibuja el recorte arrastrando sobre la imagen. Ajusta sus esquinas o usa Ctrl+arrastrar para mover el recorte.')
        tip.setWordWrap(True)
        layout.addWidget(tip)
        layout.addLayout(images,1)
        layout.addLayout(grid)
        layout.addLayout(tools)
        layout.addLayout(arrangement)
        layout.addWidget(self.notice)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)
        self.canvas.cropChanged.connect(self._visual_changed)
        self.rotation_box.currentIndexChanged.connect(lambda *_:self.rotation_spin.setValue(self.rotation_box.currentData()))
        self.rotation_spin.valueChanged.connect(self._refresh)
        self.fit_box.currentIndexChanged.connect(self._refresh)
        self.flip_horizontal.toggled.connect(self._refresh)
        self.flip_vertical.toggled.connect(self._refresh)
        self.reset_button.clicked.connect(self._reset)
        self.replace_button.clicked.connect(self._replace)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.canvas.set_image(self._image)
        if initial_operation:
            self.rotation_spin.setValue(initial_operation.get('rotation',0))
            self.flip_horizontal.setChecked(initial_operation.get('flip_horizontal',False))
            self.flip_vertical.setChecked(initial_operation.get('flip_vertical',False))
            index=self.fit_box.findData(initial_operation.get('fit_mode','fit'))
            self.fit_box.setCurrentIndex(max(0,index))
            self.canvas.set_crop(initial_operation.get('crop',(0,0,1,1)))
            self._visual_changed(self.canvas.crop)
        self._refresh()

    def operation(self):
        if not self.preview_button.isEnabled():
            raise ValueError(self.status_label.text())
        return {'replacement_bytes':self.replacement_bytes,
                'crop':self.canvas.crop,'rotation':self.rotation_spin.value(),
                'fit_mode':self.fit_box.currentData(),
                'flip_horizontal':self.flip_horizontal.isChecked(),
                'flip_vertical':self.flip_vertical.isChecked()}

    def _visual_changed(self,crop):
        self._invalid_crop=False
        for spin,value in zip(self.crop_spins,crop):
            with QSignalBlocker(spin):
                spin.setValue(value*100)
        self._refresh()

    def _numbers_changed(self,*_):
        crop=tuple(spin.value()/100 for spin in self.crop_spins)
        if crop[0]>=crop[2] or crop[1]>=crop[3]:
            self._invalid_crop=True
            self.status_label.setText('El recorte debe tener anchura y altura mayores que cero.')
            self.preview_button.setEnabled(False)
            return
        self._invalid_crop=False
        self.canvas.set_crop(crop)
        self._refresh()

    def _refresh(self,*_):
        if self._invalid_crop:
            self.status_label.setText('El recorte debe tener anchura y altura mayores que cero.')
            self.preview_button.setEnabled(False)
            return
        if self._image.isNull() or self._error:
            self.status_label.setText(self._error or 'No se pudo decodificar la imagen seleccionada.')
            self.preview_button.setEnabled(False)
            return
        x0,y0,x1,y1=self.canvas.crop
        left,top=math.floor(x0*self._image.width()),math.floor(y0*self._image.height())
        right,bottom=math.ceil(x1*self._image.width()),math.ceil(y1*self._image.height())
        # Pointer moves copy only a bounded proxy; the exact full-resolution
        # crop and validation run later in the worker process.
        pl,pt=math.floor(x0*self._proxy.width()),math.floor(y0*self._proxy.height())
        pr,pb=math.ceil(x1*self._proxy.width()),math.ceil(y1*self._proxy.height())
        cropped=self._proxy.copy(pl,pt,pr-pl,pb-pt)
        # Draw the bounded proxy using the same frame geometry as the PDF. Only
        # this preview is rasterized; export transforms the original resource.
        angle=self.rotation_spin.value()
        mode=self.fit_box.currentData()
        fw,fh=(270.,270./self._frame_ratio) if self._frame_ratio>=1 else (270.*self._frame_ratio,270.)
        preview=QPixmap(max(1,round(fw)),max(1,round(fh)))
        preview.fill(QColor('#fafafa'))
        painter=QPainter(preview)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setClipRect(QRectF(0,0,fw,fh))
        radians=math.radians(angle)
        c,s=abs(math.cos(radians)),abs(math.sin(radians))
        cw,ch=cropped.width(),cropped.height()
        if mode=='fill':
            sx=sy=max((c*fw+s*fh)/cw,(s*fw+c*fh)/ch)
        elif mode=='fit':
            sx=sy=min(fw/(c*cw+s*ch),fh/(s*cw+c*ch))
        else:
            sx,sy=fw/(c*cw+s*ch),fh/(s*cw+c*ch)
        painter.translate(fw/2,fh/2)
        painter.scale(sx,sy)
        painter.rotate(angle)
        painter.scale(-1 if self.flip_horizontal.isChecked() else 1,-1 if self.flip_vertical.isChecked() else 1)
        painter.drawImage(QRectF(-cw/2,-ch/2,cw,ch),cropped)
        painter.end()
        self.preview_label.setPixmap(preview)
        width,height=right-left,bottom-top
        self.size_label.setText(f'Recurso conservado: {self._image.width()} × {self._image.height()} px\nRecorte elegido: {width} × {height} px\nGiro: {angle:g}° · Marco: {self._frame_ratio:.3f}:1')
        self.status_label.setText('La previsualización del PDF comprobará las demás imágenes, texto, enlaces y elementos de la página.')
        self.preview_button.setEnabled(True)

    def _reset(self):
        self.canvas.set_crop((0.,0.,1.,1.))
        with QSignalBlocker(self.rotation_box):
            self.rotation_box.setCurrentIndex(0)
        with QSignalBlocker(self.rotation_spin):
            self.rotation_spin.setValue(0)
        with QSignalBlocker(self.flip_horizontal),QSignalBlocker(self.flip_vertical):
            self.flip_horizontal.setChecked(False)
            self.flip_vertical.setChecked(False)
        self._visual_changed(self.canvas.crop)

    def set_replacement(self,image_bytes):
        """Testable local import, with the same limits enforced by the worker."""
        if not image_bytes or len(image_bytes)>50*1024*1024:
            raise ValueError('La imagen está vacía o supera el límite de 50 MB.')
        image=self._read_image(image_bytes)
        self.replacement_bytes=image_bytes
        self._image=image
        self._proxy=image.scaled(1200,900,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        self._error=''
        self.canvas.set_image(image)
        self._reset()

    @staticmethod
    def _read_image(image_bytes):
        buffer=QBuffer()
        buffer.setData(QByteArray(image_bytes))
        buffer.open(QIODevice.ReadOnly)
        reader=QImageReader(buffer)
        size=reader.size()
        if size.width()*size.height()>40_000_000:
            raise ValueError('La imagen supera el límite de 40 millones de píxeles.')
        reader.setAutoTransform(True)
        image=reader.read()
        if image.isNull():
            raise ValueError('El formato de imagen no puede previsualizarse. Usa PNG, JPEG, BMP o TIFF.')
        return image

    def _replace(self):
        path,_=QFileDialog.getOpenFileName(self,'Reemplazar la imagen seleccionada','','Imágenes (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)')
        if not path:
            return
        try:
            source=Path(path)
            if source.stat().st_size>50*1024*1024:
                raise ValueError('La imagen supera el límite de 50 MB.')
            self.set_replacement(source.read_bytes())
        except (OSError,ValueError) as exc:
            # Leave the last usable image and operation intact after an import
            # failure; the user may retry or cancel without losing the PDF.
            self.status_label.setText(str(exc))
