# Verificación 0.9.0 — Windows 11 x64

La compatibilidad se acredita para cada operación probada, no para todos los PDF.
El original privado no se incluye en la entrega. Los ejemplos reproducibles están
en `examples` y sus generadores/pruebas, en el código correspondiente.

## Contraste independiente del motor

Ejecutado el 21 de septiembre de 2026 en Windows 11, PyMuPDF 1.26.7:
**8 de 8 casos aprobados**, 14,317 segundos en este equipo.

- Ejemplo digital: fecha, formato parcial y párrafos con tabulación/salto suave.
- Factura aportada: sustitución de ESPAÑA, cambio de fecha, salto de línea,
  formato parcial y ampliación del concepto de producto.

Se contrastaron extracción con pypdf y render con Poppler a 144 ppp. La extracción
simple puede insertar espacios heurísticos entre tramos de formato; también se
contrastó el modo layout, que conservó la fecha exacta. No se confundieron esas
heurísticas con una pérdida de caracteres.

Fuera de las pequeñas regiones por glifo de origen/destino hubo **0 píxeles con
desviación superior a 8/255 por canal**. Las regiones excluidas ocuparon entre
0,074 % y 0,715 % de la página; se incluyen contornos tipográficos verificados
cuando la tinta de la Ñ rebasa la caja métrica. La tolerancia permite diferencias
de redondeo del render sin excluir bloques completos. Se comprobaron también
vecinos, páginas de control y huellas de los originales.

Informe local: `tmp/acceptance-v09-final-20260921/report.json`. Es privado y no se
redistribuye porque contiene resultados de la factura. Este contraste se puede
repetir con `scripts/acceptance_v09.py` y los documentos disponibles localmente.

## Batería y ejecutable

La batería final de código e interfaz aprobó **581 pruebas de 581** en **143,61 s**,
sin errores ni pruebas omitidas. Incluye edición rica, borrado completo, campos
estrechos, movimiento de subrayados, grupos, imágenes compartidas, cancelación
durante la validación, deshacer/rehacer, guardado/reapertura y rutas anteriores.
Informe local: `output/pytest-v09-results.xml`.

El ejecutable final de Windows aprobó **5 recorridos y 95 pasos**:

| Recorrido | Pasos | Segundos |
|---|---:|---:|
| Edición y herramientas anteriores | 17 | 11,278 |
| Documento etiquetado | 16 | 2,440 |
| Recortes PDF | 25 | 4,205 |
| Herramientas 0.8 y OCR | 23 | 4,306 |
| Editor 0.9 | 14 | 6,340 |

Se usó un directorio de trabajo vacío, PATH limitado a Windows y sin variables
heredadas de Python/Qt. El SHA-256 del EXE permaneció idéntico durante las pruebas:
`09eb7b5279500cf5f1b2ef2867367d9432fab57b43bc79f6703bfc171142d7f3`.
Informe local: `output/packaged-verification.json`.

Los resultados finales de la batería, los recorridos del ejecutable y la prueba
de instalación se registran en la entrega junto al SHA-256 del binario exacto.
`ENTREGA.json` acredita el ejecutable portable; `INSTALADOR.json` y el informe
de instalación acreditan el instalador. Un informe de código fuente por sí solo
no acredita el ejecutable.

## Límites conocidos

- Editor rico para texto horizontal y recursos verificables; páginas giradas y
  CropBox se transforman explícitamente. Recortes arbitrarios, recursos ambiguos
  o una fuente sin caracteres necesarios pueden bloquear una operación.
- OCR y documentos etiquetados siguen la ruta conservadora específica anterior.
- Qt ofrece el borrador interactivo; el render PDF muestra el resultado final.
  La identidad tipográfica depende del programa de fuente verificado, no del nombre.
- Subrayado semitransparente no admitido; otras propiedades compatibles se conservan.
- Unir/dividir usa fragmentos elegidos explícitamente. Los grupos propios no son
  una estructura accesible ni objetos equivalentes a párrafos de Word.
- Orden delante/detrás limitado a ámbitos gráficos completos y aislables.
  Movimiento/alineación de un lote falla íntegro si algún miembro no se puede aislar.
- Copiar formato requiere la misma página/revisión; se comprueban los caracteres nuevos.
- Recorte de imagen reversible; no elimina los píxeles ocultos del archivo.
- No se ha probado esta versión en otro equipo físico. La prueba de paquete utiliza
  rutas independientes y un entorno sin Python/Qt del desarrollo en PATH.
