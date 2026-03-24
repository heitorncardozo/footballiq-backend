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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
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
    # MUDE A VERIFICAÇÃO PARA A NOVA CHAVE:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Chave do Gemini não configurada.")

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
                GEMINI_URL,
                headers={
                    "content-type": "application/json",
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}]
                },
            )
            
            if r.status_code != 200:
                print(f"ERRO DO GEMINI: {r.text}") 
                raise HTTPException(status_code=500, detail=f"Erro na API do Gemini: {r.text}")

            data = r.json()
            
            # Navegar no JSON do Gemini para encontrar o texto da resposta
            try:
                tip = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                tip = ""
            
            if not tip:
                raise HTTPException(status_code=500, detail="IA não retornou resposta válida.")
            
            return {"tip": tip}

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout na IA. Tente novamente.")
    except Exception as e:
        print(f"ERRO INTERNO NO PYTHON: {str(e)}") 
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")
