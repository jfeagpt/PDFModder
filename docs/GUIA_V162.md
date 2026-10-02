# Dibujar el área de firma en PDF Modder 1.6.2

1. Abra el PDF y pulse **Firmar…**.
2. Seleccione su certificado y active **Mostrar firma en la página**.
3. Elija la página y pulse **Dibujar recuadro en la página…**.
4. Sobre el documento, mantenga pulsado el botón izquierdo y arrastre hasta
   delimitar el espacio donde desea el sello. Puede arrastrar en cualquier
   dirección. Al soltar, reaparece el diálogo con las medidas seleccionadas.
5. Pulse **Previsualizar firma y posición** para revisar el sello. Después pulse
   **Elegir destino y firmar…** y guarde la copia.

**Escape** o **Cancelar** durante el dibujo vuelve al diálogo sin cambiar la
posición anterior ni firmar. Puede repetir el dibujo o ajustar las medidas
en milímetros. Si el recuadro resulta pequeño para el certificado, se le pide
ampliarlo. El contenido del PDF no se desplaza para hacer sitio a la firma.

La posición se toma de la página renderizada y contempla zoom, desplazamiento,
rotación y CropBox. La vista previa y la firma utilizan esas mismas medidas.
Los límites de certificados, documentos etiquetados y sellado de tiempo siguen
siendo los descritos en [GUIA_V161.md](GUIA_V161.md).

Esta actualización incorpora selección mediante arrastre del área de firma.
Los resultados de sus comprobaciones dirigidas aparecen en `RESULTADOS_V162.md`
y en los informes de la entrega. No acredita una repetición de la batería
completa ni una prueba en un segundo ordenador físico.
