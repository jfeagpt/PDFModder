[CmdletBinding()]
param(
    [string]$ExecutablePath,
    [string]$OutputDirectory,
    [string]$ExpectedVersion = '1.5.0'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# A parent PowerShell 7 can pass its module search path to Windows PowerShell.
# Load the matching built-in module explicitly instead of resolving a 7.x copy.
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $ExecutablePath) { $ExecutablePath = Join-Path $projectRoot 'dist/PDFModder/PDFModder.exe' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'output' }
$ExecutablePath = (Resolve-Path -LiteralPath $ExecutablePath).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$expectedHash = (Get-FileHash -LiteralPath $ExecutablePath -Algorithm SHA256).Hash.ToLowerInvariant()
$runId = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$cleanDirectory = Join-Path $OutputDirectory ('isolated-runtime/' + $runId)
[IO.Directory]::CreateDirectory($cleanDirectory) | Out-Null
$cleanPath = @(
    (Join-Path $env:SystemRoot 'System32'),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot 'System32/Wbem'),
    (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0')
) -join ';'
$runs = @(
    @{ Name = 'extended'; Flag = '--smoke-extended'; Timeout = 90 },
    @{ Name = 'tagged'; Flag = '--smoke-tagged'; Timeout = 90 },
    @{ Name = 'clipped'; Flag = '--smoke-clipped'; Timeout = 90 },
    @{ Name = 'v08'; Flag = '--smoke-v08'; Timeout = 90 },
    # RichSmoke enforces 180 seconds; allow shutdown to finish and report it.
    @{ Name = 'v09'; Flag = '--smoke-v09'; Timeout = 195 },
    @{ Name = 'compat'; Flag = '--smoke-compat'; Timeout = 195 },
    @{ Name = 'v150'; Flag = '--smoke-v150'; Timeout = 195 }
)
$results = [Collections.Generic.List[object]]::new()
foreach ($run in $runs) {
    $reportPath = Join-Path $OutputDirectory ('packaged-' + $run.Name + '-smoke.json')
    $started = [DateTime]::UtcNow
    $entry = [ordered]@{
        name = $run.Name; ok = $false; report = $reportPath; error = $null
        started_utc = $started.ToString('o'); exit_code = $null; steps = 0
        elapsed_seconds = $null; version = $null; exe_sha256 = $expectedHash
        report_sha256 = $null; output_sha256 = $null; screenshot_sha256 = $null
        source_unchanged = $false; removed_environment_variables = @()
    }
    $process = $null
    try {
        if ((Get-FileHash -LiteralPath $ExecutablePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
            throw 'El ejecutable cambió durante las comprobaciones.'
        }
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $ExecutablePath
        $start.Arguments = $run.Flag + ' "' + $reportPath + '"'
        $start.WorkingDirectory = $cleanDirectory
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
        # Only the child environment changes. Search paths cannot find a local
        # Python/Qt installation or inherit an activated virtual environment.
        $removed = @($start.EnvironmentVariables.Keys | Where-Object {
            $_ -match '^(PYTHON|PYSIDE|QT_|QML|VIRTUAL_ENV|CONDA|PYENV|_PYI|_MEIPASS)'
        })
        foreach ($name in $removed) { $start.EnvironmentVariables.Remove($name) }
        $start.EnvironmentVariables['PATH'] = $cleanPath
        $entry.removed_environment_variables = $removed
        $process = [Diagnostics.Process]::Start($start)
        $deadline = [DateTime]::UtcNow.AddSeconds($run.Timeout)
        while (-not $process.WaitForExit(1000)) {
            if ([DateTime]::UtcNow -ge $deadline) {
                # Only this smoke process and its own worker are terminated.
                & (Join-Path $env:SystemRoot 'System32/taskkill.exe') /PID $process.Id /T /F | Out-Null
                throw ('El recorrido ' + $run.Name + ' excedió ' + $run.Timeout + ' segundos.')
            }
        }
        $entry.exit_code = $process.ExitCode
        $reportFile = Get-Item -LiteralPath $reportPath
        if ($reportFile.LastWriteTimeUtc -lt $started) { throw 'El informe pertenece a una ejecución anterior.' }
        $entry.report_sha256 = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($process.ExitCode -ne 0 -or -not $report.ok) {
            throw ('El ejecutable falló con código ' + $process.ExitCode + ': ' + $report.error)
        }
        if (-not $report.frozen -or $report.stage -ne 'complete' -or $report.exe_sha256 -ne $expectedHash -or $report.app_version -ne $ExpectedVersion) {
            throw 'El informe no acredita la versión congelada, completa y con la huella esperada.'
        }
        $failedSteps = @($report.steps | Where-Object { -not $_.ok })
        if ($report.steps.Count -eq 0 -or $failedSteps.Count -ne 0) { throw 'Hay pasos incompletos o fallidos en el recorrido.' }
        if ($run.Name -eq 'v09' -and $report.elapsed_seconds -gt 180) { throw 'El recorrido 0.9 excedió su límite de 180 segundos.' }
        if ((Get-FileHash -LiteralPath $report.source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $report.source_sha256) {
            throw 'El PDF original del ejemplo no conserva su huella.'
        }
        $entry.steps = $report.steps.Count
        $entry.elapsed_seconds = $report.elapsed_seconds
        $entry.version = $report.app_version
        $entry.source_unchanged = $true
        $entry.output_sha256 = (Get-FileHash -LiteralPath $report.output -Algorithm SHA256).Hash.ToLowerInvariant()
        $entry.screenshot_sha256 = (Get-FileHash -LiteralPath $report.screenshot -Algorithm SHA256).Hash.ToLowerInvariant()
        $entry.ok = $true
    }
    catch { $entry.error = $_.Exception.Message }
    finally {
        if ($null -ne $process) { $process.Dispose() }
        $results.Add([PSCustomObject]$entry)
        [PSCustomObject]$entry | Select-Object name,ok,steps,elapsed_seconds,version,error | ConvertTo-Json -Compress
    }
}
$hashUnchanged = (Get-FileHash -LiteralPath $ExecutablePath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedHash
$allPassed = $hashUnchanged -and @($results | Where-Object { -not $_.ok }).Count -eq 0
$summary = [ordered]@{
    ok = $allPassed; run_id = $runId; expected_version = $ExpectedVersion
    executable = $ExecutablePath; exe_sha256 = $expectedHash; executable_unchanged = $hashUnchanged
    path = $cleanPath; working_directory = $cleanDirectory
    environment_scope = 'Proceso hijo: PATH sólo Windows; variables Python, entornos virtuales, Qt y PyInstaller retiradas. No equivale a otra instalación de Windows.'
    runs = @($results.ToArray())
}
$summaryPath = Join-Path $OutputDirectory 'packaged-verification.json'
[IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
if (-not $allPassed) { throw ('La comprobación del ejecutable no se ha superado. Consulte ' + $summaryPath) }
Write-Output ('Siete recorridos aprobados. Informe: ' + $summaryPath)
