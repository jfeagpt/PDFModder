# OCR existente en PDF Modder 0.8

La aplicación puede corregir PDFs que ya contienen OCR. No ejecuta reconocimiento de caracteres, no necesita IA ni servicios externos y no convierte una página escaneada en un documento de texto maquetado.

## Texto digital visible con una capa OCR duplicada

Cuando una palabra visible tiene un duplicado invisible superpuesto, la edición retira ese duplicado de las palabras afectadas antes de modificar su texto real. La vista previa informa de la retirada. Las demás palabras OCR permanecen en su posición original. El texto digital resultante sigue siendo seleccionable y buscable.

La retirada se limita a palabras OCR cuyos **centros de todos sus caracteres** están dentro de la palabra digital que se edita, con tolerancias de 0,5 puntos horizontales y 1 punto vertical. Estas tolerancias cubren redondeos y pequeñas diferencias de línea base; no se acepta que sólo una mayoría del rectángulo se solape. Si un OCR mal agrupado abarca otra columna o zona, se bloquea con una explicación concreta.

Al corregir un solo carácter de una palabra, se retira su duplicado OCR completo: los otros caracteres siguen presentes como texto digital visible. Se prefiere la modificación nativa del operador de texto para mantener el orden de búsqueda de la palabra. Si un fragmento intermedio no dispone de esa ruta verificable, se solicita seleccionar la palabra completa; no se acepta una corrección que sólo parezca correcta y rompa el orden del texto.

Los límites del texto original siguen vigentes: recortes parciales, fuentes sin códigos disponibles, transformaciones ambiguas o regiones que no pueden aislarse pueden impedir un cambio concreto. La limpieza y la edición son una sola transacción; si falla la edición final, no se incorpora ninguna retirada al historial.

## Corregir sólo la capa buscable de una imagen escaneada

1. Abra el panel **Elementos de la zona** y seleccione el texto OCR invisible de la zona.
2. Active explícitamente **Corregir sólo la capa OCR buscable**.
3. Escriba la corrección y solicite **Ver vista previa**.
4. Lea el aviso y pulse **Aplicar cambio** si quiere corregir la búsqueda.

**La imagen escaneada conserva su texto y apariencia originales.** Modificar su capa OCR no modifica lo que está fotografiado. La vista previa lo advierte antes de aplicar; nunca se representa una modificación invisible como una corrección visual del documento.

Este modo permite sustituir, insertar y borrar caracteres de un tramo contiguo de una sola operación OCR. Conserva su recurso de fuente y origen. La anchura del área puede ajustarse automáticamente o ampliarse explícitamente; no se escala la fuente. Se rechaza el desbordamiento hacia otra palabra OCR. No admite movimiento, cambios de fuente/tamaño/color, justificación ni saltos de línea, porque estas acciones no editarían las letras de la imagen.

## Qué se modifica y qué se comprueba

`ocr.py` interpreta los operadores mediante el parser de pypdf y relaciona los glifos con su recurso `Tf` real. Admite fuentes simples de un byte y fuentes compuestas `Type0` con codificación `Identity-H` de dos bytes, cuando cada código corresponde a un glifo verificable. Los códigos de sustitución deben existir en ese mismo recurso; un nombre de familia coincidente no es suficiente.

Al eliminar caracteres OCR, sus códigos desaparecen del operador `Tj/TJ`. Se sustituyen por desplazamientos numéricos `TJ` calculados con los anchos PDF y el espaciado `Tc/Tw`. La sustitución de texto de longitud diferente compensa el cursor después del fragmento, de modo que los caracteres vecinos conservan sus posiciones. Se escribe un stream privado de la página, con guardado completo y limpieza de objetos; no se modifica un stream compartido por otras páginas.

Se comprueban todos los caracteres no seleccionados, su posición, fuente, tamaño, color, opacidad y modo de pintura. Se verifican páginas, imágenes, vectores, enlaces, anotaciones, marcadores y metadatos. La retirada de OCR y la corrección de una capa buscable se comparan a 144 ppp **sin excluir ninguna región**: los documentos del corpus dan diferencia de píxeles cero. Los operadores ajenos y los recursos originales también se comparan con un parser independiente. Las pruebas incluyen recursos compartidos, fuente CID, espaciados, CropBox desplazado y rotación de página.

El acceso a las cadenas conserva sus bytes auténticos. En pypdf 6.6 se usa `TextStringObject.original_bytes`: reconstruirlas con `get_original_bytes()` podría introducir una marca BOM que no pertenecía al código CID original.

## Límites y corpus

No se modifican capas OCR con semántica accesible etiquetada que requiera actualizar sus relaciones, contenido marcado ambiguo, Form XObjects no aislados, modos de texto que recortan, codificaciones sin correspondencia verificable o documentos con restricciones ya detectadas por el editor. Se conserva el original en todos los casos.

El texto oculto mediante **opacidad cero** y un modo distinto de `Tr=3` se distingue de las líneas visibles en la selección, el panel de elementos y la búsqueda, pero su corrección se bloquea con un mensaje específico. No se mezcla con el texto visible ni se considera automáticamente una capa OCR compatible.

El corpus generado de `tests/test_ocr_edit.py` prueba edición visible con retirada del duplicado, corrección buscable más larga y más corta, borrado, reapertura, origen de página rotada, recursos compartidos, caracteres ausentes, solapamientos ambiguos y rechazo de opciones no admitidas. `tests/test_text_clips.py` cubre además OCR superpuesto a una fecha con recortes y avances especiales.

También se probó privadamente el PDF real aportado por el usuario: una fecha con once caracteres OCR superpuestos se modificó conservando las demás apariciones legítimas. La retirada dejó idénticos los 2.006.835 píxeles comprobados a 144 ppp. La comparación independiente con Poppler excluyó sólo 260 píxeles del carácter visible cambiado (0,012956% de la página) y encontró cero diferencias fuera de esa zona. El archivo original, la copia y sus capturas permanecen fuera del paquete público. Esta evidencia valida esa operación concreta, no todas las regiones o programas exportadores.

Referencias: [operadores y cadenas de pypdf 6.6](https://pypdf.readthedocs.io/en/6.6.0/modules/generic.html), [extracción y renderizado de PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html).
