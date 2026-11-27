from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey, Text, Boolean
from ..core.database import Base

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    is_master = Column(Boolean, default=False, index=True)
    name = Column(String, index=True)
    source_type = Column(String, default="upload")
    file_type = Column(String)
    status = Column(String, default="queued")
    size_bytes = Column(Integer, default=0)
    content = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
