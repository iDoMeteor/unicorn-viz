#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PythonVersion = '3.11',
    [switch]$SkipPackageManagers,
    [switch]$SkipFfmpeg,
    [switch]$SkipVenv
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $projectRoot

Write-Host "Unicorn Viz Windows installer" -ForegroundColor Cyan
Write-Host "Project root: $projectRoot"

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonExe {
    if (Test-Path '.venv\Scripts\python.exe') {
        return (Resolve-Path '.venv\Scripts\python.exe').Path
    }

    if (Test-Command 'py') {
        $target = "-$PythonVersion"
        & py $target -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return 'py ' + $target
        }
    }

    if (Test-Command 'python') {
        return 'python'
    }

    return $null
}

function Get-VenvPython {
    $candidates = @(
        '.venv\Scripts\python.exe',
        '.venv\Scripts\python'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

function Ensure-Python {
    $pythonExe = Get-PythonExe
    if ($pythonExe) {
        Write-Host "Python detected: $pythonExe" -ForegroundColor Green
        return
    }

    if ($SkipPackageManagers) {
        throw "Python not found and package manager installation is disabled (--SkipPackageManagers)."
    }

    if (Test-Command 'winget') {
        Write-Host 'Installing Python via winget...' -ForegroundColor Yellow
        & winget install -e --id Python.Python.$PythonVersion --accept-package-agreements --accept-source-agreements
        return
    }

    if (Test-Command 'choco') {
        Write-Host 'Installing Python via choco...' -ForegroundColor Yellow
        & choco install -y python --version $PythonVersion
        return
    }

    throw 'Python not found and neither winget nor choco is available. Install Python manually and re-run.'
}

function Ensure-Ffmpeg {
    if ($SkipFfmpeg) {
        Write-Host 'Skipping ffmpeg installation by request.' -ForegroundColor Yellow
        return
    }

    if (Test-Command 'ffmpeg') {
        Write-Host 'ffmpeg detected.' -ForegroundColor Green
        return
    }

    if ($SkipPackageManagers) {
        Write-Host 'ffmpeg not found (package manager install disabled). Recording may be unavailable.' -ForegroundColor Yellow
        return
    }

    if (Test-Command 'winget') {
        Write-Host 'Installing ffmpeg via winget...' -ForegroundColor Yellow
        & winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        return
    }

    if (Test-Command 'choco') {
        Write-Host 'Installing ffmpeg via choco...' -ForegroundColor Yellow
        & choco install -y ffmpeg
        return
    }

    Write-Host 'ffmpeg not found and no package manager available. Recording may be unavailable.' -ForegroundColor Yellow
}

Ensure-Python
Ensure-Ffmpeg

# If Python was just installed, PATH may not be refreshed in this shell yet.
$hostPython = Get-PythonExe
if (-not $hostPython) {
    throw 'Python appears installed but is not visible in this shell yet. Open a new PowerShell window and re-run tools\\install_windows.bat.'
}

if (-not (Test-Path 'requirements.txt')) {
    throw "requirements.txt not found in $projectRoot"
}

if (-not $SkipVenv) {
    if (-not (Get-VenvPython)) {
        Write-Host 'Creating virtual environment (.venv)...' -ForegroundColor Yellow
        $venvCreated = $false
        if (Test-Command 'py') {
            & py -$PythonVersion -m venv .venv
            if ($LASTEXITCODE -eq 0) {
                $venvCreated = $true
            }
            else {
                # Fallback if exact version launcher key is unavailable.
                & py -3 -m venv .venv
                if ($LASTEXITCODE -eq 0) {
                    $venvCreated = $true
                }
            }
        }
        if (-not $venvCreated) {
            & python -m venv .venv
            if ($LASTEXITCODE -eq 0) {
                $venvCreated = $true
            }
        }
        if (-not $venvCreated -or -not (Get-VenvPython)) {
            throw 'Failed to create .venv or locate venv Python executable. Ensure Python 3.11+ is installed, then retry in a new shell.'
        }
    }

    $venvPython = Get-VenvPython
    if (-not $venvPython) {
        throw 'Virtual environment Python was not found after setup.'
    }

    Write-Host 'Installing Python packages into .venv...' -ForegroundColor Yellow
    & $venvPython -m pip install --upgrade pip wheel
    & $venvPython -m pip install -r requirements.txt

    Write-Host ''
    Write-Host 'Install complete.' -ForegroundColor Green
    Write-Host 'Run with:'
    Write-Host '  .\.venv\Scripts\python.exe -m unicornviz'
    Write-Host '  or tools\launchers\windows\UnicornViz.bat'
}
else {
    Write-Host 'Skipping virtual environment setup by request.' -ForegroundColor Yellow
}
