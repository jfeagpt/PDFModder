# Instalación y desinstalación en 0.8.3

Ejecute `PDFModder-v0.8.3-Instalar.exe` y pulse **Instalar**. Se instala
para el usuario actual, con el icono elegido y sin necesitar Python.

Puede desinstalar mediante:

- **Configuración → Aplicaciones → Aplicaciones instaladas → PDF Modder 0.8.3 → Desinstalar**.
- El acceso **Desinstalar PDF Modder 0.8.3** del menú Inicio.
- `Desinstalar.exe` en la carpeta de instalación.

Cierre el editor antes de desinstalar. El programa bloquea la retirada si
detecta el editor abierto en esa instalación, sin forzar su cierre.

El desinstalador usa el inventario de archivos creado al instalar y elimina
sólo los archivos que siguen coincidiendo con ese inventario. Conserva los
documentos propios, archivos añadidos o modificados y preferencias del editor,
incluidas asociaciones de fuentes. Si quedan archivos conservados, lo indica
al terminar. No elimina otras versiones ni carpetas de código o de entregas.

El registro y los accesos directos se eliminan sólo cuando apuntan a esta
instalación. Se rechazan rutas que salgan de ella y enlaces de directorio.
El inventario y el marcador se eliminan al finalizar correctamente.
Los directorios sólo se retiran si quedan vacíos.

La retirada se ejecuta desde una copia temporal del desinstalador para poder
eliminar su ejecutable instalado. Windows puede conservar esa copia pequeña
en su carpeta temporal; no contiene documentos del usuario.

Para administración local:

```powershell
& 'C:\ruta\PDFModder\Desinstalar.exe' --silent --dir 'C:\ruta\PDFModder' --report 'C:\ruta\informe-desinstalacion.json'
```

El informe debe estar fuera de la carpeta retirada. El relanzamiento temporal
es asíncrono: espere a que aparezca el informe final antes de considerar
terminada la operación.

Construcción reproducible desde el entorno del proyecto:

```powershell
.venv\Scripts\python.exe scripts\collect_licenses.py
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean PDFModder.spec
.venv\Scripts\python.exe scripts\build_current_installer.py
```

La batería focalizada `scripts/verify_uninstaller_v083.py` comprueba
copias aisladas: archivos personales/modificados, rutas peligrosas,
duplicados, metadatos protegidos, bloqueo y reintento, autodesinstalación y
repetición sin cambios y rutas largas. Los informes quedan en
`output/portability/desinstalador-*/verificacion-desinstalador.json`.
`scripts/verify_install_uninstall_v083.py` comprueba por separado la instalación
del paquete final, el registro, los accesos y su posterior retirada; deja
el informe en `output/portability/install-uninstall-v083-*/resultado.json`.
Las pruebas históricas de edición PDF se mantienen en sus informes originales;
no acreditan esta nueva compilación.

Referencias oficiales: [entrada de desinstalación de Windows](https://learn.microsoft.com/en-us/windows/win32/msi/uninstall-registry-key)
y [desinstalar aplicaciones desde Windows](https://support.microsoft.com/en-us/windows/uninstall-or-remove-apps-and-programs-in-windows-4b55f974-2cc6-2d2b-d092-5905080eaf98).
