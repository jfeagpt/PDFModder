# Exportación local en v1.5.0

`pdfmodder.export_v150.export_document(data, destination, format, pages=None, dpi=144)`
se ejecuta en el proceso PDF. `pages` usa índices desde cero, sin duplicados,
y conserva el orden indicado. `Session` aplica los permisos y la protección del
archivo de origen antes de llamar. El documento de entrada no se modifica.

- **TXT**: archivo `.txt` UTF-8, texto extraído, separador de páginas `\f`.
  No contiene maquetación ni imágenes. El orden en tablas y columnas puede variar;
  no ejecuta OCR.
- **PNG/JPEG**: una imagen RGB por página, anotaciones visibles, fondo blanco.
  Resolución de 36 a 600 ppp, con máximo de 40 millones de píxeles por página para
  acotar memoria. JPEG usa calidad 95 y tiene pérdida. Una página rotada conserva
  sus dimensiones visibles. Los formatos de imagen pierden texto seleccionable.
- **SVG**: una página vectorial por archivo, caracteres convertidos en contornos
  para no depender de fuentes instaladas en el visor. Estos caracteres no son
  texto seleccionable. Las fotografías siguen siendo mapas de bits. No se
  conservan etiquetas de accesibilidad, vínculos ni formularios interactivos;
  pueden variar efectos gráficos según el visor SVG. DPI no se aplica a SVG.

PNG/JPEG/SVG reciben una carpeta, existente o nueva, y generan nombres como
`pagina-0001.png` usando el número original de página. Se rechazan colisiones
antes de escribir y de nuevo al publicar, sin sobrescribir archivos existentes.
Se preparan todos los resultados en temporales propios y se publican completos
con renombrado atómico en Windows. No existe una transacción de sistema de archivos
para un conjunto: si falla una publicación posterior, los archivos completos ya
publicados se conservan y se enumeran en el error. Sólo se borran los temporales
propios. No se realizan llamadas de red ni se añaden dependencias.

El resultado es JSON serializable: formato, páginas, resolución, archivos con
tamaño y SHA-256, y avisos específicos del formato. Esta exportación es distinta
de Guardar como PDF; no convierte el PDF de trabajo en una imagen.

API oficial consultada para PyMuPDF 1.26.7:
[Page.get_svg_image y Page.get_pixmap](https://pymupdf.readthedocs.io/en/latest/page.html),
[Pixmap.tobytes](https://pymupdf.readthedocs.io/en/latest/pixmap.html).

Pruebas reproducibles: `python -m pytest tests/test_export_v150.py -q`.
Cubren acentos, orden y selección de páginas, rotación, PNG idéntico al render
de origen, JPEG, estructura SVG, rutas y rangos inválidos, colisiones, fallo de
render, fallo de publicación, documentos cifrados y límite de memoria estimado.
