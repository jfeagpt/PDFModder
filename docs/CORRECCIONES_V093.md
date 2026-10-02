# Correcciones 0.9.3

## Eliminación de páginas

El bloqueo genérico de `/AcroForm` y `/Names` rechazaba también formularios vacíos
y destinos con nombre compatibles. Ahora se analizan esas estructuras: se conserva
el formulario vacío y sus recursos, se remapean los destinos a las páginas retenidas
y se eliminan sólo los destinos hacia páginas excluidas. Los destinos que ya carecían
de página se conservan. También se admite extracción, reordenación, rotación e
inserción de páginas en blanco dentro de este alcance.

Siguen bloqueados los formularios con campos reales, acciones, árboles de nombres
no admitidos, enlaces con destinos de nombre no compatibles y combinaciones no
soportadas con etiquetado. Duplicar o combinar documentos con estos destinos
requiere soporte adicional; los controles correspondientes no se habilitan.

## Movimiento de texto

La comparación de operadores confundía el redondeo decimal de la escritura PDF
con una alteración ajena al movimiento. Se compara ahora con los mismos operadores
serializados que se envían al motor. La comparación sigue siendo exacta: no se
relajan la validación visual, las comprobaciones de recursos ni la protección
de los caracteres vecinos. Una prueba comprueba que una alteración ajena real
continúa siendo rechazada.

## Comprobaciones realizadas

- 54 pruebas automatizadas dirigidas: 10 de catálogo, 40 de operaciones de páginas,
  dos regresiones de organizador/capacidades y dos de serialización del movimiento.
- MAPA BIODIVERSIDAD aportado: eliminar páginas 2 y 4, guardar y reabrir. Quedan
  10 páginas, sin diferencias de píxeles en las páginas conservadas a 144 ppp.
  Los destinos pasan de 67 a 65; se conservan los 56 destinos que ya tenían destino nulo.
- En el mismo documento: mover `2025` 30 puntos hacia la derecha, guardar y reabrir.
  Conserva las 12 páginas y el texto real. No hay diferencias visuales fuera de
  los rectángulos individuales de los caracteres de origen y destino a 144 ppp.
- El PDF original se conserva intacto. Los documentos y resultados privados no
  forman parte del código distribuido.

Por petición del usuario se limitan las comprobaciones a estas correcciones.
No se ha ejecutado la batería completa ni se acredita una prueba del ejecutable
final o de instalación/desinstalación de esta compilación. Los resultados de
versiones anteriores no se presentan como pruebas de esta entrega.
