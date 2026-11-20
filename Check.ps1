param([switch]$RequireModels, [switch]$RequireDownloader, [switch]$RequirePlayer)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.runtime\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run Install.ps1 first.' }
$arguments = @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'app\workbench\check.py'))
if ($RequireModels) { $arguments += '--require-models' }
if ($RequireDownloader) { $arguments += '--require-downloader' }
if ($RequirePlayer) { $arguments += '--require-player' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Workbench check failed.' }
