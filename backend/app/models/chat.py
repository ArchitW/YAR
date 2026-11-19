from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, func, ForeignKey, JSON
from ..core.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True, nullable=False)
    role = Column(String, nullable=False)          # "user" | "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSON, default=list)          # stored only for assistant messages
    provider = Column(String, default="")
    model = Column(String, default="")
    degraded = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
