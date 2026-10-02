# Instalar PDF Modder 0.8.2 en otro ordenador

Use `PDFModder-v0.8.2-Instalar.exe` en Windows 11 x64. Copia todos los archivos
del programa y comprueba su tamaño y SHA-256 antes de terminar. No necesita
Python, conexión, permisos de administrador ni instalar Qt por separado.
La carpeta predeterminada se encuentra dentro de los programas de su usuario.

La revisión 0.8.2 incluye las [correcciones de edición y movimiento](CORRECCIONES_V082.md).
El instalador incluye el mismo editor que su ZIP portable verificado.
Se instala en una carpeta 0.8.2 independiente y crea un acceso directo con esa versión;
conserve la instalación 0.8 anterior hasta comprobar la nueva.
Las DLL de Qt siguen siendo archivos separados y reemplazables. El código y
las licencias de la aplicación y del instalador están incluidos en `_internal`.

## Mensaje shiboken6/libshiboken does not exist

En la versión de PySide6 incluida, ese mensaje aparece cuando no se reconoce
la carpeta `_internal/shiboken6` junto a `_internal/PySide6`. La ruta
`libshiboken` pertenece a una alternativa para árboles de compilación; no hay
que crearla manualmente ni descargar DLL sueltas.

El ZIP distribuido contiene `Shiboken.pyd`, `shiboken6.abi3.dll` y las DLL de
soporte dentro de esa carpeta. La captura de otro equipo no permite determinar
si faltaron al extraer/copiar, se está abriendo otra copia o existe un problema
de acceso. No se atribuye el fallo a OneDrive ni al antivirus sin comprobarlo.

Instale con el EXE nuevo y abra el programa desde su ubicación de instalación
o acceso directo. Conserve su carpeta anterior y sus PDFs hasta comprobarlo.
Si usa el ZIP portable, extraiga TODO su contenido a una carpeta local y abra
`PDFModder.exe` manteniendo `_internal` a su lado.

## Comprobaciones y reproducción

El ZIP original pasó también el recorrido de 23 pasos tras extraerse en otra
carpeta con espacios, con un directorio de trabajo distinto y sin las variables
de entorno de Python/Qt; PATH contenía sólo Windows. Es una prueba en el equipo
de desarrollo bajo esas condiciones, no una ejecución en el ordenador afectado.
Los informes del instalador y de la aplicación instalada se guardan en
`output/portability/`; consulte `releases/v0.8.2/INSTALADOR.json` para el estado final de 0.8.2.
Los resultados de 0.8 citados arriba son históricos y no sustituyen la comprobación del nuevo paquete.

Construcción offline desde Windows con .NET Framework y el ZIP verificado:

```powershell
.venv\Scripts\python.exe scripts\build_installer.py
.venv\Scripts\python.exe scripts\verify_installer.py
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File scripts\verify_installer_ui.ps1 -Version 0.8.2
```

El instalador permite pruebas automatizadas con `--silent --dir RUTA`
`--no-shortcut --no-launch --report INFORME_JSON`. La instalación interactiva
permite elegir la carpeta. Una instalación anterior reconocida se conserva
como copia; una carpeta ajena no se reemplaza silenciosamente.

La comprobación crea carpetas nuevas dentro de `output/portability`, compara
todos los archivos instalados, simula una dependencia ausente y comprueba la
reparación con copia de seguridad. Después ejecuta los 23 pasos del editor
instalado con un directorio de trabajo y entorno independientes. No instala en
el perfil real del usuario ni crea accesos directos durante esa comprobación.

La prueba de la ventana utiliza `Application.Run` y un temporizador de WinForms,
con detección de accesos desde otro hilo. Espera la finalización del trabajo
antes de cerrar. El primer arnés de pruebas usaba `DoEvents` y podía forzar
`Dispose` mientras la ventana seguía ocupada; se sustituyó tras detectar el
aviso de .NET durante la comprobación. El arranque normal del instalador usa
`Application.Run` desde su primera versión.

Las operaciones de archivo admiten rutas largas mediante el formato extendido
de Windows. No se modifica el registro ni se requieren permisos de administrador.

Referencias: [estructura de PyInstaller](https://pyinstaller.org/en/v6.18.0/runtime-information.html)
y [despliegue de Qt for Python](https://doc.qt.io/qtforpython-6.10/deployment/deployment-pyinstaller.html).
