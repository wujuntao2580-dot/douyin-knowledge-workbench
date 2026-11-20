[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$Models,
    [switch]$Downloader,
    [switch]$Player,
    [switch]$DesktopShortcut,
    [string]$ShortcutDirectory = [Environment]::GetFolderPath('Desktop')
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# Requests/Hugging Face and Git do not consistently read the Windows proxy registry.
# Reuse an already-enabled user proxy for this installer process only.
if (-not $env:HTTPS_PROXY) {
    $network = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
    if ($network.ProxyEnable -eq 1 -and $network.ProxyServer) {
        $proxyAddress = [string]$network.ProxyServer
        if ($proxyAddress -match '(^|;)https=([^;]+)') { $proxyAddress = $Matches[2] }
        elseif ($proxyAddress -match '(^|;)http=([^;]+)') { $proxyAddress = $Matches[2] }
        if ($proxyAddress -notmatch '^https?://') { $proxyAddress = 'http://' + $proxyAddress }
        $env:HTTPS_PROXY = $proxyAddress
        if (-not $env:HTTP_PROXY) { $env:HTTP_PROXY = $proxyAddress }
    }
}

$runtime = Join-Path $PSScriptRoot '.runtime'
$python = Join-Path $runtime 'venv\Scripts\python.exe'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Program" }
}

function Get-VerifiedFile {
    param([string]$Url, [string]$Destination, [string]$Hash)
    Invoke-Checked $python @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'app\workbench\download.py'), $Url, $Destination, $Hash)
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
Invoke-Checked $python @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $PSScriptRoot 'requirements.txt'), '-c', (Join-Path $PSScriptRoot 'constraints.txt'))
Invoke-Checked $python @('-m', 'pip', 'check')
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data\inputs'), (Join-Path $PSScriptRoot 'data\workflow') -Force | Out-Null
Invoke-Checked $python @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'app\catalog\build_full.py'))

if ($Models) {
    $env:HF_HUB_DISABLE_XET = '1'
    $modelsDir = Join-Path $runtime 'models'
    $whisper = Join-Path $modelsDir 'faster-whisper-small'
    Invoke-Checked $python @('-c', "from huggingface_hub import snapshot_download; import sys; snapshot_download('Systran/faster-whisper-small', revision='536b0662742c02347bc0e980a01041f333bce120', local_dir=sys.argv[1], allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.txt'])", $whisper)
    $summary = Join-Path $modelsDir 'summary'
    Get-VerifiedFile 'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/1872720/Qwen3-4B-Instruct-2507-Q4_K_M.gguf' (Join-Path $summary 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf') '3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597'
    Install-Archive 'https://github.com/ggml-org/llama.cpp/releases/download/b12374/llama-b12374-bin-win-cpu-x64.zip' '73629652b2ced9dd89d054e185f3b2beb5476f90bb1853834a89647fc558e70e' (Join-Path $summary 'llama') 'llama-server.exe'
}
if ($Downloader) {
    Install-Archive 'https://github.com/JoeanAmier/TikTokDownloader/releases/download/5.8/DouK-Downloader_V5.8_Windows_X64.zip' 'c96342ef1256b708b26ab742cac2e6f29aed78e40c82d52098af01737951910c' (Join-Path $runtime 'douk') 'DouK-Downloader.exe'
    Write-Host 'First online use: launch .runtime\douk\DouK-Downloader.exe once if initialization is requested; review its first-run prompts yourself, then return to the workbench.'
    $f2Python = Join-Path $runtime 'f2\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $f2Python)) { Invoke-Checked $python @('-m', 'venv', (Join-Path $runtime 'f2')) }
    Invoke-Checked $f2Python @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $PSScriptRoot 'requirements-online.txt'), '-c', (Join-Path $PSScriptRoot 'constraints-online.txt'))
    Invoke-Checked $f2Python @('-m', 'pip', 'check')
    Invoke-Checked $f2Python @('-c', 'from f2.apps.douyin.crawler import DouyinCrawler; from f2.apps.douyin.model import UserCollects, UserCollectsVideo, BaseRequestModel')
    $workflowData = Join-Path $PSScriptRoot 'data\workflow'
    New-Item -ItemType Directory -Path $workflowData -Force | Out-Null
    $f2Check = Join-Path $workflowData 'f2-verification.json'
    $checkContent = @{ download = $true; catalog = $true; build = 'f6be8c0ffba9a127075bbeafe4838716650b6325'; validation = 'Pinned integration imports checked; online access requires user login.' } | ConvertTo-Json
    [IO.File]::WriteAllText($f2Check, $checkContent, (New-Object System.Text.UTF8Encoding($false)))
}
if ($Player) {
    Install-Archive 'https://download.videolan.org/pub/videolan/vlc/3.0.24/win64/vlc-3.0.24-win64.zip' 'fcf30850371ad10c9373cc4f0f4501e7dee49e3e9ae9f20c72fb2661a1ca6323' (Join-Path $runtime 'vlc') 'vlc.exe'
}
if ($DesktopShortcut) {
    New-Item -ItemType Directory -Path $ShortcutDirectory -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $ShortcutDirectory '知识工作台.lnk'))
    $shortcut.TargetPath = Join-Path $runtime 'venv\Scripts\pythonw.exe'
    $shortcut.Arguments = '-B -X utf8 "' + (Join-Path $PSScriptRoot 'app\workbench\open-workbench.py') + '"'
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = '本地视频知识工作台'
    $shortcut.Save()
}
& (Join-Path $PSScriptRoot 'Check.ps1') -RequireModels:$Models -RequireDownloader:$Downloader -RequirePlayer:$Player
