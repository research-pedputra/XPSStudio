param([string]$InnoCompiler)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python build_standalone.py
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
$report = Join-Path $PSScriptRoot 'release\packaged-self-test.json'
if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report }
$check = Start-Process -FilePath '.\release\XPSStudio.exe' -ArgumentList '--self-test', ('"' + $report + '"') -WindowStyle Hidden -Wait -PassThru
if ($check.ExitCode -ne 0) { throw "Packaged self-test failed. See $report" }
if (-not (Get-Content -LiteralPath $report -Raw | ConvertFrom-Json).success) { throw 'Self-test did not pass.' }
if (-not $InnoCompiler) {
    $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($found) { $InnoCompiler = $found.Source }
}
if (-not $InnoCompiler) { throw 'Provide -InnoCompiler with the path to Inno Setup 6 ISCC.exe.' }
& $InnoCompiler installer\XPSStudio.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
& $python installer\package_source.py
if ($LASTEXITCODE -ne 0) { throw 'Source packaging failed.' }
Write-Output 'Verified Windows release is ready in release\.'
