@echo off
REM Sobe a API e a interface web no mesmo servidor.

setlocal
set "ROOT=%~dp0"

REM Seleciona o interpretador Python: prioriza o venv local.
if exist "%ROOT%.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%.venv\Scripts\python.exe"
    echo Usando Python do ambiente virtual: %ROOT%.venv\Scripts\python.exe
) else (
    set "PYTHON=python"
    echo Ambiente virtual .venv nao encontrado; usando 'python' do PATH.
    echo Dica: crie um venv com "python -m venv .venv" e rode "pip install -r requirements.txt".
)

REM Avisa se o .env nao existir (a chamada de IA precisa da chave de API).
if not exist "%ROOT%.env" (
    echo Aviso: arquivo .env nao encontrado. Copie .env.example para .env e configure a chave de API.
)

echo Aplicacao: http://localhost:8000  (API em /docs)
echo Pressione Ctrl+C para encerrar.
cd /d "%ROOT%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start-postgres.ps1"
if errorlevel 1 exit /b 1
"%PYTHON%" -m backend.migrate
if errorlevel 1 exit /b 1
"%PYTHON%" -m uvicorn backend.main:app --reload --port 8000
endlocal
