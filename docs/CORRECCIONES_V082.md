# Edición de campos fragmentados, párrafos y movimientos — 0.8.2

Esta revisión amplía la edición nativa de PDF Modder. Las versiones 0.8 y 0.8.1 se conservan en carpetas independientes. La compatibilidad se valida por operación; no se garantiza cualquier fuente, recorte o exportador.

## Cómo editar

1. Seleccione la palabra, línea o bloque y haga doble clic.
2. Escriba. **Intro** introduce una línea y activa su composición. **Ajustar altura al texto** está activado inicialmente: mantiene la anchura de la selección y deja crecer su altura sin reducir letras. También adapta la altura al cambiar el formato. Puede modificar la anchura, el interlineado y la separación de párrafos en Propiedades. Si una palabra no cabe en esa anchura, debe ampliarla.
3. Pulse **Ctrl+Intro / Ver vista previa**. La imagen mostrada procede del PDF modificado. **Aplicar cambio** incorpora el resultado al historial; **Esc** lo descarta.
4. **Guardar como** crea una copia; el original permanece intacto.

Para colocar texto encima de otro, active **Permitir superponer texto** antes de arrastrar o usar las coordenadas. El texto vecino conserva sus caracteres, formato y posición. La opción no autoriza perder texto ni salir de la página, ni atravesar enlaces o elementos cuyo comportamiento no se pueda conservar. Revise la legibilidad; Deshacer recupera el estado exacto anterior.

## Fuentes y caracteres adicionales

La ruta consulta primero los códigos y glifos del recurso original. Si falta un código PDF pero el programa TrueType incrustado contiene el carácter Unicode, crea un recurso local con un mapa de códigos nuevo. Conserva los contornos, métricas y programas de glifo; no modifica el recurso compartido original ni otras páginas.

Si el glifo no existe en el subconjunto, abra **Tipografía / formato…**, active **Cambiar la fuente explícitamente** y elija la variante completa instalada o un archivo compatible. La vista previa indica el cambio de fuente. Esto permite escribir caracteres adicionales sin presentar una sustitución como identidad tipográfica.

El diálogo también permite tamaño fraccionario y color RGB en la composición nativa compatible. La línea base original se conserva; el interlineado y la anchura se calculan con el tamaño elegido. Negrita y cursiva requieren elegir su variante real. El cambio de formato no desplaza los vecinos.

En la factura privada utilizada para comprobar la aplicación, el subconjunto Arial no incluye la Í. El Arial instalado tiene una versión diferente. No se presume identidad a partir del nombre. No se incluyen esa factura ni las fuentes comerciales del sistema en la distribución.

## Integridad de la composición nativa

El parser identifica los operadores que pintan los caracteres seleccionados, incluso cuando el campo está fragmentado entre varios `Tj/TJ`. Se retiran esos códigos y se compensa su avance; las nuevas líneas se insertan con transformaciones locales y se restaura el cursor para conservar los siguientes operadores. No se usan rectángulos blancos, contenido invisible ni imágenes de la página.

Se mantienen las restricciones sobre recortes complejos, transformaciones no admitidas, estilos mezclados y combinación de esta ruta con etiquetas accesibles cuya semántica no se pueda actualizar. La ampliación no elimina todos los bloqueos de integridad. Las fuentes adicionales de esta ruta requieren contornos TrueType estáticos o una fuente estándar compatible; una fuente OTF/CFF necesita otra ruta de codificación.

El fallo de pocos píxeles al mover «ESPAÑA» se debía a que la tilde de la Ñ sobresalía de su caja tipográfica declarada. La validación puede incorporar el contorno real verificado de ese glifo TrueType. Mantiene el umbral de 8/255 a 144 ppp y el margen antialias de 0,75 puntos; no excluye toda la cabecera ni aumenta globalmente la tolerancia.

## Reproducir las comprobaciones

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv\Scripts\python.exe -m pytest --junitxml output/pytest-results.xml
.venv\Scripts\python.exe run_pdfmodder.py --smoke-clipped output/source-v082-clipped.json
powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipTests
powershell -ExecutionPolicy Bypass -File scripts/verify_executable.ps1
```

Los informes del motor, la factura privada y el ejecutable se distinguen: las pruebas de código no acreditan por sí solas el instalador final. Los recuentos y huellas finales se registran en `ENTREGA.json`, `VERSION.json` e `INSTALADOR.json` de la entrega.

El 16 de septiembre de 2026, en Windows 11 x64, la batería completa aprobó **498 pruebas en 103,70 segundos**. Incluye el diálogo Qt real con cambio de variante y tamaño, Intro, vista previa, guardado y reapertura; los controles de altura fija siguen detectando desbordamiento.

La aceptación privada de la factura comprobó **nueve casos** con extracción independiente pypdf/pdfminer y renderizado Poppler: cabecera superior ampliada, cabecera en dos líneas, dos composiciones del concepto y cinco movimientos de «ESPAÑA». Todos conservaron los caracteres vecinos y obtuvieron cero diferencias fuera de las pequeñas regiones verificadas. Un desplazamiento de 15 puntos reprodujo exactamente el error anterior de seis píxeles. El original conservó su SHA-256.

Otra prueba de diez ediciones consecutivas con una fuente completa y espaciado explícito midió un residuo constante de 0,0002594 puntos, sin acumulación; la página compartida permaneció idéntica y Poppler no detectó diferencias ajenas. Estos resultados corresponden al corpus medido, no son una garantía universal de precisión.

Se intentó iniciar el control de Acrobat con la habilidad computer-use y reiniciar su sesión. El componente devolvió «failed to write kernel assets: el sistema no puede encontrar la ruta especificada». No se realizaron ni se acreditan acciones de edición en Acrobat.

Referencias técnicas: [objetos y operadores pypdf 6.6](https://pypdf.readthedocs.io/en/6.6.0/modules/generic.html), [fuentes PyMuPDF](https://pymupdf.readthedocs.io/en/latest/font.html), [recursos de página PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html). Las versiones instaladas y fijadas en dependencias se comprueban con las pruebas locales.
