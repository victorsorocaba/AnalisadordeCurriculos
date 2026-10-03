# Alinha

Aplicação para comparar um currículo com uma vaga, sugerir melhorias e gerar uma nova versão em LaTeX. A interface web responsiva e a API FastAPI rodam no mesmo servidor.

## Requisitos

- Python 3.11+
- Chave de API da OpenAI ou do Google GenAI
- Docker Compose para executar a aplicação com PostgreSQL, ou uma instância PostgreSQL 17 acessível pela aplicação

## PostgreSQL com Docker Compose

1. Copie `.env.example` para `.env` e configure `POSTGRES_PASSWORD` com uma senha forte e a chave do provedor de IA.
2. Encerre uma instância local que esteja usando a porta 8000 e execute `docker compose up --build -d` na raiz do projeto.
3. Abra **http://localhost:8000**. A aplicação só inicia após o banco ficar saudável e a migração SQL ser aplicada.

O volume `postgres_data` guarda as versões salvas do currículo e o planejamento das rotas entre reinicializações. O banco não é exposto na rede do computador; apenas a aplicação usa sua porta interna. A aplicação fica disponível somente em `127.0.0.1:8000`. Para acompanhar os serviços, execute `docker compose ps` e `docker compose logs -f app`.

Para guardar uma cópia do banco, use `docker compose exec -T db pg_dump -U alinha -d alinha -Fc > alinha.backup`. Guarde o arquivo em local privado: ele contém dados pessoais dos currículos. Antes de atualizar o PostgreSQL para outra versão principal, faça um backup e planeje a migração do volume.

É possível executar a API fora do Docker: configure `DATABASE_URL=postgresql://usuario:senha@host:5432/alinha` no `.env`, instale as dependências e use `run.ps1` ou `run.bat`. Esses scripts aplicam as migrações antes de iniciar a API. Sem `DATABASE_URL`, o modo local anterior continua disponível com armazenamento no navegador.

### Instalação local neste computador

O PostgreSQL 17.11 está instalado em `.local/postgresql-17`, com dados em `.local/postgresql-data`. Ambas as pastas são privadas para esta cópia do projeto e ignoradas pelo Git. A conexão está no `.env`. O script `run.ps1` inicia esse banco quando necessário, aplica as migrações e abre a API. Nesta sessão, a aplicação conectada está em **http://localhost:8000**. Depois de reiniciar o computador, execute `./run.ps1` para iniciar o banco e o site. Se outra instância ocupar o endereço IPv4 da porta 8000, use `./run.ps1 -BindAddress ::1` para manter o mesmo endereço `localhost:8000`. A instalação local não cria um serviço do Windows.

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Preencha `OPENAI_API_KEY` em `.env`. Para usar o Google GenAI, altere `AI_PROVIDER=google` e preencha `GOOGLE_API_KEY`. O modelo pode ser escolhido em `AI_MODEL`.

## Execução

```powershell
.\run.ps1
```

Ou, pelo Prompt de Comando, execute `run.bat`. Abra **http://localhost:8000**. A documentação da API fica em **http://localhost:8000/docs**. Pressione Ctrl+C para encerrar.

Também é possível iniciar diretamente:

```powershell
python -m uvicorn backend.main:app --reload --port 8000
```

## Uso

1. Envie um currículo em PDF ou TXT, com até 10 MB.
2. Cole a descrição da vaga e, se desejar, informe projetos relevantes.
3. Clique em **Analisar meu currículo**.
4. Revise o percentual estimado, os trechos encontrados e os requisitos sem evidência.
5. Revise as experiências escritas com o método STAR (contexto, tarefa, ação e resultado). Em **Ajuste sua versão**, use **Deixar currículo pronto pra vaga** para adaptar o texto à vaga com palavras-chave sustentadas pelo currículo, ou edite os campos manualmente. Atualize a prévia e baixe o PDF compilado ou o arquivo `.tex`.
6. Se quiser, salve uma versão. Com PostgreSQL configurado, ela fica no banco; caso contrário, permanece no navegador. É possível recuperar e comparar duas versões salvas.
7. Em **Vagas para você**, busque oportunidades usando a versão atual ou a última versão salva. Filtre por palavra-chave, região e modalidade; abra cada anúncio na plataforma de origem. Use **Registrar candidatura** para levar cargo, empresa, origem, link e descrição ao acompanhamento como vaga salva.
8. Em **Minhas candidaturas** (`/candidaturas`), salve vagas e acompanhe a etapa (preparando, enviada, entrevista, proposta e desfecho), data de acompanhamento, contato do recrutador, versão do currículo enviada, descrição da vaga e retorno. O painel mostra candidaturas por dia e mês e os acompanhamentos pendentes. Com uma versão salva vinculada e a descrição da vaga, gere uma carta de apresentação, mensagem ao recrutador e perguntas de entrevista para revisar e salvar.
9. Abra **Rotas de estudo** em `/rotas-estudo`, escolha uma das 95 rotas e entre na página individual dela. Marque cada assunto aprendido no checklist; o cartão mostra quantos assuntos foram concluídos e a página da rota mostra o progresso em porcentagem. Você pode desmarcar um assunto a qualquer momento. Quando a rota estiver concluída no planejamento ou todos os assuntos estiverem marcados, selecione as palavras-chave que domina e use **Adicionar selecionadas ao currículo**. Elas entram no campo Habilidades da versão editável para revisão.
10. Abra **Certificações** em `/certificacoes` para ver credenciais relacionadas às habilidades da análise atual ou da última versão salva. Você também pode enviar um PDF/TXT e informar um objetivo profissional.

O currículo e a descrição da vaga são enviados ao provedor de IA configurado. A resposta detalhada usa um esquema estruturado; trechos apresentados como evidência são conferidos contra o texto extraído do currículo. As experiências seguem STAR apenas com fatos fornecidos: quando faltar um resultado comprovável, o sistema sugere acrescentá-lo em vez de inventar um. Revise todas as informações geradas antes de usar o documento. O LaTeX é montado pelo servidor a partir dos campos editáveis e compilado para produzir o PDF.

Para gerar a prévia em PDF, instale **MiKTeX** ou **TeX Live** com `xelatex` ou `pdflatex` disponível no PATH. O servidor retorna uma mensagem clara se o compilador não estiver disponível.

Após a análise, **Plano de evolução** relaciona lacunas da vaga com assuntos das rotas e, quando há correspondência no catálogo, certificações. A recomendação é por termos e não substitui uma avaliação do seu domínio real: se você já domina uma habilidade, demonstre-a com uma evidência verdadeira no currículo.

Na primeira visita com PostgreSQL ativo, as versões, o planejamento, os checkboxes de estudo e as candidaturas já salvos no navegador são importados para o banco. A cópia local é preservada até a importação terminar. Em **Minha conta** (`/conta`), é possível criar uma conta com e-mail e senha; o cadastro transfere os dados deste navegador para a conta. Depois, entre com o mesmo login em outros dispositivos. As senhas são armazenadas com scrypt e as sessões usam tokens aleatórios com validade de 30 dias. Não há recuperação de senha por e-mail nesta versão; guarde sua senha. Ao sair, o cache local do perfil é limpo.

## Fontes de vagas

A busca consulta as APIs públicas de [Himalayas](https://himalayas.app/docs/remote-jobs-api) e [Remotive](https://remotive.com/remote-jobs/api) para vagas remotas. Os resultados mostram a plataforma de origem e levam ao anúncio original. A consulta à Remotive fica em cache por seis horas para respeitar sua orientação de frequência. Vagas remotas são filtradas para anúncios que aceitam candidatos no Brasil ou globalmente.

Para incluir vagas locais brasileiras, configure `JOOBLE_BR_API_KEY` com uma chave da [Jooble Brasil](https://br.jooble.org/api/about) e/ou `ADZUNA_APP_ID` e `ADZUNA_APP_KEY` da [Adzuna](https://developer.adzuna.com/overview) no arquivo `.env` e reinicie o servidor. Sem essas chaves, a seção continua funcionando com as fontes remotas e informa a limitação na tela.

A afinidade exibida é uma ordenação por palavras e habilidades encontradas nos anúncios. Não é uma previsão de contratação. O currículo completo permanece no aplicativo; as plataformas recebem apenas o termo de busca e, quando aplicável, a região.

O botão **Buscar no LinkedIn** abre a busca de vagas do próprio LinkedIn com o termo e a região preenchidos. Ele não importa anúncios para o Alinha nem exige cookies da sessão. O pacote `@florydev/linkedin-api-voyager` não foi integrado: ele usa endpoints internos do LinkedIn e sua interface documentada não oferece busca de vagas.

Em **Minhas candidaturas**, **Importar dados do link** tenta ler metadados públicos de anúncios da Gupy, LinkedIn, Indeed, Glassdoor, Greenhouse, Lever, Remotive e Himalayas. A importação depende dos dados que a plataforma publica na página, pode retornar só parte do anúncio e não usa sessão privada. Revise os campos; para outros sites ou páginas bloqueadas, cole a descrição manualmente. Links externos são restritos a HTTPS e a essa lista de plataformas.

## Rotas de estudo

O catálogo local em `frontend/roadmaps.json` contém as 95 rotas listadas em [roadmap.sh/roadmaps](https://roadmap.sh/roadmaps/) em 29/09/2026: 31 de carreiras, 55 de habilidades, 4 para iniciantes e 5 de boas práticas. Cada rota tem uma página própria em `/rotas-estudo/{id}` e um checklist original de 12 assuntos, distribuídos em três etapas. Os assuntos editáveis estão em `frontend/study-topics-source.txt`; execute `python scripts/build_study_topics.py` para atualizar o JSON servido ao navegador. As sugestões para currículo estão em `frontend/study-keywords-source.txt`; gere o JSON com `python scripts/build_study_keywords.py`. A página oferece um link para o mapa oficial e seus recursos. O Alinha não replica os mapas completos nem importa progresso da conta roadmap.sh. O planejamento e os checkboxes são salvos por perfil no PostgreSQL quando configurado, com cópia local no navegador. As palavras selecionadas são levadas ao editor por esta aba do navegador; o usuário deve atualizar a prévia e salvar uma nova versão após revisar.

## Minhas candidaturas

A página `/candidaturas` mantém cargo, empresa, origem, data, link, etapa, próximo acompanhamento, contato, versão do currículo, descrição, materiais de preparação e observações. O checkbox **Teve retorno** pode ser atualizado na lista. Os registros podem ser editados ou excluídos. A migração 004 adiciona os novos campos à tabela `job_applications` sem remover registros anteriores. Os dados continuam separados por perfil local ou conta autenticada.

## Certificações

A página `/certificacoes` compara termos presentes no currículo e no objetivo profissional com um catálogo curado de 19 certificações em `backend/services/certification_catalog.json`, conferido em 29/09/2026. Cada sugestão mostra os sinais encontrados, o nível e a página oficial do emissor. A ordenação usa regras locais, sem chamada ao provedor de IA; não representa probabilidade de contratação. O arquivo enviado é lido em memória pelo servidor e não é salvo. Antes de se inscrever, confira na página oficial os requisitos, preços, idioma e validade.

## Testes

```powershell
python -m pytest backend/tests -q
node --test frontend/tests/*.test.js
```

## Estrutura

```text
backend/main.py                 API, validação e entrega da interface
backend/storage.py              API de versões e progresso no PostgreSQL
backend/migrate.py              aplicação das migrações SQL
migrations/                     esquema versionado do banco
compose.yaml                    aplicação e PostgreSQL com volume persistente
Dockerfile                      imagem da API com compilador LaTeX
backend/services/              extração de texto e integração com IA
backend/models/schemas.py      contrato de resposta
frontend/index.html            estrutura da interface
frontend/roadmaps.html         página independente de rotas de estudo
frontend/applications.html     painel de candidaturas, etapas e preparação
frontend/account.html          cadastro e login para sincronização entre dispositivos
frontend/roadmap-detail.html   página individual com checklist de assuntos
frontend/study-topics-source.txt  assuntos originais de todas as rotas
frontend/study-keywords-source.txt  termos sugeridos para o currículo
frontend/certifications.html   página independente de certificações
frontend/styles.css            visual responsivo
frontend/app.js                edição, prévia, histórico e chamadas à API
frontend/storage.js            sincronização e importação do cache do navegador
```

## Publicação

Cada análise e cada geração de materiais faz uma chamada paga ao provedor de IA. Defina `APP_ACCESS_TOKEN` em `.env` para exigir um código de acesso nas rotas pagas e ativar limites em memória de 10 análises e 60 compilações de PDF por IP a cada hora. Esses limites reiniciam com o processo e não são compartilhados entre instâncias. As contas organizam os dados, mas não substituem o código de acesso das rotas pagas. Para publicação pública, acrescente recuperação de senha, verificação de e-mail e limites persistentes compartilhados entre instâncias.
