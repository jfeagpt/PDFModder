# PDF Modder 1.7.1

La aplicación y cada PDF abierto comienzan en **Lectura**. Hace clic sobre una
palabra para seleccionarla; arrastra para seleccionar caracteres o varias líneas
del mismo bloque y columna. **Ctrl+C**, el icono Copiar o el menú contextual copian
el texto al portapapeles. El doble clic selecciona una palabra sin abrir el editor.
Se respetan los permisos de copia del documento. La selección de lectura se limita
a la página visible: no mezcla automáticamente columnas ni continúa a otra página.

La rueda desplaza la página visible. Cuando ya has alcanzado el borde inferior,
el siguiente desplazamiento hacia abajo abre la página siguiente, por arriba.
En el borde superior, hacia arriba abre la anterior, por abajo. También siguen
disponibles las miniaturas. No cambia de página durante una escritura, vista
previa o colocación de contenido. No presenta todas las páginas simultáneamente.

Pulsa **Herramientas** para entrar en **Edición**: se preparan las fuentes y las
comprobaciones del documento en el proceso PDF. Después aparecen las herramientas
de contenido, formato, páginas y propiedades. Mantienen sus restricciones reales
de compatibilidad y los paneles inicialmente plegados. Seleccionar/Escribir/Mover
son los tres controles del modo Edición. **Lectura** vuelve al lector sin descartar
los cambios ya aplicados; acepta o cancela primero cualquier borrador pendiente.

La lectura inicial omite el análisis de operadores, la resolución tipográfica y
el catálogo de imágenes para editar. Se renderiza sólo la página solicitada y
las miniaturas visibles, con caché limitada. No se atribuye una mejora porcentual
de velocidad ni compatibilidad adicional a este cambio.

Las versiones públicas se descargan de
[jfeagpt/PDFModder](https://github.com/jfeagpt/PDFModder/releases).
**Buscar actualizaciones** consulta las entregas estables y descarga el instalador
verificando tamaño y SHA-256. Es una consulta manual, sin cuentas en la aplicación.
Si una instalación anterior consulta otro repositorio, instala esta entrega para
pasar al canal público actual.

Las comprobaciones dirigidas y del ejecutable figuran en RESULTADOS_V171.md y
ENTREGA.json. Se usa corpus sintético reproducible; no se repite el corpus completo
de versiones anteriores ni se afirma una prueba en otro ordenador físico.
