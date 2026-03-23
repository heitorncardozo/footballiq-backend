"""
FootballIQ — Agendador integrado ao servidor
=============================================
Roda junto com o FastAPI e executa a análise automaticamente todo dia às 8h.
Não precisa rodar nada manualmente — funciona sozinho no Railway.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_daily_analysis():
    """Executa análise automática para todas as ligas configuradas."""
    log.info("=== Iniciando análise diária automática — %s ===", datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        from football_betting_analyzer import BettingAnalyzer
        from database.connection import AsyncSessionLocal, init_db, Match, Analysis, DailyRun
        from sqlalchemy import select
        import json

        ligas = ["BSA"]  # Adicione mais ligas conforme necessário
        tomorrow = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

        await init_db()

        for league in ligas:
            log.info("Analisando liga: %s", league)
            analyzer = BettingAnalyzer(odds_mode="simuladas")
            analyzer.run(league, next_n=10, date=tomorrow)

            if not analyzer.results:
                log.warning("Nenhuma partida encontrada para %s", league)
                continue

            async with AsyncSessionLocal() as session:
                saved = 0
                for result in analyzer.results:
                    try:
                        # Verifica se partida já existe
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
                                league      = league,
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
                            value_bets     = json.dumps(vbs, ensure_ascii=False),
                            odds_source    = result.get("odds_fonte", "simuladas"),
                        )
                        session.add(analysis)
                        saved += 1
                    except Exception as e:
                        log.error("Erro ao salvar %s: %s", result.get("partida"), e)

                run_log = DailyRun(
                    league           = league,
                    run_date         = tomorrow,
                    matches_found    = len(analyzer.results),
                    matches_analyzed = saved,
                    status           = "ok",
                )
                session.add(run_log)
                await session.commit()
                log.info("✅ %s: %d análises salvas", league, saved)

    except Exception as e:
        log.error("Erro na análise diária: %s", e)


def start_scheduler():
    """Inicia o agendador — chamado na inicialização do FastAPI."""
    # Roda todo dia às 8h (horário do servidor — Railway usa UTC, então 8h UTC = 5h Brasília)
    # Para 8h Brasília (UTC-3), use hour=11
    scheduler.add_job(
        run_daily_analysis,
        CronTrigger(hour=11, minute=0),  # 8h horário de Brasília
        id="daily_analysis",
        replace_existing=True,
    )
    scheduler.start()
    log.info("⏰ Agendador iniciado — análise diária às 8h (Brasília)")


def stop_scheduler():
    """Para o agendador."""
    if scheduler.running:
        scheduler.shutdown()
