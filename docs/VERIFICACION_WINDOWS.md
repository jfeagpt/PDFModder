# Verificación en Windows de PDF Modder 0.8.0

La compilación Windows 11 x64 de 0.8 se generó con PyInstaller 6.18.0 y Python 3.12.10. **Comprobación final completada:** el ejecutable entregado pasó los cuatro recorridos completos, sin recompilar ni modificar su contenido. SHA-256: `f981ccec0c1939139de5bfb8a7b0559045af77a2b4036361f2676d01a1f37cea`. La distribución portable contiene ese mismo ejecutable y las DLL de Qt reemplazables.

| Recorrido sobre PDFModder.exe | Pasos aprobados | Duración | Páginas finales |
|---|---:|---:|---:|
| Texto nuevo, movimiento, imágenes, extracción, eliminación y combinación | 17 | 12,920 s | 3 |
| Texto etiquetado, estructura accesible, doble clic e historial | 16 | 4,331 s | 2 |
| Campos recortados, longitud variable, vecinos y dos guardados | 12 | 2,826 s | 2 |
| OCR, reemplazos revisados, imágenes, párrafo y organizador | 23 | 6,522 s | 4 |

Los 68 pasos finalizaron con `ok: true`, `frozen: true`, versión 0.8.0 y la misma huella del ejecutable. Los recorridos guardaron y reabrieron sus PDFs, comprobaron contenido, geometría, recursos y apariencia, y conservaron sus originales. Se revisaron además las cuatro capturas de ventana; son evidencia complementaria, no sustituyen la validación del PDF. El tiempo total de esos recorridos fue 26,599 s. Son medidas del corpus sintético en este equipo; no acreditan todos los PDFs posibles.

Evidencia disponible de la integración 0.8:

- 416 pruebas de motor e interfaz aprobadas en 106,76 s, sin fallos, errores ni pruebas omitidas. Incluyen las siete regresiones del último ajuste de anchura nativa.
- Recorrido desde código: 23 pasos, cinco validaciones del motor, 10,085 s. Guarda y reabre OCR, coincidencias elegidas, imágenes, párrafo y cuatro páginas organizadas.
- Después del ajuste nativo, prueba privada con ratón: ocho campos de factura, cancelación, historial, guardado y reapertura; aprobada en 16,80 s. Los archivos privados no se distribuyen.
- Aceptación sintética independiente con Poppler: 4,649 s; cero diferencias fuera de los glifos y la única imagen editados; control de página completa, OCR buscable y páginas reorganizadas idénticos.
- La entrega inicial con verificación pendiente se conserva por separado en `releases/v0.8-sin-verificar-20260911/`. Sus avisos describen aquel estado histórico. El paquete actualizado de `releases/v0.8/` contiene los informes finales.

`ENTREGA.json` vincula el SHA-256 del ejecutable con este estado verificado. `COMPROBACIONES/` incluye `pytest-results.xml`, los cuatro `packaged-*-smoke.json`, sus capturas y PDFs, y la evidencia independiente. Se han actualizado `ESTADO.txt` y `LEEME-INICIO.txt` para reflejar la comprobación completada. Las dependencias y el ejecutable permanecen iguales a los probados.

Para repetir: ejecute `.venv/Scripts/python.exe -m pytest --junitxml output/pytest-results.xml` y `powershell -ExecutionPolicy Bypass -File scripts/verify_executable.ps1`. El script lanza secuencialmente los cuatro recorridos, exige informes nuevos y comprueba la huella de cada ejecución. Refresque licencias/fuentes con `scripts/collect_licenses.py` y cierre con `scripts/package_release.py`, que exige los resultados aprobados y comprueba la correspondencia entre fuentes y compilación.

## Histórico: verificación de PDF Modder 0.5.0

Las cifras, SHA-256 y nombres de informes que siguen describen la versión histórica 0.5.0. No corresponden al paquete 0.8 ni deben interpretarse como los informes actuales con esos mismos nombres.

Entorno ejecutado: Windows 11 x64, compilación 26200; CPython 3.12.10 x64; PySide6 6.10.2 y PyMuPDF 1.26.7. Se utilizaron procesos nativos de Windows para la interfaz y el motor. No se presenta una compilación Linux como ejecutable Windows.

La batería pública final de la versión **0.5.0** obtuvo **284 pruebas aprobadas en 51,55 segundos**. Incluye el motor, fuentes, integridad, estructuras accesibles y la interfaz Qt. Son medidas de estas ejecuciones en este equipo, sin garantía de rendimiento para otros PDFs.

Las tres comprobaciones del **ejecutable Windows 0.5.0** se ejecutaron después de la compilación y pasaron con `ok: true`, `frozen: true` y el mismo SHA-256: `48913418f636d4237661ab5d092e1702e0ca966365c4f440afa5e88b0caa545e`.

| Recorrido congelado | Informe | Resultado y duración de 0.5.0 |
|---|---|---|
| Ampliado: texto, imágenes y páginas | `output/packaged-extended-smoke.json` | 17 pasos aprobados; 6,975 s; 3 páginas |
| Etiquetado: edición y estructura accesible | `output/packaged-tagged-smoke.json` | 16 pasos aprobados; 2,188 s; 2 páginas |
| Recortado: sustitución de longitud variable y vecinos fijos | `output/packaged-clipped-smoke.json` | 12 pasos aprobados; 1,650 s; 2 páginas |

El recorrido recortado guarda y reabre SOL→ESTRELLA, vuelve a SOL, comprueba deshacer/rehacer exactos y guarda una segunda copia. Las fuentes, los vecinos y la página de control permanecen intactos. La prueba correspondiente desde código también pasó, en 2,048 s. Las capturas de ventana son evidencia complementaria, no la prueba de integridad del PDF.

## Evidencia disponible

- `output/pytest-results.xml`: resultados de las pruebas automatizadas del motor, fuentes, integridad e interacción Qt. Incluyen escritura sobre la página, arrastre real con ratón, deshacer/rehacer, guardado, reapertura y otra edición; también Escape, imposibilidad de sobrescribir el original y conservación del estado tras fallar el guardado.
- Las pruebas Qt incluyen el diálogo de composición por eventos de ratón y teclado, arrastre y tamaño de imagen, flechas, historial y páginas. La versión 0.3 añade doble clic sobre palabra, línea y sus espacios, escritura durante la carga de miniaturas, Escape y dos sustituciones justificadas encadenadas con guardado y reapertura entre ellas. Se comprueba que seleccionar una línea recupera todos sus fragmentos después de ampliar los espacios.
- `output/vertical/report.json`: primera operación vertical, ejecutada antes de completar la interfaz.
- `output/acceptance/report.json`: cuatro operaciones encadenadas, escritura completa, reapertura, extracción independiente con pypdf y comparación visual independiente con Poppler 26.07.0. El informe resumido está en `RESULTADOS_CORPUS.md`.
- `output/corpus-qa/`: renderizado y hoja de contacto de los ejemplos definitivos.
- `output/packaged-extended-smoke.json`, `output/packaged-tagged-smoke.json` y `output/packaged-clipped-smoke.json`: los tres informes del ejecutable congelado, vinculados a la versión 0.5.0 y al SHA-256 actual. Los informes anteriores `extended-smoke.json` y `packaged-smoke.json` se conservan como evidencia histórica y no acreditan esta compilación.
- `output/acceptance-extensions/report.json`: comparación independiente de composición e imágenes y de páginas extraídas/combinadas, generada por `scripts/acceptance_extensions.py`.
- `output/acceptance-tagged/report.json`: fecha con ActualText, sustitución justificada y movimiento, guardado/reapertura, auditoría de estructura y renderizado independiente con Poppler.

La aceptación independiente del flujo de texto se repitió durante la integración de la versión 0.4 y tardó **4,001 segundos** para las cuatro operaciones y sus comprobaciones. A 144 ppp, el máximo cambio fuera de las cajas individuales de los caracteres modificados fue **0/255** en ambas páginas. La primera página excluye el 1,629973 % de sus píxeles, correspondiente a los caracteres de origen/destino más 0,75 pt; la segunda no excluye ningún píxel. También se verifican por separado los caracteres vecinos dentro de esas regiones.

La aceptación independiente ampliada registrada en la integración anterior pasó en **4,546 segundos** con Poppler 26.07.0. Añadió 41 caracteres en LiberationSans-Bold a 13,25 pt y color explícito, incorporó una imagen de 80 × 60 píxeles, la movió y redimensionó, extrajo la página 2, la eliminó y la volvió a combinar. Los 473 caracteres originales de la primera página conservan su texto y formato; los píxeles RGB de la imagen final coinciden con el PNG generado. Se guardó y reabrió el PDF, y la fuente original conservó su SHA-256.

| Comparación con Poppler a 144 ppp | Píxeles comprobados | Excluidos | Máximo cambio fuera de máscara |
|---|---:|---:|---:|
| Página 1 original frente a final | 1.968.084 | 1,790255 % | 0/255 |
| Página 2 original frente a final | 2.003.960 | 0 % | 0/255 |
| Página 2 original frente a PDF extraído | 2.003.960 | 0 % | 0/255 |

La primera comparación excluye únicamente los caracteres nuevos individuales y el rectángulo final de la imagen, con margen de 0,75 pt. No excluye sus posiciones intermedias: se comprueba que la imagen desaparezca de ellas. El texto también se contrasta mediante extracción con pypdf. Como pypdf interviene en la copia de páginas, Poppler aporta la comparación visual independiente de toda la cadena.

La aceptación etiquetada registrada en la integración anterior pasó en **2,093 segundos**. Actualizó `Fecha: 10/09/2026` a `Fecha: 11/09/2026` junto con su ActualText, sustituyó PALABRA por VOZ justificando la línea y movió VOZ 20 puntos hacia abajo. El recurso ActualText obsoleto desapareció; las relaciones MCID, ParentTree y el orden de lectura se conservaron. La página 1 comprobó **698.459 píxeles**, excluyó sólo **1,012046 %** por caracteres realmente cambiados o movidos y obtuvo **0/255** de diferencia exterior. La página 2 comprobó sus **705.600 píxeles sin exclusiones**, con identidad exacta. Se conservaron el texto vecino, la figura y su Alt y el original.

Las regresiones de etiquetado cubren referencias directas y MCR, propiedades nombradas, OBJR, estilos diferentes, orden de pintado distinto del lógico, ActualText y Alt. Se comprueba el bloqueo de estructuras incoherentes, atributos de disposición y ámbitos marcados anidados —incluidos ReversedChars y marcadores desconocidos— que no pueden reconstruirse sin alterar su significado. Un ámbito incompatible no impide mover un MCID independiente compatible. No se certifica PDF/UA ni la interpretación de todos los lectores de pantalla.

## Pruebas privadas y regresiones de 0.4 y 0.5

Se probó además un PDF real de una página, 42 operadores de recorte, 5.414 caracteres y nueve imágenes. La fecha elegida no tenía OCR invisible superpuesto. Se sustituyó una cifra conservando el recurso incrustado, su SHA-256, codificación, tamaño, posiciones y todos los demás caracteres. La extracción con pypdf identificó un único operador de texto modificado. La comparación con Poppler a 144 ppp comprobó 2.006.475 píxeles, excluyó sólo 360 (0,017939 %, caja de esa cifra con margen de 0,75 pt) y obtuvo 0/255 de diferencia exterior. El original y la capa OCR ajena a esa selección conservaron su contenido. La ejecución final de esta comprobación tardó 3,123 segundos.

En ese mismo PDF, cinco operaciones de imágenes (agregar, mover, redimensionar, eliminar y mover una instancia existente) pasaron en 4,919 segundos. Los 5.414 caracteres permanecieron intactos; Poppler obtuvo cero diferencias fuera de las regiones concretas de imagen. Eliminar la imagen añadida restauró la página sin diferencias de píxeles. Las nueve instancias originales pudieron aislarse bajo una matriz global de escala.

Dos pruebas privadas completas de interfaz pasaron en 10,94 segundos: doble clic, escritura, botones visibles de previsualización/aplicación, inspector de fuente, guardado y reapertura de la fecha; y arrastre, tirador de tamaño, deshacer, imagen nueva, aplicar, guardar y reabrir. Se verificó también que la fecha permanece visible durante la previsualización. Estas pruebas Qt se ejecutaron desde código en Windows; los recorridos congelados se ejecutan con ejemplos sintéticos. No se confunden ambas evidencias.

Las regresiones públicas cubren fuentes directas sin xref, discriminación por recurso, códigos que no deben tomarse de otra fuente, lectura de huella aunque tamaño y fechas del archivo se conserven, OCR superpuesto, Tr4 usado como recorte, matrices heredadas y clips rectangulares/parciales. La versión 0.5.0 amplía la ruta de texto recortado para sustituir fragmentos de **distinta longitud** mediante operadores `Tj`/`TJ` interpretados: mantiene fuente, tamaño y escala, recompone los avances del fragmento y compensa el cursor PDF para conservar fijos los vecinos. No justifica automáticamente un campo recortado ni distribuye el cambio por el resto de la línea. Se mantienen los controles de códigos disponibles, espacio, recortes, contenido y apariencia. Véase [EDICION_CON_RECORTES.md](EDICION_CON_RECORTES.md).

Un **segundo PDF real privado**, una factura de una página, permitió comprobar 16 operaciones encadenadas. Incluyeron cambios de distinta longitud en destinatario, dirección y concepto, además de fechas, identificador e importes seleccionados explícitamente. Se conservaron las fuentes incrustadas y sus recursos, incluida la huella SHA-256 del programa, y se compensó el cursor para mantener fijos los vecinos. Los importes de demostración se calcularon fuera de la aplicación: el editor no recalcula una factura automáticamente.

El flujo de la factura, con guardado, reapertura, extracción con pypdf y comparación independiente con Poppler, pasó en **11,206 segundos**. Se comprobaron **1.977.594 píxeles** y se excluyeron **26.366 (1,315695 %)**, correspondientes a las regiones individuales de caracteres cambiados con el margen técnico. La diferencia máxima exterior fue **0/255**. Los caracteres vecinos se validaron también por contenido y posición. Una prueba Qt privada de esta factura pasó en **7,15 segundos**; se suma a las dos pruebas privadas anteriores de 10,94 segundos, sin presentarlas como pruebas del ejecutable congelado.

El ejemplo público `examples/recortado.pdf` reproduce un campo con recorte, una palabra para alargar, vecinos que deben permanecer fijos y una segunda página intacta, sin datos de ninguno de los documentos privados. El recorrido `--smoke-clipped` verificó su flujo desde la aplicación 0.5.0 compilada, con las medidas indicadas al principio.

Los dos PDFs reales, sus datos comerciales, capturas, rutas e informes detallados permanecen fuera del paquete distribuible. Las pruebas públicas no dependen de esos archivos. La comparación en una región concreta no acredita compatibilidad de todas las demás regiones del mismo documento.

## Repetir las comprobaciones

```powershell
.venv\Scripts\python.exe -m pytest -q --junitxml output\pytest-results.xml
.venv\Scripts\python.exe scripts\acceptance_report.py
.venv\Scripts\python.exe scripts\acceptance_extensions.py
.venv\Scripts\python.exe scripts\acceptance_tagged.py
.venv\Scripts\python.exe scripts\generate_clipped_example.py
.venv\Scripts\python.exe run_pdfmodder.py --smoke-extended output\extended-smoke.json
.venv\Scripts\python.exe run_pdfmodder.py --smoke-clipped output\clipped-smoke.json
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
dist\PDFModder\PDFModder.exe --smoke-extended output\packaged-extended-smoke.json
dist\PDFModder\PDFModder.exe --smoke-tagged output\packaged-tagged-smoke.json
dist\PDFModder\PDFModder.exe --smoke-clipped output\packaged-clipped-smoke.json
.venv\Scripts\python.exe scripts\collect_licenses.py
.venv\Scripts\python.exe scripts\package_release.py
```

Los modos `--smoke-test`, `--smoke-extended`, `--smoke-tagged` y `--smoke-clipped` son comprobaciones de entrega con los ejemplos sintéticos incluidos; utilizan el proceso y los métodos de la aplicación. El modo etiquetado también envía eventos Qt de doble clic y escritura sin depender de QtTest en el ejecutable. El procedimiento conserva el PDF de ejemplo y escribe copias junto al informe. El modo ampliado termina con un PDF de tres páginas y una imagen que sigue siendo editable al reabrir. El modo recortado cubre la sustitución de distinta longitud y la conservación de vecinos. El uso normal no ejecuta estas pruebas ni necesita Poppler, pytest o acceso a Internet.

La entrega 0.5.0 exige pruebas aprobadas y **tres controles de aceptación del paquete**: los recorridos congelados ampliado, etiquetado y recortado completos, vinculados al mismo SHA-256 y versión del ejecutable. `package_release.py` verifica que el código de aplicación no haya cambiado desde la compilación probada, incluye licencias/fuentes/evidencias, valida todos los CRC del ZIP y escribe su SHA-256. La documentación y los informes se actualizan después de medir la entrega; la implementación y el ejecutable probado no se alteran.

## Alcance pendiente

Se han proporcionado y comprobado **dos PDFs reales** dentro del alcance descrito más arriba. Siguen pendientes otros exportadores, fuentes y regiones incompatibles, además de medidas con documentos grandes. La versión admite edición de texto etiquetado dentro del alcance documentado y bloquea las estructuras incompatibles. Todavía no crea etiquetas para texto o imágenes nuevos ni las remapea al eliminar, extraer o combinar páginas: estas herramientas se deshabilitan al abrir un PDF etiquetado. También se bloquean formularios, cifrado/restricciones, firmas, Form XObjects, fuentes no reproducibles y regiones cuya modificación no pueda aislarse. No se ha certificado PDF/A, PDF/UA ni la validez criptográfica de firmas; el ejemplo de firma es un marcador inválido para probar su detección.

El paquete portable conserva sus DLL y recursos junto al ejecutable. Su arranque comprobado no sustituye una prueba de instalación en todas las configuraciones de Windows, monitores y controladores gráficos. No tiene firma de editor comercial ni instalador con registro en el sistema.

Durante la construcción se limita `PATH` al entorno Python y Windows, y se rechaza cualquier DLL ajena a esos directorios. Esto evita incorporar versiones incompatibles de ICU o de otras bibliotecas procedentes de herramientas de desarrollo instaladas junto a la aplicación. Qt utiliza la ICU de Windows 11.
