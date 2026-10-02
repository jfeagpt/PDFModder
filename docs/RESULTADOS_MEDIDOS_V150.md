# Resultados medidos de PDF Modder 1.5.0

Generado a partir de los informes de esta compilación. Las huellas completas se conservan en ENTREGA.json; los PDF privados no se distribuyen.

- Pruebas de fuente: **801 aprobadas**, 0 omitidas; cero fallos y errores.
- Ejecutable Windows: **7 recorridos aprobados** con PATH reducido a Windows.
- Cuatro PDF privados: **53 operaciones completadas** y **11 bloqueadas**; cero fallos inesperados.
- Los cuatro originales conservan sus huellas SHA-256.
- Poppler: 6 comparaciones a 144 ppp; cero píxeles fuera de tolerancia fuera de las regiones de texto modificadas.
- Máxima zona excluida en esas comparaciones: 0.174408% de la página.

| Recorrido del ejecutable | Pasos | Segundos |
| --- | ---: | ---: |
| extended | 17 | 10.448 |
| tagged | 16 | 3.864 |
| clipped | 25 | 4.638 |
| v08 | 23 | 6.071 |
| v09 | 14 | 11.104 |
| compat | 35 | 10.99 |
| v150 | 15 | 10.589 |

La instalación y desinstalación se acreditan por separado en `INSTALACION-VERIFICADA.json`. Estas pruebas no equivalen a otro ordenador físico ni a compatibilidad universal. Consulte RESULTADOS_V150.md para el protocolo y límites.
