from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.database import Base, engine
from .core.middleware import TraceIDMiddleware
from .routers import workspaces, documents, chat, auth, memory, audit, connectors, health
from .models import chat as _chat_model  # noqa: F401 — register ChatMessage table
from .models import memory as _memory_model  # noqa: F401 — register MemoryNode & MemoryEdge tables
from .models import audit as _audit_model  # noqa: F401 — register AuditLog table
from .models import connector as _connector_model  # noqa: F401 — register Connector table

Base.metadata.create_all(bind=engine)

app = FastAPI(title="YAR")

app.add_middleware(TraceIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(auth.router)
app.include_router(memory.router)
app.include_router(audit.router)
app.include_router(connectors.router)
app.include_router(health.router)
