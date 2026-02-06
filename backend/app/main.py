from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.database import Base, engine
from .routers import workspaces, documents, chat, auth

Base.metadata.create_all(bind=engine)

app = FastAPI(title="YAR")
