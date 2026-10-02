# Run with Windows PowerShell 5.1 -STA. Only controls of our loaded installer are used.
param([string]$Version = '')
$ErrorActionPreference = 'Stop'
[AppContext]::SetSwitch('Switch.System.IO.UseLegacyPathHandling', $false)
[AppContext]::SetSwitch('Switch.System.IO.BlockLongPaths', $false)
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $Version) {
    $versionSource = [IO.File]::ReadAllText((Join-Path $root 'pdfmodder/__init__.py'))
    $versionMatch = [regex]::Match($versionSource, '__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"')
    if (-not $versionMatch.Success) { throw 'No se encuentra la versión de PDF Modder.' }
    $Version = $versionMatch.Groups[1].Value
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'La versión debe tener tres componentes numéricos.' }
$label = 'v' + $Version
$exe = Join-Path $root ('releases/' + $label + '/PDFModder-' + $label + '-Instalar.exe')
if (-not (Test-Path -LiteralPath $exe) -and $Version.EndsWith('.0')) {
    $label = 'v' + $Version.Substring(0, $Version.Length - 2)
    $exe = Join-Path $root ('releases/' + $label + '/PDFModder-' + $label + '-Instalar.exe')
}
# Resolve/load the hash command before entering the WinForms callback. Module
# autoload can be unavailable inside a Timer delegate in Windows PowerShell.
$installerHash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
$qa = Join-Path $root ('output/portability/ui-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss'))
[IO.Directory]::CreateDirectory($qa) | Out-Null
$assembly = [Reflection.Assembly]::LoadFrom($exe)
$optionsType = $assembly.GetType('PdfModderInstallation.Options')
$options = [Activator]::CreateInstance($optionsType, $true)
$destination = Join-Path $qa 'PDFModder'
$optionsType.GetField('Directory').SetValue($options, $destination)
$optionsType.GetField('Shortcut').SetValue($options, $false)
$formType = $assembly.GetType('PdfModderInstallation.InstallerWindow')
$flags = [Reflection.BindingFlags]'Instance,Public,NonPublic'
[Windows.Forms.Application]::EnableVisualStyles()
$form = [Activator]::CreateInstance($formType, $flags, $null, @($options), $null)
function Capture-Installer([string]$name) {
    $bitmap = New-Object Drawing.Bitmap($form.Width, $form.Height)
    try {
        $form.DrawToBitmap($bitmap, [Drawing.Rectangle]::new(0, 0, $form.Width, $form.Height))
        $bitmap.Save((Join-Path $qa $name), [Drawing.Imaging.ImageFormat]::Png)
    } finally { $bitmap.Dispose() }
}
$button = $form.Controls.Find('installButton', $true)[0]
$status = $form.Controls.Find('installationStatus', $true)[0]
$close = $form.Controls.Find('closeButton', $true)[0]
[Windows.Forms.Control]::CheckForIllegalCrossThreadCalls = $true
$script:phase = 0
$script:pulses = 0
$script:failure = $null
$script:report = $null
$clock = [Diagnostics.Stopwatch]::new()
$timer = [Windows.Forms.Timer]::new()
$timer.Interval = 100
# Start and observe the operation INSIDE the WinForms message loop. DoEvents
# alone can uninstall SynchronizationContext before BackgroundWorker starts.
$timer.add_Tick({
    try {
        if ($script:phase -eq 0) {
            if ($form.Controls.Find('launchApplication', $true)[0].Checked) { throw 'Abrir no debe estar marcado inicialmente.' }
            Capture-Installer 'instalador-inicio.png'
            $script:phase = 1
            $clock.Start()
            $button.PerformClick()
            if ($button.Enabled -or $close.Enabled) { throw 'Los controles deben bloquearse mientras instala.' }
            return
        }
        $script:pulses++
        if ($close.Enabled) {
            Capture-Installer 'instalador-fin.png'
            if ($button.Text -ne 'Instalado') { throw $status.Text }
            if (-not (Test-Path -LiteralPath (Join-Path $destination '_internal/shiboken6/Shiboken.pyd'))) { throw 'Falta Shiboken.pyd.' }
            $marker = Get-Content -LiteralPath (Join-Path $destination '.pdfmodder-installation.json') -Raw | ConvertFrom-Json
            if ($marker.version -ne $Version) { throw 'La versión instalada no coincide con la solicitada.' }
            if ($script:pulses -lt 3) { throw 'No se ha ejercitado la interfaz durante la instalacion.' }
            $script:report = [ordered]@{ok=($null -eq $script:failure); app_version=$Version; installer_sha256=$installerHash; seconds=$clock.Elapsed.TotalSeconds; event_pulses=$script:pulses; directory=$destination; message=$status.Text; automatic_launch=$false; shortcut_created=$false; cross_thread_checks=$true; message_loop='Application.Run'}
            $script:phase = 2
            $timer.Stop()
            $form.Close()
        } elseif ($clock.Elapsed.TotalSeconds -gt 120) {
            $script:failure = 'La instalacion supera 120 segundos. Se espera su finalizacion antes de cerrar.'
        }
    } catch {
        $script:failure = $_.ToString()
        # Never bypass FormClosing's protection with Dispose while busy.
        if ($close.Enabled -or $script:phase -eq 0) { $timer.Stop(); $form.Close() }
    }
})
try {
    $timer.Start()
    [Windows.Forms.Application]::Run($form)
    if ($script:failure) { throw $script:failure }
    if ($null -eq $script:report) { throw 'La ventana se cerro sin completar la prueba.' }
    if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $installerHash) { throw 'El instalador cambió durante la prueba.' }
    $script:report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $qa 'verificacion-ui.json') -Encoding UTF8
    $script:report | ConvertTo-Json -Compress
} finally {
    $timer.Stop()
    $timer.Dispose()
    if (-not $form.IsDisposed -and ($close.Enabled -or $script:phase -eq 0)) { $form.Dispose() }
}
