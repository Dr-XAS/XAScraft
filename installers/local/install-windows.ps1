$ErrorActionPreference = 'Stop'
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
    throw 'This first local edition supports Windows x64. Native Windows ARM support is not yet available.'
}
$source = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$root = if ($env:XASCRAFT_INSTALL_ROOT) { $env:XASCRAFT_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA 'XAScraft' }
$uvDirectory = Join-Path $root 'runtime/uv'
$cache = Join-Path $root 'cache'
New-Item -ItemType Directory -Force -Path $uvDirectory, $cache | Out-Null
$uv = Join-Path $uvDirectory 'uv.exe'
if (-not (Test-Path $uv)) {
    $temp = Join-Path $cache ([guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $temp | Out-Null
    try {
        $archive = Join-Path $temp 'uv.zip'
        Write-Host 'Preparing the private installer...'
        Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip' -OutFile $archive -UseBasicParsing
        if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne '3b2661a463a5baea7f5076ea2b25ab71d77f36a6c0d809e5350651792f80a672') {
            throw 'Installer checksum verification failed.'
        }
        Expand-Archive $archive -DestinationPath (Join-Path $temp 'unpacked')
        $binary = Get-ChildItem (Join-Path $temp 'unpacked') -Recurse -Filter uv.exe | Select-Object -First 1
        Copy-Item $binary.FullName $uv
    } finally { Remove-Item $temp -Recurse -Force }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root 'runtime/python'
$env:UV_CACHE_DIR = Join-Path $root 'cache/uv'
$env:UV_NO_CONFIG = '1'
& $uv python install --no-bin 3.12.14
if ($LASTEXITCODE -ne 0) { throw 'Could not install the private Python runtime.' }
$python = & $uv python find --managed-python 3.12.14
if ($LASTEXITCODE -ne 0) { throw 'Could not find the private Python runtime.' }
& $python (Join-Path $source 'installers/local/run.py') --root $root install --source $source --uv $uv @args
if ($LASTEXITCODE -ne 0) { throw 'XAScraft installation failed. Inspect logs/install.log inside the install directory.' }
