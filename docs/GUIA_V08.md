# Guía de PDF Modder 0.8

Extraiga todo el ZIP de Windows y abra `PDFModder.exe`, manteniendo su carpeta
`_internal`. Es portable y no necesita instalar Python. Esta guía describe los
controles implementados. La comprobación final del ejecutable está completada:
cuatro recorridos y 68 pasos aprobados, además de 416 pruebas desde código.
Consulte `ENTREGA.json` y `COMPROBACIONES/ESTADO.txt` para ver la huella del
ejecutable probado y los resultados de cada recorrido.

La versión **0.7 está archivada por separado** en `releases/v0.7/`, con sus ZIP
del programa Windows y del código, sus huellas `.sha256` y `VERSION.json`.
Puede extraer su paquete en otra carpeta para conservar una instalación
independiente. No copie archivos de 0.8 encima de esa carpeta: mantenga cada
versión con su propio ejecutable y su carpeta `_internal`. Los resultados
históricos de 0.7 corresponden a ese paquete, no a esta ampliación.

El trabajo sigue siendo local. No se generan reconocimientos OCR, no se usan
cuentas, nube, telemetría ni IA. El soporte descrito de OCR corrige texto
invisible que **ya existe** en ciertos PDFs.

## Antes de empezar

Abra un PDF y seleccione carácter, palabra, línea o bloque. Para escribir, haga
doble clic dentro de una selección coherente; una línea seleccionada se conserva
al entrar en edición. Los bloques son agrupaciones inferidas del PDF y no cajas
de un procesador de textos.

El recorrido habitual es **Ver vista previa · Ctrl+Intro → Aplicar cambio →
Guardar como…**. La vista previa procede del PDF modificado y validado. Escape
o Cancelar descarta la escritura o la vista previa; Deshacer y Rehacer recuperan
los estados aplicados. Use una ruta nueva al guardar y reabra esa copia si desea
comprobar su selección y búsqueda. Los PDFs de origen utilizados en el trabajo
quedan protegidos frente a una sobrescritura accidental.

## 1. Abrir arrastrando un PDF

Arrastre **un único archivo `.pdf`** desde el Explorador de Windows hasta la
ventana o la vista del documento. Si hay cambios sin guardar o una edición
pendiente, la aplicación solicita decidir si se descartan antes de abrir otro
archivo. Cancelar conserva el trabajo actual.

Arrastrar abre ese documento. Para incorporar varios archivos al mismo trabajo,
use **Combinar PDFs…** o **Organizar páginas…**, descritos más abajo. Durante una
operación del motor, espere a que termine antes de abrir otro documento.

## 2. Ajustar la anchura al texto

**Ajustar anchura al texto** está activado por defecto en las propiedades.
Al sustituir texto de una sola línea, permite que el área crezca o se reduzca
según el contenido. Mantiene el tamaño de fuente: ampliar la anchura del área
no estira las letras ni las comprime.

Seleccione la palabra o línea, escriba el cambio y previsualice. Revise la
anchura resultante en el panel. Si el destino invade caracteres ajenos o rebasa
el borde de página, la operación se bloquea; no empuja automáticamente otras
filas ni columnas. Puede mover el área, ajustar sus dimensiones o escoger
manualmente otro formato.

**Ajustar el resto de la línea** es otro control: distribuye los espacios de una
línea compatible al sustituir un fragmento. Si necesita ampliar una línea
justificada completa, selecciónela entera antes de ajustar su área. Desactive
ese control cuando quiera mantener inmóviles los caracteres vecinos y sustituir
únicamente el fragmento elegido. Los anclajes izquierdo, centrado, derecho y
decimal siguen siendo elecciones explícitas; los importes no se recalculan.

La anchura automática no redistribuye párrafos. Cuando activa la redistribución
entre líneas, se respeta la anchura que haya indicado para el área.

## 3. Líneas, párrafos e interlineado

Para recomponer texto dentro de un área, seleccione un tramo o bloque de
**estilo uniforme**, establezca su anchura y altura, y active **Redistribuir sólo
esta selección**. Escriba en el contenido del panel o en el editor sobre la
página:

- Un **Intro** inserta un salto de línea explícito.
- **Dos Intro** dejan una línea vacía y comienzan otro párrafo.
- **Interlineado** indica en puntos PDF la distancia entre líneas. El valor
  «Original / automático» permite utilizar el criterio disponible del texto.
- **Separación párrafos** añade espacio entre los párrafos separados mediante
  una línea vacía, además de esa separación básica.

Previsualice después de cambiar estos valores. Las palabras se redistribuyen
dentro de la selección sin reducir automáticamente el tamaño de letra. Si
falta altura o una palabra no cabe, amplíe el área o ajuste manualmente el
formato. El contenido del resto de la página permanece fijo.

Este es un ajuste local de párrafos sencillos. No compone columnas, listas
automáticas, tablas ni texto entre páginas. Si la selección mezcla estilos que
no se pueden reproducir, la escritura se bloquea; mover el grupo completo tiene
un alcance distinto. La orientación, codificación o recorte del PDF también
pueden impedir esta operación.

## 4. Buscar y reemplazar con revisión

Abra **Buscar y reemplazar…** o pulse **Ctrl+H**.

1. Escriba el texto de búsqueda y el reemplazo.
2. Elija **Todo el documento**, **Páginas indicadas** —por ejemplo `1,3-5`— o
   **Selección actual**. La selección actual es la que tenía al abrir el diálogo.
3. Ajuste **Distinguir mayúsculas** y **Palabras completas**. La búsqueda utiliza
   texto literal de una línea; no es una búsqueda por expresiones regulares.
4. Pulse **Buscar todas las coincidencias**. Compruebe página, texto, contexto y
   capa de cada fila.
5. Seleccione una fila y pulse **Previsualizar esta**, o marque exactamente las
   casillas deseadas y pulse **Previsualizar marcadas**. **Marcar todas** es una
   acción explícita; las coincidencias aparecen inicialmente sin marcar.
6. Revise la página renderizada. Puede elegir otras filas para revisar sus
   páginas. Pulse **Aplicar cambios previsualizados** cuando el resultado sea
   correcto; después, **Guardar como…** desde la ventana principal.

Si cambia los criterios de búsqueda, vuelva a buscar. Cambiar el reemplazo o
las casillas seleccionadas exige otra previsualización antes de aplicar. El
lote aplicado constituye una sola unidad de Deshacer. Si una coincidencia no
se puede aislar o editar con garantías, el lote no se aplica parcialmente.

**Incluir capa OCR invisible** incorpora coincidencias de esa capa a la tabla y
las identifica por separado. Activarlo no convierte la edición en una corrección
visual del documento escaneado; consulte la función 8. Si el documento cambia,
hay que repetir la búsqueda para no utilizar selecciones de una revisión anterior.

## 5. Elegir elementos superpuestos

En **Elementos de la zona**, pulse **Seleccionar zona** y dibuje un rectángulo
en la página. La lista permite distinguir elementos que ocupan el mismo lugar:
texto visible, texto OCR invisible e imágenes.

Elija el nivel **Líneas**, **Palabras** o **Caracteres**, y pulse la fila concreta
que quiere seleccionar. La aplicación centra esa región y utiliza sus caracteres
o su instancia de imagen. **Siguiente elemento de la zona** recorre las filas;
**Toda la página** elimina el filtro de zona.

La lista no implica que todo elemento sea editable. Una imagen o un texto puede
aparecer para identificarlo y, aun así, tener un motivo concreto de bloqueo.
Tampoco es una lista de objetos vectoriales: no permite editar las líneas de una
tabla o un logotipo dibujado mediante trazados.

## 6. Guardar una imagen existente

Active **Seleccionar imágenes** y pulse la imagen, o elíjala desde **Elementos de
la zona**. Use **Guardar imagen…** en sus propiedades. También dispone del menú
contextual con el botón derecho y **Guardar / exportar imagen…**.

Elija la ruta ofrecida para exportar la imagen. Esta acción crea un archivo de
imagen y no modifica el PDF. La extensión depende de lo que pueda extraerse o
reconstruirse de esa imagen; no es una captura de toda la página ni una
exportación de sus textos y vectores superpuestos.

Un JPEG sin máscara conserva sus bytes originales. Otros casos compatibles se
exportan como PNG RGB o RGBA, incorporando la transparencia suave cuando se
puede reconstruir. Se exporta la imagen completa del recurso: un recorte, giro
u opacidad aplicados a su colocación en la página no se incorporan a ese archivo.
Se respeta el permiso de copia del PDF. Las máscaras o imágenes que no puedan
extraerse correctamente muestran un motivo concreto de bloqueo.

## 7. Recortar, girar o reemplazar una instancia de imagen

Seleccione una imagen compatible y abra **Recortar / girar / reemplazar…** desde
las propiedades o el menú contextual. El diálogo trabaja sobre la imagen
seleccionada:

1. Dibuje un rectángulo para recortar, ajuste sus esquinas o utilice los campos
   **Izquierda**, **Arriba**, **Derecha** y **Abajo**, expresados en porcentajes.
   **Ctrl+arrastrar** desplaza el rectángulo de recorte.
2. Elija un giro horario de **0°, 90°, 180° o 270°**.
3. Si quiere sustituir su contenido, pulse **Elegir otra imagen…** y seleccione
   un PNG, JPEG, BMP o TIFF compatible.
4. Revise la imagen resultante y sus dimensiones en píxeles. **Restablecer
   recorte y giro** recupera el área completa y el giro cero.
5. Pulse **Ver en el PDF**. Compruebe la vista previa real del documento y
   después **Aplicar cambio**.

El resultado ocupa la caja que tenía la imagen original en la página. Recortar,
girar o elegir otra imagen puede cambiar las proporciones al ajustar el resultado
a esa caja; el diálogo lo advierte. Compruebe ese efecto antes de aplicar y
ajuste posteriormente la colocación si lo necesita.

La imagen editada se genera como RGB/RGBA de ocho bits por canal. Una imagen
CMYK o con un perfil de impresión puede requerir conversión: no se promete
conservar ese perfil en la instancia modificada. La entrada se limita a 50 MB,
40 millones de píxeles y un solo fotograma.

La operación afecta a **esa instancia**. Si el mismo recurso se utiliza en
otras posiciones o páginas, esas apariciones conservan su imagen. Reemplazar
no es una sustitución global por nombre de recurso.

Mover o redimensionar la colocación sigue disponible mediante arrastre, el
tirador de tamaño y **Posición / tamaño…**. Esas acciones son distintas de
recortar o girar los píxeles de la imagen. Los textos y vectores de la página
siguen siendo contenido independiente; editar una imagen no los convierte en
parte de ella.

El motor rechaza imágenes que no puede aislar de recortes, máscaras,
transformaciones o estructuras complejas. La edición exige una instancia
aislable y no se admite en PDFs etiquetados o con formularios. Se bloquean, entre
otros casos, imágenes inline ambiguas, imágenes de estarcido y determinadas
máscaras duras, por color o con fondo de máscara no reproducible. Consulte
[Imágenes 0.8](IMAGENES_V08.md) para el alcance de formatos, recortes y
transparencias.

## 8. Corregir OCR existente: dos situaciones diferentes

### Texto digital visible con un duplicado OCR invisible

Seleccione el **texto visible** y edítelo mediante el recorrido normal. Cuando
el motor puede demostrar que debajo hay palabras OCR duplicadas correspondientes
a las palabras visibles editadas, retira esos duplicados de la capa invisible.
El texto visible nuevo sigue siendo seleccionable y buscable y la vista previa
informa de esa retirada. No borra todas las apariciones de la palabra del
documento.

Si una palabra OCR se extiende hacia otra región o no se puede aislar de sus
vecinos, la operación se bloquea. Seleccione la palabra visible completa cuando
el mensaje lo solicite. La aplicación no elimina indiscriminadamente la capa
OCR para hacer editable un documento.

Se exige que los centros de todos los caracteres OCR afectados queden cubiertos
por la palabra visible, con tolerancias pequeñas. En un cambio de sólo un
carácter puede retirarse el duplicado de la palabra completa: los demás
caracteres siguen existiendo como texto visible. Si no se puede conservar el
orden de búsqueda de ese fragmento, se solicita seleccionar toda la palabra.
La retirada y la edición se aplican juntas; un fallo no deja una limpieza parcial.

### Una imagen escaneada con texto OCR buscable

Si las letras visibles forman parte de una imagen, corregir la capa OCR **no
cambia esas letras**. Para corregir únicamente lo que se selecciona, copia o
busca:

1. Dibuje una zona o liste toda la página en **Elementos de la zona**.
2. Seleccione una palabra o tramo identificado como **OCR**.
3. Active **Corregir sólo la capa OCR buscable**.
4. Escriba una sustitución de una sola línea y genere la vista previa.
5. Revise el aviso de que la apariencia permanece igual, aplique y guarde una
   copia. Reabra el resultado y compruebe también la búsqueda o extracción.

Esta ruta conserva el recurso OCR original y necesita códigos de caracteres
únicos y verificables en él. Puede rechazar un carácter nuevo aunque la fuente
completa instalada en Windows lo contenga. **Ajustar anchura al texto** puede
adaptar su área; también puede desactivarlo y ampliar la anchura explícitamente
dentro de la misma región. No escala la fuente ni permite invadir otra palabra
OCR. El origen izquierdo se conserva. No admite mover esa capa, cambiar
su formato, justificarla, recomponer párrafos ni modificar su imagen. También
se bloquean selecciones discontinuas, operadores o orientaciones no aislables
y capas en documentos etiquetados que requieran actualizar relaciones accesibles.

PDF Modder no reconoce texto de imágenes ni genera una capa OCR nueva. Para
alterar visualmente las letras de un escaneado se necesita otro trabajo sobre
la imagen; este modo no afirma realizarlo.

El alcance técnico y las comprobaciones de esta ruta se detallan en
[Corrección de OCR existente](OCR.md).

## 9. Organizar, duplicar e incorporar páginas

Abra **Organizar páginas…**. Los números de las filas muestran el orden final:
arrastre las miniaturas o utilice **Subir** y **Bajar**. Puede seleccionar varias
filas, **Girar 90° a la derecha**, **Duplicar selección** o **Quitar del orden**.
No puede dejar el PDF sin páginas.

Para insertar, indique **Insertar antes de posición**. El valor posterior a la
última página añade al final. Elija una de estas acciones:

- **Insertar página en blanco**: establezca su anchura y altura en milímetros.
- **Insertar páginas de PDF…**: seleccione los archivos; sus páginas se incorporan
  a esa posición y después pueden ordenarse individualmente.

**Restablecer documento original** deshace el plan del diálogo y recupera el
orden que tenía el trabajo al abrirlo. **Previsualizar orden final** reconstruye
y valida el PDF; después pulse **Aplicar cambio** en la ventana principal.
Cancelar el diálogo conserva el trabajo. Deshacer y Rehacer también recuperan
la organización aplicada. Las copias heredan los cambios que ya tenía su página;
las modificaciones posteriores se asocian a cada instancia.

Para añadir **archivos completos al final** también puede usar **Combinar
PDFs…**, ordenar la lista y mantener marcada **Añadir al final del documento de
trabajo actual**. Al desmarcarla se inicia un trabajo combinado con los archivos
seleccionados y se debe decidir sobre los cambios pendientes del trabajo anterior.
Esta función pide archivos completos; use el organizador para intercalar o
reordenar sus páginas.

Los enlaces internos y marcadores admitidos apuntan a la primera copia final de
su destino. Un enlace a su propia página permanece en esa copia. Si una página
conservada enlaza a una que se excluye, se bloquea la operación. Los marcadores
de páginas excluidas se retiran y se informa de cuáles. Se conservan los
metadatos del documento de trabajo; los de un anexo no los reemplazan.

El organizador está deshabilitado para **PDFs etiquetados**. También se rechazan
firmas, formularios, cifrado/restricciones, destinos nombrados, acciones especiales
y otras estructuras que esta reconstrucción no pueda preservar. No se eliminan
etiquetas o firmas para permitir el cambio. El alcance completo se detalla en
[Organizador de páginas](PAGINAS_V08.md).

## Límites comunes y estado de entrega

La conservación estricta sigue activa: no hay fuentes parecidas elegidas
silenciosamente, reducción automática del tamaño ni compresión de letras para
ocultar un desbordamiento. Si falta una fuente, variante o carácter, consulte
el inspector y asocie un archivo legítimo compatible cuando proceda.

Una operación puede estar disponible en un PDF y bloqueada en otra región del
mismo documento. La vista previa, los mensajes concretos y la validación del
archivo generado determinan el resultado. No se certifica compatibilidad
universal, PDF/UA, PDF/A ni identidad binaria con el original.

La edición de formularios y sus cálculos, la validación criptográfica de firmas,
la redistribución entre páginas, la edición de vectores y el reconocimiento OCR
siguen fuera del alcance. Los PDFs de prueba y sus resultados se documentan en
las pruebas del proyecto; la prueba final del paquete 0.8 se registrará al cerrar
la entrega. Esta guía no traslada a 0.8 las cifras ni los resultados del paquete
archivado 0.7.
