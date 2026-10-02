[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$installationBase = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\PDFModder'))
$reports = [Collections.Generic.List[object]]::new()
function Assert-NoDirectoryLinks([string]$Path) {
    $cursor = $Path
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "No se sigue un enlace: $cursor" }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
foreach ($version in @('0.8.1', '0.8.2')) {
    $target = [IO.Path]::GetFullPath((Join-Path $installationBase $version))
    if (-not $target.StartsWith($installationBase + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Destino fuera del directorio de instalaciones.' }
    if (-not (Test-Path -LiteralPath $target)) { $reports.Add(@{ version=$version; status='absent' }); continue }
    Assert-NoDirectoryLinks $target
    $markerPath = Join-Path $target '.pdfmodder-installation.json'
    Assert-NoDirectoryLinks $markerPath
    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if ($marker.application_id -ne 'PDFModder.Windows.PerUser' -or $marker.version -ne $version) { throw "Instalación no reconocida: $target" }
    $exe = Join-Path $target 'PDFModder.exe'
    foreach ($process in @(Get-Process -Name PDFModder -ErrorAction SilentlyContinue)) {
        if (-not $process.Path -or $process.Path -eq $exe) { throw "Cierre PDF Modder antes de continuar: $target" }
    }
    $installer = Join-Path $projectRoot "releases\v$version\PDFModder-v$version-Instalar.exe"
    $assembly = [Reflection.Assembly]::LoadFile($installer)
    $resource = $assembly.GetManifestResourceStream('PDFModderPayload.tsv')
    if ($null -eq $resource) { throw "El instalador no contiene su inventario: $installer" }
    $reader = [IO.StreamReader]::new($resource)
    try { $inventory = $reader.ReadToEnd() } finally { $reader.Dispose() }
    $owned = @{}
    foreach ($row in ($inventory -split "`n")) {
        if (-not $row.Trim()) { continue }
        $parts = $row.TrimEnd("`r") -split "`t", 3
        if ($parts.Count -ne 3 -or $parts[0] -notmatch '^[0-9a-f]{64}$' -or -not $parts[2].StartsWith('PDFModder/')) { throw 'Inventario inválido.' }
        $relative = $parts[2].Substring(10)
        if ($relative -match '(^|/)(\.|\.\.)(/|$)|[:\\]' -or [IO.Path]::IsPathRooted($relative)) { throw 'Ruta inválida en el inventario.' }
        $file = [IO.Path]::GetFullPath((Join-Path $target $relative))
        if (-not $file.StartsWith($target+'\', [StringComparison]::OrdinalIgnoreCase) -or $owned.ContainsKey($file)) { throw 'Ruta repetida o fuera de instalación.' }
        $owned[$file] = $parts[0]
    }
    $files = [Collections.Generic.List[string]]::new()
    $dirs = [Collections.Generic.List[string]]::new()
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($target)
    while ($pending.Count) {
        $dir = $pending.Pop(); $dirs.Add($dir)
        foreach ($item in Get-ChildItem -LiteralPath $dir -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Elemento enlazado: $($item.FullName)" }
            if ($item.PSIsContainer) { $pending.Push($item.FullName) } else { $files.Add($item.FullName) }
        }
    }
    $delete = [Collections.Generic.List[string]]::new()
    $preserve = [Collections.Generic.List[string]]::new()
    foreach ($file in $files) {
        if ($file -eq $markerPath) { continue }
        if ($owned.ContainsKey($file) -and (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -eq $owned[$file]) { $delete.Add($file) }
        else { $preserve.Add($file) }
    }
    if (-not $delete.Contains($exe)) { throw "El ejecutable difiere del instalador archivado; no se borra: $exe" }
    $shortcuts = [Collections.Generic.List[string]]::new()
    $shell = New-Object -ComObject WScript.Shell
    try {
        foreach ($directory in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))) {
            $linkPath = Join-Path $directory "PDF Modder $version.lnk"
            if (Test-Path -LiteralPath $linkPath) {
                $link = $shell.CreateShortcut($linkPath)
                try { if ($link.TargetPath -eq $exe) { $shortcuts.Add($linkPath) } }
                finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) }
            }
        }
    } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) }
    if ($Apply) {
        foreach ($file in $delete) {
            Assert-NoDirectoryLinks $file
            if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $owned[$file]) { throw "El archivo cambió; se detiene: $file" }
            Remove-Item -LiteralPath $file -Force
        }
        Remove-Item -LiteralPath $markerPath -Force
        foreach ($shortcut in $shortcuts) { Remove-Item -LiteralPath $shortcut -Force }
        foreach ($directory in ($dirs | Sort-Object Length -Descending)) {
            Assert-NoDirectoryLinks $directory
            if (@(Get-ChildItem -LiteralPath $directory -Force).Count -eq 0) { Remove-Item -LiteralPath $directory -Force }
        }
    }
    $reports.Add(@{version=$version;directory=$target;applied=[bool]$Apply;files=$delete.Count;shortcuts=@($shortcuts.ToArray());preserved=@($preserve.ToArray())})
}
$result = @{ created_utc=[DateTime]::UtcNow.ToString('o'); applied=[bool]$Apply; installations=@($reports.ToArray()) }
$out = Join-Path $projectRoot 'output\uninstall-legacy'
[void][IO.Directory]::CreateDirectory($out)
$filename = if ($Apply) { 'removed.json' } else { 'plan.json' }
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $out $filename) -Encoding utf8
$result | ConvertTo-Json -Depth 8
