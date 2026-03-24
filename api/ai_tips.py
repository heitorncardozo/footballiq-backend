"""
FootballIQ — AI Tips API
========================
Endpoint que gera palpites usando Claude (Anthropic).
"""

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import get_current_user

router = APIRouter()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"


class TipRequest(BaseModel):
    home_team:      str
    away_team:      str
    liga:           str = ""
    home_goals_exp: float = 0
    away_goals_exp: float = 0
    prob_home:      float = 0
    prob_draw:      float = 0
    prob_away:      float = 0
    prob_over25:    float = 0
    value_bets:     list  = []


@router.post("/tip")
async def generate_tip(body: TipRequest, user=Depends(get_current_user)):
    """Gera palpite com IA para um jogo."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="Chave da IA não configurada.")

    vbs_text = ", ".join(
        f"{vb.get('mercado')} (odd {vb.get('odd')}, EV +{vb.get('ev')})"
        for vb in body.value_bets if vb.get("is_vb")
    ) or "Nenhum value bet identificado"

    prompt = f"""Você é um analista especializado em apostas esportivas. Com base nos dados abaixo, gere um palpite curto e direto em português brasileiro (máximo 4 linhas), com tom profissional mas acessível. Não use markdown, não use asteriscos, não use emojis excessivos.

Jogo: {body.home_team} vs {body.away_team}
Liga: {body.liga}
Gols esperados: Casa {body.home_goals_exp:.1f}, Fora {body.away_goals_exp:.1f}
Probabilidades: Casa {body.prob_home*100:.0f}%, Empate {body.prob_draw*100:.0f}%, Fora {body.prob_away*100:.0f}%
Over 2.5 gols: {body.prob_over25*100:.0f}%
Value bets encontrados: {vbs_text}

Gere o palpite:"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                ANTHROPIC_URL, # <-- Não esqueça dessa variável aqui!
                headers={
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      "claude-3-5-haiku-20241022", # <-- Modelo corrigido
                    "max_tokens": 300,
                    "messages":   [{"role": "user", "content": prompt}],
                },
            )
            
            if r.status_code != 200:
                print(f"ERRO DA ANTHROPIC: {r.text}") 
                raise HTTPException(status_code=500, detail=f"Erro na API da Anthropic: {r.text}")

            data = r.json()
            tip  = data.get("content", [{}])[0].get("text", "")
            
            if not tip:
                raise HTTPException(status_code=500, detail="IA não retornou resposta válida.")
            
            return {"tip": tip}

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout na IA. Tente novamente.")
    except Exception as e:
        print(f"ERRO INTERNO NO PYTHON: {str(e)}") 
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")
