# Instalador con el icono elegido

La compilación de PDF Modder 0.8.2 con el icono elegido se empaqueta en
`releases/v0.8.2-icono/PDFModder-v0.8.2-Instalar.exe`.
El instalador incorpora el programa completo, sus dependencias, las licencias
y el código correspondiente. Instala para el usuario actual y permite crear
un acceso directo con el icono del editor.

Esta entrega se compila sin ejecutar pruebas ni abrir el instalador, por
indicación expresa del usuario. Las comprobaciones históricas de 0.8.2
documentadas en otros archivos no acreditan esta nueva compilación.

Esta nota describe la entrega histórica 0.8.2 con icono. El script de
construcción sigue la versión del código actual (0.8.3 o posterior).
Para reconstruir su instalador a partir de `dist/PDFModder`:

```powershell
.venv\Scripts\python.exe scripts\build_current_installer.py
```

El proceso genera el inventario necesario para que el instalador conserve
sus controles de integridad durante la instalación. No ejecuta una instalación
ni pruebas del programa. La entrega anterior de `releases/v0.8.2` se conserva.
