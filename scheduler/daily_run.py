"""
FootballIQ — Agendador Automático
==================================
Roda todo dia às 8h e salva as análises no banco de dados.

Uso:
  python scheduler/daily_run.py                  # roda agora
  python scheduler/daily_run.py --league PL      # liga específica
  python scheduler/daily_run.py --all-leagues    # todas as ligas

Para agendar automaticamente:
  Windows Task Scheduler → executar daily_run.py todo dia às 8h
  Linux/Mac cron:
    0 8 * * * cd /caminho/do/projeto && python scheduler/daily_run.py
"""

import sys, os, json, asyncio, argparse, logging
from datetime import datetime, timedelta

# Adiciona o backend ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import init_db, AsyncSessionLocal, Match, Analysis, DailyRun

# Importa o motor de análise do script original
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

LIGAS_DEFAULT = ["BSA"]
LIGAS_TODAS   = ["BSA", "PL", "PD", "SA", "BL1", "FL1", "CL"]


async def save_analysis(session, match_db: Match, result: dict):
    """Salva uma análise no banco de dados."""
    p    = result["probabilidades"]
    odds = result.get("odds", {})
    vbs  = result.get("value_bets", [])

    analysis = Analysis(
        match_id        = match_db.id,
        home_goals_exp  = result["hge"],
        away_goals_exp  = result["age"],
        prob_home       = p["home_win"],
        prob_draw       = p["draw"],
        prob_away       = p["away_win"],
        prob_over25     = p["over_2_5"],
        prob_under25    = p["under_2_5"],
        odd_home        = odds.get("home_win"),
        odd_draw        = odds.get("draw"),
        odd_away        = odds.get("away_win"),
        odd_over25      = odds.get("over_2_5"),
        odd_under25     = odds.get("under_2_5"),
        value_bets      = json.dumps(vbs, ensure_ascii=False),
        odds_source     = result.get("odds_fonte", "simuladas"),
    )
    session.add(analysis)


async def save_match(session, match_data: dict, league_code: str) -> Match:
    """Salva ou atualiza uma partida no banco."""
    from sqlalchemy import select
    result = await session.execute(
        select(Match).where(Match.external_id == match_data["fixture_id"])
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    m = Match(
        external_id = match_data["fixture_id"],
        home_team   = match_data["home_team"],
        away_team   = match_data["away_team"],
        league      = league_code,
        match_date  = datetime.fromisoformat(match_data["data"]),
        status      = "SCHEDULED",
    )
    session.add(m)
    await session.flush()
    return m


async def run_for_league(league_code: str, date_str: str = None):
    """Executa análise para uma liga e salva no banco."""
    log.info("=== Iniciando análise — %s ===", league_code)

    # Importa o analisador
    try:
        from football_betting_analyzer import BettingAnalyzer
    except ImportError:
        log.error("football_betting_analyzer.py não encontrado no diretório raiz do projeto.")
        return 0, 0

    analyzer = BettingAnalyzer(odds_mode="simuladas")
    analyzer.run(league_code, next_n=10, date=date_str)

    if not analyzer.results:
        log.warning("Nenhuma análise gerada para %s", league_code)
        return 0, 0

    async with AsyncSessionLocal() as session:
        saved = 0
        for result in analyzer.results:
            try:
                match_data = {
                    "fixture_id": result.get("match_id", hash(result["partida"])),
                    "home_team":  result["home_team"],
                    "away_team":  result["away_team"],
                    "data":       result["data"],
                }
                match_db = await save_match(session, match_data, league_code)
                await save_analysis(session, match_db, result)
                saved += 1
            except Exception as e:
                log.error("Erro ao salvar %s: %s", result["partida"], e)

        # Registra a execução
        run_log = DailyRun(
            league           = league_code,
            run_date         = (date_str or datetime.today().strftime("%Y-%m-%d")),
            matches_found    = len(analyzer.results),
            matches_analyzed = saved,
            status           = "ok",
        )
        session.add(run_log)
        await session.commit()
        log.info("✅ %s: %d/%d análises salvas", league_code, saved, len(analyzer.results))
        return len(analyzer.results), saved


async def main(leagues: list, date_str: str = None):
    await init_db()
    total_found = total_saved = 0
    for league in leagues:
        found, saved = await run_for_league(league, date_str)
        total_found += found
        total_saved += saved

    log.info("=" * 50)
    log.info("Execução concluída: %d análises salvas de %d partidas", total_saved, total_found)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FootballIQ — Agendador diário")
    parser.add_argument("--league",      type=str, help="Liga específica (ex: BSA)")
    parser.add_argument("--all-leagues", action="store_true", help="Todas as ligas")
    parser.add_argument("--date",        type=str, help="Data YYYY-MM-DD (padrão: amanhã)")
    args = parser.parse_args()

    if args.all_leagues:
        leagues = LIGAS_TODAS
    elif args.league:
        leagues = [args.league.upper()]
    else:
        leagues = LIGAS_DEFAULT

    date_str = args.date or (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    log.info("Rodando para: %s | Data: %s", leagues, date_str)

    asyncio.run(main(leagues, date_str))
