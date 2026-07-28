# Resume Analyzer + LaTeX Generator

Aplicação de análise de currículos com geração automática de LaTeX. Arquitetura
dividida em dois processos Python:

- **Backend (FastAPI)** — expõe o endpoint assíncrono `POST /api/analyze`, que
  extrai o texto do currículo (PDF/TXT), envia para um modelo de IA (OpenAI ou
  Google GenAI) e devolve uma resposta validada com: percentual de match, lista
  de melhorias e código LaTeX pronto para compilar.
- **Frontend (Streamlit)** — interface para enviar o currículo, colar a
  descrição da vaga, disparar a análise e visualizar o resultado.

## Pré-requisitos

- Python 3.11+ (testado em 3.14)
- Uma chave de API de IA: OpenAI (padrão) ou Google GenAI

## 1. Instalar dependências

A partir da raiz do projeto, de preferência em um ambiente virtual:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 2. Configurar o ambiente

Copie o template e preencha a chave de API:

```powershell
copy .env.example .env
```

Conteúdo mínimo do `.env` para o provedor padrão (OpenAI):

```
AI_PROVIDER=openai
OPENAI_API_KEY=sua-chave-aqui
BACKEND_URL=http://localhost:8000
```

Para usar o Google GenAI, defina `AI_PROVIDER=google` e preencha `GOOGLE_API_KEY`.
A chave é lida **somente** do ambiente, nunca dos dados da requisição.

## 3. Rodar a aplicação

### Opção A — script (sobe backend + frontend juntos)

PowerShell:

```powershell
.\run.ps1
```

cmd:

```cmd
run.bat
```

O script sobe o backend em `http://localhost:8000` e o frontend em
`http://localhost:8501`.

### Opção B — manualmente (dois terminais)

Terminal 1 — backend:

```powershell
python -m uvicorn backend.main:app --reload --port 8000
```

Terminal 2 — frontend (com o venv ativado):

```powershell
python -m streamlit run frontend/app.py
```

## Uso

1. Abra `http://localhost:8501` no navegador.
2. Faça upload do currículo (PDF ou TXT).
3. Cole a descrição da vaga.
4. Clique em **Analyze**.

Documentação interativa da API: `http://localhost:8000/docs`.

## Testes

```powershell
python -m pytest backend/tests frontend/tests -q
```

## Estrutura do projeto

```
backend/
  main.py                 # app FastAPI + rota /api/analyze + pipeline de validação
  models/schemas.py       # modelos Pydantic + limpeza de fences markdown
  services/
    text_extractor.py     # extração de texto (pdfplumber / UTF-8)
    ai_service.py         # construção do prompt + chamada ao SDK de IA
  tests/                  # testes unitários e property-based (pytest + Hypothesis)
frontend/
  app.py                  # UI Streamlit + fluxo de requisição
  tests/
requirements.txt          # dependências unificadas (versões fixadas)
.env.example              # template de configuração
```

## Avisos de segurança

- Cada análise bem-sucedida **dispara uma chamada paga** ao provedor de IA.
- O endpoint `/api/analyze` é **não autenticado** por design. Antes de qualquer
  deploy público, adicione autenticação e rate limiting para evitar abuso e
  custos descontrolados.
- Não faça commit do arquivo `.env` (ele já está no `.gitignore`).
