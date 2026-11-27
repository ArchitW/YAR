# YAR — Yet Another RAG

> **Active development.** Core features are stable and tested end-to-end. APIs and schemas may change between sessions. Not production-hardened yet — see [What's Missing](#whats-missing).

YAR is a **self-hosted, privacy-first knowledge intelligence platform**. Upload your documents, ask questions in plain language, and get grounded answers with numbered citations that link back to the exact source passage — including visual bounding-box highlights on PDFs. YAR also remembers what matters across sessions via a cognitive memory engine, reasons autonomously when your documents don't have the answer, and runs entirely on local hardware with no data leaving your machine.

---

## What YAR Does Today

### Document Ingestion
- **Formats:** PDF, TXT, Markdown, CSV, XLSX, EPUB, PNG/JPG/WEBP/TIFF (via OCR)
- **PDF bounding boxes:** Visual text-run extraction with `{page, bbox, page_width, page_height}` metadata for citation highlighting
- **Tabular extraction:** CSV, XLSX, and PDF tables converted to clean GitHub-flavoured Markdown
- **OCR fallback:** RapidOCR on scanned images and image-only PDF pages
- **Text cleaning:** NFKC normalization, hyphenation repair, whitespace collapse

### Retrieval & Ranking
- **Hybrid search:** Dense embeddings (bge-m3) + 31-bit sparse lexical vectors (sublinear TF, stopword filtering, ascending index constraint) fused via Reciprocal Rank Fusion (RRF)
- **Late chunking:** Transformer attention-span pooling over full-document context before slicing (preserves cross-sentence semantics)
- **Parent-child hierarchical chunking:** Child chunks (150 tokens) vectorized for precision; parent sections (800 tokens) injected into LLM context for completeness
- **Cross-encoder reranking:** BGE reranker with graceful extractive fallback when no LLM is available
- **Query rewriting:** Conversational pronoun resolution from chat history (last 4 turns)
- **HyDE:** Hypothetical Document Embeddings to bridge vocabulary gaps (opt-in via `HYDE_ENABLED=true`)
- **Workspace-scoped filtering:** All Qdrant queries are tenant-isolated at the database level

### Chat & Streaming
- **SSE streaming:** `POST /chat/stream` returns `text/event-stream` with structured `init → token → done` events; first token in < 500 ms on fast providers
- **Unary chat:** `POST /chat` for non-streaming clients; both paths share the same retrieval + guardrails pipeline
- **Extractive fallback:** When no LLM is configured, returns a grounded bullet-point answer from retrieved chunks and marks `"degraded": true`
- **Citation viewer:** Side-by-side PDF split-screen with SVG/canvas bounding-box highlight overlay on click
- **Multi-turn history:** Full conversation stored in DB; prior context injected into query rewriting

### Agentic Reasoning
- **ReAct loop:** `AgenticOrchestrator` evaluates local retrieval confidence; if below threshold, falls back to SearXNG private web search automatically
- **Explicit web triggers:** Phrases like "search the web", "latest news", "real-time" always route to web search
- **Web citations:** Results formatted as `[n] Title (url)` distinct from document citations
- **SearXNG connector:** Define a topic query as a persistent connector; Celery syncs, extracts, and indexes web results into your workspace on demand

### Cognitive Memory Engine
- **Awake phase:** Episodic memory stream — every interaction logged with heuristic importance scoring
- **Living Dossier:** High-salience user preferences and entity facts extracted and persisted across sessions
- **Sleep phase — NREM:** Background pruning of low-importance noise (< 0.3 importance, > 48 h old), near-duplicate deduplication (Jaccard ≥ 0.85), contradiction resolution with supersession links
- **Sleep phase — REM:** Cross-document associative dreaming — finds chunk pairs with cosine similarity 0.55–0.78 across files, synthesizes latent insights, generates multi-hop Q&A, vectorizes dream nodes into Qdrant (`is_dream=True`)
- **Tri-factor scoring:** Retrieval ranked by Recency × Importance × Lexical Relevance
- **Right-to-Forget API:** `DELETE /memory/{id}` with soft or hard delete + best-effort Qdrant vector cleanup

### Trust & Guardrails
- **Faithfulness verification:** Token-overlap groundedness scoring (0.0–1.0) against retrieved context; flags hallucination risk when score < 0.65
- **PII sanitization:** Redacts emails, phone numbers, SSNs, and credit card patterns before vectorization of web-sourced content
- **Audit log:** Every chat query, document upload, export, and connector sync recorded in `AuditLog` with trace ID, provider, model, faithfulness score

### Integrations & Infrastructure
- **Local Ollama autodiscovery:** Detects running Ollama daemon via `/api/tags`, lists installed models, falls back gracefully offline
- **Any OpenAI-compatible endpoint:** Works with llama.cpp, vLLM, remote APIs
- **Celery + Redis:** Background document ingestion, connector sync tasks
- **Distributed tracing:** RFC-4122 `X-Trace-ID` header on every request; propagated through audit logs
- **Export:** Conversation history to Markdown, JSON, or plain text
- **Health probes:** Docker Compose healthchecks on all services

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + SQLAlchemy + PostgreSQL (SQLite for dev) |
| Retrieval | Qdrant, bge-m3 embeddings, BGE reranker |
| Memory | SQLAlchemy relational graph (MemoryNode + MemoryEdge) |
| Cache / Queue | Redis + Celery |
| Extraction | pypdf, openpyxl, ebooklib, RapidOCR |
| Web search | SearXNG (self-hosted) |
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| Auth | JWT (bcrypt, native — no Passlib) |

---

## Quick Start

Everything in Docker:

```bash
docker compose up --build
```

- **Web UI:** <http://localhost:5173>
- **API docs:** <http://localhost:8000/docs>

Or run services locally (with Docker handling Postgres, Redis, and Qdrant):

```bash
docker compose up postgres redis qdrant searxng
./install.sh
./run.sh
```

Requires Python 3.11+, Node 18+, Docker.

---

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# LLM — any OpenAI-compatible endpoint
LLM_BASE_URL=http://localhost:11434/v1   # Ollama, llama.cpp, vLLM, remote API
LLM_MODEL=llama3.2
LLM_API_KEY=                             # only for hosted providers
LLM_TIMEOUT=60

# Auth (disabled by default for local dev)
AUTH_ENABLED=false
JWT_SECRET=change-me-in-production       # required when AUTH_ENABLED=true

# Retrieval & Query
QUERY_REWRITE_ENABLED=true
HYDE_ENABLED=false                       # opt-in: generates hypothetical passages
WEB_SEARCH_ENABLED=true
WEB_SEARCH_CONFIDENCE_THRESHOLD=0.25
SEARXNG_BASE_URL=http://localhost:8080

# Ollama local model autodiscovery
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_AUTODISCOVER=true
OLLAMA_TIMEOUT=3.0

# Infrastructure
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/yar
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6379/0
UPLOAD_DIR=./uploads
```

If `LLM_BASE_URL` or `LLM_MODEL` is unset, or the provider is unreachable, `/chat` returns a grounded extractive answer and marks `"degraded": true`. With no retrieved context it refuses instead of guessing.

---

## API Overview

| Endpoint | Description |
|---|---|
| `POST /chat` | Unary chat with document retrieval + memory + guardrails |
| `POST /chat/stream` | SSE streaming chat (`text/event-stream`) |
| `GET /chat/history` | Paginated conversation history |
| `GET /chat/models` | Active provider, model, Ollama status, local model list |
| `GET /chat/export` | Export conversation (markdown/json/txt) |
| `POST /documents/upload` | Upload and index a document |
| `GET /documents/{id}/file` | Serve raw document binary (PDF range support pending) |
| `GET /memory` | Paginated memory nodes with type/status filtering |
| `GET /memory/entities` | Living Dossier — active entity preferences and facts |
| `PATCH /memory/entities/{id}` | Edit entity attributes manually |
| `DELETE /memory/{id}` | Right-to-Forget: soft or hard delete + vector cleanup |
| `POST /memory/dream` | Trigger on-demand NREM + REM consolidation cycle |
| `GET /memory/dream/status` | Memory health metrics and node counts |
| `GET /audit` | Paginated audit log with trace IDs |
| `POST /connectors` | Create a web knowledge connector (SearXNG) |
| `POST /connectors/{id}/sync` | Trigger connector sync |

Full interactive docs at `/docs` (Swagger UI) and `/redoc`.

---

## Project Layout

```
backend/app/
  core/               settings, database session, middleware (trace ID)
  models/             SQLAlchemy tables (chat, document, memory, audit, connector)
  routers/            auth, workspaces, documents, chat, memory, audit, connectors, health
  services/
    chunking.py       split_text, adaptive_chunk, hierarchical_chunk (parent-child)
    extraction.py     multi-format extraction, extract_pdf_boxes, rows_to_markdown_table
    embeddings.py     dense (bge-m3), sparse (31-bit), late chunking
    retrieval.py      hybrid search, RRF fusion, reranker
    query.py          QueryRewriter, HyDE
    chat.py           answer_query, stream_answer_query, build_context
    providers.py      OpenAICompatibleProvider, OllamaProvider, get_provider
    guardrails.py     PIISanitizer, FaithfulnessVerifier
    memory.py         MemoryService — node/edge CRUD, dossier, tri-factor retrieval
    dreaming/
      nrem.py         NREMConsolidator — pruning, deduplication, contradiction resolution
      rem.py          REMDreamer — associative dreaming, synthetic QA, Qdrant indexing
    tools/
      searxng.py      SearXNGSearchTool
    connectors/
      searxng.py      SearXNGConnectorService
    agent/
      orchestrator.py AgenticOrchestrator — confidence routing, web fallback
    audit.py          AuditService
  tasks.py            Celery background tasks (document indexing, connector sync)
frontend/src/
  App.tsx             Main chat interface + SSE stream reader
  components/
    CitationInspector.tsx   Side-by-side PDF viewer with bounding-box overlay
    MemoryInspector.tsx     Memory stream, Living Dossier, Sleep/Dream UI
    DocumentDropzone.tsx    Drag-and-drop document upload
    WorkspaceSelector.tsx   Workspace switcher
backend/eval.py       Retrieval evaluation (recall@k)
backend/tests/        Full pytest suite (176+ tests across all modules)
```

---

## What's Missing

Known gaps being tracked for the next sprint. See `docs/audit-reports/` for the full DoD audit.

### Blockers (before any team/production use)
- **Auth guards on `/memory/*`** — all 6 memory endpoints are unauthenticated. `AUTH_ENABLED=true` has no effect on this router. Fix before exposing to multiple users.
- **No HTTP Range support on `GET /documents/{id}/file`** — large PDFs cannot be seeked in browser iframes. The entire file is returned as one blob. Implement `206 Partial Content` / `Accept-Ranges: bytes`.

### Logic Gaps
- **Faithfulness verifier logic error** — answers with zero citations are classified as "fully faithful" (score 1.0). Should be flagged as highest hallucination risk.
- **PII scrubbing only on web-connector content** — uploaded PDFs, TXT, CSV files are not PII-scrubbed before vectorization. The `extract_text()` pipeline does not call `PIISanitizer`.
- **SearXNG connector commits per-document** in the sync loop — a failed Qdrant upsert mid-sync leaves orphaned SQL records with no vectors.
- **Confidence threshold mismatch** — `WEB_SEARCH_CONFIDENCE_THRESHOLD` defaults to `0.25`; the ticket spec says the "high confidence" cutoff is `0.4`. Undocumented deviation.

### Architectural Debt
- `services/connectors/searxng.py` imports from `routers/documents.py` — services must not depend on routers. `parse_chunk_metadata`, `ensure_collection`, and the Qdrant client should live in a shared `services/indexing.py`.
- `stream_complete()` uses a synchronous `httpx.Client` inside a sync generator. Blocks a FastAPI thread per active stream. Switch to `httpx.AsyncClient` for real async streaming under load.
- `GET /chat/models` makes two separate HTTP calls to Ollama (`discover_models` + `is_online`) — these can be merged into one `/api/tags` request.
- Parent chunks have no upper size cap — a single large markdown section becomes one unbounded parent, bloating LLM context.
- `late_chunk()` in `chunking.py` is a stub that just calls `adaptive_chunk()` — delete the wrapper.

### Not Yet Started
- **Multi-user RBAC** — single-user auth works; no roles, no per-document ACLs
- **Document-level permissions** — all workspace members see all documents
- **GraphRAG / knowledge graph extraction** — entity/relationship extraction from documents into a queryable graph (LightRAG-style)
- **RAGAS / continuous evaluation CI** — `eval.py` measures recall@k only; no faithfulness, relevance, or context precision metrics on a golden dataset
- **Webhook integrations** — no event hooks for document lifecycle, ingest completion, or answer quality feedback
- **Observability** — no Langfuse/OpenTelemetry integration; tracing exists via `X-Trace-ID` but no span-level pipeline visibility
- **Audio ingestion** — no Whisper or speech-to-text pipeline
- **Vision / diagram parsing** — OCR works on images but no VLM for charts, diagrams, or multi-column layout intelligence (RAGFlow-style DeepDoc)
- **User feedback loop** — no thumbs up/down on answers; no mechanism to feed corrections back into evaluation or prompt tuning
- **Alembic migrations** — schema changes are applied via `Base.metadata.create_all()` (dev-only); no migration history for schema evolution
- **Deployment automation** — no Helm chart, Ansible playbook, or one-click cloud deployment path

---

## Note for Contributors

`.ai/`, `.context/`, `docs/`, and `_docs/` are local agent working notes. They are gitignored and not part of the shipped project.

Tests live in `backend/tests/`. Run them with:

```bash
cd backend && python -m pytest
```

The full suite (176+ tests) uses in-memory SQLite and mocked Qdrant/LLM calls — no running services needed.
