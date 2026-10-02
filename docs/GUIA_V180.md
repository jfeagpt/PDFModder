# PDF Modder 1.8.0

## Lectura continua

Al abrir un documento se inicia Lectura. Las páginas aparecen una debajo de otra:
la rueda desplaza el mismo documento y permite ver simultáneamente el final de
una página y el inicio de la siguiente. Las miniaturas y la búsqueda conservan
sus accesos a páginas. Zoom y Ajustar página/anchura actúan sobre este lector.

Se renderizan las páginas visibles y cercanas; las imágenes y los modelos de texto
tienen cachés limitadas. El proceso PDF permanece separado de la interfaz y se usa
de forma serial. Desplazarse por un documento largo no carga todas sus páginas en
alta resolución.

Arrastra sobre el texto para seleccionar varios renglones, párrafos o páginas.
Al acercarte al borde de la vista durante el arrastre, esta se desplaza. También
puedes marcar el comienzo, desplazarte a otra página y pulsar Mayús+clic en el final.
Ctrl+C o el menú contextual Copiar incluye las páginas intermedias aunque sus
imágenes hayan salido de la caché. Doble clic selecciona una palabra. La selección
de Lectura no activa el editor ni modifica el documento.

Se infiere el orden de lectura a partir de líneas y columnas. En diseños complejos
no se garantiza el orden semántico de todos los documentos. No se realiza OCR: una
página que solo contiene una fotografía no tiene texto para copiar. Se respetan
las restricciones de copia del PDF.

Pulsa Herramientas para preparar la página actual y entrar en Edición. Una selección
que cruza páginas sigue siendo una selección para copiar: no se convierte en un
único bloque editable.

## Actualizar

Buscar actualizaciones consulta las versiones públicas de jfeagpt/PDFModder en
GitHub Releases. No requiere una cuenta en la aplicación. Actualizar ahora descarga
el instalador y comprueba su SHA-256 antes de iniciarlo. Si hay cambios pendientes,
puedes guardarlos o cancelar la actualización antes de cerrar la aplicación.

El instalador instala y verifica la nueva versión primero y después ejecuta el
desinstalador de la instalación anterior identificada. Solo retira archivos de esa
instalación, comprobados mediante su inventario. Conserva preferencias, PDF y archivos
ajenos o modificados. Si la retirada no puede completarse, informa del problema;
no borra carpetas indiscriminadamente. Una copia portable no se trata como una
instalación que deba eliminarse automáticamente.

El instalador iniciado por una versión antigua también ofrece retirar la versión
anterior registrada, con esa opción activada inicialmente. Este proceso no barre
todas las carpetas históricas ni elimina copias que no pueda identificar.

## Qué es un PDF etiquetado

Las etiquetas describen la estructura accesible: títulos, párrafos, listas, tablas
y relaciones y orden de lectura para lectores de pantalla. No son marcas visibles,
contraseñas ni metadatos de autor. La apariencia de una página puede ser idéntica
con o sin etiquetas, pero su accesibilidad cambia.

En Herramientas, dentro de las herramientas adicionales, usa **Quitar etiquetas de
accesibilidad…**. El aviso explica la pérdida de accesibilidad. La operación prepara
una vista previa del PDF real; acepta para incorporarla al historial y usa Guardar
como para producir la copia. Cancelar y Deshacer recuperan el documento etiquetado.
El original sigue intacto.

Se retiran el árbol estructural y sus asociaciones. Se preservan el texto, los
operadores gráficos y de contenido marcado, ActualText, capas, formularios, enlaces,
anotaciones, marcadores, metadatos y adjuntos en los casos comprobados. Se valida el
texto y la apariencia; no se rasterizan las páginas.

Se bloquea la retirada en documentos cifrados, firmados o con estructuras que no
puedan verificarse. Quitar etiquetas pierde la estructura accesible y no resuelve
automáticamente otros límites del motor, contenido marcado complejo, firmas o
permisos. Mantenerlas sigue siendo preferible cuando su edición es compatible.

## Alcance de las comprobaciones

Pruebas dirigidas con PDF reproducibles y un recorrido del ejecutable Windows de
lectura, copia, edición, movimiento, historial y guardado/reapertura. La retirada
de etiquetas contrasta extracción y píxeles a 144 ppp. La actualización se ensaya
con instalaciones aisladas; no se usan documentos ni certificados personales.
Los resultados medidos de esta entrega figuran en RESULTADOS_V180.md y en los
informes de instalación y actualización. No se repite el corpus completo histórico
ni se acredita una prueba en otro ordenador físico.
