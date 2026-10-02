# Imágenes en PDF Modder v0.8

El menú contextual de una imagen ofrece guardar su recurso y abrir el editor de recorte, giro y reemplazo. Seleccione la instancia deseada y pulse el botón derecho. El cambio se verifica y previsualiza en el PDF real antes de **Aplicar**; después use **Guardar como**. Cancelar el diálogo no altera el documento.

## Exportar

Se guarda el recurso de imagen completo a su resolución original, sin rasterizar la página ni incluir el texto superpuesto. JPEG sin máscara conserva sus bytes codificados; las demás imágenes compatibles se exportan como PNG RGB/RGBA. La máscara de transparencia suave se incorpora al canal alfa. El recorte, giro y opacidad que proceden del ámbito gráfico de la página no se incorporan al archivo exportado: no es una captura de su apariencia en la página. La exportación respeta el permiso de copia del PDF.

No se exportan silenciosamente máscaras de estarcido, máscaras duras, máscaras por clave de color, máscaras con `Matte` o imágenes inline cuyo recurso sea ambiguo. Estos casos muestran un motivo concreto. Una imagen que no se puede mover puede seguir siendo exportable, porque leer su recurso no modifica la página.

## Recortar, girar o reemplazar

En **Recortar, girar o reemplazar imagen**:

1. Dibuje un rectángulo arrastrando sobre la imagen. Sus esquinas ajustan el recorte; **Ctrl+arrastrar** lo mueve.
2. También puede usar los campos **Izquierda, Arriba, Derecha y Abajo**, expresados como porcentaje de la imagen original.
3. Elija **0°, 90°, 180° o 270° horario**. Primero se recorta y después se gira.
4. **Elegir otra imagen…** importa PNG, JPEG, BMP o TIFF. Se respeta la orientación EXIF. El recorte y giro vuelven a su estado inicial al elegir otro archivo.
5. **Ver en el PDF** solicita la previsualización real. Compruébela y pulse **Aplicar cambio**.

La caja conserva su posición y dimensiones en el PDF. El resultado del recorte o giro se ajusta a esa caja; sus proporciones pueden cambiar. El diálogo lo avisa antes de aplicar. Si se desea otra proporción, puede redimensionarse después la instancia mediante los controles de imagen existentes. El recorte elimina píxeles del asset nuevo, no tapa una parte del recurso con una anotación ni con un rectángulo.

La imagen seleccionada se convierte en un recurso PNG RGB/RGBA de ocho bits por canal. El giro en múltiplos de 90° y el recorte operan sobre los píxeles sin interpolación. CMYK, perfiles o profundidad de color distinta pueden requerir conversión RGB; no se promete conservar el perfil de impresión de la imagen editada. Las otras imágenes conservan sus recursos y transparencia. Límite de entrada: 50 MB y 40 millones de píxeles, un único fotograma. Durante el arrastre del recorte se dibuja una copia limitada a 1200 × 900 px; el proceso PDF usa la imagen completa.

## Integridad de la instancia

No se usa `Page.replace_image(xref)`: según la [documentación oficial de PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html#Page.replace_image), esa operación reemplaza todas las apariciones del recurso. Se materializan y copian los diccionarios `Resources` y `XObject` de la página, incluso cuando son heredados. Se crea un recurso nuevo y se cambia únicamente el operador `Do` seleccionado dentro de una copia del stream. Se conservan `q/cm/Do/Q`, el orden de pintado, matriz, recortes y opacidad existentes. El recurso original compartido no se sobrescribe.

La validación comprueba todas las páginas, dimensiones, texto extraído, vectores, enlaces, anotaciones, otros recursos de imagen y transparencia. Compara los píxeles nuevos contra el recorte/giro solicitado y renderiza fuera de la caja modificada a 144 ppp con la tolerancia existente de 8/255. Otra aparición en la misma página o en otra página se comprueba expresamente. La escritura es completa y el resultado se abre con el lector independiente pypdf.

La transformación conserva los límites del motor para instancias que no se pueden aislar: formularios gráficos, giros/inclinaciones originales complejos, contenido marcado, recortes parciales/desconocidos, mezcla especial, máscaras externas y documentos incompatibles se bloquean con una explicación. No se aplica el cambio globalmente como alternativa.

## Pruebas reproducibles

`tests/test_image_tools.py` genera todas sus imágenes y PDFs localmente y cubre exportación JPEG exacta, transparencia, recorte, giros, reemplazo transparente, instancias y streams compartidos, recursos heredados, enlaces, anotaciones, texto vecino, CropBox desplazado, página girada, recorte heredado, opacidad, permisos, selección obsoleta y el diálogo mediante eventos de ratón y teclado. No contiene documentos privados.

Ejecutar junto con la batería de imágenes anterior:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_image_tools.py tests/test_media.py tests/test_media_clips.py
```

API de lectura: `export_image_pdf(data, page, image_id, revision=None)` devuelve bytes, extensión, PNG de previsualización y metadatos. API de edición: `edit_image_pdf(data, page, image_id, replacement_bytes=None, crop=None, rotation=0, revision=None)` devuelve PDF y validación; los tres parámetros de edición son argumentos por nombre. `ImageEditorDialog.operation()` devuelve exactamente estos datos, sin mutar el PDF. Si no se elige un archivo nuevo, `replacement_bytes` es `None`.
