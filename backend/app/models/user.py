import bcrypt
from sqlalchemy import Column, Integer, String, DateTime, func
from ..core.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="user")
    created_at = Column(DateTime, server_default=func.now())

    def set_password(self, password: str):
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode("utf-8")[:72], salt).decode("utf-8")

    def verify_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode("utf-8")[:72], self.password_hash.encode("utf-8"))

class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    description = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
