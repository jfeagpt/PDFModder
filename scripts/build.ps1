[CmdletBinding()]
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Ejecute primero .\scripts\install.ps1 -Development.' }
function Assert-Exit([string]$Operation) {
    if ($LASTEXITCODE -ne 0) { throw "$Operation falló (código $LASTEXITCODE)." }
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -c "import sys,struct; assert sys.platform == 'win32' and sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Compile en Windows con Python 3.12 x64'; import PyInstaller"
    Assert-Exit 'La comprobación del entorno de compilación'
    & $pythonPath -m pip check
    Assert-Exit 'La comprobación de dependencias'
    if (-not $SkipTests) {
        & $pythonPath -m pytest --junitxml 'output/pytest-results.xml'
        Assert-Exit 'Las pruebas'
    }
    & $pythonPath (Join-Path $PSScriptRoot 'collect_licenses.py')
    Assert-Exit 'La recopilación de licencias y código'
    & $pythonPath -m PyInstaller --noconfirm --clean 'PDFModder.spec'
    Assert-Exit 'PyInstaller'
    & $pythonPath (Join-Path $PSScriptRoot 'build_uninstaller.py')
    Assert-Exit 'La compilación del desinstalador'
    & $pythonPath (Join-Path $PSScriptRoot 'build_signing_bridge.py')
    Assert-Exit 'La compilación del acceso a certificados de Windows'
    $executable = Join-Path $projectRoot 'dist/PDFModder/PDFModder.exe'
    if (-not (Test-Path -LiteralPath $executable)) { throw 'La compilación no ha producido PDFModder.exe.' }
    Write-Host "Paquete creado: $executable"
    Write-Host 'Distribuya la carpeta PDFModder completa: incluye DLL reemplazables, licencias y código en _internal.'
    Write-Host 'Verifique el ejecutable abriendo, editando y guardando un PDF antes de distribuir esta compilación.'
} finally {
    Pop-Location
}
