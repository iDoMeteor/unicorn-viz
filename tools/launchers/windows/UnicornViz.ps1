$ErrorActionPreference = 'Stop'
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
Set-Location $repo

if (Test-Path '.venv\Scripts\python.exe') {
    & '.venv\Scripts\python.exe' -m unicornviz @args
} else {
    & python -m unicornviz @args
}
