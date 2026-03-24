"""
FootballIQ — Popular banco com todas as ligas
==============================================
Roda o analisador para cada liga e salva no banco SQLite local.
Depois sobe para o Railway via git push.

Uso:
  python populate_all_leagues.py
"""

import os
import sys
import json
import math
import asyncio
import logging
import numpy as np
from datetime import datetime, timedelta

class SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.bool_, np.integer)): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        return super().default(obj)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

# Adiciona o diretório do analisador ao path
ANALISADOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analisador_odds-py')
sys.path.insert(0, ANALISADOR_DIR)

# Adiciona o backend ao path
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'footballiq', 'backend')
sys.path.insert(0, BACKEND_DIR)

LIGAS = ["PL", "CL", "PD", "SA", "BL1", "FL1"]


async def save_to_db(results: list, league_code: str):
    """Salva os resultados no banco de dados."""
    from database.connection import AsyncSessionLocal, init_db, Match, Analysis, DailyRun
    from sqlalchemy import select

    await init_db()

    async with AsyncSessionLocal() as session:
        saved = 0
        for result in results:
            try:
                fixture_id = hash(f"{result['home_team']}{result['away_team']}{result['data']}")
                existing = await session.execute(
                    select(Match).where(Match.external_id == fixture_id)
                )
                match_db = existing.scalar_one_or_none()

                if not match_db:
                    match_db = Match(
                        external_id = fixture_id,
                        home_team   = result["home_team"],
                        away_team   = result["away_team"],
                        league      = league_code,
                        match_date  = datetime.fromisoformat(result["data"]),
                        status      = "SCHEDULED",
                    )
                    session.add(match_db)
                    await session.flush()

                p    = result["probabilidades"]
                odds = result.get("odds", {})
                vbs  = result.get("value_bets", [])

                analysis = Analysis(
                    match_id       = match_db.id,
                    home_goals_exp = result["hge"],
                    away_goals_exp = result["age"],
                    prob_home      = p["home_win"],
                    prob_draw      = p["draw"],
                    prob_away      = p["away_win"],
                    prob_over25    = p["over_2_5"],
                    prob_under25   = p["under_2_5"],
                    odd_home       = odds.get("home_win"),
                    odd_draw       = odds.get("draw"),
                    odd_away       = odds.get("away_win"),
                    odd_over25     = odds.get("over_2_5"),
                    odd_under25    = odds.get("under_2_5"),
                    value_bets     = json.dumps(vbs, ensure_ascii=False, cls=SafeEncoder),
                    odds_source    = result.get("odds_fonte", "simuladas"),
                )
                session.add(analysis)
                saved += 1
            except Exception as e:
                log.error("Erro ao salvar %s: %s", result.get("partida"), e)

        run_log = DailyRun(
            league           = league_code,
            run_date         = datetime.today().strftime("%Y-%m-%d"),
            matches_found    = len(results),
            matches_analyzed = saved,
            status           = "ok",
        )
        session.add(run_log)
        await session.commit()
        log.info("✅ %s: %d análises salvas", league_code, saved)
        return saved


async def main():
    from football_betting_analyzer import BettingAnalyzer

    total = 0
    for league in LIGAS:
        log.info("=== Analisando %s ===", league)
        try:
            analyzer = BettingAnalyzer(odds_mode="simuladas")
            analyzer.run(league, next_n=10)

            if not analyzer.results:
                log.warning("Nenhuma partida encontrada para %s", league)
                continue

            saved = await save_to_db(analyzer.results, league)
            total += saved
        except Exception as e:
            log.error("Erro na liga %s: %s", league, e)

    log.info("=" * 50)
    log.info("Total: %d análises salvas em %d ligas", total, len(LIGAS))
    log.info("Agora rode: git add . && git commit -m 'banco populado' && git push")


if __name__ == "__main__":
    asyncio.run(main())
