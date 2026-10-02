# Controles y alcance de 0.9

## Edición y vista previa

Seleccionar marca caracteres de la misma línea sin incorporar otra columna.
Escribir coloca el cursor; Mover arrastra el contenido. Dentro del editor las
flechas siempre desplazan el cursor. Ctrl+A selecciona todo el cuadro, Ctrl+Intro
acepta y Esc cancela. Una sesión aceptada ocupa una entrada en Deshacer.

La barra modifica el rango seleccionado. Sin rango establece el estilo de los
caracteres siguientes. Negrita y cursiva exigen variantes reales. El subrayado es
vectorial y el espaciado entre caracteres está en puntos PDF.
El subrayado de texto semitransparente se bloquea expresamente: en esta versión
no se reproduce aún la opacidad de esa línea vectorial. Sin subrayado se conserva
la opacidad del texto compatible.

La composición Qt puede diferir en rasterización y métricas de cursor de MuPDF.
La muestra lateral y Ver PDF real proceden del PDF candidato, generado por la misma
operación de aceptación. Un error identifica el borrador como no validado aunque
exista una vista anterior correcta. Los resultados atrasados se descartan al seguir
escribiendo. Cancelar una vista en cálculo no cambia el documento. Aceptar valida
el último borrador; un fallo permite continuar corrigiéndolo.
Esc también puede cancelar mientras se valida la aceptación. La incorporación
final al historial es una operación breve e indivisible; después puede deshacerse.

## Áreas, párrafos y celdas

Los tiradores modifican el área sin escalar letras. En un área fija se redistribuye
sólo su contenido y se informa si falta espacio. Intro inicia un párrafo con espacios
anterior/posterior; Mayús+Intro es un salto del mismo párrafo. Tab utiliza topes
configurados. Las sangrías son independientes de la posición absoluta del cuadro.
Para redistribuir toda una línea en el editor sobre la página, seleccione la línea
completa. La opción «Ajustar línea desde el panel lateral» corresponde a la ruta
anterior de sustitución lateral y a la edición conservadora OCR/etiquetada.

Objetos y bloques lista líneas e instancias de imagen. Ctrl/Mayús permiten selección
múltiple. Arrastrar filas establece el orden de los fragmentos antes de unirlos.
Unir abre el texto combinado para revisar: sólo Aceptar lo recompone en el PDF.
Dividir pide los caracteres del primer fragmento y crea dos grupos de edición,
sin introducir saltos ni mover letras. Esto permite delimitar celdas manualmente.

## Grupos y orden

Los grupos se guardan en el PDF como datos propios de edición. Cada miembro se
verifica por contenido y posición antes de utilizarlo. Alinear usa el rectángulo
conjunto. Distribuir mantiene sus extremos y establece separaciones iguales;
si no hay espacio, lo informa. El lote se acepta o descarta íntegro.

Traer delante/Enviar detrás requiere ámbitos PDF completos, autocontenidos y sin
vecinos no seleccionados. No reorganiza el árbol accesible ni separa formularios
complejos. Una operación incompatible muestra su causa; no elimina protecciones.

## Imágenes

Encajar conserva la imagen entera en el marco. Rellenar recortando lo cubre con
proporciones conservadas. Estirar las cambia explícitamente. Giro libre y volteos
se representan mediante la matriz PDF. Los tiradores respetan el bloqueo opcional
de proporciones. Cambios de una instancia no reemplazan otras apariciones compartidas.

El recorte conserva los píxeles subyacentes y permite recuperar el encuadre: no sirve
para eliminar información confidencial. Importar/reemplazar puede normalizar a
RGB/RGBA; no se promete equivalencia de perfiles CMYK de impresión.

## Copiar formato

Exige una selección uniforme, verifica su recurso y permite añadir texto en la
misma página. Si cambia el documento debe copiarse de nuevo. Una fuente parcial
puede carecer de los caracteres nuevos; no se sustituye silenciosamente.

La edición rica no convierte OCR invisible en letras visibles ni crea etiquetas
accesibles nuevas. Desde 0.9.1 admite texto etiquetado compatible con recortes
conservando sus relaciones; las demás selecciones específicas mantienen su ruta
conservadora. Véase CORRECCIONES_V091.md para el soporte ampliado y sus límites.
