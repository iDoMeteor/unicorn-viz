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

function Test-PythonVersionAtLeast {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [int]$Major = 3,
        [int]$Minor = 11
    )

    & $PythonExe -c "import sys; raise SystemExit(0 if sys.version_info >= ($Major, $Minor) else 1)" | Out-Null
    return $LASTEXITCODE -eq 0
}

function Get-PythonExe {
    if (Test-Path '.venv\Scripts\python.exe') {
        return (Resolve-Path '.venv\Scripts\python.exe').Path
    }

    if (Test-Command 'py') {
        $pyList = & py -0p 2>$null
        if ($LASTEXITCODE -eq 0 -and $pyList) {
            $matches = @()
            foreach ($line in $pyList) {
                if ($line -match '^\s*-?(?<major>\d+)\.(?<minor>\d+)(?:-\d+)?\s+(?<path>.+python(?:\.exe)?)\s*$') {
                    $major = [int]$Matches.major
                    $minor = [int]$Matches.minor
                    $path = $Matches.path.Trim()
                    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                        $matches += [pscustomobject]@{ Major = $major; Minor = $minor; Path = $path }
                    }
                }
            }
            if ($matches) {
                $best = $matches | Sort-Object Major, Minor -Descending | Select-Object -First 1
                if (Test-Path $best.Path) {
                    return $best.Path
                }
            }
        }
    }

    if (Test-Command 'python') {
        $python = (Get-Command python).Source
        if (-not $python) {
            $python = (Get-Command python).Path
        }
        if ($python -and (Test-PythonVersionAtLeast $python 3 11)) {
            return $python
        }
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

    Write-Host 'Python 3.11+ not found on PATH/py launcher; trying package manager install...' -ForegroundColor Yellow

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
        $hostPython = Get-PythonExe
        if ($hostPython) {
            & $hostPython -m venv .venv
            if ($LASTEXITCODE -eq 0) {
                $venvCreated = $true
            }
        }
        if (-not $venvCreated -or -not (Get-VenvPython)) {
            throw 'Failed to create .venv or locate venv Python executable. Ensure a Python 3.11+ interpreter is installed, then retry in a new shell.'
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
