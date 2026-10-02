# PDF Modder 1.5.0 — Herramientas de edición

Aplicación local para Windows 11 x64. No necesita cuenta, conexión a Internet,
telemetría ni servicios de IA para editar. Trabaja con texto y objetos PDF reales;
la compatibilidad depende de los recursos y estructuras de cada documento.

Esta guía describe las funciones implementadas. No acredita una comprobación
exhaustiva de Acrobat ni del instalador. Los resultados medidos de la entrega se
documentan por separado; los informes de versiones anteriores son históricos.

## Distribución de las herramientas

La barra superior contiene las operaciones del documento, navegación y zoom.
Las miniaturas están a la izquierda y el documento ocupa el centro. A la derecha,
**Herramientas** presenta secciones desplegables:

| Sección | Operaciones |
| --- | --- |
| Edición del contenido | Editar texto e imágenes, agregar texto, agregar imagen y exportar archivo |
| Formato | Fuente, tamaño, negrita, cursiva, subrayado, color y alineación; controles de imagen al seleccionar una |
| Páginas | Miniaturas, rotar, eliminar, extraer, reemplazar, recortar, dividir e insertar páginas; combinar archivos |
| Propiedades y herramientas avanzadas | Propiedades detalladas, objetos y bloques, fuentes, copiar formato y comparación |

El panel puede ocultarse y recuperarse mediante **Herramientas**. Las miniaturas
tienen su propio control de visibilidad. Los pictogramas son dibujos originales
de PDF Modder. La organización favorece un flujo familiar, pero la aplicación no
es Adobe Acrobat ni utiliza su motor, recursos gráficos o licencias.

## Editar y agregar texto

1. Abra un PDF con **Abrir** o arrástrelo sobre la ventana.
2. Active **Editar texto e imágenes**. Pulse un texto para seleccionarlo; haga
   doble clic para entrar en edición y coloque el cursor donde quiera escribir.
3. Arrastre sobre letras para seleccionar un fragmento. Los controles de
   **Formato** afectan a ese fragmento; sin selección afectan a lo que escriba.
4. **Intro** inicia un párrafo y **Mayús+Intro** introduce un salto de línea dentro
   del párrafo. Los controles de párrafo permiten ajustar interlineado y espacios
   en los casos compatibles. El contenido sólo se redistribuye en el área elegida.
5. En el editor rico, pulse **Aceptar ✓ / Ctrl+Intro** para validar y aplicar;
   **Cancelar × / Esc** descarta la sesión. La vía conservadora de etiquetas u
   OCR mantiene dos pasos: generar la vista previa y pulsar **Aplicar cambio**.
6. Use **Guardar como…** para escribir la copia final. El original se protege.

**Agregar texto** permite pulsar en la página y escribir directamente. El texto
nuevo comienza con Liberation Sans incluida, 12 pt, y su cuadro crece al escribir;
la fuente inicial se indica expresamente y no sustituye fuentes de texto existente.
El panel Formato permite elegir tipografía, variante, tamaño y color.
**Agregar texto con propiedades…**, en las herramientas avanzadas, conserva el
diálogo con dimensiones numéricas. **Copiar formato** reutiliza propiedades verificadas cuando la fuente
y sus caracteres lo permiten. Mover un cuadro conserva el tamaño de letra;
cambiar sus dimensiones redistribuye el texto cuando el motor puede hacerlo.
Un desbordamiento o una región no aislable se informa antes de aplicar.

## Identificación de fuentes

El inspector de fuentes diferencia el nombre declarado en el PDF, la fuente
incrustada, los subconjuntos, la cobertura de caracteres y el programa que se
puede reutilizar. Cuando existe un programa tipográfico accesible, muestra sus
datos y evidencias de identidad. Un nombre de familia coincidente no prueba que
dos fuentes tengan los mismos contornos o métricas.

El modo estricto permanece activo. No sustituye una fuente por otra parecida ni
simula automáticamente la variante negrita o cursiva. Puede ser necesario asociar
un archivo TTF/OTF adecuado o elegir una fuente explícitamente. La cobertura se
valida para el texto nuevo; un subconjunto válido para cifras puede no contener
una letra o un signo. Las fuentes personales no se redistribuyen con la aplicación.

El borrador de Qt facilita la escritura; la referencia de apariencia es el PDF
generado y validado por el motor. **Ver PDF real** permite revisarlo antes de
aceptar en los flujos que ofrecen esa vista.

## Imágenes

**Editar texto e imágenes** selecciona una imagen al pulsarla si no hay texto
visible en ese punto. El modo específico de imágenes y el panel de elementos
permiten resolver selecciones superpuestas.

Arrastre la imagen para moverla y utilice los ocho tiradores para cambiar sus
dimensiones. Los controles rápidos permiten voltear horizontal o verticalmente,
girar a izquierda o derecha y abrir las opciones de recorte o sustitución. El
diálogo de imagen conserva controles de giro libre, **Encajar**, **Rellenar
recortando** y estiramiento explícito. Los cambios se aplican a la instancia
seleccionada compatible y se previsualizan en el PDF real.

Use **Agregar imagen** para elegir un archivo local y pulsar en su posición. La
anchura inicial es de hasta 60 mm y puede cambiarse con los tiradores o en
Posición / tamaño. El menú contextual de una
imagen permite exportarla. Una instancia con máscaras, recortes u otros recursos
que no puedan aislarse mantiene un bloqueo concreto para evitar alterar otras
apariciones.

## Páginas y documentos

Los campos de páginas utilizan números desde 1 y aceptan, por ejemplo, `1-3,5`.
El organizador permite revisar el orden final antes de aplicar rotaciones,
inserciones, duplicaciones y reordenamientos.

- **Reemplazar páginas** requiere igual número de páginas originales y de
  sustitución. Cambia páginas completas, incluidas sus anotaciones; no equivale
  a sustituir únicamente el dibujo y mantener los comentarios anteriores.
- **Recortar páginas** pide márgenes en milímetros respecto a los bordes que se
  ven, incluso cuando la página está girada. Sólo modifica CropBox: el contenido
  oculto permanece dentro del archivo. No sirve para borrar información
  confidencial. La comparación conserva el tamaño original en su vista y adapta
  los resaltados a las coordenadas correspondientes.
- **Dividir documento** crea `parte-001.pdf`, `parte-002.pdf`, etc. en la carpeta
  elegida. Puede dividir por un número de páginas o por grupos como `1-3;4-6;7`.
  Los grupos deben cubrir todas las páginas sin repetirlas; para exportar sólo
  algunas use **Extraer**. No sobrescribe archivos existentes ni cambia el PDF
  abierto. La publicación es atómica por archivo, no por el conjunto entero.
- **Insertar desde archivo** permite elegir las páginas del archivo y situarlas
  antes o después de una página del documento. **Rotar** admite un intervalo,
  páginas pares/impares y orientación vertical/horizontal. El organizador ofrece
  una revisión más detallada del orden. **Combinar** reúne PDFs compatibles en el
  orden elegido.
- **Eliminar**, **Extraer** y **Rotar** conservan las comprobaciones de destinos,
  anotaciones, contenido y aspecto del motor de páginas existente.

Reemplazar y recortar generan una vista previa que se acepta con **Aplicar** o se
descarta con **Cancelar**. Deshacer y rehacer restauran instantáneas completas del
PDF. Dividir y exportar generan archivos independientes y no añaden operaciones
al historial del documento abierto.

## Exportar archivo

| Formato | Resultado y límites |
| --- | --- |
| TXT | Texto UTF-8; sin imágenes ni formato. El orden extraído puede variar en tablas y columnas. No aplica OCR. |
| PNG | Una imagen RGB por página; resolución elegida entre 36 y 600 ppp. Pierde texto seleccionable y vectores. |
| JPEG | Una imagen por página con compresión con pérdida; mismas limitaciones que PNG. |
| SVG | Dibujos vectoriales y letras convertidas en contornos; las imágenes siguen siendo mapas de bits. No conserva texto seleccionable, etiquetas ni interactividad. |

Los archivos de imagen/vector usan nombres como `pagina-0001.png` y el número
corresponde a la página de origen. La exportación no sobrescribe archivos
existentes. Hay un límite de 40 millones de píxeles por página para PNG/JPEG; si
se supera, reduzca la resolución. Para conservar un PDF editable use **Guardar
como…**, **Extraer**, **Dividir** o **Combinar**, según el caso.

No se ofrece conversión a Word, Excel o PowerPoint, ni se afirma equivalencia
general con los exportadores de Acrobat.

## Alcance y límites de integridad

Permanecen los bloqueos por cifrado, permisos, firmas, formularios activos y
estructuras que el motor no puede conservar. Los PDFs etiquetados admiten sólo
las operaciones cuya estructura y relaciones puedan validarse. Combinar árboles
de accesibilidad de distintos documentos requiere soporte adicional. Los destinos
con nombre se conservan al insertar o combinar si sus nombres son distintos;
se bloquean las colisiones y la duplicación de páginas con destinos ambiguos.
No se permite generar partes con enlaces internos a páginas excluidas.

Los documentos con OCR sólo reutilizan la capa existente en las operaciones
admitidas; esta versión no reconoce imágenes para crear texto. La compatibilidad
con un PDF concreto no demuestra compatibilidad con todos los documentos del
mismo programa de origen. Un error de validación conserva el estado de trabajo
y el original; no se omiten las comprobaciones para imitar una acción de otro
editor.

La validación estructural y visual no garantiza identidad binaria ni ausencia de
indicios de edición. Las licencias de distribución y dependencias se describen
en [LICENCIAS.md](LICENCIAS.md).

## Trasladar texto con recorte y límites de accesibilidad

Un fragmento o una línea pueden trasladarse junto con su recorte rectangular
cuando pertenecen a un ámbito aislado que sólo contiene ese tramo de texto.
Se mantienen los códigos de fuente, los ajustes entre caracteres, el contenido
vecino y la forma del recorte: el recorte se mueve, no se amplía. Un recorte
superior compartido, otras pinturas en el mismo ámbito, codificaciones no
verificables o una selección que atraviese varios tramos pueden impedirlo.
El destino debe permanecer dentro de la página y de los recortes superiores.

En documentos con texto digital y OCR invisible duplicado, la operación puede
retirar únicamente el duplicado OCR identificado de la palabra seleccionada,
según el aviso de la aplicación. El texto visible conserva su tipografía y
sigue siendo seleccionable; al mover letras blancas a un fondo blanco seguirá
siendo blanco hasta que el usuario cambie expresamente su color.

En el ANEXO etiquetado probado, parte de la cabecera está marcada como artefacto
y el cuerpo pertenece a etiquetas de lectura. La combinación de texto recortado
y etiquetas todavía puede bloquear su edición o movimiento. Añadir texto o
imágenes y combinar árboles de accesibilidad requieren soporte adicional; no
se eliminan las etiquetas para permitir esas operaciones.
