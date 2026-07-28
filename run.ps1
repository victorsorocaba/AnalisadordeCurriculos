<#
.SYNOPSIS
    Sobe o backend (FastAPI/Uvicorn) e o frontend (Streamlit) da aplicacao
    Resume Analyzer + LaTeX Generator.

.DESCRIPTION
    - Usa o Python do ambiente virtual (.venv) se existir; senao usa o python do PATH.
    - Inicia o backend em uma nova janela do PowerShell na porta 8000.
    - Inicia o frontend em uma nova janela do PowerShell na porta 8501.

.EXAMPLE
    .\run.ps1
#>

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

Write-Host "Iniciando backend em http://localhost:8000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location -LiteralPath '$Root'; & '$Python' -m uvicorn backend.main:app --reload --port 8000"
)

Write-Host "Iniciando frontend em http://localhost:8501 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location -LiteralPath '$Root'; & '$Python' -m streamlit run frontend/app.py"
)

Write-Host ""
Write-Host "Backend:  http://localhost:8000  (docs em /docs)" -ForegroundColor Green
Write-Host "Frontend: http://localhost:8501" -ForegroundColor Green
Write-Host "Feche as janelas abertas para encerrar os processos." -ForegroundColor Green
