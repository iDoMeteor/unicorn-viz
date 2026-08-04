# windows_deps.ps1 — bootstrap the unicorn-viz dependency stack on Windows.
#
# Automates every fix discovered in the 2026-07-11 clean-machine session
# (docs/packaging/windows-native-deps-2026-07-11.md): the MinGW toolchain
# for packages without cp314 wheels, the python-rtmidi /EHsc meson patch,
# runtime-DLL colocation, the setuptools MinGW config, and VLC for
# python-vlc. This is the interim bridge until the Windows installer ships
# a bundled runtime + prebuilt wheels (installers.md P3).
#
# Usage (from the repo root, inside PowerShell):
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\tools\install\windows_deps.ps1
#
# Status: transcribed from the validated field-notes session; re-verify on
# the next clean Windows machine (this script cannot be exercised on the
# Linux dev box).

$ErrorActionPreference = 'Stop'

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "WARN: $msg" -ForegroundColor Yellow }

# ---------------------------------------------------------------- venv ----
Step 'Checking Python virtual environment'
if (-not (Test-Path '.venv')) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw 'python not found on PATH. Install Python 3.11+ first.' }
    python -m venv .venv
}
$venvPython = Join-Path (Resolve-Path '.venv') 'Scripts\python.exe'
$venvScripts = Join-Path (Resolve-Path '.venv') 'Scripts'
& $venvPython --version

# ------------------------------------------------------------ toolchain ----
Step 'Checking for a C/C++ toolchain (needed when no prebuilt wheel exists)'
$mingwBin = $null
$gcc = Get-Command gcc -ErrorAction SilentlyContinue
if ($gcc) {
    $mingwBin = Split-Path $gcc.Source
} else {
    Step 'Installing LLVM MinGW UCRT via winget'
    winget install MartinStorsjo.LLVM-MinGW.UCRT --silent `
        --accept-package-agreements --accept-source-agreements
    $pkgRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    $mingwDir = Get-ChildItem $pkgRoot -Directory -Filter 'MartinStorsjo.LLVM-MinGW.UCRT*' |
        Select-Object -First 1
    if (-not $mingwDir) { throw 'LLVM MinGW install not found under WinGet packages.' }
    $mingwBin = Get-ChildItem $mingwDir.FullName -Recurse -Directory -Filter 'bin' |
        Select-Object -First 1 -ExpandProperty FullName
}
$env:PATH = "$mingwBin;$venvScripts;$env:PATH"
Write-Host "Toolchain bin: $mingwBin"

# setuptools on Windows ignores CC/CXX; the user-level distutils config is
# the only reliable way to select MinGW (field notes §2).
Step 'Writing %USERPROFILE%\pydistutils.cfg (compiler=mingw32)'
$cfgPath = Join-Path $env:USERPROFILE 'pydistutils.cfg'
if (-not (Test-Path $cfgPath)) {
    "[build]`ncompiler=mingw32`n" | Set-Content -Encoding ascii $cfgPath
} else {
    Write-Host 'pydistutils.cfg already exists — leaving it untouched.'
}

# ----------------------------------------------------------------- VLC ----
Step 'Checking for VLC (libvlc.dll, needed by media-01/python-vlc)'
$vlc = @(
    "$env:ProgramFiles\VideoLAN\VLC\libvlc.dll",
    "${env:ProgramFiles(x86)}\VideoLAN\VLC\libvlc.dll"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $vlc) {
    winget install VideoLAN.VLC --silent `
        --accept-package-agreements --accept-source-agreements
}

# -------------------------------------------------- python-rtmidi build ----
Step 'Building python-rtmidi from patched source (meson /EHsc fix)'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install meson meson-python ninja cython
$rtmidiOk = & $venvPython -c "import rtmidi" 2>$null; $?
if (-not $rtmidiOk) {
    $work = Join-Path $env:TEMP 'uv-rtmidi-build'
    New-Item -ItemType Directory -Force $work | Out-Null
    Push-Location $work
    try {
        & $venvPython -m pip download python-rtmidi --no-binary :all: --no-deps -d .
        $tarball = Get-ChildItem *.tar.gz | Select-Object -First 1
        tar -xzf $tarball.Name
        $srcDir = Get-ChildItem -Directory -Filter 'python_rtmidi*' | Select-Object -First 1
        if (-not $srcDir) { $srcDir = Get-ChildItem -Directory -Filter 'python-rtmidi*' | Select-Object -First 1 }
        Push-Location $srcDir.FullName
        # Upstream meson.build adds the MSVC-only /EHsc flag for every
        # non-GCC compiler; clang-in-MinGW-mode treats it as a file path.
        $meson = Get-Content 'rtmidi\meson.build' -Raw
        $meson = $meson -replace "get_id\(\)\s*!=\s*'gcc'", "get_id() == 'msvc'"
        Set-Content 'rtmidi\meson.build' $meson
        & $venvPython -m pip install --no-build-isolation .
        Pop-Location
    } finally { Pop-Location }
}

# MinGW-built extensions link against libc++.dll/libunwind.dll; colocate
# them next to each .pyd that needs them (field notes §1.5).
Step 'Colocating MinGW runtime DLLs next to native extensions'
$sitePackages = & $venvPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
foreach ($pkg in @('rtmidi', 'moderngl')) {
    $dest = Join-Path $sitePackages $pkg
    if (Test-Path $dest) {
        foreach ($dll in @('libc++.dll', 'libunwind.dll')) {
            $src = Join-Path $mingwBin $dll
            if ((Test-Path $src) -and -not (Test-Path (Join-Path $dest $dll))) {
                Copy-Item $src $dest
            }
        }
    }
}

# ------------------------------------------------------- remaining deps ----
Step 'Installing remaining requirements'
& $venvPython -m pip install -r requirements.txt
& $venvPython -m pip install -e .

# ---------------------------------------------------------------- smoke ----
Step 'Import smoke test'
$mods = @('moderngl', 'sdl2', 'numpy', 'scipy', 'sounddevice', 'rtmidi',
          'PIL', 'psutil', 'cv2', 'soundfile', 'pythonosc')
$failed = @()
foreach ($m in $mods) {
    & $venvPython -c "import $m" 2>$null
    if (-not $?) { $failed += $m }
}
& $venvPython -m pip check
if ($failed.Count -gt 0) {
    Warn ("These modules failed to import: " + ($failed -join ', '))
    Warn 'See docs/packaging/windows-native-deps-2026-07-11.md for the manual fixes.'
    exit 1
}
Write-Host "`nAll dependencies installed and importable. Run:  .venv\Scripts\python -m unicornviz" -ForegroundColor Green
