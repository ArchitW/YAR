from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, func, ForeignKey, JSON
from ..core.database import Base


class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True, nullable=False)
    title = Column(String, default="New chat")
    use_local_knowledge = Column(Boolean, default=True)
    save_to_memory = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True, nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id"), index=True, nullable=True)
    role = Column(String, nullable=False)          # "user" | "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSON, default=list)          # stored only for assistant messages
    provider = Column(String, default="")
    model = Column(String, default="")
    degraded = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())