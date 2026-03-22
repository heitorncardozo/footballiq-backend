"""
FootballIQ — Database
=====================
SQLAlchemy async com SQLite (dev) ou PostgreSQL (prod).
Troque DATABASE_URL para postgres em produção.
"""

import os
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# SQLite para dev, PostgreSQL para prod
# Prod: postgresql+asyncpg://user:pass@host/dbname
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./footballiq.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


# ── Modelos ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)
    email         = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name          = Column(String)
    plan          = Column(String, default="free")   # free | pro | premium
    stripe_id     = Column(String, nullable=True)
    active        = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    analyses      = relationship("Analysis", back_populates="user")


class Match(Base):
    __tablename__ = "matches"
    id            = Column(Integer, primary_key=True)
    external_id   = Column(Integer, unique=True)
    home_team     = Column(String, nullable=False)
    away_team     = Column(String, nullable=False)
    league        = Column(String)
    match_date    = Column(DateTime)
    home_goals    = Column(Integer, nullable=True)
    away_goals    = Column(Integer, nullable=True)
    status        = Column(String, default="SCHEDULED")  # SCHEDULED | FINISHED
    created_at    = Column(DateTime, default=datetime.utcnow)
    analyses      = relationship("Analysis", back_populates="match")


class Analysis(Base):
    __tablename__ = "analyses"
    id              = Column(Integer, primary_key=True)
    match_id        = Column(Integer, ForeignKey("matches.id"))
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    home_goals_exp  = Column(Float)
    away_goals_exp  = Column(Float)
    prob_home       = Column(Float)
    prob_draw       = Column(Float)
    prob_away       = Column(Float)
    prob_over25     = Column(Float)
    prob_under25    = Column(Float)
    odd_home        = Column(Float, nullable=True)
    odd_draw        = Column(Float, nullable=True)
    odd_away        = Column(Float, nullable=True)
    odd_over25      = Column(Float, nullable=True)
    odd_under25     = Column(Float, nullable=True)
    value_bets      = Column(Text)   # JSON string
    odds_source     = Column(String, default="simuladas")
    created_at      = Column(DateTime, default=datetime.utcnow)
    match           = relationship("Match",    back_populates="analyses")
    user            = relationship("User",     back_populates="analyses")


class DailyRun(Base):
    """Registro de cada execução automática do scraper."""
    __tablename__ = "daily_runs"
    id          = Column(Integer, primary_key=True)
    league      = Column(String)
    run_date    = Column(String)   # YYYY-MM-DD
    matches_found   = Column(Integer, default=0)
    matches_analyzed = Column(Integer, default=0)
    status      = Column(String, default="ok")   # ok | error
    error_msg   = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


# ── Init ───────────────────────────────────────────────────────────────────────

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
