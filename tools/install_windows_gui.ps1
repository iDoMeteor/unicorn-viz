#requires -Version 5.1
[CmdletBinding()]
param()

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = 'Stop'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$installerScript = Join-Path $PSScriptRoot 'install_windows.ps1'
$iconPath = Join-Path $projectRoot 'assets\icons\unicorn-viz.ico'
$avatarPath = Join-Path $projectRoot 'assets\icons\unicorn-viz.png'

function New-UiFont([float]$size, [System.Drawing.FontStyle]$style = [System.Drawing.FontStyle]::Regular) {
    return New-Object System.Drawing.Font('Segoe UI', $size, $style)
}

function Append-Log {
    param(
        [System.Windows.Forms.TextBox]$Box,
        [string]$Text
    )
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return
    }
    $Box.AppendText($Text)
    if (-not $Text.EndsWith("`r`n")) {
        $Box.AppendText("`r`n")
    }
    $Box.SelectionStart = $Box.TextLength
    $Box.ScrollToCaret()
}

function Run-Installer {
    param(
        [bool]$SkipPackageManagers,
        [bool]$SkipFfmpeg,
        [bool]$SkipVenv,
        [System.Windows.Forms.TextBox]$LogBox,
        [System.Windows.Forms.Label]$StatusLabel,
        [System.Windows.Forms.Button]$InstallButton
    )

    if (-not (Test-Path $installerScript)) {
        [System.Windows.Forms.MessageBox]::Show(
            "Installer script not found: $installerScript",
            'Unicorn Viz Installer',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
        return
    }

    $argList = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installerScript)
    if ($SkipPackageManagers) { $argList += '-SkipPackageManagers' }
    if ($SkipFfmpeg) { $argList += '-SkipFfmpeg' }
    if ($SkipVenv) { $argList += '-SkipVenv' }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.WorkingDirectory = $projectRoot.Path
    $psi.Arguments = [string]::Join(' ', ($argList | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }))
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    $InstallButton.Enabled = $false
    $StatusLabel.Text = 'Installing... this can take a few minutes.'
    Append-Log -Box $LogBox -Text ('=' * 72)
    Append-Log -Box $LogBox -Text ("Starting installer at " + (Get-Date).ToString('u'))

    try {
        [void]$proc.Start()
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()

        while (-not $proc.HasExited) {
            [System.Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 80
        }

        $stdout = $outTask.Result
        $stderr = $errTask.Result
        if ($stdout) { Append-Log -Box $LogBox -Text $stdout }
        if ($stderr) { Append-Log -Box $LogBox -Text $stderr }

        if ($proc.ExitCode -eq 0) {
            $StatusLabel.Text = 'Install complete.'
            Append-Log -Box $LogBox -Text 'Installer completed successfully.'
            [System.Windows.Forms.MessageBox]::Show(
                'Unicorn Viz install complete. You can now launch from the launcher.',
                'Unicorn Viz Installer',
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
        }
        else {
            $StatusLabel.Text = "Installer failed (exit code $($proc.ExitCode))."
            Append-Log -Box $LogBox -Text "Installer failed with exit code $($proc.ExitCode)."
            [System.Windows.Forms.MessageBox]::Show(
                "Installer failed with exit code $($proc.ExitCode). See log panel for details.",
                'Unicorn Viz Installer',
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error
            ) | Out-Null
        }
    }
    catch {
        $StatusLabel.Text = 'Installer crashed.'
        Append-Log -Box $LogBox -Text ("Unexpected installer error: " + $_.Exception.Message)
        [System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            'Unicorn Viz Installer',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    finally {
        $InstallButton.Enabled = $true
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Unicorn Viz Installer'
$form.Width = 940
$form.Height = 700
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.Color]::FromArgb(22, 25, 35)
$form.ForeColor = [System.Drawing.Color]::FromArgb(232, 240, 255)
$form.Font = New-UiFont -size 10
$form.MinimumSize = New-Object System.Drawing.Size(920, 660)

if (Test-Path $iconPath) {
    $form.Icon = New-Object System.Drawing.Icon($iconPath)
}

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Unicorn Viz Windows Installer'
$title.Font = New-UiFont -size 16 -style ([System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(24, 20)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = 'One-click install for Python, ffmpeg, virtualenv, and dependencies'
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(24, 54)
$form.Controls.Add($subtitle)

$avatarPanel = New-Object System.Windows.Forms.Panel
$avatarPanel.Location = New-Object System.Drawing.Point(688, 18)
$avatarPanel.Size = New-Object System.Drawing.Size(210, 240)
$avatarPanel.BackColor = [System.Drawing.Color]::FromArgb(32, 37, 56)
$form.Controls.Add($avatarPanel)

$avatarTitle = New-Object System.Windows.Forms.Label
$avatarTitle.Text = 'Unicorn Viz Avatar'
$avatarTitle.AutoSize = $true
$avatarTitle.Font = New-UiFont -size 10 -style ([System.Drawing.FontStyle]::Bold)
$avatarTitle.Location = New-Object System.Drawing.Point(12, 10)
$avatarPanel.Controls.Add($avatarTitle)

$avatarPic = New-Object System.Windows.Forms.PictureBox
$avatarPic.Location = New-Object System.Drawing.Point(12, 36)
$avatarPic.Size = New-Object System.Drawing.Size(186, 186)
$avatarPic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
$avatarPic.BackColor = [System.Drawing.Color]::FromArgb(18, 21, 30)
if (Test-Path $avatarPath) {
    $avatarPic.Image = [System.Drawing.Image]::FromFile($avatarPath)
}
$avatarPanel.Controls.Add($avatarPic)

$checkSkipManagers = New-Object System.Windows.Forms.CheckBox
$checkSkipManagers.Text = 'Skip package manager installs (Python/ffmpeg must already exist)'
$checkSkipManagers.AutoSize = $true
$checkSkipManagers.Location = New-Object System.Drawing.Point(26, 96)
$form.Controls.Add($checkSkipManagers)

$checkSkipFfmpeg = New-Object System.Windows.Forms.CheckBox
$checkSkipFfmpeg.Text = 'Skip ffmpeg install'
$checkSkipFfmpeg.AutoSize = $true
$checkSkipFfmpeg.Location = New-Object System.Drawing.Point(26, 126)
$form.Controls.Add($checkSkipFfmpeg)

$checkSkipVenv = New-Object System.Windows.Forms.CheckBox
$checkSkipVenv.Text = 'Skip virtual environment setup'
$checkSkipVenv.AutoSize = $true
$checkSkipVenv.Location = New-Object System.Drawing.Point(26, 156)
$form.Controls.Add($checkSkipVenv)

$btnInstall = New-Object System.Windows.Forms.Button
$btnInstall.Text = 'Install Unicorn Viz'
$btnInstall.Width = 210
$btnInstall.Height = 40
$btnInstall.Location = New-Object System.Drawing.Point(24, 202)
$btnInstall.BackColor = [System.Drawing.Color]::FromArgb(34, 166, 179)
$btnInstall.ForeColor = [System.Drawing.Color]::White
$btnInstall.FlatStyle = 'Flat'
$form.Controls.Add($btnInstall)

$btnLauncher = New-Object System.Windows.Forms.Button
$btnLauncher.Text = 'Open Launcher'
$btnLauncher.Width = 160
$btnLauncher.Height = 40
$btnLauncher.Location = New-Object System.Drawing.Point(248, 202)
$btnLauncher.FlatStyle = 'Flat'
$form.Controls.Add($btnLauncher)

$btnOpenRoot = New-Object System.Windows.Forms.Button
$btnOpenRoot.Text = 'Open Project Folder'
$btnOpenRoot.Width = 180
$btnOpenRoot.Height = 40
$btnOpenRoot.Location = New-Object System.Drawing.Point(420, 202)
$btnOpenRoot.FlatStyle = 'Flat'
$form.Controls.Add($btnOpenRoot)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Ready.'
$status.AutoSize = $true
$status.Location = New-Object System.Drawing.Point(24, 256)
$form.Controls.Add($status)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ScrollBars = 'Vertical'
$logBox.ReadOnly = $true
$logBox.WordWrap = $false
$logBox.BackColor = [System.Drawing.Color]::FromArgb(10, 14, 22)
$logBox.ForeColor = [System.Drawing.Color]::FromArgb(140, 250, 200)
$logBox.Font = New-Object System.Drawing.Font('Consolas', 9)
$logBox.Location = New-Object System.Drawing.Point(24, 284)
$logBox.Width = 874
$logBox.Height = 334
$form.Controls.Add($logBox)

$btnInstall.Add_Click({
    Run-Installer `
        -SkipPackageManagers $checkSkipManagers.Checked `
        -SkipFfmpeg $checkSkipFfmpeg.Checked `
        -SkipVenv $checkSkipVenv.Checked `
        -LogBox $logBox `
        -StatusLabel $status `
        -InstallButton $btnInstall
})

$btnLauncher.Add_Click({
    $launcher = Join-Path $projectRoot.Path 'tools\launchers\windows\UnicornVizGUI.ps1'
    if (Test-Path $launcher) {
        Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $launcher) | Out-Null
    }
    else {
        [System.Windows.Forms.MessageBox]::Show('Launcher GUI script not found.', 'Unicorn Viz Installer') | Out-Null
    }
})

$btnOpenRoot.Add_Click({
    Start-Process -FilePath 'explorer.exe' -ArgumentList $projectRoot.Path | Out-Null
})

[void]$form.ShowDialog()
