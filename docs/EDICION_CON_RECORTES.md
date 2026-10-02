> La descripción siguiente conserva el alcance de 0.8.1. La [revisión 0.8.2](CORRECCIONES_V082.md) amplía campos fragmentados, líneas, fuentes y movimientos.

# Texto recortado e identificación de fuentes en 0.8.1

La presencia de recortes gráficos no bloquea por sí sola agregar imágenes. El texto existente dispone de una ruta conservadora que modifica códigos dentro de sus operadores originales. No elimina los recortes, no ejecuta reconocimiento OCR, no tapa texto ni rasteriza la página. Desde 0.8 también se pueden retirar duplicados OCR invisibles cuando se demuestra su correspondencia con las palabras digitales editadas.

Las funciones de recortes de 0.5 se conservaron en la versión 0.7, archivada por separado en `releases/v0.7/`. Como evidencia histórica, 0.8.0 completó 416 pruebas y cuatro recorridos de su ejecutable; el recorrido de campos recortados pasó 12 pasos. Estas cifras no acreditan el paquete 0.8.1. La aceptación nueva del motor, sus límites y el estado del paquete se documentan en [CORRECCIONES_V081.md](CORRECCIONES_V081.md).

## Aceptar una edición

1. Seleccione una palabra o línea y haga doble clic, o pulse **Editar sobre la página**.
2. Escriba el contenido. Pulse **1. Ver vista previa · Ctrl+Intro**, o use Ctrl+Intro.
3. Revise la página renderizada desde el PDF realmente modificado. La región cambiada permanece visible. Pulse **2. Aplicar cambio** para incorporarla al historial.
4. Use **Guardar como…** para guardar otra copia. Reábrala para seguir trabajando.

**Cancelar · Esc** descarta la escritura o la previsualización. Aplicar no guarda todavía un archivo; Guardar como es una acción distinta. Los mismos botones de aplicar y cancelar sirven para la previsualización de inserción o propiedades de imágenes.

## Alcance del texto recortado

`clipping.py` interpreta operadores mediante `pypdf.generic.ContentStream`. Un sondeo temporal identifica qué operador y recurso pintan cada carácter; el sondeo no se exporta. En 0.8.1, `native_codes.py` amplía los códigos ya observados con los declarados por Encoding/ToUnicode del mismo recurso y exige un glifo real verificable. No inventa una codificación, no toma códigos de otra fuente por nombre ni convierte automáticamente un carácter ausente en otra tipografía. La ruta de igual avance conserva directamente los códigos y operadores; la ruta de longitud variable compensa el avance del cursor dentro del mismo Tj/TJ. Recursos directos sin xref también se distinguen por su nombre de recurso.

La ruta de igual avance conserva la cantidad de caracteres, el recurso original, su codificación, el programa de fuente, los ajustes TJ, las matrices y los operadores de recorte. Se escribe un stream privado de la página y una copia completa, evitando alterar otras páginas que compartan recursos. Se vuelven a comprobar todos los caracteres, posiciones y estilos, las capas invisibles, imágenes, vectores, elementos relacionados y apariencia fuera de las pequeñas cajas de los caracteres realmente modificados.

Desde 0.5, `clipped_layout.py` permite además longitud y avances diferentes en un fragmento contiguo de un solo Tj/TJ. Conserva Tf, Tc, Tw, Tz, las matrices horizontales positivas y el programa original, recalculando los ajustes TJ del fragmento y compensando el cursor posterior. Los caracteres vecinos del mismo operador y de los siguientes permanecen en sus posiciones. Admite anclajes izquierdo, derecho y centrado; el decimal no está habilitado en esta ruta. No reduce ni comprime el texto.

En 0.8, **Ajustar anchura al texto** está activo por defecto para una sola línea. Adapta el área sin escalar las letras; sigue comprobando el recorte de origen y destino, los vecinos, los elementos interactivos y el borde de página. Para usar una anchura fija, desactive esa opción y establezca **Anchura de área** dentro de su columna. Disponer de una caja mayor no permite invadir otro campo.

Se mantienen los bloqueos de cambios de fuente/tamaño/color y redistribución entre líneas en esta ruta. **Ajustar el resto de la línea** requiere seleccionar el campo completo; la vista previa informa de que no se justifica ni se desplazan vecinos. Para editar sólo un fragmento sin desplazarlos, desactive esa opción. La justificación de una línea y la composición de párrafos en otros PDFs compatibles conservan sus controles propios, descritos en la [guía 0.8](GUIA_V08.md).

Desde 0.8.1, `move_clipped_text` permite mover caracteres, palabras y líneas compatibles mediante una transformación `q / cm / TJ / Q` alrededor de los fragmentos seleccionados. Conserva sus códigos, avances TJ, fuente y distribución interna; restaura el estado gráfico y deja el cursor textual posterior en su posición nativa. El recorte ya establecido permanece fijo: no se desplaza ni se elimina para permitir el movimiento. Las coordenadas se convierten mediante la transformación de página y se validan después de guardar, también con desplazamientos fraccionarios. Se bloquean recortes complejos o desconocidos, caracteres originalmente cortados, destinos fuera de su recorte o página, solapamientos y codificaciones que no permitan aislar cada carácter.

El ajuste de línea de 0.8.1 también reconoce pequeñas diferencias de línea base introducidas por exportadores: además de la tolerancia anterior, admite como máximo 0,3 puntos y el 4 % del tamaño de letra, con la misma línea, tramo y fuente, una operación de pintura coherente y fuerte superposición vertical. Las letras conservadas mantienen sus alturas; no se unen filas ni columnas por cercanía. Esta mejora no convierte un campo recortado dividido entre varios operadores en un párrafo editable: esa limitación sigue comprobándose de forma independiente.

Cuando existe OCR invisible duplicado bajo una palabra digital, 0.8 verifica que los centros de todos sus caracteres estén cubiertos por esa palabra visible, dentro de tolerancias pequeñas. Sólo entonces retira el duplicado y aplica la edición digital en una misma transacción. Los caracteres de la palabra que no se modifican siguen presentes como texto visible real; la capa OCR de otras palabras permanece intacta. La vista previa informa de la retirada. Para una selección parcial se necesita mantener también el orden de extracción; si la ruta nativa no puede demostrarlo, se solicita seleccionar la palabra completa.

La retirada del duplicado debe conservar la apariencia y se valida sin excluir regiones; el corpus de esta ruta obtiene diferencia de píxeles cero. Después, el texto visible modificado se valida por separado. Si un OCR abarca otra columna, no corresponde a las palabras seleccionadas o no se puede aislar, se bloquea la operación sin retirar nada del estado de trabajo. Se conservan los límites sobre codificaciones, selecciones no contiguas, regiones inseguras y combinación de recortes con etiquetas accesibles.

El modo **Corregir sólo la capa OCR buscable** es diferente: selecciona texto invisible existente desde Elementos y modifica lo que se busca o copia, manteniendo idéntica la imagen escaneada. Conserva el origen y recurso OCR, permite ajustar su área sin escalar la fuente y requiere códigos verificables. No mueve ni recompone la imagen ni admite cambios de formato, justificación o saltos de línea. El texto visible de la ruta de recortes sigue requiriendo relleno normal `Tr=0`; no se admite convertir texto visible en invisible para simular una edición. Consulte [OCR existente](OCR.md) y [etiquetado accesible](ETIQUETADO.md).

## Certeza tipográfica

Seleccione texto y abra **Inspector de fuentes**. La identificación se vincula al operador PDF y al recurso exacto cuando se pueden verificar; no se decide sólo por el nombre de familia. El inspector muestra nombre PostScript interno, variante, versión, recurso/objeto, incrustación, subconjunto y SHA-256 del programa extraído. Si la vinculación es ambigua o no verificable, lo comunica.

La huella acredita qué bytes contiene ese recurso. No demuestra que un archivo completo instalado sea el origen de un subconjunto. Los candidatos locales se comparan por nombre PostScript, variante, versión y huella; ninguna coincidencia nominal se convierte silenciosamente en una sustitución. Cada inspección explícita relee los bytes del candidato y calcula su huella: no confía sólo en tamaño o fechas de archivo. Se limita la caché del análisis a 24 archivos y 16 MiB.

**Cobertura Unicode para reinserción** y **códigos PDF existentes** son comprobaciones diferentes. Un subconjunto puede dibujar las cifras originales gracias a su codificación PDF aunque no permita insertarlas con la API Unicode de una fuente completa. En ese caso, los cambios mediante códigos PDF y compensación de avances pueden seguir siendo viables, conservando el recurso sin reincrustarlo. La vista previa valida cada operación concreta.

Una asociación manual guarda localmente la ruta y huella del TTF/OTF, sin copiarlo ni descargar fuentes. Debe elegirse la variante exacta con permisos adecuados; nombre, versión y selección visual no garantizan compatibilidad de todos los glifos.

## Comprobaciones

El corpus reproducible incluye `tests/test_text_clips.py`, `tests/test_clipped_layout.py`, `tests/test_media_clips.py`, `tests/test_font_evidence.py` y `tests/test_accept_buttons.py`: recortes con matrices heredadas, avances TJ irregulares, recursos compartidos/directos, OCR superpuesto, texto usado como recorte, caché de fuentes, aceptación por botones y conservación de la zona visible. En 0.8, `tests/test_ocr_edit.py` amplía la retirada de duplicados y la corrección buscable, y `tests/test_review_text.py` cubre la anchura automática y la revisión de sustituciones. La existencia de estas pruebas no sustituye el informe final de su ejecución.

Como evidencia histórica, se verificó un PDF real de una página, con 42 recortes, 5.414 caracteres y nueve imágenes. Se probó una sustitución de fecha conservando la fuente incrustada, y agregar, mover, redimensionar y eliminar imágenes. Esa prueba privada no representa todos los exportadores ni todas las regiones del documento. El PDF, sus datos y sus capturas no se incluyen en el paquete distribuible. Los resultados conservan su versión en [VERIFICACION_WINDOWS.md](VERIFICACION_WINDOWS.md); la comprobación concreta de limpieza OCR de 0.8 se describe por separado en [OCR.md](OCR.md).

Referencias de API: [operadores y streams de pypdf 6.6.0](https://pypdf.readthedocs.io/en/6.6.0/modules/generic.html), [páginas de PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html).

En otra prueba histórica privada, una factura de una página con tres recortes y 2.400 glifos sin OCR, se validaron 16 operaciones encadenadas: fecha, número, cliente, direcciones, concepto e importes, conservando fuentes, líneas de tabla, logotipo y pie legal. Se guardó y reabrió, se extrajo texto con pypdf y se contrastó la apariencia con Poppler. El archivo original y la factura de demostración no se incluyen en el paquete público. Esta evidencia no se presenta como verificación final del paquete nuevo.
