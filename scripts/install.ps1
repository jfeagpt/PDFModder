[CmdletBinding()]
param(
    [switch]$Development,
    [string]$PythonExe
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts/python.exe'

function Assert-Exit([string]$Operation) {
    if ($LASTEXITCODE -ne 0) { throw "$Operation falló (código $LASTEXITCODE)." }
}

if ($PSVersionTable.PSEdition -eq 'Core' -and -not $IsWindows) {
    throw 'Este instalador está preparado para Windows 11 x64.'
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonExe) {
        & $PythonExe -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Se requiere Python 3.12 x64'"
        Assert-Exit 'La comprobación de Python'
        & $PythonExe -m venv $venvRoot
    } else {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if (-not $launcher) { throw 'Instale Python 3.12 x64 de python.org o indique -PythonExe con su ruta.' }
        & $launcher.Source -3.12 -c "import sys,struct; assert struct.calcsize('P') == 8, 'Se requiere Python x64'"
        Assert-Exit 'La comprobación de Python'
        & $launcher.Source -3.12 -m venv $venvRoot
    }
    Assert-Exit 'La creación del entorno aislado'
}
& $venvPython -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'El entorno existente debe ser Python 3.12 x64'"
Assert-Exit 'La comprobación del entorno aislado'
$requirements = if ($Development) { 'requirements-dev.txt' } else { 'requirements.txt' }
Write-Host 'Instalando únicamente dependencias de Python desde PyPI. La aplicación no necesita red para funcionar.'
& $venvPython -m pip --disable-pip-version-check install --only-binary=:all: -r (Join-Path $projectRoot $requirements)
Assert-Exit 'La instalación de dependencias'
& $venvPython -m pip check
Assert-Exit 'La comprobación de dependencias'
Write-Host 'Entorno listo. Inicie con .\scripts\start.ps1'
