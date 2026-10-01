<#
.SYNOPSIS
    Sobe a API e a interface web no mesmo servidor.

.DESCRIPTION
    - Usa o Python do ambiente virtual (.venv) se existir; senao usa o python do PATH.
    - Inicia o servidor na porta 8000; pressione Ctrl+C para encerrar.

.EXAMPLE
    .\run.ps1
#>

param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [ValidateSet("127.0.0.1", "::1")][string]$BindAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

# Raiz do projeto = pasta deste script.
$Root = $PSScriptRoot

# Seleciona o interpretador Python: prioriza o venv local.
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
    Write-Host "Usando Python do ambiente virtual: $Python" -ForegroundColor Green
}
else {
    $Python = "python"
    Write-Host "Ambiente virtual .venv nao encontrado; usando 'python' do PATH." -ForegroundColor Yellow
    Write-Host "Dica: crie um venv com 'python -m venv .venv' e instale 'pip install -r requirements.txt'." -ForegroundColor Yellow
}

# Avisa se o .env nao existir (a chamada de IA precisa da chave de API).
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "Aviso: arquivo .env nao encontrado. Copie .env.example para .env e configure a chave de API." -ForegroundColor Yellow
}

Write-Host "Iniciando Alinha em http://localhost:$Port ..." -ForegroundColor Cyan
Write-Host ""
Write-Host "Aplicacao: http://localhost:$Port  (API em /docs)" -ForegroundColor Green
Set-Location -LiteralPath $Root
& (Join-Path $Root "start-postgres.ps1")
& $Python -m backend.migrate
if ($LASTEXITCODE -ne 0) { throw "Falha ao aplicar as migrações do PostgreSQL." }
& $Python -m uvicorn backend.main:app --reload --host $BindAddress --port $Port
