# services/auth.py (PII-free: account_id only)
from __future__ import annotations
import os
import datetime as dt
from pathlib import Path
from typing import Optional

import bcrypt
from sqlalchemy import create_engine, String, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, sessionmaker, Session

DEFAULT_SQLITE_PATH = Path("data/users.db")
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

Base = declarative_base()
_engine = None
_SessionLocal = None

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)  # ユーザーが決めるID（英数/記号可）
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    __table_args__ = (UniqueConstraint("account_id", name="uq_users_account_id"),)

    def to_public_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

def _ensure_sqlite_dir():
    if DATABASE_URL.startswith("sqlite:///"):
        DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

def get_engine():
    global _engine
    if _engine is None:
        _ensure_sqlite_dir()
        connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
        _engine = create_engine(DATABASE_URL, echo=False, future=True, connect_args=connect_args)
    return _engine

def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return _SessionLocal()

def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)

def hash_password(plain: str) -> str:
    if not isinstance(plain, str) or not plain:
        raise ValueError("Password must be non-empty string")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_user(account_id: str, password: str, display_name: Optional[str] = None) -> User:
    aid = (account_id or "").strip()
    if not aid:
        raise ValueError("account_id required")
    if not password:
        raise ValueError("password required")

    init_db()
    with get_session() as db:
        exists = db.query(User).filter(User.account_id == aid).first()
        if exists:
            raise ValueError("account_id already registered")

        user = User(
            account_id=aid,
            display_name=(display_name or "").strip() or None,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

def authenticate(account_id: str, password: str) -> Optional[User]:
    aid = (account_id or "").strip()
    init_db()
    with get_session() as db:
        user = db.query(User).filter(User.account_id == aid).first()
        if user and verify_password(password, user.password_hash):
            return user
        return None

def get_user_by_id(user_id: int) -> Optional[User]:
    init_db()
    with get_session() as db:
        return db.query(User).filter(User.id == user_id).first()

if __name__ == "__main__":
    init_db()
    print(f"DB initialized at: {DATABASE_URL}")
