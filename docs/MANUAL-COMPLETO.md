# InvestAI — Manual Completo do Projeto

Este documento explica **tudo** o que foi construído até agora: o que cada
arquivo faz, como as peças se conectam, o que você precisa alterar antes de
rodar, e o passo a passo completo de execução — do zero até uma resposta
do assessor aparecendo no chat do navegador.

Ele complementa (não substitui) o `arquitetura-ia-investimentos.md`, que é
o plano geral do projeto. Este aqui é o "manual de instruções" do que **já
existe e já funciona** dentro da pasta `investai/`.

---

## 1. A ideia em uma frase

Pegamos dados financeiros públicos da CVM → transformamos em texto legível
→ transformamos esse texto em vetores (embeddings) → guardamos esses
vetores num banco de busca (Qdrant) → quando alguém faz uma pergunta,
buscamos os trechos mais relevantes → mandamos pra um LLM (Claude)
responder com base só naqueles trechos, citando a fonte.

Isso é **RAG** (Retrieval-Augmented Generation). Nenhuma parte deste
projeto treina um modelo de IA do zero — a "inteligência" vem do Claude via
API; o valor que você está construindo é o pipeline de dados + busca em
volta dele.

---

## 2. O fluxo completo, de ponta a ponta

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌─────────────────┐     ┌──────────────┐
│  ingestion/ │ --> │ processing/  │ --> │   embeddings/  │ --> │    backend/     │ --> │  frontend/   │
│  (baixa e   │     │  chunking/   │     │  (vetoriza e   │     │  (API que       │     │  (chat com   │
│  organiza   │     │  (transforma │     │   indexa no    │     │   responde,     │     │  streaming   │
│  os dados)  │     │  em texto)   │     │   Qdrant)      │     │   com streaming │     │ no navegador)│
└─────────────┘     └──────────────┘     └────────────────┘     └─────────────────┘     └──────────────┘
      │                     │                     │                      │                      │
      ▼                     ▼                     ▼                      ▼                      ▼
 data/raw/cvm/        (em memória,         data/qdrant_local/      POST /chat/stream      http://localhost:3000
 *.zip                não salva em            (banco vetorial         (NDJSON: fontes  
                       disco por padrão)       persistido em disco)    + tokens + done)
      │
      ▼
 data/processed/cvm/
 *.parquet
```

Duas coisas que não aparecem no diagrama por simplicidade, mas existem:

- O passo de `embeddings/` também gera `data/bm25_index.pkl` (busca por
  palavra-chave) — o `backend/` usa os dois (Qdrant + BM25) juntos.
- O `backend/` lê e grava num banco de dados (`data/investai.db` por
  padrão, ou Postgres se configurado) pra guardar o histórico de cada
  conversa — é o que permite perguntas de seguimento.

Cada seta é uma etapa que você dispara manualmente via linha de comando
(por enquanto — automatizar isso com agendamento é um próximo passo
possível, mas não necessário agora).

---

## 3. O que cada arquivo faz (por pasta)

### `ingestion/` — baixar e organizar os dados brutos da CVM

| Arquivo | Para que serve |
|---|---|
| `config.py` | Constantes do projeto: URLs base da CVM, pastas de dados, política de retry. **É aqui que você muda o e-mail de contato no `USER_AGENT`** (ver seção 4). |
| `scrapers/cvm.py` | O coração da ingestão: a classe `CVMClient`. Baixa os ZIPs (com retry/backoff e sem refazer download do que já existe), extrai, e converte os CSVs pra Parquet. |
| `cli.py` | Comando de terminal pra disparar o download (`download`) e o processamento (`process`). É o que você de fato vai digitar no terminal. |

**Por que Parquet e não CSV puro?** Parquet é binário, comprimido e
muito mais rápido de ler depois (a etapa de chunking lê esses arquivos
repetidamente). CSV continua existindo, só dentro do ZIP original.

### `processing/chunking/` — transformar dados tabulares em texto

| Arquivo | Para que serve |
|---|---|
| `cvm_chunker.py` | Lê os Parquets (formato "uma linha por conta contábil") e agrupa tudo em blocos de texto completos — uma demonstração financeira inteira de uma empresa, num período. Também remove duplicatas entre anos e exporta pra JSONL. |
| `text_chunker.py` | Chunker de texto livre genérico (parágrafo-aware, com overlap) — usado pelo `cvm_parecer_chunker.py` abaixo, mas é independente e reutilizável pra qualquer texto longo. |
| `cvm_parecer_chunker.py` | Lê os arquivos de "parecer" (Relatório do Auditor Independente — texto corrido, não tabular) e gera um ou mais chunks por relatório. **Detecta automaticamente** qual coluna do CSV tem o texto (ver aviso na seção 4 abaixo). |

**Por que isso existe?** Um LLM não "entende" uma tabela com 80 linhas
soltas — ele entende texto corrido com contexto. Esse módulo é a ponte
entre "dado tabular da CVM" e "texto que faz sentido pra uma IA ler".

**Por que o parecer precisou de um chunker separado?** Diferente das
demonstrações (tabela, uma linha por conta), o parecer é texto corrido —
às vezes várias páginas. `text_chunker.py` divide isso em pedaços
gerenciáveis (por parágrafo, com sobreposição entre pedaços vizinhos pra
não perder contexto na fronteira), em vez de tentar colocar o relatório
inteiro como um único embedding gigante (o que prejudicaria a qualidade
da busca).

### `embeddings/` — transformar texto em vetores e indexar

| Arquivo | Para que serve |
|---|---|
| `embedder.py` | Define o que é um "gerador de embeddings" (`Embedder`) e a implementação real, `BGEM3Embedder` (modelo BAAI/bge-m3). |
| `qdrant_index.py` | A classe `QdrantIndexer`: cria a collection no Qdrant, indexa os chunks em lote, e faz a busca por similaridade (com filtro opcional por empresa/tipo de demonstração). |
| `bm25_index.py` | A classe `BM25Index`: busca por palavra-chave exata (tickers, números, códigos de conta) — complementa a busca semântica, que erra esse tipo de termo. |
| `reranker.py` | A classe `CrossEncoderReranker`: reordena os candidatos da busca avaliando pergunta+documento juntos — mais preciso que comparar vetores isolados. |
| `cli.py` | Comando único que liga tudo: lê os Parquets → gera os chunks → embeda → indexa no Qdrant → constrói e salva o índice BM25. |

**Por que uma interface (`Embedder`) em vez de só uma função?** Pra você
poder trocar de modelo de embedding (ex.: ir pra um da OpenAI no futuro)
sem precisar tocar em nenhuma outra parte do código. Só troca essa peça.

**Por que busca híbrida (BM25 + vetorial)?** Busca semântica pura "entende
significado", mas é ruim com termos exatos — um ticker como "ITUB4" ou um
código de conta específico podem não "parecer" semanticamente especiais
pro modelo de embedding. BM25 (palavra-chave clássica) resolve exatamente
esse ponto cego. A fusão dos dois rankings usa **Reciprocal Rank Fusion**
(`reciprocal_rank_fusion` em `backend/app/services/retrieval.py`) — soma
`1/(k+posição)` de cada lista, o que funciona mesmo sem normalizar as
escalas de score (cosseno do Qdrant não é comparável ao score do BM25
diretamente). Se o índice BM25 ainda não foi gerado, o sistema cai
automaticamente pra busca só-vetorial — nada quebra.

**Por que reranking depois da busca híbrida?** Busca híbrida (vetorial +
BM25) é rápida, mas avalia pergunta e documento separadamente. Um
cross-encoder (`reranker.py`) avalia os dois JUNTOS — mais preciso, mas
mais lento, por isso só roda nos `fetch_k` candidatos já filtrados (não na
base inteira de documentos). É opcional e ligado por padrão; desligue com
`INVESTAI_ENABLE_RERANKING=false` se quiser economizar memória/latência
numa máquina mais fraca.

### `backend/app/` — a API que responde perguntas

| Arquivo | Para que serve |
|---|---|
| `config.py` | Lê as configurações de variáveis de ambiente (chave de API, endereço do Qdrant, etc.). |
| `services/retrieval.py` | Pega a pergunta do usuário, busca no Qdrant, e formata os resultados como texto numerado e citável pro prompt. |
| `services/llm.py` | Define o que é um "cliente de LLM" e a implementação real (`AnthropicLLMClient`), que chama a API do Claude. |
| `services/assessor.py` | **O cérebro do assessor.** Junta retrieval + LLM, define o *system prompt* (a personalidade/regras do assessor) e monta a resposta final com as fontes usadas. |
| `dependencies.py` | Onde as peças reais são "montadas" (Qdrant + bge-m3 + Claude + brapi.dev). Nos testes, essa montagem é substituída por versões falsas/locais. |
| `db.py` | Configura o banco (Postgres real ou SQLite local por padrão) e expõe `get_db`, usado pelo FastAPI pra abrir/fechar uma sessão por requisição. |
| `models/db_models.py` | As tabelas `users`, `conversations` e `messages` (SQLAlchemy ORM). |
| `services/auth.py` | Hashing de senha (argon2) e JWT: `hash_password`, `verify_password`, `create_access_token`, `decode_access_token`. |
| `services/user_store.py` | CRUD de usuários — criar, buscar por email/ID, autenticar (verifica hash). |
| `services/conversation_store.py` | Todo o acesso ao banco passa por aqui — criar/buscar conversa (agora com `user_id`), salvar mensagem, montar o histórico. |
| `auth_deps.py` | Dependencies do FastAPI: `get_current_user` (obrigatório, levanta 401) e `get_optional_user` (retorna None se anônimo). |
| `models/schemas.py` | Formato exato (Pydantic) do que entra e sai da API — inclui os schemas de registro, login e resposta de token. |
| `routers/auth.py` | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`. |
| `routers/chat.py` | `POST /chat` e `POST /chat/stream` — aceita token opcional; se presente, vincula a conversa ao usuário. |
| `routers/conversations.py` | `GET /conversations` e `GET /conversations/{id}` — **agora exigem autenticação** e filtram por usuário. |
| `main.py` | Junta tudo na aplicação FastAPI, e cria as tabelas automaticamente ao iniciar. |
| `tools/` | Ferramentas de cotação em tempo real (brapi.dev) via tool-calling — ver seção anterior. |

**Por que tantos arquivos pequenos em vez de um `main.py` gigante?** Cada
peça (retrieval, LLM, montagem de dependências, rotas, banco) pode ser
testada e trocada isoladamente. Esse é o mesmo princípio de design usado
nos módulos anteriores (`Embedder`, ingestão) — é o que torna o projeto
"profissional" em vez de um script só.

**Sobre o multi-turno:** cada pergunta nova entra como mais uma mensagem
numa lista (`role: "user"`/`"assistant"`), junto com as mensagens
anteriores da mesma conversa — exatamente como a API da Anthropic espera.
Isso é diferente de simplesmente colar o histórico como texto dentro de
uma string; deixa o modelo "ver" a estrutura real da conversa, turno por
turno, o que funciona melhor pra resolver referências como "essa empresa".

### `frontend/` — a interface de chat no navegador

| Arquivo | Para que serve |
|---|---|
| `lib/parseStream.ts` | Lê o NDJSON que chega do backend em pedaços (que podem chegar com uma linha "quebrada" no meio) e remonta os eventos completos. Testado isoladamente, sem depender do React. |
| `lib/api.ts` | Chama `POST /chat/stream` e dispara callbacks (`onSources`, `onToken`, `onDone`) conforme os eventos chegam. |
| `components/ChatMessage.tsx` | Renderiza uma mensagem — bolha pro usuário, bloco de "memo" com fontes citadas pro assessor. |
| `components/SourceChip.tsx` | A "ficha" de citação de cada fonte (empresa, demonstração, período, % de relevância). |
| `components/ChatInput.tsx` | Campo de texto (Enter envia, Shift+Enter quebra linha). |
| `components/EmptyState.tsx` | Tela inicial com exemplos de pergunta clicáveis. |
| `app/page.tsx` | Junta tudo: mantém a lista de mensagens em estado React e atualiza a mensagem do assessor token a token conforme o streaming chega. |
| `app/layout.tsx` + `app/globals.css` | Layout raiz e os tokens visuais (cores, fontes) do tema "terminal financeiro". |
| `tailwind.config.ts` | A paleta e tipografia próprias do projeto — pensadas pra não parecer "mais um chatbot genérico". |

**Por que streaming e não só JSON de uma vez?** Sem streaming, a tela fica
parada esperando a resposta inteira e só aparece tudo de uma vez — péssima
sensação de uso. Com streaming, o texto vai aparecendo conforme o Claude
gera, exatamente como você vê no claude.ai ou no ChatGPT.

**Validação real feita durante a construção:** gerei um output de verdade
do endpoint `/chat/stream` (via TestClient do FastAPI), salvei o NDJSON
bruto, e alimentei esse exato output — fragmentado artificialmente em
pedaços de 17 bytes, simulando uma rede instável — direto no parser do
frontend (`lib/parseStream.ts`) rodando via `tsx`. O resultado remontado
bateu perfeitamente com o esperado. Ou seja: a integração entre backend e
frontend não é "deveria funcionar" — foi testada ponta a ponta de verdade.

### `tests/` — garante que nada quebra silenciosamente

| Arquivo | Para que serve |
|---|---|
| `test_cvm.py` | Testa o download/parsing da CVM, sem rede real (usa um servidor HTTP simulado). |
| `test_cvm_chunker.py` | Testa o chunking com dados sintéticos que imitam o formato real da CVM. |
| `test_qdrant_index.py` | Testa indexação e busca contra um Qdrant **real** (modo local, sem servidor) — não é mock. |
| `test_chat_api.py` | Testa a API completa de ponta a ponta (retrieval real + resposta HTTP), com um LLM falso no lugar do Claude. |
| `fake_embedder.py` / `fake_llm.py` | Versões falsas e determinísticas, usadas só nos testes, pra não depender de modelo/rede/custo de API. |

**Por que isso importa pro seu portfólio:** ter 105 testes automatizados
passando é exatamente o tipo de coisa que diferencia um projeto de
estudante de um projeto "nível produção" — e é um ótimo ponto pra
mencionar numa entrevista ou no pitch.

### Arquivos na raiz

| Arquivo | Para que serve |
|---|---|
| `requirements.txt` | Todas as dependências Python do projeto (backend/ingestão). |
| `.env.example` | Modelo das variáveis de ambiente do backend — copie pra `.env` e preencha. |
| `.gitignore` | Evita versionar dados baixados, caches e o `.env` real (com sua chave de API). |
| `README.md` | Guia de uso rápido, módulo por módulo (mais resumido que este documento). |
| `docs/` | Este manual + o documento de arquitetura geral do projeto. |
| `frontend/` | O chat em si (Next.js) — tem seu próprio `package.json` e `.env.local.example`, independente do Python. |

---

## 4. O que você PRECISA alterar antes de rodar de verdade

- [ ] **Criar o arquivo `.env`** a partir do `.env.example` e colocar sua
      chave da API da Anthropic em `ANTHROPIC_API_KEY`. Sem isso, a parte
      de geração de resposta não funciona (o resto do pipeline — download,
      chunking, embeddings, indexação — funciona sem chave nenhuma).
- [ ] **Editar o `USER_AGENT` em `ingestion/config.py`** e colocar um e-mail
      de contato real seu, no lugar de `"defina-seu-email-aqui"`. Isso é
      boa prática ao consumir uma API/dado público — identifica quem está
      fazendo as requisições.
- [ ] **Decidir onde o Qdrant vai morar**: por padrão, tudo roda no modo
      local embarcado (`data/qdrant_local/`, sem precisar instalar nada
      além da lib Python). Se um dia você quiser rodar via Docker ou
      Qdrant Cloud, defina `INVESTAI_QDRANT_URL` no `.env`.
- [ ] **Nada mais é obrigatório.** Os defaults (anos a baixar, nome da
      collection, top_k de resultados) já vêm preenchidos com valores
      razoáveis em `ingestion/config.py`, `backend/app/config.py` e nos
      argumentos da CLI. O banco de dados também não exige nada: por
      padrão usa SQLite local (cria o arquivo sozinho). Só defina
      `INVESTAI_DATABASE_URL` no `.env` se quiser usar um Postgres real.
- [ ] **Recomendado (não obrigatório): conferir a detecção do parecer.**
      O chunker do Relatório do Auditor Independente
      (`processing/chunking/cvm_parecer_chunker.py`) detecta sozinho qual
      coluna do CSV tem o texto do relatório, porque esse nome não pôde
      ser confirmado durante o desenvolvimento (sem acesso de rede a
      `dados.cvm.gov.br` no ambiente usado). Na primeira vez que rodar com
      dados reais, vale conferir: pegue um chunk gerado e dê um
      `print(chunk.text[:200])` — se parecer o início de um relatório de
      auditoria de verdade, está tudo certo. Se não, veja a seção 8 (item
      do parecer) pra como corrigir manualmente.

---

## 5. Passo a passo de execução, do zero

Execute tudo isso na pasta raiz do projeto (onde está o `requirements.txt`).

### 5.1. Preparar o ambiente

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # depois edite o .env com sua chave da Anthropic
```

### 5.2. Baixar os dados da CVM

```bash
python -m ingestion.cli download --doc-type dfp --start-year 2020 --end-year 2025 -v
```

Isso baixa os ZIPs anuais pra `data/raw/cvm/dfp/`. Rodar de novo é seguro
(não baixa o que já existe).

### 5.3. Processar (extrair + converter pra Parquet)

```bash
python -m ingestion.cli process --doc-type dfp --start-year 2020 --end-year 2025 -v
```

Gera os Parquets em `data/processed/cvm/dfp/<ano>/`.

### 5.4. Gerar embeddings, indexar no Qdrant e construir o índice BM25

```bash
python -m embeddings.cli --doc-type dfp -v
```

Esse comando faz o chunking (das demonstrações **e** do parecer/relatório
do auditor), baixa o modelo `bge-m3` (só na primeira vez, ~2GB), indexa
tudo no Qdrant local (`data/qdrant_local/`) **e** constrói o índice de
busca por palavra-chave (`data/bm25_index.pkl`) — é isso que habilita a
busca híbrida no backend automaticamente. Use `--skip-parecer` se quiser
indexar só as demonstrações financeiras.

> ⏱️ Esse passo pode demorar dependendo da quantidade de empresas/anos.
> Comece com um intervalo pequeno (2-3 anos) pra validar que tudo funciona
> antes de processar o histórico completo.
>
> 🔍 Na primeira vez, vale conferir se o chunker do parecer detectou a
> coluna de texto certa (ver checklist na seção 4) — é rápido e evita
> indexar lixo sem perceber.

### 5.5. Subir a API

```bash
uvicorn backend.app.main:app --reload
```

Abra `http://localhost:8000/docs` no navegador — é a documentação
interativa (Swagger) gerada automaticamente pelo FastAPI. Dá pra testar o
endpoint direto ali, sem precisar de `curl` nem Postman.

### 5.6. Fazer uma pergunta de verdade

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Qual o ativo total da empresa no último balanço disponível?"}'
```

A resposta vem em JSON, com o campo `answer` (texto do assessor) e
`sources` (lista das demonstrações usadas como base, com o score de
relevância de cada uma).

### 5.7. Subir o frontend (chat de verdade, com autenticação e streaming)

Em **outro terminal** (deixe a API do passo 5.5 rodando):

```bash
cd frontend
npm install
copy .env.local.example .env.local    # Windows (cmd). PowerShell: cp .env.local.example .env.local
npm run dev
```

Abra `http://localhost:3000` — você será redirecionado para `/login`.
Crie uma conta em `/register` (qualquer email + senha com 8+ caracteres)
e você terá acesso ao chat. A resposta aparece token a token, com o
indicador de ferramenta pulsando dourado quando o assessor busca cotações.

> 💡 O chat funciona sem conta também: teste via Swagger (`/docs`) ou
> `curl POST /chat` sem header de autenticação — conversas anônimas ainda
> são criadas, só não ficam vinculadas a um usuário.

---

## 6. Como rodar os testes

```bash
pytest tests/ -v
```

Isso roda os 105 testes sem precisar de internet, sem baixar nenhum modelo,
sem um Postgres real rodando e sem gastar nenhum token de API — tudo via
dados sintéticos, SQLite em memória e versões falsas das peças que custam
dinheiro/rede (LLM e modelo de embedding). Rodar isso depois de qualquer
alteração no código é a forma mais rápida de saber se você quebrou algo.

---

## 7. Glossário rápido (útil pra explicar o projeto em entrevista/pitch)

- **RAG (Retrieval-Augmented Generation)**: em vez de o LLM "saber tudo de
  cabeça", ele recebe trechos relevantes de documentos reais junto com a
  pergunta, e responde com base neles. Reduz alucinação e permite citar fontes.
- **Embedding**: um vetor de números que representa o "significado" de um
  texto. Textos com significado parecido geram vetores próximos entre si.
- **Vector store / banco vetorial**: banco de dados otimizado pra buscar
  "o que está mais próximo" de um vetor de consulta — é o que o Qdrant faz.
- **Chunk**: um pedaço de texto, do tamanho certo, que vira um vetor e fica
  guardado no banco vetorial. Neste projeto, cada chunk é uma demonstração
  financeira completa de uma empresa em um período.
- **Upsert idempotente**: inserir ou atualizar (nunca duplicar) — reindexar
  o mesmo dado várias vezes não cria cópias repetidas.
- **System prompt**: a instrução fixa que define a "personalidade" e as
  regras do assistente (no nosso caso, está em `backend/app/services/assessor.py`).
- **BM25**: algoritmo classico de busca por palavra-chave (não semântico) —
  bom em encontrar termos exatos que a busca vetorial pode não valorizar.
- **RRF (Reciprocal Rank Fusion)**: método pra combinar dois rankings
  diferentes (ex.: busca semântica + busca por palavra-chave) num só,
  somando `1/(k+posição)` de cada lista — não exige que os scores das duas
  buscas estejam na mesma escala.
- **Multi-turno**: quando o assistente "lembra" das mensagens anteriores da
  mesma conversa, permitindo perguntas de seguimento como "e essa empresa?".

---

## 8. Status final do roadmap

1. ~~**Frontend**~~ ✅ — chat com streaming em Next.js.
2. ~~**Postgres / histórico de conversas**~~ ✅ — multi-turno funcionando.
3. ~~**Busca híbrida (BM25 + RRF)**~~ ✅
4. ~~**Reranking**~~ ✅ — cross-encoder reordenando candidatos.
5. ~~**Chunker do "parecer"**~~ ✅ — texto livre do auditor, parágrafo-aware.
6. ~~**Dados em tempo real (tool-calling)**~~ ✅ — cotações via brapi.dev.
7. ~~**Autenticação (JWT + argon2)**~~ ✅ — registro/login, conversas por
   usuário, redirecionamento automático no frontend.

**🎉 Roadmap original 100% concluído.**

**Próximas evoluções possíveis** (fora do escopo original, mas naturais):
- Deploy em produção (Docker Compose + Nginx, HTTPS, variáveis seguras)
- Painel de histórico de conversas no frontend (`GET /conversations`)
- Importação de outros tipos de dado (FIIs, fundos da CVM, RI das empresas)
- Integração oficial com a FinClass via parceria (pitch pra o Grupo Primo)
- Fine-tuning leve (LoRA) num modelo open-source pra reduzir custo de API

## 9. Aviso de segurança para deploy público

Antes de publicar qualquer versão online:

- `INVESTAI_SECRET_KEY` — troque por uma chave aleatória longa:
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `ANTHROPIC_API_KEY` — nunca commite no Git, sempre via variável de ambiente
- `INVESTAI_BRAPI_TOKEN` — idem
- `INVESTAI_DATABASE_URL` — aponte pra um Postgres com senha forte
- `INVESTAI_QDRANT_URL` — use uma instância Qdrant Cloud ou protegida por VPN
- No `main.py`, substitua `allow_origins=["http://localhost:3000"]` pelo
  domínio real do frontend antes de colocar em produção

