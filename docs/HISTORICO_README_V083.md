# PDF Modder 0.8.3

**0.8.3 incorpora un desinstalador integrado**, registro en Aplicaciones instaladas de Windows y un acceso en el menú Inicio. Conserva documentos y archivos ajenos al inventario del programa. Consulte [instalación y desinstalación de 0.8.3](docs/DESINSTALACION_V083.md). Las pruebas históricas siguientes corresponden a sus versiones respectivas.

**0.8.2 añade composición de campos fragmentados, nuevas líneas y solapamiento explícito de texto.** Consulte la [guía de 0.8.2](docs/CORRECCIONES_V082.md) para los nuevos controles, fuentes y límites. El instalador de esta versión se llama `PDFModder-v0.8.2-Instalar.exe`. Comprueba todos sus archivos y conserva una copia de instalaciones anteriores reconocidas. No necesita instalar Python. Como alternativa, extraiga todo el ZIP portable y conserve `_internal` junto a `PDFModder.exe`. La [guía de instalación](docs/INSTALACION_WINDOWS.md) explica el instalador y el mensaje de dependencia Shiboken ausente. Consulte [correcciones y verificación de 0.8.1](docs/CORRECCIONES_V081.md) para distinguir las pruebas del motor de la comprobación del paquete final.

**Comprobación de 0.8.2:** 498 pruebas aprobadas en 103,70 s y cuatro recorridos sobre el EXE Windows final con 81 pasos aprobados en 23,10 s. Se verificaron nueve casos de la factura privada con extractores independientes y Poppler. Consulte la [guía de 0.8.2](docs/CORRECCIONES_V082.md) y los manifiestos de entrega para resultados y límites.

La ampliación incorpora búsqueda y reemplazo con revisión, anchura automática, párrafos sencillos, selección de elementos superpuestos, corrección de OCR existente, exportación/recorte/giro/reemplazo de imágenes y un organizador de páginas. La [guía de las nueve funciones](docs/GUIA_V08.md) explica los controles y sus límites.

**Evidencia histórica de 0.8.1:** 454 pruebas aprobadas en 84,44 s y cuatro recorridos sobre el ejecutable Windows final con **75 pasos aprobados en 16,229 s**. La aceptación con una factura privada añade 17 operaciones individuales y una secuencia de ocho cambios, con guardado, reapertura, extracción mediante pypdf y pdfminer y comparación visual con Poppler: ningún píxel alterado fuera de los caracteres afectados. Cuatro operaciones incompatibles se bloquearon con motivos concretos. `ENTREGA.json` identifica el ejecutable probado y `releases/v0.8.1/INSTALADOR.json` registra la comprobación del instalador exacto; no se promete compatibilidad universal.

**Evidencia histórica de 0.8.0:** 416 pruebas automatizadas y 68 pasos sobre su ejecutable Windows final. Los cuatro recorridos comprobaron texto, OCR, imágenes, párrafos, páginas, documentos etiquetados, historial, guardado y reapertura. Los archivos de comprobación y sus huellas SHA-256 acreditan ese paquete, no el de 0.8.1.

La versión **0.7 permanece archivada e independiente** en `releases/v0.7/`: programa Windows, código, huellas SHA-256 y `VERSION.json`. Fue una versión de conservación de las funciones verificadas de 0.5. Sus comprobaciones históricas mantienen su versión original; no acreditan el paquete nuevo de 0.8. Extraiga cada versión en una carpeta distinta y conserve su propia carpeta `_internal`.

Editor local de PDF para Windows 11 x64, en español: corregir y añadir texto, trabajar con imágenes compatibles y organizar páginas. Python 3.12, PySide6 y PyMuPDF. No ejecuta reconocimiento OCR ni utiliza cuentas, servicios remotos, telemetría o modelos de IA. Puede corregir una capa OCR que ya exista en el PDF, con los límites descritos más abajo. La instalación inicial de las dependencias necesita conexión; el ejecutable y la edición funcionan sin conexión.

Es una versión funcional de alcance conservador, no un editor universal de PDF. La compatibilidad demostrada comprende el corpus sintético incluido y pruebas privadas con dos PDFs reales, dentro del alcance de cada operación. Los archivos y capturas privados no se incluyen en la distribución.

## Arranque en Windows

Instalador: copie `PDFModder-v0.8.3-Instalar.exe` al equipo de destino, ábralo y pulse **Instalar**. Puede marcar **Abrir PDF Modder al terminar**. La carpeta propuesta está dentro de los programas de su usuario; no requiere permisos de administrador. Para desinstalar, use **Configuración → Aplicaciones → Aplicaciones instaladas → PDF Modder 0.8.3 → Desinstalar**, o abra `Desinstalar.exe` dentro de la carpeta instalada.

Paquete portable: abra `dist\PDFModder\PDFModder.exe` después de construir o recibir la distribución de la versión correspondiente. Mantenga toda la carpeta junto al ejecutable, especialmente `_internal`. No necesita Python instalado. Copie la carpeta entera si desea moverla.

Desde el código, con Python 3.12 x64 instalado:

```powershell
cd "C:\ruta\PDFModder"
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

También puede iniciar el entorno ya preparado:

```powershell
.venv\Scripts\python.exe run_pdfmodder.py
```

Los scripts se limitan a este proyecto; no modifican las otras aplicaciones del directorio padre. No se necesita ejecutar la aplicación como administrador.

## Recorrido de edición

1. Abra un PDF, por ejemplo `examples\digital.pdf`, o arrastre un único archivo PDF desde el Explorador a la ventana. Para varios archivos use Combinar PDFs u Organizar páginas.
2. Seleccione carácter, palabra, línea o bloque en el documento. Los bloques se infieren del PDF: no son cajas de Word. Ajuste los fragmentos de la selección con Ctrl y use selecciones pequeñas cuando haya columnas o estilos distintos.
3. Haga **doble clic sobre una palabra o línea seleccionada** para entrar directamente en edición; también puede usar Propiedades. El doble clic conserva la selección de línea existente, incluso al pulsar un espacio entre sus palabras. Para aceptar, pulse **1. Ver vista previa · Ctrl+Intro** (o Ctrl+Intro), revise el PDF realmente modificado y pulse **2. Aplicar cambio**. Después use **Guardar como…**. **Cancelar · Esc** descarta la escritura o la vista previa. La zona modificada permanece visible al previsualizar.
4. Para mover, arrastre la selección, use las flechas con el foco en el documento o escriba su posición en milímetros. El movimiento conserva las posiciones relativas de todos los caracteres seleccionados. Con el foco en el editor, las flechas mueven el cursor de escritura.
5. **Ajustar el resto de la línea** está activado por defecto al escribir: conserva los extremos de la línea y reparte los espacios entre palabras. Los vecinos conservan su fuente, tamaño y estilo. Si no cabe, seleccione la línea completa y amplíe su área explícitamente. Desactive esta casilla para sustituir sólo el fragmento seleccionado. El anclaje derecho mantiene el extremo derecho de un importe; el decimal necesita elegir su separador. No se detectan ni reformatean cantidades automáticamente.
6. Compare con el original y revise el resaltado de las regiones cambiadas. Use Deshacer/Rehacer si necesita recuperar un estado anterior.
7. Use Guardar como en otra ruta. Reabra esa copia para continuar editando; el resultado conserva texto real seleccionable y buscable.

La anchura del área y el tamaño de letra son parámetros distintos. **Ajustar anchura al texto**, activado por defecto, adapta el área de una sola línea a su contenido sin estirar letras. Se bloquean la invasión de vecinos y el desbordamiento fuera de página. Si necesita una anchura fija, desactive esa opción y escriba la medida. **Redistribuir sólo esta selección** compone varias líneas dentro del ancho y alto indicados, exige un estilo uniforme y no cambia automáticamente el tamaño. El resto de la página no se mueve.

En ese modo de párrafo, Intro fuerza una línea y dos Intro separan párrafos mediante una línea vacía. **Interlineado** fija la distancia entre líneas en puntos; **Separación párrafos** añade espacio entre los párrafos separados explícitamente. No se reconstruyen tablas, listas automáticas ni texto entre páginas. Si falta altura o una palabra no cabe, se solicita ampliar el área o ajustar manualmente el formato.

El ajuste de una línea cambia sólo espacios reales entre palabras: admite desde el 75 % de su avance natural hasta cuatro veces el tamaño de letra. No reduce la fuente, no comprime letras y no une otras columnas por proximidad. Se bloquean líneas ambiguas, espacios de tabla y selecciones discontinuas. Una palabra aislada no se estira. Cambiar manualmente tamaño o redistribuir en varias líneas utiliza sus controles propios y desactiva el ajuste automático de una línea para esa operación.

## Campos de facturas con recortes

Seleccione **Línea** para un campo completo y haga doble clic. **Ajustar anchura al texto** puede adaptar el espacio de una línea compatible; si utiliza anchura fija o necesita controlar el límite de su columna, ajuste **Anchura de área** explícitamente. El área no estira las letras y el motor sigue comprobando recortes y vecinos. Para editar sólo parte del campo manteniendo fijos los demás caracteres, desactive **Ajustar el resto de la línea**. Las operaciones de longitud variable de esta ruta no justifican ni desplazan los vecinos, y la previsualización lo indica antes de aplicar.

Se verificaron fecha, número de factura, cliente, direcciones, precios, importes y concepto en una factura real, incluidas palabras más cortas y más largas. Sus fuentes parciales se conservaron byte a byte. Los caracteres adicionales pueden usar un recurso nuevo verificado cuando existen en el programa TrueType incrustado, o una fuente completa elegida explícitamente. La composición nativa admite campos fragmentados y nuevas líneas compatibles; mantiene límites sobre recortes complejos y estilos no reproducibles.

En 0.8.1 también se pueden mover palabras y líneas dentro de recortes compatibles, incluidos desplazamientos fraccionarios. Se conserva la distribución interna y se comprueban la posición de destino, los vecinos y el recorte original. La resolución de caracteres consulta la codificación declarada y comprueba el glifo del recurso exacto, aunque todavía no aparezca en la página. El ajuste de línea admite pequeñas diferencias de línea base verificables sin unir filas o columnas distintas ni nivelar las letras conservadas. Véase [texto recortado](docs/EDICION_CON_RECORTES.md).

Los nombres que forman parte de un logotipo rasterizado se gestionan como imágenes; no se presentan como texto editable. El editor tampoco conoce las fórmulas contables de una factura ni recalcula automáticamente sus totales o impuestos. En las pruebas se introducen y verifican valores de demostración explícitos.

## Buscar, reemplazar y elegir elementos

**Buscar y reemplazar… · Ctrl+H** busca texto literal de una línea en todo el documento, páginas indicadas como `1,3-5` o la selección actual. Permite distinguir mayúsculas y palabras completas. Revise la tabla de coincidencias, elija **Previsualizar esta** o marque exactamente las que quiere cambiar y use **Previsualizar marcadas**. Las páginas de revisión proceden del PDF realmente modificado. **Aplicar cambios previsualizados** incorpora el lote como una unidad de historial; una coincidencia incompatible bloquea el lote completo. Cambiar los criterios requiere repetir la búsqueda; cambiar el reemplazo o las casillas exige otra previsualización. Cancelar descarta la vista previa.

**Elementos de la zona** permite dibujar un rectángulo y elegir texto visible, OCR invisible o una instancia de imagen aunque estén superpuestos. Cambie entre líneas, palabras y caracteres, recorra la lista con **Siguiente elemento de la zona**, o use **Toda la página** para quitar el filtro. Identificar un elemento no garantiza que sea editable: los bloqueos de su región y tipo siguen aplicándose. No es un selector de vectores.

## OCR existente: apariencia y búsqueda

Si una palabra digital visible tiene un duplicado OCR invisible verificable, editar el texto visible retira únicamente el duplicado de las palabras afectadas. Se exige cobertura geométrica de todos sus caracteres, sin invadir otra columna. La limpieza y la edición son una sola transacción: si falla el resultado, no se incorpora ninguna retirada. La vista previa informa de la limpieza y el texto visible nuevo conserva selección y búsqueda. Una selección parcial puede requerir elegir la palabra completa para mantener su orden de extracción.

Si el texto visible forma parte de una imagen escaneada, seleccione la fila **OCR** en Elementos y active **Corregir sólo la capa OCR buscable**. Esta ruta cambia únicamente el texto que se busca, copia o extrae; **la imagen conserva sus letras y apariencia originales**. Permite un tramo contiguo de una sola operación OCR con códigos disponibles y únicos en el mismo recurso. Puede ajustar el área sin escalar la fuente, pero no mover la capa, cambiar su formato, justificarla ni introducir saltos de línea. Las superposiciones, codificaciones o estructuras no aislables se bloquean. La búsqueda por lotes incluye esa capa sólo al activar explícitamente **Incluir capa OCR invisible** y distingue sus coincidencias.

No se reconoce texto de imágenes ni se genera una capa OCR nueva. Consulte [OCR existente](docs/OCR.md) para los controles, las verificaciones y los límites de ambas rutas.

## PDFs etiquetados y accesibilidad

Se admite **editar y mover texto existente compatible** en documentos etiquetados, conservando el árbol de estructura, su orden lógico, los identificadores de contenido MCID y sus relaciones ParentTree. También se comprueban el idioma, los roles, el texto alternativo de figuras y las relaciones de anotaciones compatibles. Los ejemplos reproducibles `examples/etiquetado.pdf` y `examples/etiquetado_actualtext.pdf` demuestran este flujo.

Cuando `/ActualText` coincide exactamente con el texto visible, se actualiza junto con la sustitución y se comprueba que no permanezca un recurso obsoleto con el texto anterior. Si expresa una alternativa diferente o depende de estructuras que no pueden actualizarse, se bloquea la operación con su motivo. El movimiento conserva el orden de lectura lógico: arrastrar un fragmento no reorganiza el árbol como un procesador de textos.

El soporte es conservador: todavía no se asignan etiquetas a contenido nuevo ni se remapean al reorganizar páginas. Esas herramientas se deshabilitan en un documento etiquetado; siguen disponibles para PDFs sin etiquetas. Tampoco se reconstruyen atributos de disposición, expansiones semánticas, texto alternativo ambiguo ni etiquetas en flujos externos. No se certifica PDF/UA ni se garantiza que un archivo que ya tenía errores de accesibilidad se vuelva accesible. Consulte [alcance y pruebas de etiquetado](docs/ETIQUETADO.md).

## Añadir texto y elegir tipografía

Use **Agregar texto**, pulse donde quiere colocar el área y escriba su contenido. El diálogo permite elegir familia, variante real, tamaño fraccionario, color, posición, dimensiones y alineación. Puede escoger una fuente disponible en el catálogo local o un archivo TTF/OTF concreto. La previsualización muestra texto real incorporado al PDF; revise el resultado antes de aplicarlo. Si no cabe, amplíe el área o cambie manualmente el formato.

Para cambiar el aspecto de texto existente, seleccione un tramo uniforme y abra **Tipografía / formato…**. Puede cambiar el contenido, la fuente, el tamaño y el color de esa selección de forma explícita. Negrita y cursiva seleccionan variantes reales de la familia; no se generan estilos artificiales. Cuando falta una variante o algún carácter, el diálogo o la validación informa del límite. Un cambio tipográfico manual no desactiva las comprobaciones del resto del documento ni permite sustituir silenciosamente otras fuentes.

## Imágenes y páginas

Use **Agregar imagen…**, elija un archivo de imagen de un solo fotograma y pulse en la página para situarlo. Ajuste posición y dimensiones en milímetros y aplique la previsualización. La imagen se incorpora al contenido del PDF: puede cubrir visualmente otros elementos si se coloca encima; no elimina esos elementos.

Active **Seleccionar imágenes** y pulse una imagen. Arrastre su interior para moverla o el tirador de la esquina inferior derecha para cambiar su tamaño. Puede conservar las proporciones o desactivar esa opción de forma explícita. **Posición / tamaño…** permite introducir medidas numéricas; las flechas desplazan la imagen cuando el foco está en el documento. También puede eliminar la imagen seleccionada. Cada arrastre constituye una operación de historial; Deshacer/Rehacer recupera el estado anterior. Guarde como otra copia y reábrala para continuar trabajando.

Mover o redimensionar una imagen compatible modifica su colocación y conserva sus píxeles, sin reemplazar accidentalmente las demás instancias del mismo recurso. Se admiten instancias aislables con transformaciones rectangulares sencillas. Imágenes integradas en construcciones más complejas, matrices inclinadas, recortes parciales, máscaras de estado gráfico o streams ambiguos se muestran con el motivo por el que no pueden transformarse.

**Guardar imagen…** o el menú contextual exportan su recurso completo: JPEG sin máscara conserva sus bytes; otras imágenes compatibles se exportan como PNG RGB/RGBA. Se respeta el permiso de copia. El archivo exportado no incluye el recorte, giro u opacidad de su colocación en la página ni textos superpuestos. **Recortar / girar / reemplazar…** permite dibujar un recorte, ajustar sus porcentajes, girar 0/90/180/270° o elegir otro archivo. Pulse **Ver en el PDF**, revise y aplique. Sólo se cambia la instancia seleccionada; otras apariciones conservan el recurso anterior. La caja de colocación se mantiene y el ajuste puede cambiar las proporciones. La instancia editada se genera en RGB/RGBA de ocho bits; no se promete conservar perfiles CMYK o de impresión. No hay pinceles, retoque libre ni edición de vectores.

Los formatos y la colocación se detallan en [Imágenes](docs/IMAGENES.md); la exportación, recorte, giro, reemplazo y conservación de color, en [Imágenes 0.8](docs/IMAGENES_V08.md).

**Eliminar páginas…** retira páginas de la copia de trabajo y se puede deshacer; no permite dejar un PDF vacío. **Extraer páginas…** guarda otro PDF sin alterar el trabajo actual. Indique números y rangos como `1,3-5`; para un orden distinto puede escribir `3,1-2`. **Combinar PDFs…** permite ordenar los archivos con Subir/Bajar y añadirlos al documento actual o iniciar un trabajo combinado. Las páginas mantienen sus tamaños, recortes y rotaciones. Deshacer/Rehacer también recupera la composición anterior del documento.

La comparación con el original sigue a las páginas conservadas después de eliminar otras. Las páginas añadidas al combinar se identifican como nuevas y no tienen una página correspondiente en el original. Los enlaces internos y marcadores se remapean en el alcance admitido; un enlace hacia una página que se pretende excluir bloquea la operación. Consulte [Operaciones de páginas](docs/PAGINAS.md) para los límites, el tratamiento de marcadores y la política de metadatos del documento combinado.

**Organizar páginas…** muestra miniaturas arrastrables y el orden final antes de previsualizar. Permite subir/bajar, girar 90°, duplicar, quitar e insertar páginas en blanco o PDFs en una posición concreta. Las copias heredan los cambios previos de su página; las ediciones y su resaltado posteriores pertenecen sólo a esa instancia. Los enlaces a otra página y marcadores utilizan su primera aparición final; los enlaces a la propia página permanecen en su copia. Los metadatos del documento actual se conservan. La operación se bloquea en PDFs etiquetados, con firmas, formularios u otras estructuras que no puedan remapearse. No se retiran esas estructuras para hacer posible el cambio. Consulte [Organizador 0.8](docs/PAGINAS_V08.md).

## Conservación estricta y fuentes

El modo de conservación estricta está activo: no existe una sustitución automática por fuentes parecidas, ni reducción automática del tamaño, ni compresión del texto. Se admite texto horizontal con tamaño fraccionario, color RGB/gris, opacidad de relleno y posiciones de caracteres comprobables. Una página puede estar girada 0/90/180/270 grados; esa rotación es diferente de la orientación propia del texto.

El inspector identifica, cuando es verificable, el operador y recurso concreto de los caracteres seleccionados, y distingue fuentes con el mismo nombre o sin xref. Muestra primero el nombre PostScript, variante, versión y grado de evidencia; compara candidatos instalados sin sustituir automáticamente. La huella del programa incrustado no demuestra identidad con un archivo completo del que pudiera proceder un subconjunto. Cada inspección explícita relee los bytes y su SHA-256, incluso si no cambian las fechas del archivo.

El inspector muestra los datos disponibles: nombre del recurso, familia, variante, versión, incrustación, subconjunto, cobertura Unicode, permisos técnicos y origen de resolución. El orden es fuente incrustada viable, nombre PostScript exacto instalado y asociación manual de TTF/OTF. Un nombre coincidente no prueba identidad: se comprueban los caracteres y las métricas, y se reproduce la selección original a sus posiciones exactas antes de permitir la operación. Esta comprobación de una muestra tampoco certifica todos los glifos de una fuente ni su identidad binaria.

Las asociaciones se guardan localmente, sin copiar el archivo de fuente; se comprueba su hash y disponibilidad en cada resolución. Si el archivo cambia o no tiene un carácter necesario, la operación se bloquea. La aplicación no descarga fuentes. Las tablas de permisos técnicos no sustituyen la licencia del proveedor.

Los tramos de estilos diferentes se pueden mover juntos. Para escribir, esta versión exige seleccionar un tramo de estilo uniforme; informa del límite antes de modificarlo. Las posiciones de caracteres permiten conservar espaciado irregular al mover. La sustitución con espaciado irregular o ajustes por pares no reproducibles se bloquea.

## Cómo protege el PDF

La edición de texto visible utiliza dos rutas. En páginas con recortes explícitos, `clipping.py` conserva los operadores originales cuando los códigos tienen igual avance. `clipped_layout.py` añade sustituciones de longitud o avance diferentes dentro de un campo compatible Tj/TJ: conserva el programa de fuente, Tf/Tc/Tw/Tz y el recorte, y compensa el cursor posterior para no mover vecinos. No admite cambios de fuente/tamaño/color, movimiento ni redistribución entre líneas. Una capa OCR duplicada compatible se limpia de forma transaccional antes de esa edición; los casos ambiguos siguen bloqueados. Véase [edición con recortes y certeza tipográfica](docs/EDICION_CON_RECORTES.md).

En el resto de casos soportados, `engine.py` aplica eliminación por regiones diminutas interiores a los caracteres seleccionados. Usa `fill=False`, `images=PDF_REDACT_IMAGE_NONE`, `graphics=PDF_REDACT_LINE_ART_NONE` y `text=PDF_REDACT_TEXT_REMOVE`. No añade un rectángulo blanco, no deja una anotación de redacción como edición, no oculta texto y no rasteriza el PDF de salida. MuPDF interpreta las codificaciones y operadores; no se hacen reemplazos de cadenas en el binario.

Se comprueba que los caracteres originales seleccionados desaparezcan de sus posiciones y que todos los demás permanezcan, incluso si contienen palabras repetidas. Se reinsertan glifos con fuentes verificadas y coordenadas explícitas. Si no se puede aislar un carácter de sus vecinos, no se modifica el documento.

Para el texto español representable en Windows-1252 se crean recursos WinAnsi, lo que evita que dos caracteres con el mismo glifo (por ejemplo espacio/espacio no separable) pierdan su identidad Unicode. Los espacios no separables y guiones blandos originales conservan su ruta de codificación al moverlos. No se cambia el mapa Unicode de recursos compartidos. Toda salida se vuelve a contrastar por carácter.

`ocr.py` modifica únicamente códigos identificados de operaciones Tj/TJ de la capa invisible existente y compensa sus avances para conservar a los vecinos. No convierte texto visible en invisible como sustituto de una edición. La retirada del duplicado y la corrección buscable deben conservar la apariencia de la página completa, sin máscaras de exclusión; la modificación visible posterior se comprueba por separado.

Cada operación escribe una copia completa, la reabre y valida las páginas que deben conservarse. Se comparan geometría, texto por carácter y posición, imágenes, vectores, marcadores, enlaces, anotaciones y metadatos según el cambio solicitado. En las operaciones de páginas, cada página del resultado se contrasta con su página concreta de origen y con los destinos remapeados. La limpieza `garbage=4` elimina objetos no referenciados; no se guardan cambios como revisiones incrementales. Después de una escritura completa se reabre el documento porque la limpieza puede renumerar recursos.

La validación visual usa 144 ppp y RGB. Para editar texto, fuera de los envolventes **individuales de los caracteres** de origen y destino, ampliados sólo 0,75 puntos, ningún píxel puede superar una diferencia de 8/255 por canal. La misma tolerancia, sin regiones excluidas, verifica la reproducción inicial de la fuente. Los caracteres vecinos también se contrastan por contenido y coordenadas, con tolerancia de 0,035 puntos.

Para una operación de imagen, la máscara visual se limita al rectángulo de la imagen original y al rectángulo de destino, según corresponda, con el mismo margen de 0,75 puntos. Se comprueban además los caracteres, vectores, enlaces, anotaciones y las otras imágenes, incluidos los recursos compartidos. Al mover/redimensionar se comprueban los píxeles originales; al recortar/girar/reemplazar se comprueban contra el resultado solicitado. Para eliminar, extraer, combinar u organizar páginas, la comparación visual de cada página conservada se realiza **sin ninguna máscara de exclusión**, aplicando a la referencia el giro solicitado. Son tolerancias técnicas para redondeo y antialiasing, no una afirmación de identidad visual universal; no se excluyen páginas enteras para ocultar errores.

Guardar como escribe primero un temporal en la carpeta de destino, valida, vacía los buffers y utiliza `os.replace`. La sustitución es atómica cuando el sistema de archivos lo permite. Se bloquean las rutas originales de todos los PDFs utilizados en el trabajo, incluidos los añadidos al combinar y los enlaces físicos detectables. La extracción de páginas aplica la misma protección. Si falla el guardado, los estados de edición y deshacer permanecen disponibles. El historial conserva instantáneas exactas en disco, hasta 40 estados o 512 MiB; no ejecuta operaciones inversas que acumulen errores. No es una función de recuperación tras un cierre abrupto del proceso.

## Límites detectados

Los documentos cifrados, con restricciones, firmas o campos de formulario se abren para visualización; la edición y el guardado de una copia PDF modificada quedan bloqueados. Las contraseñas válidas sólo sirven para abrir en esta versión; no se eliminan restricciones ni se invalidan firmas silenciosamente. La exportación de un recurso de imagen es una lectura independiente y respeta el permiso de copia. Se detectan formularios XFA, firmas declaradas y campos de firma, pero no se certifica criptográficamente su validez. El corpus de firma contiene un marcador sintético deliberadamente inválido.

También se bloquean PDFs etiquetados cuya estructura no pueda verificarse y operaciones concretas cuya información accesible no pueda actualizarse. La edición de texto bloquea páginas con Form XObjects, capas, contenido marcado sin estructura compatible, recortes gráficos que no admitan las rutas conservadoras de edición nativa, redacciones pendientes, máscaras o mezclas especiales de color y sobreimpresión. En regiones de texto se rechazan orientaciones propias distintas de horizontal, escritura bidireccional/vertical, codificación ambigua, ligaduras no reconstruibles, marcas combinantes, texto trazado, escalas no reproducibles y superposiciones que no puedan aislarse. El texto invisible sólo se modifica en la ruta OCR explícita o como duplicado verificable de texto visible, nunca como texto ordinario. Las operaciones de imágenes y páginas aplican sus propios controles de aislamiento y preservación. Son bloqueos conservadores; algunos PDFs digitales correctos de programas de oficina caerán en ellos.

No hay redistribución de texto entre páginas, retoque libre de píxeles, edición de vectores, cálculos de formularios ni reconocimiento OCR. La edición de un enlace o de texto tocando una anotación se bloquea para preservar su comportamiento. Las operaciones de páginas rechazan, entre otros casos, destinos con nombre, acciones especiales, capas de documento, adjuntos y etiquetas de página que no se puedan remapear con garantías. Los elementos compatibles ajenos al cambio se conservan y verifican. Las páginas que exceden 16 millones de píxeles a la resolución de validación quedan bloqueadas; el render de interfaz limita su resolución. La importación de imágenes se limita a 50 MB, 40 millones de píxeles y un solo fotograma.

No se certifica PDF/A, PDF/UA, fidelidad de separaciones de imprenta ni ausencia de indicios de modificación. La fidelidad visual no equivale a identidad binaria. El original y las copias externas siempre permanecen fuera del proceso de modificación.

## Diseño y ejecución

| Módulo | Responsabilidad |
|---|---|
| `model.py` | Selección, caracteres, unidades y transformaciones serializables. |
| `engine.py` | Planificación, aislamiento, sustitución/movimiento y guardado. |
| `clipping.py` | Identificación de recursos de texto y sustituciones de igual avance conservando recortes. |
| `clipped_layout.py` | Campos Tj/TJ de longitud variable, aislamiento del cursor y validación de vecinos. |
| `lineflow.py` | Ajuste de espacios en una línea conservando extremos y estilos vecinos. |
| `tagged.py` | Asociación de glifos a etiquetas, reconstrucción del contenido marcado y validación lógica. |
| `composition.py` | Inserción de texto real con fuente, tamaño, color y área explícitos. |
| `media.py` | Inserción, eliminación y transformación de instancias de imagen aislables. |
| `pageops.py` | Clonación de páginas, eliminación, extracción, unión y remapeo verificado. |
| `fonts.py` | Inspección y resolución conservadora de fuentes. |
| `validation.py` | Contenido, estructura y comparación de píxeles. |
| `history.py` | Instantáneas inmutables en disco. |
| `worker.py` | Sesión y único proceso del motor; caché de páginas limitada. |
| `app.py`, `canvas.py` | Interfaz Qt, edición sobre página y propiedades. |
| `dialogs.py` | Selector de familias y variantes reales; diálogo de texto y formato. |
| `editing_ui.py` | Flujos de texto nuevo, imágenes, rangos y combinación de PDFs. |
| `textlayout.py`, `paragraphs.py` | Anchura automática y distribución local de párrafos sencillos. |
| `search_replace.py`, `search_dialog.py` | Coincidencias vinculadas a una revisión y reemplazo por lotes con revisión. |
| `ocr.py` | Limpieza de duplicados y corrección explícita de OCR existente. |
| `elements.py`, `advanced_ui.py` | Selección de elementos superpuestos y flujos ampliados. |
| `image_editor.py` | Recorte, giro y reemplazo de imagen en un diálogo Qt. |
| `page_organizer.py` | Plan serializable de páginas y miniaturas asíncronas. |

No se comparten documentos MuPDF entre hilos. Un proceso hijo ejecuta las operaciones secuencialmente y la interfaz consulta sus resultados sin bloquear su bucle de eventos. Se renderiza por páginas, con caché de hasta 12 entradas/32 MiB de PNG y límites de resolución. No se cargan todas las páginas a máxima resolución.

Se usa pypdf para analizar formularios, estructura etiquetada y estado gráfico que la extracción de MuPDF no expone por completo. Su parser identifica las secuencias de colocación de imágenes y permite cambiar la matriz de una instancia aislada sin buscar cadenas en el binario ni sustituir el recurso compartido. También clona los objetos de páginas y anotaciones y conserva destinos XYZ originales al reorganizar páginas: la prueba de las operaciones equivalentes de MuPDF detectó pérdidas de XMP, relaciones Popup y desplazamientos de destinos con CropBox rotado. Estos límites y la solución se detallan en [PAGINAS.md](docs/PAGINAS.md). Para operaciones construidas con pypdf, MuPDF aporta la lectura, el render y la escritura final de contraste; pypdf no se presenta como verificador independiente de sus propias transformaciones.

APIs contrastadas con la documentación oficial y con las versiones instaladas: [Page/redacciones/coordenadas](https://pymupdf.readthedocs.io/en/latest/page.html), [get_texttrace](https://pymupdf.readthedocs.io/en/latest/functions.html), [procesos](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html), [fontTools](https://fonttools.readthedocs.io/en/latest/ttLib/ttFont.html) y [Qt for Python](https://doc.qt.io/qtforpython-6/index.html). Se fijan versiones comprobadas; no se supone que la biblioteca proporcione un editor completo.

## Pruebas y empaquetado

**0.8.1, verificada en Windows:** 454 pruebas aprobadas en 84,44 s. El recorrido ampliado de recortes completó 19 pasos desde el código en 2,95 s y desde el ejecutable en 2,245 s. Los cuatro recorridos del mismo ejecutable suman 75 pasos; su huella y resultados están en [CORRECCIONES_V081.md](docs/CORRECCIONES_V081.md).

**Resultados históricos de 0.8.0 en Windows:** 416 pruebas aprobadas en 106,76 s; cuatro recorridos de aquel ejecutable con 68 pasos aprobados en 26,599 s en total. Las siete regresiones del ajuste de anchura forman parte de esa ejecución completa. Son medidas de ese equipo, paquete y corpus, no una garantía de rendimiento general ni la verificación de 0.8.1. El estado actual se recoge en [CORRECCIONES_V081.md](docs/CORRECCIONES_V081.md).

Las pruebas focales nuevas están en `tests/test_ocr_edit.py`, `tests/test_review_text.py`, `tests/test_advanced_ui.py`, `tests/test_image_tools.py`, `tests/test_page_organizer.py` y `tests/test_instance_changes.py`. La ejecución completa de pytest incluye estas pruebas y las regresiones anteriores.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Development
.venv\Scripts\python.exe scripts\generate_examples.py
.venv\Scripts\python.exe scripts\generate_clipped_example.py
.venv\Scripts\python.exe scripts\generate_v08_examples.py
.venv\Scripts\python.exe scripts\vertical_probe.py
.venv\Scripts\python.exe -m pytest -q --junitxml output/pytest-results.xml
.venv\Scripts\python.exe scripts\acceptance_report.py
.venv\Scripts\python.exe scripts\acceptance_extensions.py
.venv\Scripts\python.exe scripts\acceptance_tagged.py
.venv\Scripts\python.exe scripts\acceptance_v08.py
.venv\Scripts\python.exe run_pdfmodder.py --smoke-extended output/extended-smoke.json
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_executable.ps1
.venv\Scripts\python.exe scripts\collect_licenses.py
.venv\Scripts\python.exe scripts\package_release.py
```

La comprobación independiente de imágenes requiere Poppler (`pdftoppm`) en PATH; no es una dependencia para utilizar la aplicación. El script de aceptación produce los resultados medidos y detalla si falta esa comprobación. Véanse `docs/CORPUS.md`, `docs/RESULTADOS_CORPUS.md` y los JSON de `output/`.

`docs/VERIFICACION_WINDOWS.md` recoge el entorno y las pruebas ejecutadas. Para repetir la operación vertical desde el paquete: `dist\PDFModder\PDFModder.exe --smoke-test output\packaged-smoke.json`. Esa opción modifica y mueve una fecha del ejemplo incluido, guarda otra copia, la reabre y contrasta texto, posición y apariencia, incluida la segunda página intacta.

Para comprobar el flujo ampliado desde el paquete: `dist\PDFModder\PDFModder.exe --smoke-extended output/extended-smoke.json`. Desde el código: `.venv/Scripts/python.exe run_pdfmodder.py --smoke-extended output/extended-smoke.json`. La prueba añade texto con formato e imagen, transforma la imagen, extrae y elimina páginas, deshace, combina, guarda y reabre el PDF. El JSON registra el resultado de esa ejecución; disponer del script no equivale a una prueba superada.

`--smoke-tagged output/packaged-tagged-smoke.json` comprueba además la edición del documento etiquetado, el doble clic mediante eventos de ratón, el ajuste de línea, deshacer/rehacer y la copia reabierta. `scripts/acceptance_tagged.py` genera los ejemplos y contrasta por separado la estructura lógica, el contenido y los píxeles con Poppler.

`--smoke-clipped output/packaged-clipped-smoke.json` comprueba un campo con recortes: sustituye SOL por ESTRELLA, guarda y reabre, vuelve a SOL, deshace y rehace, y guarda otra copia. Verifica la fuente original, el cursor posterior, los vecinos y los píxeles de la página de control. Se ejecuta con `examples/recortado.pdf`, regenerable mediante `scripts/generate_clipped_example.py`.

El recorrido de recortes de 0.8.1 amplía esa prueba a caracteres verificables todavía no usados y movimiento nativo, incluidos desplazamientos fraccionarios; su resultado debe revisarse por separado para ejecución desde código y desde el ejecutable congelado.

La entrega incluye los scripts de construcción y avisos de dependencias. Código de la aplicación AGPL-3.0-or-later; PyMuPDF/MuPDF AGPL o licencia comercial, Qt/PySide LGPL/GPL según componentes o licencia comercial. No se introduce un SDK de pago obligatorio. Consulte `docs/LICENCIAS.md` antes de redistribuir el paquete a terceros; las obligaciones de fuentes correspondientes no se resuelven únicamente con un enlace al proveedor.
