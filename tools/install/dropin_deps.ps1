# dropin_deps.ps1 — install the drop-ins' Python dependencies (W2).
#
# Dot-sourced by tools\install_windows.ps1 and tools\install\windows_deps.ps1.
# The root requirements.txt covers only the core; each drop-in declares its own
# needs in drop-ins\<name>\requirements.txt (PyAV, mutagen, python-vlc, ably,
# usd-core, demucs, ...).  A packaged payload carries the curated union as
# requirements-dropins.txt instead, and that wins when present.
#
# Drop-in dependencies are optional by design (each drop-in degrades without
# them) and some have no wheel on every interpreter, so a requirement that will
# not install is a warning, never an abort: each file is tried whole, then one
# requirement at a time.  The root requirements.txt is passed as a constraints
# file so a drop-in can never move a core pin.  Set UV_NO_DROPIN_DEPS=1 to skip.

function Get-DropinRequirementFiles {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)
    $union = Join-Path $ProjectRoot 'requirements-dropins.txt'
    if (Test-Path $union) { return @($union) }
    $found = @()
    $dropins = Join-Path $ProjectRoot 'drop-ins'
    if (Test-Path $dropins) {
        foreach ($f in (Get-ChildItem -Path $dropins -Filter requirements.txt -Recurse -Depth 1 -ErrorAction SilentlyContinue | Sort-Object FullName)) {
            if (Select-String -Path $f.FullName -Pattern '^\s*[^#\s]' -Quiet) { $found += $f.FullName }
        }
    }
    return $found
}

# Packages that install with --no-deps (plus the extras they really need):
# mediapipe's dependency chain pulls opencv-contrib-python, which owns the same
# `cv2` import path as the core's opencv-python-headless (see webcam-01).
$script:NoDepsPackages = @{ 'mediapipe' = @('absl-py', 'flatbuffers') }

function Install-DropinRequirements {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )
    if ($env:UV_NO_DROPIN_DEPS -eq '1') { return }
    $constraints = Join-Path $ProjectRoot 'requirements.txt'
    foreach ($file in (Get-DropinRequirementFiles -ProjectRoot $ProjectRoot)) {
        Write-Host "Installing drop-in dependencies from $file" -ForegroundColor Yellow
        $plain = @()
        foreach ($raw in (Get-Content $file)) {
            $req = ($raw -replace '#.*$', '').Trim()
            if (-not $req) { continue }
            $name = ($req -split '[<>=!~ \[;]')[0]
            if ($script:NoDepsPackages.ContainsKey($name)) {
                & $PythonExe -m pip install --prefer-binary --no-deps $req
                if ($LASTEXITCODE -eq 0) {
                    & $PythonExe -m pip install --prefer-binary -c $constraints @($script:NoDepsPackages[$name])
                }
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "Skipped $req (no installable build for this interpreter); the drop-in that needs it will run without it"
                }
            }
            else { $plain += $req }
        }
        if ($plain.Count -eq 0) { continue }
        $filtered = New-TemporaryFile
        Set-Content -Path $filtered -Value $plain
        & $PythonExe -m pip install --prefer-binary -c $constraints -r $filtered
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Some dependencies in $file did not install together; retrying one at a time"
            foreach ($req in $plain) {
                & $PythonExe -m pip install --prefer-binary -c $constraints $req
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "Skipped $req (no installable build for this interpreter); the drop-in that needs it will run without it"
                }
            }
        }
        Remove-Item $filtered -ErrorAction SilentlyContinue
    }
    $global:LASTEXITCODE = 0
}
