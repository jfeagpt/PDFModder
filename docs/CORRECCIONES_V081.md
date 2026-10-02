# Correcciones y verificación de PDF Modder 0.8.1

Esta revisión corrige bloqueos de edición y movimiento en PDFs digitales compatibles. Mantiene la conservación estricta de fuentes, recortes, vecinos y recursos compartidos; no declara compatibilidad universal. Los documentos privados utilizados para verificarla no forman parte del repositorio ni del paquete.

## Tres mensajes que motivaron la revisión

- **«La línea mezcla líneas base distintas»**: algunos exportadores colocan letras de una misma línea con diferencias pequeñas de altura. Se acepta esa variación únicamente si la selección pertenece a una línea y un tramo coherentes, con la misma fuente y tamaño, y geometría y secuencia de pintura verificables. El límite adicional es el menor entre 0,3 puntos y el 4 % del tamaño de letra. Se conservan las alturas originales de los caracteres no afectados; no se fusionan filas ni columnas próximas.
- **«Faltan códigos únicos en la fuente original»**: observar las letras ya usadas no proporciona el catálogo completo de una fuente. Ahora se consulta su codificación PDF declarada y se prueba el glifo en el recurso exacto antes de reutilizar el código. Un carácter realmente ausente o ambiguo continúa bloqueado y el mensaje identifica cuál falta. No se sustituye la fuente por otra parecida.
- **«Texto recortado… sólo se pueden sustituir caracteres conservando su cantidad y avances»** al mover: se incorpora movimiento nativo de los fragmentos compatibles, conservando códigos, avances y recursos. La traslación se aplica mediante `q / cm / TJ / Q`; el recorte original permanece fijo y el cursor del contenido posterior conserva su avance. Se comprueban las coordenadas serializadas, incluidas fracciones de punto, y la extracción del texto trasladado.

También se conserva la anchura automática para sustituciones compatibles sin modificar el tamaño ni comprimir las letras. La previsualización y el guardado utilizan el PDF realmente modificado.

## Aceptación del motor con un documento real

Prueba privada realizada el 16 de septiembre de 2026 sobre una factura digital de una página:

- **17 operaciones individuales correctas**: sustituciones de fecha, número, cliente, direcciones, importes y concepto; ampliación de texto, anclaje derecho y movimientos de palabra y línea, incluidos desplazamientos fraccionarios.
- **Ocho operaciones encadenadas correctas**: sustituciones, ampliación de concepto, movimiento, cambio de importe, guardado, reapertura y nueva edición de una fecha. Son una comprobación adicional de secuencia; no se suman a una cifra de compatibilidad general.
- Las copias reabiertas conservan el texto esperado según **pypdf y pdfminer**. Se verificaron al menos 2375 caracteres vecinos por operación individual. La prueba no recalcula importes contables ni acredita la validez de los valores de demostración.
- **Poppler a 144 ppp** comparó origen y resultado con los mismos parámetros. Se excluyeron únicamente las pequeñas cajas de los caracteres de origen y destino, con margen de 0,75 puntos para el antialiasing; la máscara mayor cubrió el **0,322761 %** de la página. El resultado medido fue **cero píxeles diferentes fuera de las máscaras**, aunque el validador permite una diferencia máxima de ocho niveles por canal. También se verificaron los caracteres vecinos dentro de las regiones afectadas.
- Se comprobó que los bytes del archivo original permanecieran intactos. Los PDFs, capturas y resultados con información privada se guardan fuera del material distribuible.

## Límites comprobados

En la misma batería se mantuvieron cuatro bloqueos explícitos, sin incorporar la operación al documento:

1. Un carácter acentuado que no tenía código y glifo verificables en la fuente parcial del campo.
2. Un emoji ausente del recurso original.
3. Una ampliación de texto que atravesaba varios operadores PDF; esta ruta de longitud variable requiere un fragmento aislable de un solo operador.
4. Un movimiento corto que solapaba un carácter vecino. El mismo fragmento pudo moverse a una posición libre.

Los recortes complejos o no verificables, el texto originalmente cortado, los destinos fuera del recorte y la combinación de esta ruta con etiquetas accesibles siguen teniendo bloqueos específicos. La mejora de pequeñas diferencias de línea base no elimina esas restricciones. Un cambio explícito de tipografía tampoco garantiza que pueda reconstruirse una región incompatible.

## Estado de las comprobaciones de entrega

La aceptación del motor descrita arriba está completada. La suite completa de 0.8.1 obtuvo **454 pruebas aprobadas en 84,44 s** en Windows. El recorrido ampliado de recortes obtuvo **19 pasos aprobados en 2,95 s desde el código**. Son medidas de este entorno y corpus, no una garantía de rendimiento general.

**Ejecutable Windows 11 x64 comprobado el 16 de septiembre de 2026:** cuatro recorridos, 75 pasos aprobados, todos con `ok: true`, `frozen: true`, versión 0.8.1 y la misma huella SHA-256:
`a74740179f647f76603c66c50ebb7dbe052bb50df951514655d470e75e12a860`.

| Recorrido del ejecutable | Pasos | Segundos |
| --- | ---: | ---: |
| Texto, imágenes y operaciones de páginas | 17 | 7,361 |
| PDF etiquetado y orden lógico | 16 | 2,468 |
| Recortes, caracteres nuevos, movimiento, historial y reapertura | 19 | 2,245 |
| OCR, reemplazos revisados, imágenes, párrafos y organización | 23 | 4,155 |

El total observado es 16,229 s. Las aceptaciones independientes de herramientas 0.8 y PDF etiquetado también se repitieron con Poppler y terminaron verificadas en 4,449 y 1,666 s. Estos resultados corresponden a este equipo y corpus. No se ha probado la revisión en el ordenador remoto del usuario.

El estado de instalación se registra por separado en `releases/v0.8.1/INSTALADOR.json`, vinculado al SHA-256 exacto del instalador. El constructor lo inicia con `tested: false`; sólo pasa a `true` tras verificar la copia de archivos, reparación, rechazos seguros, ejecución del editor instalado y ventana del instalador. Esta documentación incluida en el paquete no contiene su propia huella circular; los informes externos identifican el archivo final.

Como referencia histórica, **0.8.0** completó 416 pruebas automatizadas y 68 pasos sobre su ejecutable. Esas cifras corresponden a aquel paquete y no se presentan como resultados de 0.8.1.

Para el flujo de edición y los límites técnicos, consulte [edición con recortes](EDICION_CON_RECORTES.md). Las APIs se contrastan con [ContentStream de pypdf](https://pypdf.readthedocs.io/en/6.6.0/modules/generic.html) y [páginas de PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html).
