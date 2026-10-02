# Observación de Adobe Acrobat XI Pro para PDF Modder 1.5.0

Registro de pruebas manuales sobre copias locales de cuatro documentos aportados
por el usuario. No constituye una prueba exhaustiva de Acrobat ni acredita que
PDF Modder admita cualquier PDF. Los archivos privados y resultados se guardan
en `tmp/acrobat-v150-private`; no forman parte del corpus distribuible.

Las acciones realizadas hasta ahora por el agente principal se distinguen de
las pendientes. Una acción visible en la interfaz no sustituye la validación del
contenido, relaciones y renderizado del PDF exportado.

## Matriz de acciones

| Documento | Acción | Resultado observado | Evidencia / alcance |
| --- | --- | --- | --- |
| FACTURA F25-1 | Editar texto existente | Cambio de `ESPAÑA` a `PORTUGAL` realizado | Copia `factura-acrobat.pdf` guardada |
| FACTURA F25-1 | Mover texto | Cabecera desplazada arrastrando el borde superior del cuadro | Arrastrar desde el interior no produjo el mismo movimiento |
| FACTURA F25-1 | Agregar texto | Texto añadido en la copia | Interacción sobre la página |
| FACTURA F25-1 | Intro en un párrafo | No concluyente | El comportamiento de inserción/selección fue inesperado; no se acredita un párrafo multilínea correcto |
| FACTURA F25-1 | Agregar imagen | Insertada la imagen local de prueba del proyecto | `assets/icons/pdfmodder.png` |
| FACTURA F25-1 | Mover imagen | Desplazamiento mediante el borde | No se extrapola a cualquier imagen o máscara |
| FACTURA F25-1 | Voltear y girar imagen | Volteo horizontal y giro de 90° realizados | Interfaz de la copia |
| FACTURA F25-1 | Redimensionar y recortar imagen | No concluyente | Los arrastres probados no permiten acreditar el resultado final |
| ANEXO 09 | Guardar copia | Copia base guardada | `anexo-acrobat.pdf`; conserva el estado previo del usuario |
| ANEXO 09 | Girar página | Primera página girada a la derecha | Cambio en la sesión de la copia; guardado posterior pendiente |
| ANEXO 09 | Eliminar página | Eliminada la primera página; quedaron dos | Cambio en la sesión de la copia; guardado posterior pendiente |
| ANEXO 09 | Extraer página | Abierta una ventana independiente con una página extraída | Ventana «Páginas desdeanexo-acrobat.pdf»; guardado pendiente |
| ANEXO 09 | Editar texto natural | `2024` → `2026`, Times New Roman 12 pt negrita centrada; `responsable` → `representante`, Times New Roman 11,04 pt justificada | Copia `anexo-texto-acrobat.pdf` guardada |
| ANEXO 09 | Ampliar párrafo | El párrafo creció y se superpuso al primer elemento de la lista siguiente | Acrobat tampoco desplazó automáticamente los otros elementos |
| ANEXO 09 | Sustituir logotipo | Botón derecho → Reemplazar imagen, usando el icono del proyecto | Guardado en `anexo-texto-acrobat.pdf`; la imagen cuadrada conservó proporción y altura, reduciendo su anchura y quedando centrada |
| ANEXO 09 | Mover o ampliar el logotipo | No concluyente | Los arrastres probados no produjeron cambio verificable |
| MAPA biodiversidad | Editar cifras existentes | `2025` → `2026` con Myriad Hebrew 12 pt y `5,8177` → `6,8177` con Myriad Hebrew 11,04 pt | Operaciones realizadas en la copia de Acrobat |
| MAPA biodiversidad | Agregar y mover imagen | Inserción y movimiento arrastrando el borde realizados | No se extrapola a las demás imágenes del documento |
| MAPA biodiversidad | Recortar imagen | Arrastre del tirador superior central realizado | Recorte de la instancia seleccionada |
| MAPA biodiversidad | Dividir documento | 12 páginas divididas en seis archivos de dos páginas | `mapa-acrobat_ParteN.pdf` |
| CIRU multirresiduos con capa OCR | Agregar texto y pulsar Intro | Nuevo texto Minion Pro 12 pt; Intro conservó la primera línea y añadió la siguiente | La segunda línea larga se redistribuyó al ancho inicial del cuadro |
| CIRU multirresiduos con capa OCR | Ensanchar cuadro de texto | Tirador central derecho ensanchó y redistribuyó el texto a dos líneas conservando tamaño | Resultado de interacción observado; no acredita edición universal de la capa OCR original |
| CIRU multirresiduos con capa OCR | Insertar páginas | Se insertaron las dos páginas de `mapa-acrobat_Parte1.pdf` después de la primera | El documento pasó de una a tres páginas |
| CIRU multirresiduos con capa OCR | Recortar página | Dibujar rectángulo, doble clic y aceptar el diálogo de CropBox en milímetros | Aplicado a la segunda página de la copia |
| CIRU multirresiduos con capa OCR | Reemplazar página | Segunda página sustituida por la factura | El documento conservó tres páginas |
| Cuatro documentos | Combinar archivos | OCR 3 + mapa 12 + factura 1 + anexo 3 → 19 páginas | `combinado-cuatro-acrobat.pdf` guardado, aproximadamente 7,8 MB |
| ANEXO 09 | Exportar archivo a RTF | Exportar archivo → Formato RTF → Guardar | `anexo-texto-acrobat.rtf`, 782.656 bytes; se observaron opciones de texto fluido/presentación de página, imágenes, comentarios y OCR. No se ha validado la fidelidad del RTF ni los demás formatos Office. |

## Aspectos de interacción observados

La diferencia entre arrastrar dentro de un texto y arrastrar su borde importa:
el interior puede activar escritura o selección, mientras el borde permite mover
el cuadro. En los ensayos, el movimiento se inició aproximadamente dos píxeles
por fuera del borde; arrastrar desde el interior no produjo el mismo resultado.
PDF Modder distingue esos modos y expone controles de aceptación y cancelación.
La prueba de Intro fue concluyente en texto nuevo de CIRU; la primera prueba
sobre la factura sigue figurando como no concluyente.

Acrobat muestra para una imagen seleccionada controles de volteo horizontal y
vertical, giro a izquierda y derecha, recorte y sustitución. El menú contextual
también muestra eliminar recorte y organizar. La presencia de una entrada no
acredita haber probado cada transformación en cada documento.

El diálogo Rotar páginas presenta dirección (90 grados derecha, izquierda o
180 grados), intervalo o todas las páginas, filtro de pares/impares y filtro
de orientación vertical/horizontal. Estos controles motivan el diálogo directo
de rotación de PDF Modder, además del organizador visual.

El panel derecho reúne edición del contenido, formato y operaciones de páginas.
PDF Modder 1.5.0 utiliza una distribución familiar y pictogramas propios. Las
equivalencias de ubicación no acreditan equivalencia de motor, compatibilidad o
resultado de exportación.

## Incidencias del entorno de observación

Al transferir la prueba a un subagente, la enumeración de ventanas funcionó, pero
la primera solicitud de captura/selección de ventana devolvió:

> MCP elicitations can only be requested by the root thread.

No se emitieron acciones adicionales desde ese subagente tras el bloqueo. El
agente principal retomó el control y comunicó las observaciones posteriores
registradas en esta matriz. Esta incidencia no es un error de Acrobat ni de
PDF Modder.

## Cómo interpretar este registro

«Realizado» identifica una acción observada en una copia; «pendiente» indica que
no se ha comprobado; «no concluyente» conserva explícitamente la incertidumbre.
Las pruebas automatizadas del motor y de la interfaz de PDF Modder pertenecen a
otro nivel de validación y se documentan separadamente. No se cuentan como pruebas
manuales de Acrobat.
