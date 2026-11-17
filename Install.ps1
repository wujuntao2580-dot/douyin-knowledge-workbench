[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$Models,
    [switch]$Downloader
)
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.runtime'
$python = Join-Path $runtime 'venv\Scripts\python.exe'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Program" }
}

function Get-VerifiedFile {
    param([string]$Url, [string]$Destination, [string]$Hash)
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    if ((Test-Path -LiteralPath $Destination) -and (Get-FileHash -LiteralPath $Destination).Hash -eq $Hash) {
        return
    }
    $temporary = "$Destination.download"
    Invoke-Checked 'curl.exe' @('--fail', '--location', '--retry', '2', '--output', $temporary, $Url)
    if ((Get-FileHash -LiteralPath $temporary).Hash -ne $Hash) {
        Remove-Item -LiteralPath $temporary
        throw "SHA-256 mismatch: $Url"
    }
    Move-Item -LiteralPath $temporary -Destination $Destination -Force
}

function Install-Archive {
    param([string]$Url, [string]$Hash, [string]$Destination, [string]$Executable)
    if (Test-Path -LiteralPath (Join-Path $Destination $Executable)) { return }
    $cache = Join-Path $runtime 'downloads'
    $archive = Join-Path $cache ($Url.Split('/')[-1])
    Get-VerifiedFile $Url $archive $Hash
    $stage = Join-Path $cache ([guid]::NewGuid().ToString('N'))
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $stage
        $entry = @(Get-ChildItem -LiteralPath $stage -Filter $Executable -File -Recurse)
        if ($entry.Count -ne 1) { throw "Invalid archive layout: $archive" }
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        Get-ChildItem -LiteralPath $entry[0].DirectoryName -Force |
            Copy-Item -Destination $Destination -Recurse -Force
    } finally {
        $resolvedStage = Resolve-Path -LiteralPath $stage -ErrorAction SilentlyContinue
        $resolvedCache = (Resolve-Path -LiteralPath $cache).Path
        if ($resolvedStage -and (Split-Path -Parent $resolvedStage.Path) -eq $resolvedCache) {
            Remove-Item -LiteralPath $resolvedStage.Path -Recurse -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    $check = "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Python 3.12 x64 required'"
    $target = Join-Path $runtime 'venv'
    if ($PythonPath) {
        Invoke-Checked $PythonPath @('-c', $check)
        Invoke-Checked $PythonPath @('-m', 'venv', $target)
    } else {
        Invoke-Checked 'py.exe' @('-3.12', '-c', $check)
        Invoke-Checked 'py.exe' @('-3.12', '-m', 'venv', $target)
    }
}
Invoke-Checked $python @('-m', 'pip', 'install', '-r', (Join-Path $PSScriptRoot 'requirements.txt'))
Invoke-Checked $python @('-m', 'pip', 'check')
Invoke-Checked $python @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'app\catalog\build_full.py'))

if ($Models) {
    $modelsDir = Join-Path $runtime 'models'
    $whisper = Join-Path $modelsDir 'faster-whisper-small'
    Invoke-Checked $python @('-c', "from huggingface_hub import snapshot_download; import sys; snapshot_download('Systran/faster-whisper-small', revision='536b0662742c02347bc0e980a01041f333bce120', local_dir=sys.argv[1], allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.txt'])", $whisper)
    $summary = Join-Path $modelsDir 'summary'
    Get-VerifiedFile 'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/1872720/Qwen3-4B-Instruct-2507-Q4_K_M.gguf' (Join-Path $summary 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf') '3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597'
    Install-Archive 'https://github.com/ggml-org/llama.cpp/releases/download/b12374/llama-b12374-bin-win-cpu-x64.zip' '73629652b2ced9dd89d054e185f3b2beb5476f90bb1853834a89647fc558e70e' (Join-Path $summary 'llama') 'llama-server.exe'
}
if ($Downloader) {
    Install-Archive 'https://github.com/JoeanAmier/TikTokDownloader/releases/download/5.8/DouK-Downloader_V5.8_Windows_X64.zip' 'c96342ef1256b708b26ab742cac2e6f29aed78e40c82d52098af01737951910c' (Join-Path $runtime 'douk') 'DouK-Downloader.exe'
}
& (Join-Path $PSScriptRoot 'Check.ps1') -RequireModels:$Models
