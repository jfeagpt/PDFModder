[CmdletBinding()]
param([string]$Pdf)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Falta el entorno local. Ejecute primero .\scripts\install.ps1 (requiere red para instalar dependencias).'
}
$entrypoint = Join-Path $projectRoot 'run_pdfmodder.py'
if (-not (Test-Path -LiteralPath $entrypoint)) { throw "No se encuentra $entrypoint" }
# El arranque no instala, actualiza ni descarga ningún componente.
if ($Pdf) {
    $pdfPath = (Resolve-Path -LiteralPath $Pdf).Path
    & $pythonPath $entrypoint $pdfPath
} else {
    & $pythonPath $entrypoint
}
if ($LASTEXITCODE -ne 0) { throw "PDF Modder terminó con código $LASTEXITCODE." }
