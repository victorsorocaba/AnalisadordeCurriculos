@echo off
REM Sobe o backend (FastAPI/Uvicorn) e o frontend (Streamlit) da aplicacao
REM Resume Analyzer + LaTeX Generator.

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

echo Iniciando backend em http://localhost:8000 ...
start "Backend - FastAPI" cmd /k "cd /d "%ROOT%" && "%PYTHON%" -m uvicorn backend.main:app --reload --port 8000"

echo Iniciando frontend em http://localhost:8501 ...
start "Frontend - Streamlit" cmd /k "cd /d "%ROOT%" && "%PYTHON%" -m streamlit run frontend/app.py"

echo.
echo Backend:  http://localhost:8000  (docs em /docs)
echo Frontend: http://localhost:8501
echo Feche as janelas abertas para encerrar os processos.
endlocal
