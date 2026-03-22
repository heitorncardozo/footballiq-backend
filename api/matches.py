"""
FootballIQ — Matches API
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import date

from database.connection import get_db, Match
from api.auth import get_current_user

router = APIRouter()

@router.get("/upcoming")
async def upcoming(
    league: str = Query("BSA"),
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    today  = date.today().isoformat()
    result = await db.execute(
        select(Match)
        .where(Match.league == league)
        .where(Match.status == "SCHEDULED")
        .where(Match.match_date >= today)
        .order_by(Match.match_date)
        .limit(20)
    )
    matches = result.scalars().all()
    return [
        {
            "id":        m.id,
            "home_team": m.home_team,
            "away_team": m.away_team,
            "league":    m.league,
            "date":      m.match_date.strftime("%Y-%m-%d %H:%M") if m.match_date else "",
            "status":    m.status,
        }
        for m in matches
    ]
