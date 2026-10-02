# Comprobación del instalador de Windows 0.8

Fecha: 14 de septiembre de 2026. Windows 11 x64, en el equipo de desarrollo.
No se ha ejecutado esta entrega en el ordenador remoto que notificó el fallo.

Archivo: `PDFModder-v0.8-Instalar.exe`, 96.780.288 bytes.
SHA-256: `a25e9f764a8f5e84634067d87e95f24b42b597b67190b792a5aa4a36a8d7d0c9`.
El editor incluido conserva la huella
`f981ccec0c1939139de5bfb8a7b0559045af77a2b4036361f2676d01a1f37cea`.

| Comprobación | Resultado |
| --- | --- |
| Instalación en carpeta con espacios, acento y rutas largas | 701 archivos idénticos al paquete, verificados también por Python |
| Reparación de una instalación con Shiboken ausente | Reinstalación completa; copia anterior conservada, incluido un PDF de prueba añadido por el usuario |
| Carpeta ajena con un PDF | Rechazo sin modificarla |
| Informe existente | Rechazo antes de instalar; informe conservado |
| SHA de Shiboken alterado deliberadamente en un paquete de prueba | Error de integridad concreto; no se publica la instalación |
| Editor instalado, con entorno Python/Qt limpiado y PATH limitado a Windows | 23 pasos completos: edición, imágenes, páginas, guardado y reapertura |
| Ventana del instalador con `Application.Run` y detección de acceso entre hilos | Finaliza y se cierra sin excepciones; 127 eventos del temporizador durante la instalación |

Duraciones observadas de procesos: instalación 20,641 s; reparación 14,994 s;
recorrido del editor instalado 6,558 s. La prueba de ventana duró 14,648 s.
Son mediciones puntuales de este equipo, no garantías de rendimiento.

La prueba antigua de ventana tenía un error propio: iniciaba el trabajo fuera
de un bucle WinForms permanente y podía forzar su destrucción mientras seguía
ocupada. Se sustituyó por un bucle real y cierre después de finalizar. Dos
ejecuciones posteriores completaron el recorrido sin ese aviso de .NET.

Reproducción: `scripts/build_installer.py`, `scripts/verify_installer.py` y
`scripts/verify_installer_ui.ps1`. El constructor deja `tested: false`; los
informes de las ejecuciones deben corresponder al SHA exacto que se entrega.
Los informes detallados se guardan localmente en `output/portability`; no se
publican archivos del usuario ni rutas de su perfil en el repositorio.

El ZIP portable previo también pasó 23 pasos tras extraerse en otra carpeta.
El mensaje original `shiboken6/libshiboken does not exist` indica ausencia o
inaccesibilidad de `_internal/shiboken6` en la copia afectada. La causa concreta
en ese otro ordenador no ha podido determinarse desde una captura.
