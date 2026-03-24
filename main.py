"""
FootballIQ — Backend API
========================
FastAPI + SQLite (dev) / PostgreSQL (prod)
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import uvicorn

from database.connection import init_db
from api.auth     import router as auth_router
from api.matches  import router as matches_router
from api.analysis import router as analysis_router
from api.payments import router as payments_router
from api.ai_tips  import router as ai_tips_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="FootballIQ API",
    description="Análise estatística de futebol e value bets",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em prod: trocar pelo domínio do frontend
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,     prefix="/auth",     tags=["Auth"])
app.include_router(matches_router,  prefix="/matches",  tags=["Partidas"])
app.include_router(analysis_router, prefix="/analysis", tags=["Análise"])
app.include_router(ai_tips_router,  prefix="/ai",       tags=["IA"])


@app.get("/")
def root():
    return {"status": "ok", "app": "FootballIQ API v1.0"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
