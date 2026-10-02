# Resultado de aceptación independiente

Resultado: **PASS**, medido sobre el corpus sintético indicado en `output/acceptance/report.json`.

Se cambió la fecha a 11/09/2026, el importe a 12.345,67 € con ancho explícito de 180 pt y anclaje derecho, PALABRA a VOCABLO con ancho explícito de 70 pt y anclaje derecho, y se movió una línea +10 pt en X, +15 pt en Y. VOCABLO es más largo: el anclaje derecho lo amplía hacia el margen izquierdo libre conservando el espacio y el texto vecino. Se guardó una copia y se reabrió.

Ejecución: Windows-11-10.0.26200-SP0; Python 3.12.10; PyMuPDF 1.26.7; pypdf 6.6.0. Tiempo total medido: 3.626 s.

La extracción independiente pypdf confirma los cambios, tres TOTAL legítimos en página 1 y la página 2 sin cambios. Cada operación comprueba caracteres vecinos, incluidos los que se encuentran dentro de las regiones excluidas del análisis visual. Cada carácter movido desaparece del origen y existe una sola vez en el destino. El archivo original conserva su SHA-256.

| Página | Píxeles comprobados | Excluidos | Máximo cambio fuera de máscara | Píxeles > 8/255 |
|---|---:|---:|---:|---:|
| 1 | 1971296 | 1.629973 % | 0 | 0 |
| 2 | 2003960 | 0.0 % | 0 | 0 |

Poppler usa `-cropbox -r 144`. Solo se excluyen las cajas de los caracteres originales y nuevos de las cuatro operaciones, ampliadas 0,75 pt; no líneas, bloques ni páginas completas. El umbral 8/255 permite redondeo leve del antialias. La página 2 exige identidad exacta píxel a píxel sin exclusiones.

Reproducir: `.\.venv\Scripts\python.exe scripts\acceptance_report.py`. Si Poppler no se descubre automáticamente, indicar `--poppler RUTA_A_PDFTOPPM`.

Este informe solo acredita estas operaciones y este corpus. No mide compatibilidad universal ni valida firmas criptográficas reales; los demás escenarios se comprueban en las pruebas automatizadas del proyecto.
