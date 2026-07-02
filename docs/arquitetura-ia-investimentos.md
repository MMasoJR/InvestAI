# Arquitetura Completa: Assessor de IA para o Mercado Financeiro

## Princípio orientador

"Treinar uma IA com milhares de documentos" na prática **não significa treinar um LLM do zero**. Treinar um modelo de linguagem do zero custa milhões de dólares e meses de GPU cluster — fora de cogitação para qualquer time, e desnecessário. O caminho certo, usado por praticamente todo produto sério de "IA + base de conhecimento" hoje, é **RAG (Retrieval-Augmented Generation)**:

1. Você guarda os documentos processados num banco vetorial.
2. Quando alguém pergunta algo, o sistema busca os trechos mais relevantes.
3. Um LLM já pronto (via API) recebe a pergunta + os trechos e responde com base neles, citando a fonte.

Isso significa que o "treinamento" do seu projeto é, na verdade, um pipeline de **dados + busca + orquestração** — é aí que mora 90% do trabalho de verdade, e é também onde dá pra ser "absurdamente bom": a qualidade final depende muito mais da qualidade dos dados e da engenharia de retrieval do que do modelo em si.

---

## 1. Fontes de dados (sites com PDFs, CSVs e APIs)

Importante: priorize fontes **públicas e abertas**. Conteúdo pago (FinClass, newsletters pagas, relatórios de research fechados) não deve entrar no pipeline de ingestão sem uma licença/parceria formal — isso vale tanto por questão legal quanto porque, se um dia você pitchar isso pro Grupo Primo, você quer chegar com "olha o que construí com dado público" e não "usei o conteúdo de vocês sem pedir".

### Brasil — dados regulatórios e oficiais (excelente qualidade, 100% legal)

| Fonte | O que tem | Formato | Link |
|---|---|---|---|
| CVM Dados Abertos | Demonstrações financeiras (DFP/ITR), formulários de referência, cadastro e carteiras de fundos | CSV/ZIP | dados.cvm.gov.br |
| Banco Central (SGS) | Séries históricas: Selic, IPCA, câmbio, indicadores macro | CSV/JSON via API | api.bcb.gov.br/dados/serie |
| B3 — Market Data | Cotações históricas, calendário de proventos, índices | CSV | b3.com.br/pt_br/market-data-e-indices |
| Tesouro Transparente | Preços e rentabilidade de títulos públicos | CSV | tesourotransparente.gov.br |
| IBGE/SIDRA | Indicadores macroeconômicos do Brasil | CSV/API | sidra.ibge.gov.br |
| RI das empresas listadas | Releases trimestrais, apresentações, fatos relevantes | PDF | site de RI de cada empresa (ex: ri.itausa.com.br) |

### Brasil — agregadores com API gratuita (ótimos pra dado estruturado)

| Fonte | O que tem | Link |
|---|---|---|
| brapi.dev | Cotações, dividendos, fundamentals de ações da B3 — API gratuita feita pra dev | brapi.dev |
| Fundamentus | Indicadores fundamentalistas resumidos por ação | fundamentus.com.br |
| StatusInvest | Indicadores fundamentalistas, histórico de proventos | statusinvest.com.br |

*(Fundamentus e StatusInvest não têm API oficial — qualquer coleta deve ser leve, espaçada, e respeitar o robots.txt. Não redistribua os dados brutos publicamente.)*

### Internacional — referência global

| Fonte | O que tem | Link |
|---|---|---|
| SEC EDGAR | Filings de empresas listadas nos EUA (10-K, 10-Q) | sec.gov/edgar/search |
| FRED (St. Louis Fed) | Séries macroeconômicas globais, gratuito, API robusta | fred.stlouisfed.org |
| World Bank Open Data | Indicadores econômicos globais | data.worldbank.org |
| Yahoo Finance (via `yfinance`) | Preços históricos, fundamentals — biblioteca Python pronta | pypi.org/project/yfinance |
| Alpha Vantage | API gratuita (com limite) de dados de mercado | alphavantage.co |

### Ferramentas de coleta

- **Playwright** (já é sua ferramenta preferida) para sites com JS/dinâmicos
- **httpx + BeautifulSoup** para HTML estático e APIs simples
- **PyMuPDF** ou **pdfplumber** para extrair texto/tabelas de PDFs (releases, formulários)
- A lib **`unstructured`** é excelente pra parsing automático de PDF/HTML/Word em chunks já estruturados

---

## 2. Arquitetura completa (camada por camada)

```
[Fontes de dados] 
      ↓
[Ingestão: scrapers + parsers de PDF/CSV] 
      ↓
[Processamento: limpeza, chunking, metadados] 
      ↓
[Embeddings: vetorização dos chunks]
      ↓
[Vector Store: Qdrant] ←──── [Busca híbrida: vetor + BM25] ←─ pergunta do usuário
      ↓                              ↓
[Reranking dos resultados]    [Query rewriting]
      ↓
[LLM (Claude/GPT via API) + contexto recuperado + citações]
      ↓
[API FastAPI] 
      ↓
[Frontend Next.js + streaming]
```

### Camada de processamento
- **Chunking semântico** (não fixo por caracteres): ~500-800 tokens, overlap de ~15%. Em documentos financeiros, **nunca quebre uma tabela no meio** — isso destrói a informação mais valiosa do documento.
- **Metadados ricos por chunk**: fonte, tipo de documento (DFP/release/notícia), ticker, data, trimestre, setor. Sem isso, você não consegue filtrar nem citar a fonte corretamente depois.

### Camada de embeddings
- **BAAI/bge-m3** — multilíngue, open-source, roda local ou no Colab com GPU, ótimo para português + jargão financeiro. Comece por aqui (é grátis).
- Alternativa paga e mais forte: `text-embedding-3-large` da OpenAI, via API.
- Gere os embeddings em lote no Colab quando o volume crescer (GPU T4 grátis acelera muito).

### Camada de vector store
- **Qdrant** — minha recomendação principal. Open-source, self-hostável via Docker, tem cloud free tier, filtros por metadado nativos e performance excelente.
- Alternativa mais simples de manter (um banco só): **pgvector** dentro do próprio Postgres, já que você já usa Postgres em outros projetos.

### Camada de retrieval (onde a qualidade "absurda" se constrói)
- **Busca híbrida**: combine busca vetorial (semântica) com BM25 (palavra-chave). Isso é crítico em finanças — buscas puramente semânticas erram tickers específicos como "ITUB4" ou números exatos.
- **Reranking**: depois de buscar os top-k chunks, reordene com um cross-encoder (`bge-reranker-v2-m3`, open-source, ou Cohere Rerank via API) antes de mandar pro LLM. Isso melhora MUITO a precisão final.
- **Query rewriting**: o próprio LLM reescreve a pergunta do usuário antes da busca, resolvendo ambiguidades e expandindo siglas do mercado.

### Camada de geração
- Use um LLM via API (Claude, GPT) — não tem motivo pra treinar um modelo do zero ou fazer fine-tuning nesse estágio.
- **System prompt bem desenhado**: defina a persona como assessor cauteloso, que sempre cita a fonte, nunca afirma certeza absoluta sobre o futuro do mercado, e menciona riscos.
- **Citações obrigatórias**: cada resposta deve referenciar de qual documento/trecho veio a informação. Isso constrói confiança e evita parecer "alucinação".
- **Tool calling**: deixe o modelo chamar uma ferramenta de cotação em tempo real (ex: via brapi.dev) quando a pergunta for sobre preço atual — separe dado estático (RAG) de dado dinâmico (API ao vivo).

### Orquestração
Dado seu nível, sugiro **não** usar um framework pesado (LangChain/LlamaIndex) por cima de tudo — construa o pipeline direto no FastAPI (chamada de embedding → busca no Qdrant → reranking → chamada ao LLM). Você mantém controle total, entende cada peça, e isso vira um diferencial enorme no portfólio (mostra que você entende RAG de verdade, não só "importei uma lib").

---

## 3. Stack e ferramentas

| Camada | Ferramenta | Por quê |
|---|---|---|
| Backend/API | **FastAPI** | Você já domina, performático, ótimo para endpoints de chat com streaming |
| Banco relacional | **PostgreSQL** | Usuários, histórico de chat, metadados — você já tem experiência |
| Vector DB | **Qdrant** | Open-source, rápido, filtros nativos, fácil de rodar em Docker |
| Embeddings | **bge-m3** (ou OpenAI embeddings) | Multilíngue, gratuito, bom para PT-BR financeiro |
| LLM | **Claude ou GPT via API** | Geração das respostas, com contexto recuperado |
| Frontend | **Next.js + TypeScript + Tailwind + shadcn/ui** | Você já usa essa stack (BeFit) — visual moderno e consistente |
| Chat UI | **Vercel AI SDK** | Biblioteca oficial pra interfaces de chat com streaming token a token — dá o "ar de ChatGPT/Claude" sem reinventar a roda. **Isso resolve o "nada de Streamlit"** |
| Deploy frontend | **Vercel** | Integração nativa com Next.js, deploy grátis pra projeto pessoal |
| Deploy backend | **Railway, Render ou Fly.io** | Fácil de configurar FastAPI + Postgres juntos |

### VSCode ou Colab? Os dois, com papéis diferentes

- **Google Colab** → fase de experimentação: testar modelos de embedding, validar estratégia de chunking, prototipar scraping, gerar embeddings em lote com GPU grátis. Use notebooks aqui, é descartável.
- **VSCode** → código de produção: a API FastAPI, o frontend Next.js, os scripts de ingestão versionados em Git. Tudo que vai pro GitHub e entra no seu portfólio.

Fluxo típico: você prototipa e valida uma ideia no Colab → quando funciona, "transplanta" o código limpo pro projeto VSCode/Git.

---

## 4. Roadmap em fases (sem prazo fixo — você decide o ritmo)

- **Fase 0** — Definir fontes de dados e esquema de metadados
- **Fase 1** — Pipeline de ingestão (scraping/download + parsing de PDF/CSV) salvando localmente
- **Fase 2** — Embeddings + Qdrant + teste de retrieval simples em notebook (Colab)
- **Fase 3** — API RAG funcional em FastAPI (retrieval + geração + citações), testada via Postman/terminal
- **Fase 4** — Frontend de chat bonito (Next.js + Vercel AI SDK + shadcn/ui)
- **Fase 5** — Busca híbrida + reranking + tool-calling para cotações em tempo real
- **Fase 6** — Autenticação, histórico de conversas, dashboard de carteira pessoal
- **Fase 7** — Polimento visual, métricas de qualidade das respostas, deploy público

### Se quiser ir além (v2, opcional)
Depois que tiver volume real de perguntas e respostas, dá pra considerar um fine-tuning leve (LoRA) num modelo open-source pequeno (ex: Llama 3.1 8B) só pra ajustar tom/estilo e reduzir custo de API em produção — mas isso é otimização de fase avançada, não o ponto de partida.

---

## 5. Conexão com o pitch (Grupo Primo ou outro comprador)

Construa a prova de conceito inteira com dados públicos/abertos da lista acima. Quando estiver sólida, o pitch fica: *"Aqui está a arquitetura funcionando com dados públicos — imagina isso com acesso oficial ao catálogo da FinClass."* Isso vira uma conversa de parceria, não uma acusação de uso indevido de conteúdo.

---

## 6. Estrutura de pastas do projeto (monorepo sugerido)

```
investai/
├── ingestion/                  # scripts de coleta e parsing (Python)
│   ├── scrapers/
│   │   ├── cvm.py
│   │   ├── bcb.py
│   │   ├── b3.py
│   │   └── ri_empresas.py      # Playwright
│   ├── parsers/
│   │   ├── pdf_parser.py
│   │   └── csv_parser.py
│   └── chunking.py
├── embeddings/
│   ├── generate_embeddings.py
│   └── notebooks/              # protótipos no Colab, depois migrados pra cá
├── backend/                    # FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── chat.py
│   │   │   └── documents.py
│   │   ├── services/
│   │   │   ├── retrieval.py
│   │   │   ├── reranking.py
│   │   │   └── llm.py
│   │   ├── models/             # Pydantic + SQLAlchemy
│   │   └── db/
│   └── requirements.txt
├── frontend/                   # Next.js
│   ├── app/
│   ├── components/
│   └── package.json
└── docker-compose.yml          # Qdrant + Postgres locais
```

Esse layout separa claramente "coleta de dados" (ingestion), "inteligência" (embeddings + backend) e "experiência" (frontend) — fica fácil trabalhar em uma camada sem travar as outras, e fica organizado pro GitHub/portfólio.

## 7. Dependências principais

**Python (backend/ingestion):**
```
fastapi
uvicorn
sqlalchemy
psycopg2-binary
qdrant-client
sentence-transformers   # roda o bge-m3 localmente
pdfplumber
playwright
pandas
httpx
rank-bm25                # busca por palavra-chave (parte do hybrid search)
anthropic                # ou openai, pra geração
```

**Node (frontend):**
```
next
react
typescript
tailwindcss
ai                        # Vercel AI SDK — streaming de chat
@radix-ui/react-*         # base do shadcn/ui
lucide-react
```

## 8. Rascunho do system prompt do assessor

Ponto de partida (evolui com testes reais — vale versionar isso no repo, ele é praticamente "código"):

> "Você é um assessor de investimentos que responde com base nos documentos fornecidos no contexto. Nunca afirme previsões de preço com certeza absoluta. Sempre cite a fonte (documento + data) de cada informação relevante. Se a informação não estiver no contexto recuperado, diga claramente que não tem dados suficientes em vez de inventar. Destaque riscos relevantes quando aplicável, e diferencie claramente fato (dado no documento) de interpretação (sua análise)."

Esse último ponto — separar fato de interpretação — é o que vai diferenciar um assessor confiável de um "papagaio de PDF".

## 9. Checklist pra começar essa semana

- [ ] Criar o repositório no GitHub com a estrutura da seção 6
- [ ] Subir Qdrant + Postgres localmente via `docker-compose`
- [ ] Escrever o primeiro scraper — sugestão: CVM Dados Abertos, porque já vem em CSV, sem fricção nenhuma
- [ ] No Colab, testar o `bge-m3` gerando embeddings de ~50 documentos e validar se a busca retorna chunks coerentes
- [ ] Só depois disso conectar ao LLM — valide o retrieval antes de gastar tempo (e tokens) na geração
