"""
FootballIQ — Analysis API
=========================
Endpoints para buscar análises, value bets e histórico.
"""

import json
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from database.connection import get_db, Analysis, Match, User
from api.auth import get_current_user

router = APIRouter()

PLAN_LIMITS = {
    "free":    5,   # análises por dia
    "pro":     50,
    "premium": 999,
}


@router.get("/today")
async def today_analysis(
    league: str = Query("BSA"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Análises do dia para uma liga. Plano free: até 5 resultados."""
    today = date.today().isoformat()
    result = await db.execute(
        select(Analysis, Match)
        .join(Match, Analysis.match_id == Match.id)
        .where(Match.league == league)
        .where(Match.match_date >= today)
        .order_by(desc(Analysis.created_at))
    )
    rows = result.all()
    limit = PLAN_LIMITS.get(user.plan, 5)
    rows  = rows[:limit]

    return [_format_analysis(a, m) for a, m in rows]


@router.get("/value-bets")
async def value_bets(
    league: str = Query("BSA"),
    min_prob: float = Query(0.0, description="Probabilidade mínima (0-100)"),
    min_ev: float = Query(0.05, description="EV mínimo"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista apenas as apostas com value (EV positivo)."""
    today  = date.today().isoformat()
    result = await db.execute(
        select(Analysis, Match)
        .join(Match, Analysis.match_id == Match.id)
        .where(Match.league == league)
        .where(Match.match_date >= today)
        .order_by(desc(Analysis.created_at))
    )
    rows = result.all()

    value_bets_list = []
    for analysis, match in rows:
        vbs = json.loads(analysis.value_bets or "[]")
        for vb in vbs:
            if vb.get("is_vb") and vb.get("ev", 0) >= min_ev and vb.get("prob_calc", 0) >= min_prob:
                value_bets_list.append({
                    "partida":    f"{match.home_team} vs {match.away_team}",
                    "data":       match.match_date.strftime("%Y-%m-%d") if match.match_date else "",
                    "liga":       match.league,
                    "mercado":    vb["mercado"],
                    "odd":        vb["odd"],
                    "prob_calc":  vb["prob_calc"],
                    "prob_impl":  vb["prob_impl"],
                    "ev":         vb["ev"],
                })

    # Ordena por EV decrescente
    value_bets_list.sort(key=lambda x: x["ev"], reverse=True)
    return value_bets_list


@router.get("/history")
async def history(
    league: str = Query("BSA"),
    limit: int = Query(50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Histórico de análises anteriores."""
    result = await db.execute(
        select(Analysis, Match)
        .join(Match, Analysis.match_id == Match.id)
        .where(Match.league == league)
        .order_by(desc(Match.match_date))
        .limit(limit)
    )
    return [_format_analysis(a, m) for a, m in result.all()]


@router.get("/stats")
async def stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Estatísticas gerais da plataforma."""
    total_analyses = await db.execute(select(Analysis))
    total_matches  = await db.execute(select(Match))
    return {
        "total_analyses": len(total_analyses.all()),
        "total_matches":  len(total_matches.all()),
        "ligas_cobertas": ["BSA", "PL", "PD", "SA", "BL1", "FL1", "CL"],
        "modelo":         "Poisson",
    }


def _format_analysis(analysis: Analysis, match: Match) -> dict:
    return {
        "id":             analysis.id,
        "partida":        f"{match.home_team} vs {match.away_team}",
        "home_team":      match.home_team,
        "away_team":      match.away_team,
        "liga":           match.league,
        "data":           match.match_date.strftime("%Y-%m-%d") if match.match_date else "",
        "home_goals_exp": analysis.home_goals_exp,
        "away_goals_exp": analysis.away_goals_exp,
        "probabilidades": {
            "home_win": analysis.prob_home,
            "draw":     analysis.prob_draw,
            "away_win": analysis.prob_away,
            "over_2_5": analysis.prob_over25,
            "under_2_5":analysis.prob_under25,
        },
        "odds": {
            "home_win":  analysis.odd_home,
            "draw":      analysis.odd_draw,
            "away_win":  analysis.odd_away,
            "over_2_5":  analysis.odd_over25,
            "under_2_5": analysis.odd_under25,
        },
        "value_bets":  json.loads(analysis.value_bets or "[]"),
        "odds_source": analysis.odds_source,
        "created_at":  analysis.created_at.isoformat(),
    }
