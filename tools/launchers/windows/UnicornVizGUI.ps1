#requires -Version 5.1
[CmdletBinding()]
param()

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = 'Stop'

$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$iconPath = Join-Path $repo 'assets\icons\unicorn-viz.ico'
$avatarPath = Join-Path $repo 'assets\icons\unicorn-viz.png'
$configPath = Join-Path $repo 'config.toml'
$installerGui = Join-Path $repo 'tools\install_windows_gui.ps1'

function New-UiFont([float]$size, [System.Drawing.FontStyle]$style = [System.Drawing.FontStyle]::Regular) {
    return New-Object System.Drawing.Font('Segoe UI', $size, $style)
}

function Resolve-PythonExe {
    $venv = Join-Path $repo '.venv\Scripts\python.exe'
    if (Test-Path $venv) {
        return (Resolve-Path $venv).Path
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return 'py'
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        if ($python.Source) { return $python.Source }
        if ($python.Path) { return $python.Path }
    }

    return $null
}

function Build-LaunchArguments {
    param(
        [bool]$Windowed,
        [string]$AdditionalArgs
    )

    $args = @('-m', 'unicornviz')
    if ($Windowed) {
        $args += '--windowed'
    }
    if ($AdditionalArgs) {
        $tokens = [System.Text.RegularExpressions.Regex]::Split($AdditionalArgs.Trim(), '\s+')
        foreach ($token in $tokens) {
            if ($token) { $args += $token }
        }
    }
    return $args
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

function New-DesktopShortcut {
    param([string]$TargetLauncher)

    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop 'Unicorn Viz Launcher.lnk'
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut($shortcutPath)
    $sc.TargetPath = 'powershell.exe'
    $sc.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$TargetLauncher`""
    $sc.WorkingDirectory = $repo.Path
    if (Test-Path $iconPath) {
        $sc.IconLocation = $iconPath
    }
    $sc.Save()
    return $shortcutPath
}

function Invoke-UpdateAndRefresh {
    param(
        [System.Windows.Forms.TextBox]$LogBox,
        [System.Windows.Forms.Label]$StatusLabel,
        [System.Windows.Forms.Button]$UpdateButton
    )

    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        [System.Windows.Forms.MessageBox]::Show(
            'Git is not installed or not on PATH. Install Git for Windows first.',
            'Unicorn Viz Launcher',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        return
    }

    $pythonExe = Resolve-PythonExe
    if (-not $pythonExe) {
        [System.Windows.Forms.MessageBox]::Show(
            'No Python interpreter found. Run the installer first.',
            'Unicorn Viz Launcher',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        return
    }

    $UpdateButton.Enabled = $false
    $StatusLabel.Text = 'Updating repository and dependencies...'
    Append-Log -Box $LogBox -Text ('=' * 72)
    Append-Log -Box $LogBox -Text ("Update started at " + (Get-Date).ToString('u'))

    $commands = @(
        'git pull --ff-only',
        '"{0}" -m pip install --upgrade pip wheel' -f $pythonExe,
        '"{0}" -m pip install -r requirements.txt' -f $pythonExe
    )

    try {
        foreach ($cmd in $commands) {
            Append-Log -Box $LogBox -Text ("> " + $cmd)
            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = 'cmd.exe'
            $psi.WorkingDirectory = $repo.Path
            $psi.Arguments = '/c ' + $cmd
            $psi.UseShellExecute = $false
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.CreateNoWindow = $true

            $proc = New-Object System.Diagnostics.Process
            $proc.StartInfo = $psi

            try {
                [void]$proc.Start()
                $stdout = $proc.StandardOutput.ReadToEnd()
                $stderr = $proc.StandardError.ReadToEnd()
                $proc.WaitForExit()

                if ($stdout) { Append-Log -Box $LogBox -Text $stdout }
                if ($stderr) { Append-Log -Box $LogBox -Text $stderr }

                if ($proc.ExitCode -ne 0) {
                    $StatusLabel.Text = "Update failed (exit code $($proc.ExitCode))."
                    Append-Log -Box $LogBox -Text "Command failed with exit code $($proc.ExitCode)."
                    return
                }
            }
            catch {
                $StatusLabel.Text = 'Update failed.'
                Append-Log -Box $LogBox -Text ("Update command error: " + $_.Exception.Message)
                return
            }
            finally {
                [System.Windows.Forms.Application]::DoEvents()
            }
        }

        $StatusLabel.Text = 'Update complete.'
        Append-Log -Box $LogBox -Text 'Repository and dependencies are up to date.'
    }
    finally {
        $UpdateButton.Enabled = $true
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Unicorn Viz Launcher'
$form.Width = 760
$form.Height = 480
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.Color]::FromArgb(17, 20, 31)
$form.ForeColor = [System.Drawing.Color]::FromArgb(237, 244, 255)
$form.Font = New-UiFont -size 10
$form.MinimumSize = New-Object System.Drawing.Size(740, 450)

if (Test-Path $iconPath) {
    $form.Icon = New-Object System.Drawing.Icon($iconPath)
}

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Unicorn Viz'
$title.Font = New-UiFont -size 22 -style ([System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(24, 20)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = 'Windows GUI Launcher'
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(26, 62)
$form.Controls.Add($subtitle)

$avatarPanel = New-Object System.Windows.Forms.Panel
$avatarPanel.Location = New-Object System.Drawing.Point(546, 20)
$avatarPanel.Size = New-Object System.Drawing.Size(174, 176)
$avatarPanel.BackColor = [System.Drawing.Color]::FromArgb(30, 35, 52)
$form.Controls.Add($avatarPanel)

$avatarTitle = New-Object System.Windows.Forms.Label
$avatarTitle.Text = 'Avatar'
$avatarTitle.AutoSize = $true
$avatarTitle.Font = New-UiFont -size 9.5 -style ([System.Drawing.FontStyle]::Bold)
$avatarTitle.Location = New-Object System.Drawing.Point(10, 8)
$avatarPanel.Controls.Add($avatarTitle)

$avatarPic = New-Object System.Windows.Forms.PictureBox
$avatarPic.Location = New-Object System.Drawing.Point(10, 30)
$avatarPic.Size = New-Object System.Drawing.Size(154, 134)
$avatarPic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
$avatarPic.BackColor = [System.Drawing.Color]::FromArgb(16, 20, 30)
if (Test-Path $avatarPath) {
    $avatarPic.Image = [System.Drawing.Image]::FromFile($avatarPath)
}
$avatarPanel.Controls.Add($avatarPic)

$checkWindowed = New-Object System.Windows.Forms.CheckBox
$checkWindowed.Text = 'Start windowed mode'
$checkWindowed.AutoSize = $true
$checkWindowed.Location = New-Object System.Drawing.Point(28, 108)
$form.Controls.Add($checkWindowed)

$argsLabel = New-Object System.Windows.Forms.Label
$argsLabel.Text = 'Additional CLI args (optional):'
$argsLabel.AutoSize = $true
$argsLabel.Location = New-Object System.Drawing.Point(28, 140)
$form.Controls.Add($argsLabel)

$argsBox = New-Object System.Windows.Forms.TextBox
$argsBox.Location = New-Object System.Drawing.Point(30, 164)
$argsBox.Width = 500
$form.Controls.Add($argsBox)

$btnLaunch = New-Object System.Windows.Forms.Button
$btnLaunch.Text = 'Launch Unicorn Viz'
$btnLaunch.Width = 220
$btnLaunch.Height = 42
$btnLaunch.Location = New-Object System.Drawing.Point(30, 210)
$btnLaunch.BackColor = [System.Drawing.Color]::FromArgb(255, 122, 45)
$btnLaunch.ForeColor = [System.Drawing.Color]::White
$btnLaunch.FlatStyle = 'Flat'
$form.Controls.Add($btnLaunch)

$btnConfig = New-Object System.Windows.Forms.Button
$btnConfig.Text = 'Open config.toml'
$btnConfig.Width = 170
$btnConfig.Height = 42
$btnConfig.Location = New-Object System.Drawing.Point(266, 210)
$btnConfig.FlatStyle = 'Flat'
$form.Controls.Add($btnConfig)

$btnInstaller = New-Object System.Windows.Forms.Button
$btnInstaller.Text = 'Open Installer'
$btnInstaller.Width = 150
$btnInstaller.Height = 42
$btnInstaller.Location = New-Object System.Drawing.Point(448, 210)
$btnInstaller.FlatStyle = 'Flat'
$form.Controls.Add($btnInstaller)

$btnProject = New-Object System.Windows.Forms.Button
$btnProject.Text = 'Project Folder'
$btnProject.Width = 130
$btnProject.Height = 42
$btnProject.Location = New-Object System.Drawing.Point(610, 210)
$btnProject.FlatStyle = 'Flat'
$form.Controls.Add($btnProject)

$btnDesktop = New-Object System.Windows.Forms.Button
$btnDesktop.Text = 'Create Desktop Shortcut'
$btnDesktop.Width = 220
$btnDesktop.Height = 36
$btnDesktop.Location = New-Object System.Drawing.Point(30, 258)
$btnDesktop.FlatStyle = 'Flat'
$form.Controls.Add($btnDesktop)

$btnUpdate = New-Object System.Windows.Forms.Button
$btnUpdate.Text = 'Update + Refresh Deps'
$btnUpdate.Width = 220
$btnUpdate.Height = 36
$btnUpdate.Location = New-Object System.Drawing.Point(266, 258)
$btnUpdate.FlatStyle = 'Flat'
$form.Controls.Add($btnUpdate)

$status = New-Object System.Windows.Forms.Label
$status.AutoSize = $true
$status.Location = New-Object System.Drawing.Point(30, 302)
$status.Text = 'Ready.'
$form.Controls.Add($status)

$panel = New-Object System.Windows.Forms.Panel
$panel.Location = New-Object System.Drawing.Point(30, 328)
$panel.Size = New-Object System.Drawing.Size(690, 78)
$panel.BackColor = [System.Drawing.Color]::FromArgb(29, 34, 52)
$form.Controls.Add($panel)

$info = New-Object System.Windows.Forms.Label
$info.AutoSize = $false
$info.Size = New-Object System.Drawing.Size(666, 68)
$info.Location = New-Object System.Drawing.Point(12, 10)
$info.Text = "Launcher uses .venv\Scripts\python.exe when available. If no virtual environment is found, it falls back to py/python on PATH. Use the Installer button for first-time setup."
$info.ForeColor = [System.Drawing.Color]::FromArgb(210, 220, 240)
$panel.Controls.Add($info)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Multiline = $true
$logBox.ScrollBars = 'Vertical'
$logBox.ReadOnly = $true
$logBox.WordWrap = $false
$logBox.BackColor = [System.Drawing.Color]::FromArgb(10, 14, 22)
$logBox.ForeColor = [System.Drawing.Color]::FromArgb(143, 255, 210)
$logBox.Font = New-Object System.Drawing.Font('Consolas', 8.5)
$logBox.Location = New-Object System.Drawing.Point(30, 412)
$logBox.Size = New-Object System.Drawing.Size(690, 30)
$form.Controls.Add($logBox)

$btnLaunch.Add_Click({
    $pythonExe = Resolve-PythonExe
    if (-not $pythonExe) {
        [System.Windows.Forms.MessageBox]::Show(
            'No Python interpreter found. Please run the installer first.',
            'Unicorn Viz Launcher',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        return
    }

    $launchArgs = Build-LaunchArguments -Windowed $checkWindowed.Checked -AdditionalArgs $argsBox.Text
    $status.Text = 'Launching Unicorn Viz...'

    try {
        if ($pythonExe -eq 'py') {
            $allArgs = @('-3') + $launchArgs
            Start-Process -FilePath 'py' -ArgumentList $allArgs -WorkingDirectory $repo.Path | Out-Null
        }
        else {
            Start-Process -FilePath $pythonExe -ArgumentList $launchArgs -WorkingDirectory $repo.Path | Out-Null
        }
        $status.Text = 'Launched.'
    }
    catch {
        $status.Text = 'Launch failed.'
        [System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            'Unicorn Viz Launcher',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
})

$btnConfig.Add_Click({
    if (Test-Path $configPath) {
        Start-Process -FilePath $configPath | Out-Null
    }
    else {
        [System.Windows.Forms.MessageBox]::Show('config.toml not found.', 'Unicorn Viz Launcher') | Out-Null
    }
})

$btnInstaller.Add_Click({
    if (Test-Path $installerGui) {
        Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installerGui) | Out-Null
    }
    else {
        [System.Windows.Forms.MessageBox]::Show('Installer GUI script not found.', 'Unicorn Viz Launcher') | Out-Null
    }
})

$btnProject.Add_Click({
    Start-Process -FilePath 'explorer.exe' -ArgumentList $repo.Path | Out-Null
})

$btnDesktop.Add_Click({
    $launcher = Join-Path $repo.Path 'tools\launchers\windows\UnicornVizGUI.ps1'
    try {
        $shortcut = New-DesktopShortcut -TargetLauncher $launcher
        $status.Text = 'Desktop shortcut created.'
        Append-Log -Box $logBox -Text ("Created shortcut: " + $shortcut)
    }
    catch {
        $status.Text = 'Failed to create desktop shortcut.'
        Append-Log -Box $logBox -Text ("Shortcut error: " + $_.Exception.Message)
    }
})

$btnUpdate.Add_Click({
    Invoke-UpdateAndRefresh -LogBox $logBox -StatusLabel $status -UpdateButton $btnUpdate
})

[void]$form.ShowDialog()
