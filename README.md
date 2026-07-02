# InvestAI — Assessor de Investimentos (CVM)

Projeto completo: ingestão de dados públicos da CVM → chunking → embeddings
+ Qdrant → API RAG em FastAPI (com streaming) → frontend Next.js.

📖 **Antes de tudo, leia `docs/MANUAL-COMPLETO.md`** — é o guia passo a passo
com a explicação de cada arquivo e a ordem exata de execução. Este README
é mais um resumo rápido de referência. `docs/arquitetura-ia-investimentos.md`
é o plano geral/roadmap do projeto.

## Módulo de ingestão (DFP/ITR)


Fonte oficial e 100% pública:
- DFP — https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp
- ITR — https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr

## O que esse módulo faz

1. **Download** — baixa os ZIPs anuais de DFP/ITR direto do portal da CVM,
   de forma concorrente (porém limitada e educada com o servidor), com
   retry automático e backoff exponencial em caso de falha de rede.
2. **Idempotência** — se um arquivo já foi baixado, ele não baixa de novo.
   Rodar o comando várias vezes é seguro.
3. **Extração** — descompacta os ZIPs (cada um contém várias planilhas:
   balanço patrimonial, DRE, parecer de auditoria, etc.).
4. **Normalização** — converte cada CSV (que vem em `latin-1`, separador
   `;` e decimal `,`) para **Parquet**, formato muito mais rápido e leve
   pra ser consumido depois pela camada de embeddings/chunking.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Como usar

Baixar os ZIPs de DFP de 2015 a 2025:

```bash
python -m ingestion.cli download --doc-type dfp --start-year 2015 --end-year 2025
```

Processar (extrair + converter pra Parquet) o que já foi baixado:

```bash
python -m ingestion.cli process --doc-type dfp --start-year 2015 --end-year 2025
```

Mesma coisa para ITR (informações trimestrais):

```bash
python -m ingestion.cli download --doc-type itr --start-year 2015 --end-year 2025
python -m ingestion.cli process  --doc-type itr --start-year 2015 --end-year 2025
```

Use `-v` em qualquer comando pra ver logs em modo debug.

## Estrutura de pastas geradas

```
data/
├── raw/cvm/
│   ├── dfp/dfp_cia_aberta_2023.zip
│   └── itr/itr_cia_aberta_2023.zip
└── processed/cvm/
    ├── dfp/2023/dfp_cia_aberta_BPA_con_2023.parquet
    ├── dfp/2023/dfp_cia_aberta_DRE_con_2023.parquet
    └── ...
```

`data/` está no `.gitignore` — os dados não devem ser versionados no Git
(são GBs de informação pública, sem motivo pra duplicar no repositório).

## Testes

Os testes **não fazem nenhuma chamada de rede real** — usam um
`httpx.MockTransport` pra simular as respostas do servidor da CVM. Isso
torna a suíte rápida, determinística e independente de conexão:

```bash
pytest tests/ -v
```

## Notas importantes

- **Anos sem dado**: a CVM pode não ter publicado o ano corrente ainda, ou
  o histórico de ITR começa em 2011 (DFP em 2010). O cliente trata `404`
  como "sem dado disponível", não como erro — isso é esperado e normal.
- **Educado com o servidor**: o número de downloads simultâneos é limitado
  (`MAX_CONCURRENT_DOWNLOADS` em `ingestion/config.py`) e cada requisição
  identifica o bot via `User-Agent`. Edite o e-mail de contato nesse campo
  antes de rodar em produção — é boa prática ao consumir dados públicos.
- **Ambiente de execução**: este módulo precisa de acesso direto à internet
  para `dados.cvm.gov.br`. Rode localmente (ou num ambiente com rede
  irrestrita) — não dentro de sandboxes com allowlist de domínios.

## Módulo de chunking (`processing/chunking/cvm_chunker.py`)

Transforma os Parquets gerados acima em chunks de texto prontos para
embedding. Decisão central de design: **um chunk = uma demonstração
financeira completa** de uma empresa, em um único período/exercício (ex.:
"Balanço Patrimonial Ativo Consolidado da Empresa X em 31/12/2023") — nunca
quebramos uma demonstração no meio, preservando a árvore de contas inteira
e legível, com indentação hierárquica.

```python
from pathlib import Path
from processing.chunking.cvm_chunker import load_parquet_dir_chunks, export_chunks_to_jsonl

chunks = load_parquet_dir_chunks(Path("data/processed/cvm/dfp"), doc_type="dfp")
export_chunks_to_jsonl(chunks, Path("data/chunks/dfp_chunks.jsonl"))
```

Cada chunk carrega metadados ricos (`cnpj`, `company_name`, `statement_type`,
`consolidation`, `period_end`, `exercise_order`) — essenciais para filtro na
busca e para citar a fonte exata na resposta do assessor depois.

A deduplicação entre anos é automática: a CVM repete o período anterior como
"PENÚLTIMO" em cada arquivo novo, e o pipeline remove essa repetição mantendo
a primeira ocorrência.

**Fora do escopo deste chunker:** os arquivos de "parecer" (texto livre da
opinião do auditor) têm estrutura diferente — ver seção própria abaixo.

## Chunker do "parecer" — Relatório do Auditor Independente (`processing/chunking/cvm_parecer_chunker.py` + `text_chunker.py`)

Diferente das demonstrações financeiras (uma linha por conta contábil), o
arquivo `*_parecer_AAAA.csv` traz texto corrido — a opinião do auditor
independente sobre as demonstrações. Esse módulo trata esse caso à parte:

- `text_chunker.py` — chunker de texto livre genérico e reutilizável:
  divide por parágrafo, só quebra um parágrafo no meio (por frase) se ele
  sozinho já ultrapassar o limite, e mantém sobreposição entre pedaços
  consecutivos pra não perder contexto na fronteira.
- `cvm_parecer_chunker.py` — aplica esse chunking ao relatório de cada
  empresa/período, gerando um ou mais `ParecerChunk` por relatório
  (relatórios curtos viram um chunk só; longos são divididos).

⚠️ **Importante:** a coluna exata que contém o texto do relatório nesse
CSV da CVM não pôde ser confirmada durante o desenvolvimento (o ambiente
usado não tinha acesso de rede a `dados.cvm.gov.br`). Por isso, o módulo
**detecta automaticamente** a coluna de texto (heurística: a coluna string
com maior tamanho médio de conteúdo) em vez de usar um nome fixo que
poderia estar errado. **Na primeira vez que rodar isso com dados reais,
vale a pena conferir** — `print(chunk.text[:200])` num chunk e veja se
parece o início de um relatório de auditoria. Se a heurística errar, passe
o nome certo manualmente: `build_parecer_chunks(df, doc_type, text_column="NOME_REAL")`.

Os chunks de parecer já são incluídos automaticamente na indexação — ver
seção de embeddings abaixo (`--skip-parecer` desliga isso, se quiser).

## Módulo de embeddings + indexação (`embeddings/`)

Transforma os chunks gerados acima em vetores e os indexa no Qdrant para
busca semântica.

- `embeddings/embedder.py` — interface `Embedder` (Protocol) + implementação
  de produção `BGEM3Embedder` (BAAI/bge-m3, multilíngue, open-source). O
  import de `sentence-transformers`/`torch` é tardio, então as outras partes
  do pipeline não dependem dessas libs pesadas.
- `embeddings/qdrant_index.py` — `QdrantIndexer`: cria a collection, indexa
  chunks em lote (upsert idempotente — reindexar não duplica) e busca por
  similaridade com filtro opcional por `cnpj`/`statement_type`.
- `embeddings/cli.py` — conecta tudo numa única chamada: lê os Parquets
  processados (demonstrações **e** parecer), gera os chunks, embeda e
  indexa no Qdrant + BM25. Use `--skip-parecer` se quiser indexar só as
  demonstrações financeiras.

```bash
# Qdrant local embarcado (sem precisar de servidor/Docker) — ótimo pra começar
python -m embeddings.cli --doc-type dfp --qdrant-path data/qdrant_local

# Qdrant rodando em Docker ou Qdrant Cloud
python -m embeddings.cli --doc-type dfp --qdrant-url http://localhost:6333
```

**Sobre os testes deste módulo:** os testes de indexação/busca
(`tests/test_qdrant_index.py`) rodam contra uma instância **real** do Qdrant
em modo local (embarcado, sem servidor) — não são mocks. Para isso, usam um
`FakeEmbedder` determinístico (hash do texto) no lugar do bge-m3 real, pra
não depender de download de modelo nem GPU durante os testes.

## Backend FastAPI (`backend/`)

A API que expõe o assessor como um endpoint de chat HTTP.

- `backend/app/config.py` — configurações via variáveis de ambiente (prefixo `INVESTAI_`) ou arquivo `.env`
- `backend/app/services/llm.py` — interface `LLMClient` + `AnthropicLLMClient` (Claude via SDK oficial, lê `ANTHROPIC_API_KEY` do ambiente)
- `backend/app/services/retrieval.py` — busca no Qdrant e formata os chunks como contexto citável para o prompt
- `backend/app/services/assessor.py` — junta retrieval + geração, com o system prompt do assessor
- `backend/app/dependencies.py` — monta as instâncias reais (ponto único de configuração; nos testes, é sobrescrito)
- `backend/app/routers/chat.py` + `backend/app/main.py` — endpoint `POST /chat` e app FastAPI

```bash
# variável obrigatória pra geração funcionar de verdade:
export ANTHROPIC_API_KEY="sua-chave-aqui"

uvicorn backend.app.main:app --reload
# documentação interativa em http://localhost:8000/docs
```

Exemplo de chamada:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Qual o ativo total da empresa no último balanço?"}'
```

**Testes** (`tests/test_chat_api.py`): usam Qdrant local real + `FakeLLMClient`
(sem chamar a Anthropic) — validam o fluxo completo de retrieval e a API
HTTP, sem custo de rede/tokens.

## Banco de dados / histórico de conversas (`backend/app/db.py` + `models/db_models.py`)

Toda conversa e mensagem é persistida — isso permite perguntas de
seguimento ("e o patrimônio líquido dela?") e retomar uma conversa depois
de atualizar a página.

- **Sem configuração nenhuma**, usa SQLite local (`data/investai.db`) —
  zero setup pra desenvolver.
- Pra usar Postgres de verdade, defina `INVESTAI_DATABASE_URL` no `.env`:
  `postgresql+psycopg2://usuario:senha@localhost:5432/investai`
- As tabelas (`conversations`, `messages`) são criadas automaticamente no
  startup da API — não precisa rodar nenhuma migração manual pra começar.
- `backend/app/services/conversation_store.py` — todo o acesso ao banco
  passa por aqui (nada de SQL solto espalhado pelos routers).
- Endpoints novos: `GET /conversations` (lista) e `GET /conversations/{id}`
  (histórico completo de uma conversa).

**Multi-turno:** cada chamada a `/chat` ou `/chat/stream` aceita um
`conversation_id` opcional. Se enviado, o histórico daquela conversa
(até `INVESTAI_HISTORY_LIMIT` mensagens) é incluído como contexto pro
Claude — é isso que permite referências como "essa empresa" funcionarem
entre uma pergunta e outra.

## Busca híbrida (`embeddings/bm25_index.py` + `backend/app/services/retrieval.py`)

A busca semântica (vetorial) erra um tipo específico de coisa que importa
muito em finanças: termos exatos — tickers ("ITUB4"), códigos de conta,
números. Pra resolver isso, a busca agora é **híbrida**: combina o Qdrant
(semântica) com BM25 (palavra-chave exata) via **Reciprocal Rank Fusion**
— um método que funde os dois rankings sem precisar normalizar escalas de
score diferentes entre si.

```bash
# o índice BM25 já é gerado automaticamente junto com a indexação:
python -m embeddings.cli --doc-type dfp
# por padrão salva em data/bm25_index.pkl — o backend carrega isso sozinho
```

Se o arquivo `data/bm25_index.pkl` não existir ainda, o backend cai
automaticamente para busca só-vetorial (não quebra nada, só fica sem o
reforço de palavra-chave até você gerar o índice).

## Reranking (`embeddings/reranker.py`)

Depois da busca (híbrida ou só-vetorial) trazer os candidatos, um
cross-encoder (`BAAI/bge-reranker-v2-m3`) reordena esses candidatos
avaliando a pergunta e o documento JUNTOS — mais preciso que comparar
vetores isolados, por isso só é aplicado nos top-N candidatos, não na base
inteira. Habilitado por padrão; desligue com `INVESTAI_ENABLE_RERANKING=false`
no `.env` se quiser reduzir latência/memória.

## Cotações em tempo real — tool-calling (`backend/app/tools/`)

O assessor agora "decide" sozinho quando precisa de dados de mercado: se a
pergunta mencionar um ticker (ex: "ITUB4", "BBSE3"), o Claude aciona
automaticamente a ferramenta `get_market_quote`, que busca a cotação na
brapi.dev em tempo real e injeta o resultado no contexto antes de responder.

- `tools/market_data.py` — cliente HTTP da brapi.dev (com transporte
  injetável — testado sem rede real)
- `tools/definitions.py` — schema da ferramenta no formato que a API da
  Anthropic espera
- `tools/executor.py` — despacha os `tool_use` blocks do LLM e formata o
  resultado como texto; nunca levanta exceção (erros viram texto pro LLM)

Configure `INVESTAI_BRAPI_TOKEN` no `.env` com um token gratuito de
`https://brapi.dev` para ter acesso a qualquer ticker da B3. Sem token, os
4 tickers gratuitos (PETR4, VALE3, MGLU3, ITUB4) já funcionam.

No frontend, a busca de cotação aparece como um indicador animado (⚡
pulsando dourado → ✓ verde quando concluído) com o resultado exibido antes
da resposta do assessor.

## Frontend (`frontend/`)

Interface de chat em Next.js + TypeScript + Tailwind, com **streaming
token a token** (a resposta aparece sendo "digitada", como no Claude/ChatGPT),
consumindo o endpoint `/chat/stream` do backend.

Identidade visual própria (não é um clone genérico de chatbot): paleta
"terminal financeiro" — fundo quase-preto, acento dourado, números em fonte
monoespaçada — pensada especificamente pra um assessor de investimentos,
não pra um chat qualquer.

A conversa continua entre perguntas (o `conversation_id` é guardado no
`localStorage` do navegador) — feche a aba, abra de novo, e o histórico
ainda está lá. Use "Nova conversa" pra começar do zero.

```bash
cd frontend
npm install
cp .env.local.example .env.local   # ajuste NEXT_PUBLIC_API_URL se necessário
npm run dev
# abra http://localhost:3000 (com o backend já rodando em outro terminal)
```

**Build de produção testado** (`npm run build`) e a lógica de parsing do
streaming (`lib/parseStream.ts`) foi validada de ponta a ponta contra um
output real do backend, inclusive simulando fragmentação de rede — ver
detalhes em `docs/MANUAL-COMPLETO.md`.

> Nota: o `next.js` 14.x tem algumas vulnerabilidades conhecidas relacionadas
> a deploys públicos expostos (DoS, cache poisoning) — irrelevantes pra uso
> local/dev, mas vale fazer `npm audit` e considerar atualizar antes de um
> deploy público de verdade.

## Autenticação (`backend/app/services/auth.py` + routers/auth.py)

Usuários registram e fazem login via email/senha — a senha é armazenada com
**argon2** (hash moderno, sem os problemas de compatibilidade do bcrypt com
Python 3.x). O login devolve um **JWT** com validade de 7 dias.

Endpoints novos:
- `POST /auth/register` — cria conta e devolve token
- `POST /auth/login` — autentica e devolve token
- `GET /auth/me` — retorna dados do usuário autenticado

Controle de acesso:
- `GET /conversations` lista só as conversas do usuário logado
- `GET /conversations/{id}` bloqueia com 403 se a conversa for de outro usuário
- `POST /chat` e `POST /chat/stream` aceitam token **opcional** — conversas
  anônimas continuam funcionando (útil pra testar sem criar conta)

No frontend, a página `/` redireciona pra `/login` se não houver token. O
JWT é guardado no `localStorage` e incluído em todas as requisições. Página
de registro em `/register`.

⚠️ **Antes de qualquer deploy público**, troque `INVESTAI_SECRET_KEY` por
uma chave aleatória segura (comando no `.env.example`).

## Próximos passos do pipeline

1. ~~Chunking dos Parquets~~ ✅
2. ~~Embeddings + indexação no Qdrant~~ ✅
3. ~~API RAG em FastAPI (retrieval + geração + citações + streaming)~~ ✅
4. ~~Frontend de chat~~ ✅
5. ~~Postgres (histórico de conversas, multi-turno)~~ ✅
6. ~~Busca híbrida (BM25 + RRF)~~ ✅
7. ~~Reranking (cross-encoder)~~ ✅
8. ~~Chunker dedicado para os arquivos de "parecer" (texto livre)~~ ✅
9. ~~Dados em tempo real (cotações) via tool-calling~~ ✅
10. ~~Autenticação de usuários (JWT + argon2)~~ ✅

**🎉 Roadmap original completo.**

Próximas evoluções possíveis: deploy em produção (Docker Compose + Nginx),
painel de histórico de conversas no frontend, importação de outros tipos de
dado (FIIs, fundos da CVM), integração com a FinClass via parceria.

Esses próximos passos estão detalhados no documento de arquitetura geral
do projeto (`docs/arquitetura-ia-investimentos.md`).
