param(
    [string]$ConcatPath,
    [string]$Workspace = (Join-Path $env:USERPROFILE "Videos\MilenaStudio"),
    [switch]$RegisterCodex
)
$ErrorActionPreference = "Stop"
$package = $PSScriptRoot
if (-not $ConcatPath) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Concat\concat.exe"),
        (Join-Path $env:ProgramFiles "Concat\concat.exe")
    )
    $ConcatPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $ConcatPath -or -not (Test-Path -LiteralPath $ConcatPath -PathType Leaf)) {
    throw "Instale uma versão do Concat com suporte a --mcp, ou informe -ConcatPath."
}
$ConcatPath = (Resolve-Path -LiteralPath $ConcatPath).Path
$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    & $python.Source -3 -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 ou posterior é necessário'"
    if ($LASTEXITCODE -ne 0) { throw "É necessário Python 3.11 ou posterior." }
    & $python.Source -3 -m venv (Join-Path $package ".venv")
} else {
    $python = Get-Command python -ErrorAction Stop
    & $python.Source -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 ou posterior é necessário'"
    if ($LASTEXITCODE -ne 0) { throw "É necessário Python 3.11 ou posterior." }
    & $python.Source -m venv (Join-Path $package ".venv")
}
if ($LASTEXITCODE -ne 0) { throw "Não foi possível criar o ambiente Python." }
$venvPython = Join-Path $package ".venv\Scripts\python.exe"
& $venvPython -m pip install $package
if ($LASTEXITCODE -ne 0) { throw "Não foi possível instalar a integração." }
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
$launcher = Join-Path $package ".venv\Scripts\milena-studio.exe"
$launchArgs = @("--concat", $ConcatPath, "--workspace", $Workspace)
if ($RegisterCodex) {
    $codex = Get-Command codex -ErrorAction Stop
    & $codex.Source mcp add milena-studio -- $launcher @launchArgs
    if ($LASTEXITCODE -ne 0) { throw "A integração foi instalada, mas o registro no Codex falhou." }
    Write-Host "Registrado. Reinicie o cliente local e peça studio_health."
}
Write-Host "Integração instalada. Pasta de trabalho: $Workspace"
Write-Host "Configuração para clientes MCP locais:"
@{mcpServers = @{"milena-studio" = @{command = $launcher; args = $launchArgs}}} | ConvertTo-Json -Depth 6
