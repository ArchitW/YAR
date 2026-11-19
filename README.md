# YAR

> **Work in progress.** This project is under active development and is **not**
> production-ready. APIs, database schemas and configuration can change without
> notice, and breaking changes are expected.

YAR is a document question-answering app. Upload your documents, then ask
questions in plain language and get answers that cite the chunks they came from.

## Status

Early development. Works end to end today:

- Upload and index of `.txt` files
- Hybrid retrieval (dense + sparse vectors) with cross-encoder reranking
- LLM answers grounded in retrieved chunks, with numbered citations
- Workspace-scoped documents and conversations

Not done yet: hardened authentication, multi-user permissions, deployment
automation, and evaluation beyond recall@k.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI, SQLAlchemy, PostgreSQL |
| Retrieval | Qdrant, bge-m3 embeddings, bge reranker |
| Cache / queue | Redis |
| Web | React, Vite, TypeScript, Tailwind CSS |

## Quick start

Everything in Docker:

```bash
docker compose up --build
```

- Web UI: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>

Or run the services locally (with `docker compose up postgres redis qdrant`
handling Postgres, Redis and Qdrant):

```bash
./install.sh
./run.sh
```

Requires Python 3.11+, Node 18+ and Docker.

## Choosing a model

YAR talks to any OpenAI-compatible `/chat/completions` endpoint. Copy
`.env.example` to `.env` and point it at your runtime:

```bash
cp .env.example backend/.env   # or export the variables
LLM_BASE_URL=http://localhost:11434/v1   # Ollama, llama.cpp, vLLM, remote API
LLM_MODEL=llama3.1
LLM_API_KEY=                             # only for hosted providers
```

If `LLM_BASE_URL` or `LLM_MODEL` is unset, or the provider is unreachable,
`/chat` still returns a grounded extractive answer and marks the response
`"degraded": true`. With no retrieved context it refuses instead of guessing.

## Layout

```
backend/app/
  core/       settings, database session
  models/     SQLAlchemy tables
  routers/    auth, workspaces, documents, chat
  services/   chunking, embeddings, retrieval, reranker
frontend/src/ React chat UI
backend/eval.py  retrieval evaluation
```

## Note for contributors

`.ai/`, `.context/`, `docs/` and `_docs/` are local working notes and are
gitignored — they are not part of the shipped project.
