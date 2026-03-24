"""
⚽ Football Betting Value Analyzer
===================================
Fontes de dados:
  1. football-data.org  → estatísticas dos jogos (GRATUITO)
     Cadastro: https://www.football-data.org/client/register

  2. Odds — três modos disponíveis:
     a) Manual     → você digita as odds da Bet365/Betano no terminal
     b) API        → The Odds API (500 req/mês grátis) — casas europeias
     c) Simuladas  → geradas automaticamente (para testes)

Ligas free: BSA, PL, PD, SA, BL1, FL1, CL

Uso:
  python football_betting_analyzer.py --demo
  python football_betting_analyzer.py --league BSA --date 2026-03-18
  python football_betting_analyzer.py --league BSA --date 2026-03-18 --odds manual
  python football_betting_analyzer.py --league BSA --date 2026-03-18 --odds api
  python football_betting_analyzer.py --league BSA --date 2026-03-18 --odds simuladas
  python football_betting_analyzer.py --list-leagues
"""

import os, sys, json, math, time, logging, argparse
from datetime import datetime, timedelta
from typing import Optional
from difflib import SequenceMatcher

import requests
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Configuração ───────────────────────────────────────────────────────────────
FOOTBALL_DATA_KEY  = os.getenv("FOOTBALL_DATA_KEY", "SUA_CHAVE_FOOTBALL_DATA")
ODDS_API_KEY       = os.getenv("ODDS_API_KEY",      "SUA_CHAVE_ODDS_API")

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
ODDS_API_BASE      = "https://api.the-odds-api.com/v4"

N_JOGOS_HISTORICO   = 10
VALUE_BET_THRESHOLD = 0.05

LIGAS = {
    "BSA": {"nome": "Brasileirão Série A",  "odds_key": "soccer_brazil_campeonato"},
    "PL":  {"nome": "Premier League",       "odds_key": "soccer_epl"},
    "PD":  {"nome": "La Liga",              "odds_key": "soccer_spain_la_liga"},
    "SA":  {"nome": "Serie A",              "odds_key": "soccer_italy_serie_a"},
    "BL1": {"nome": "Bundesliga",           "odds_key": "soccer_germany_bundesliga"},
    "FL1": {"nome": "Ligue 1",              "odds_key": "soccer_france_ligue_1"},
    "CL":  {"nome": "Champions League",     "odds_key": "soccer_uefa_champs_league"},
}


# ── Entrada manual de odds ─────────────────────────────────────────────────────

def input_odds_manual(home: str, away: str, probs: dict) -> dict:
    """
    Solicita ao usuário que digite as odds da Bet365/Betano para o jogo.
    Pressionar Enter sem digitar nada usa as odds simuladas para aquele mercado.
    """
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  📋  INSERIR ODDS MANUALMENTE")
    print(f"  {home}  vs  {away}")
    print(f"  (Pressione Enter para pular e usar odd simulada)")
    print(f"{sep}")

    # Mostra as probabilidades calculadas como referência
    print(f"\n  Probabilidades calculadas (referência):")
    print(f"    Casa (1):   {probs['home_win']*100:.1f}%  →  odd justa ≈ {1/probs['home_win']:.2f}")
    print(f"    Empate (X): {probs['draw']*100:.1f}%  →  odd justa ≈ {1/probs['draw']:.2f}")
    print(f"    Fora (2):   {probs['away_win']*100:.1f}%  →  odd justa ≈ {1/probs['away_win']:.2f}")
    print(f"    Over 2.5:   {probs['over_2_5']*100:.1f}%  →  odd justa ≈ {1/probs['over_2_5']:.2f}")
    print(f"    Under 2.5:  {probs['under_2_5']*100:.1f}%  →  odd justa ≈ {1/probs['under_2_5']:.2f}")
    print()

    def ask(label, sim_val, home=home, away=away):
        while True:
            try:
                val = input(f"  Odd {label} (simulada={sim_val:.2f}): ").strip()
                if val == "":
                    return sim_val
                f = float(val.replace(",", "."))
                if f > 1.0:
                    return round(f, 2)
                print("  ⚠️  Odd deve ser maior que 1.0")
            except ValueError:
                print("  ⚠️  Digite um número válido (ex: 2.30)")

    # Gera simuladas como fallback para cada mercado
    rng = np.random.default_rng()
    margin = 1.05
    nv = rng.uniform(-0.04, 0.04, 5)
    def sim(p, n): return round(1 / max(0.05, min(0.95, p+n)) / margin, 2)

    odds = {
        "home_win":  ask(f"Casa (1) — {home}",   sim(probs["home_win"],  nv[0])),
        "draw":      ask(f"Empate (X) — {home} x {away}", sim(probs["draw"],      nv[1])),
        "away_win":  ask(f"Fora (2) — {away}",   sim(probs["away_win"],  nv[2])),
        "over_2_5":  ask(f"Over 2.5 — {home} x {away}",  sim(probs["over_2_5"],  nv[3])),
        "under_2_5": ask(f"Under 2.5 — {home} x {away}", sim(probs["under_2_5"], nv[4])),
        "fonte":              "manual",
        "bookmakers_found":   ["Bet365 / Betano (manual)"],
    }
    print(f"{sep}\n")
    return odds


# ── Cliente football-data.org ──────────────────────────────────────────────────
class FootballDataClient:
    def __init__(self, api_key):
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": api_key})

    def _get(self, endpoint, params=None):
        url = f"{FOOTBALL_DATA_BASE}/{endpoint}"
        try:
            r = self.session.get(url, params=params or {}, timeout=15)
            if r.status_code == 429:
                log.warning("Rate limit — aguardando 65s...")
                time.sleep(65)
                r = self.session.get(url, params=params or {}, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.error("Erro football-data (%s): %s", endpoint, e)
            return {}

    def get_upcoming_matches(self, league_code, date_from=None, date_to=None):
        params = {"status": "SCHEDULED"}
        if date_from: params["dateFrom"] = date_from
        if date_to:   params["dateTo"]   = date_to
        return self._get(f"competitions/{league_code}/matches", params).get("matches", [])

    def get_team_matches(self, team_id, last_n=N_JOGOS_HISTORICO):
        data = self._get(f"teams/{team_id}/matches", {"status": "FINISHED", "limit": last_n})
        matches = sorted(data.get("matches", []), key=lambda m: m["utcDate"], reverse=True)
        return matches[:last_n]


# ── Cliente The Odds API ───────────────────────────────────────────────────────
class OddsAPIClient:
    def __init__(self, api_key):
        self.api_key  = api_key
        self.session  = requests.Session()
        self._cache   = {}
        self.remaining = None

    def _get(self, endpoint, params=None):
        url = f"{ODDS_API_BASE}/{endpoint}"
        p   = {"apiKey": self.api_key, **(params or {})}
        try:
            r = self.session.get(url, params=p, timeout=15)
            if "x-requests-remaining" in r.headers:
                self.remaining = r.headers["x-requests-remaining"]
            if r.status_code == 401:
                log.error("Odds API: chave inválida.")
                return []
            if r.status_code == 422:
                log.warning("Odds API: liga não disponível.")
                return []
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.error("Erro Odds API: %s", e)
            return []

    def get_odds(self, sport_key):
        if sport_key in self._cache:
            return self._cache[sport_key]
        log.info("Buscando odds reais — %s", sport_key)
        data = self._get(f"sports/{sport_key}/odds", {
            "regions": "eu,uk,us,au", "markets": "h2h,totals", "oddsFormat": "decimal",
        })
        self._cache[sport_key] = data if isinstance(data, list) else []
        if self.remaining:
            log.info("Odds API: %s requisições restantes este mês.", self.remaining)
        return self._cache[sport_key]

    def find_match_odds(self, sport_key, home_name, away_name):
        events = self.get_odds(sport_key)
        if not events: return {}
        best_match, best_score = None, 0.0
        for event in events:
            score = (SequenceMatcher(None, home_name.lower(), event.get("home_team","").lower()).ratio() +
                     SequenceMatcher(None, away_name.lower(), event.get("away_team","").lower()).ratio()) / 2
            if score > best_score and score > 0.4:
                best_score, best_match = score, event
        if not best_match:
            log.warning("Odds não encontradas para: %s vs %s", home_name, away_name)
            return {}
        log.info("Odds encontradas: %s vs %s (%.0f%%)", best_match["home_team"], best_match["away_team"], best_score*100)
        return self._extract_best_odds(best_match)

    @staticmethod
    def _extract_best_odds(event):
        best = {"home_win": None, "draw": None, "away_win": None,
                "over_2_5": None, "under_2_5": None, "bookmakers_found": []}
        hn, an = event.get("home_team",""), event.get("away_team","")
        for bm in event.get("bookmakers", []):
            nm = bm.get("title", bm.get("key",""))
            if nm not in best["bookmakers_found"]: best["bookmakers_found"].append(nm)
            for market in bm.get("markets", []):
                if market["key"] == "h2h":
                    for o in market.get("outcomes", []):
                        n, p = o.get("name",""), o.get("price",0)
                        if n == hn   and (best["home_win"] is None or p > best["home_win"]): best["home_win"] = p
                        elif n == "Draw" and (best["draw"] is None or p > best["draw"]):     best["draw"] = p
                        elif n == an and (best["away_win"] is None or p > best["away_win"]): best["away_win"] = p
                elif market["key"] == "totals":
                    for o in market.get("outcomes", []):
                        if o.get("point") == 2.5:
                            p = o.get("price", 0)
                            if o["name"] == "Over"  and (best["over_2_5"]  is None or p > best["over_2_5"]):  best["over_2_5"]  = p
                            if o["name"] == "Under" and (best["under_2_5"] is None or p > best["under_2_5"]): best["under_2_5"] = p
        return best


# ── Análise estatística ────────────────────────────────────────────────────────
class TeamStatsAnalyzer:
    def __init__(self, client):
        self.client = client

    def build_history(self, team_id, last_n=N_JOGOS_HISTORICO):
        rows = []
        for m in self.client.get_team_matches(team_id, last_n):
            is_home = m["homeTeam"]["id"] == team_id
            ft = m.get("score", {}).get("fullTime", {})
            gs = ft.get("home") if is_home else ft.get("away")
            gc = ft.get("away") if is_home else ft.get("home")
            if gs is None or gc is None: continue
            result = "W" if gs > gc else ("D" if gs == gc else "L")
            rows.append({"is_home": is_home, "gs": gs, "gc": gc, "result": result})
        return pd.DataFrame(rows)

    def averages(self, df):
        if df.empty: return {}
        return {
            "jogos":           len(df),
            "media_gols_marc": round(df["gs"].mean(), 2),
            "media_gols_sofr": round(df["gc"].mean(), 2),
            "pct_vitoria":     round((df["result"]=="W").mean()*100, 1),
            "pct_empate":      round((df["result"]=="D").mean()*100, 1),
            "pct_derrota":     round((df["result"]=="L").mean()*100, 1),
            "pct_over25":      round(((df["gs"]+df["gc"])>2.5).mean()*100, 1),
            "pct_btts":        round(((df["gs"]>0)&(df["gc"]>0)).mean()*100, 1),
        }

    def home_away(self, team_id):
        df = self.build_history(team_id)
        if df.empty or "is_home" not in df.columns:
            return {"all": {}, "home": {}, "away": {}}
        return {
            "all":  self.averages(df),
            "home": self.averages(df[df["is_home"]==True]),
            "away": self.averages(df[df["is_home"]==False]),
        }


# ── Modelo de Poisson ──────────────────────────────────────────────────────────
class ProbCalc:
    @staticmethod
    def probs(lh, la, max_g=8):
        m = np.zeros((max_g+1, max_g+1))
        for h in range(max_g+1):
            for a in range(max_g+1):
                m[h][a] = ((lh**h*math.exp(-lh))/math.factorial(h)) * \
                           ((la**a*math.exp(-la))/math.factorial(a))
        hw  = float(np.sum(np.tril(m,-1)))
        dr  = float(np.sum(np.diag(m)))
        aw  = float(np.sum(np.triu(m,1)))
        o25 = sum(m[h][a] for h in range(max_g+1) for a in range(max_g+1) if h+a>2)
        btts= sum(m[h][a] for h in range(1,max_g+1) for a in range(1,max_g+1))
        return {"home_win":round(hw,4),"draw":round(dr,4),"away_win":round(aw,4),
                "over_2_5":round(o25,4),"under_2_5":round(1-o25,4),"btts":round(btts,4)}

    @staticmethod
    def value_bet(prob, odd):
        pi = 1/odd if odd > 0 else 0
        ev = prob*odd-1
        return {"prob_calc":round(prob*100,1),"prob_impl":round(pi*100,1),
                "ev":round(ev,4),"is_vb": ev > VALUE_BET_THRESHOLD}


def sim_odds(probs, noise=0.06):
    rng = np.random.default_rng()
    margin = 1.05
    nv = rng.uniform(-noise, noise, 5)
    def to_odd(p, n): return round(1/max(0.05,min(0.95,p+n))/margin, 2)
    return {
        "home_win":  to_odd(probs["home_win"],  nv[0]),
        "draw":      to_odd(probs["draw"],      nv[1]),
        "away_win":  to_odd(probs["away_win"],  nv[2]),
        "over_2_5":  to_odd(probs["over_2_5"],  nv[3]),
        "under_2_5": to_odd(probs["under_2_5"], nv[4]),
        "fonte": "simuladas", "bookmakers_found": ["(simuladas)"],
    }


# ── Analisador principal ───────────────────────────────────────────────────────
class BettingAnalyzer:
    def __init__(self, odds_mode: str = "auto"):
        """
        odds_mode:
          'manual'    → digita as odds no terminal para cada jogo
          'api'       → busca da The Odds API
          'simuladas' → gera odds simuladas
          'auto'      → usa API se chave disponível, senão simuladas
        """
        self.fd_client   = FootballDataClient(FOOTBALL_DATA_KEY)
        self.odds_client = OddsAPIClient(ODDS_API_KEY)
        self.analyzer    = TeamStatsAnalyzer(self.fd_client)
        self.calc        = ProbCalc()
        self.results     = []
        self.odds_mode   = odds_mode
        # Resolve 'auto'
        if odds_mode == "auto":
            self.odds_mode = "api" if ODDS_API_KEY != "SUA_CHAVE_ODDS_API" else "simuladas"

    def _get_odds(self, home: str, away: str, odds_sport_key: str, probs: dict) -> dict:
        """Obtém odds conforme o modo configurado."""
        if self.odds_mode == "manual":
            return input_odds_manual(home, away, probs)

        elif self.odds_mode == "api":
            odds = self.odds_client.find_match_odds(odds_sport_key, home, away)
            if odds:
                odds["fonte"] = "the-odds-api"
                return odds
            log.warning("Odds API sem dados para este jogo — usando simuladas.")
            return sim_odds(probs)

        else:  # simuladas
            return sim_odds(probs)

    def analyze_match(self, match: dict, odds_sport_key: str) -> Optional[dict]:
        home = match["homeTeam"]
        away = match["awayTeam"]
        log.info("Analisando: %s vs %s", home["name"], away["name"])

        hs  = self.analyzer.home_away(home["id"]); time.sleep(0.5)
        as_ = self.analyzer.home_away(away["id"]); time.sleep(0.5)

        ha = hs["all"]; aa = as_["all"]
        if not ha or not aa:
            log.warning("Dados insuficientes: %s vs %s", home["name"], away["name"])
            return None

        hge = hs["home"].get("media_gols_marc") or ha["media_gols_marc"]
        age = as_["away"].get("media_gols_marc") or aa["media_gols_marc"]
        probs = self.calc.probs(hge, age)

        odds = self._get_odds(home["name"], away["name"], odds_sport_key, probs)

        mercados = {
            "Casa (1)":   ("home_win",  odds.get("home_win")),
            "Empate (X)": ("draw",      odds.get("draw")),
            "Fora (2)":   ("away_win",  odds.get("away_win")),
            "Over 2.5":   ("over_2_5",  odds.get("over_2_5")),
            "Under 2.5":  ("under_2_5", odds.get("under_2_5")),
        }
        vbs = []
        for m, (pk, odd) in mercados.items():
            if not odd or odd <= 1.0: continue
            vb = self.calc.value_bet(probs[pk], odd)
            vbs.append({"mercado": m, "odd": odd, **vb})

        return {
            "partida":        f"{home['name']} vs {away['name']}",
            "data":           match["utcDate"][:10],
            "liga":           match.get("competition", {}).get("name", ""),
            "home_team":      home["name"], "away_team": away["name"],
            "home_stats":     ha, "away_stats": aa,
            "hge":            round(hge, 2), "age": round(age, 2),
            "probabilidades": probs, "odds": odds,
            "odds_fonte":     odds.get("fonte", "?"),
            "casas":          odds.get("bookmakers_found", []),
            "value_bets":     vbs,
        }

    def run(self, league_code: str, next_n: int = 10, date: str = None):
        league_code = league_code.upper()
        liga_info   = LIGAS.get(league_code)
        if not liga_info:
            log.error("Liga '%s' não suportada. Use --list-leagues.", league_code); return

        df = date or datetime.today().strftime("%Y-%m-%d")
        dt = (datetime.strptime(df, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        log.info("Buscando partidas — %s (%s → %s)", liga_info["nome"], df, dt)

        matches = self.fd_client.get_upcoming_matches(league_code, df, dt)[:next_n]
        if not matches:
            log.error("Nenhuma partida encontrada."); return

        icons = {"manual": "✏️  MANUAL", "api": "🌐 API", "simuladas": "🔮 Simuladas"}
        log.info("%d partidas. Modo de odds: %s", len(matches), icons.get(self.odds_mode, self.odds_mode))

        for m in matches:
            r = self.analyze_match(m, liga_info["odds_key"])
            if r: self.results.append(r)

    def print_report(self):
        if not self.results:
            print("\nNenhum resultado.\n"); return
        sep = "═"*92
        print(f"\n{sep}")
        print("  ⚽  FOOTBALL BETTING VALUE ANALYZER  —  Relatório de Value Bets")
        print(f"{sep}\n")
        for r in self.results:
            p = r["probabilidades"]
            casas_str = ", ".join(r["casas"][:4]) if r["casas"] else "—"
            fonte_icon = {"manual": "✏️", "the-odds-api": "🌐", "simuladas": "🔮"}.get(r["odds_fonte"], "❓")
            print(f"  📅  {r['data']}   🏆  {r['liga']}")
            print(f"  {r['home_team']:28s}  vs  {r['away_team']}")
            print(f"  Gols esperados → Casa: {r['hge']:.2f}  |  Fora: {r['age']:.2f}")
            print(f"  Probabilidades → Casa: {p['home_win']*100:.1f}%  Empate: {p['draw']*100:.1f}%  Fora: {p['away_win']*100:.1f}%  Over 2.5: {p['over_2_5']*100:.1f}%")
            print(f"  {fonte_icon} Odds: {r['odds_fonte']}  |  Casas: {casas_str}")
            print(f"\n  {'Mercado':16s}  {'Odd':>6}  {'P.Calc%':>8}  {'P.Impl%':>8}  {'EV':>9}  {'Value?':>8}")
            print(f"  {'─'*64}")
            for vb in r["value_bets"]:
                flag = "✅ SIM" if vb["is_vb"] else "❌ NÃO"
                print(f"  {vb['mercado']:16s}  {vb['odd']:>6.2f}  {vb['prob_calc']:>7.1f}%  {vb['prob_impl']:>7.1f}%  {vb['ev']:>+9.4f}  {flag}")
            hs, as_ = r["home_stats"], r["away_stats"]
            print(f"\n  {'Estatística':24s}  {'Casa':>8}  {'Fora':>8}")
            print(f"  {'─'*44}")
            for label, key in [("Gols marcados/jogo","media_gols_marc"),("Gols sofridos/jogo","media_gols_sofr"),
                                ("% Vitórias","pct_vitoria"),("% Over 2.5","pct_over25"),("% Ambos marcam","pct_btts")]:
                print(f"  {label:24s}  {str(hs.get(key,'—')):>8}  {str(as_.get(key,'—')):>8}")
            print(f"\n  {'─'*88}\n")
        total = sum(1 for r in self.results for vb in r["value_bets"] if vb["is_vb"])
        print(f"  📊  Partidas analisadas:    {len(self.results)}")
        print(f"  🎯  Value bets encontrados: {total}")
        print(f"\n{sep}\n")

    def save_csv(self, path="value_bets.csv"):
        rows = []
        for r in self.results:
            p = r["probabilidades"]
            for vb in r["value_bets"]:
                rows.append({
                    "data": r["data"], "liga": r["liga"],
                    "time_casa": r["home_team"], "time_fora": r["away_team"],
                    "gols_esp_casa": r["hge"], "gols_esp_fora": r["age"],
                    "prob_casa_%": round(p["home_win"]*100,1), "prob_empate_%": round(p["draw"]*100,1),
                    "prob_fora_%": round(p["away_win"]*100,1), "prob_over25_%": round(p["over_2_5"]*100,1),
                    "mercado": vb["mercado"], "odd": vb["odd"],
                    "prob_calculada_%": vb["prob_calc"], "prob_implicita_%": vb["prob_impl"],
                    "valor_esperado": vb["ev"], "value_bet": "SIM" if vb["is_vb"] else "NÃO",
                    "fonte_odds": r["odds_fonte"], "casas_aposta": ", ".join(r["casas"][:4]),
                })
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
        log.info("CSV salvo: %s", path)


# ── Demo ───────────────────────────────────────────────────────────────────────
def demo_mode():
    print("\n" + "═"*72)
    print("  ⚽  FOOTBALL BETTING VALUE ANALYZER — MODO DEMO")
    print("  Dados simulados · Nenhuma chave de API necessária")
    print("═"*72 + "\n")
    calc = ProbCalc()
    rng  = np.random.default_rng(42)
    jogos = [
        ("Flamengo","Palmeiras",2.1,1.4),
        ("São Paulo","Corinthians",1.3,1.3),
        ("Santos","Grêmio",1.5,1.8),
        ("Atlético-MG","Fluminense",1.8,1.2),
        ("Botafogo","Internacional",1.6,1.5),
    ]
    rows = []; total_vbs = 0
    for home, away, he, ae in jogos:
        probs = calc.probs(he, ae)
        odds  = sim_odds(probs)
        mercados = {"Casa (1)":("home_win",odds["home_win"]),"Empate (X)":("draw",odds["draw"]),
            "Fora (2)":("away_win",odds["away_win"]),"Over 2.5":("over_2_5",odds["over_2_5"]),
            "Under 2.5":("under_2_5",odds["under_2_5"])}
        data = (datetime.today()+timedelta(days=int(rng.integers(1,5)))).strftime("%Y-%m-%d")
        print(f"  📅  {data}   🏆  Brasileirão Série A")
        print(f"  {home:20s}  vs  {away}")
        print(f"  Gols esperados → Casa: {he:.2f}  |  Fora: {ae:.2f}")
        print(f"  Probabilidades → Casa: {probs['home_win']*100:.1f}%  Empate: {probs['draw']*100:.1f}%  Fora: {probs['away_win']*100:.1f}%  Over 2.5: {probs['over_2_5']*100:.1f}%")
        print(f"  🔮 Odds: simuladas")
        print(f"\n  {'Mercado':16s}  {'Odd':>6}  {'P.Calc%':>8}  {'P.Impl%':>8}  {'EV':>9}  {'Value?':>8}")
        print(f"  {'─'*64}")
        for m, (pk, odd) in mercados.items():
            vb = calc.value_bet(probs[pk], odd)
            flag = "✅ SIM" if vb["is_vb"] else "❌ NÃO"
            if vb["is_vb"]: total_vbs += 1
            print(f"  {m:16s}  {odd:>6.2f}  {vb['prob_calc']:>7.1f}%  {vb['prob_impl']:>7.1f}%  {vb['ev']:>+9.4f}  {flag}")
            rows.append({"data":data,"liga":"Brasileirão","time_casa":home,"time_fora":away,
                "gols_esp_casa":he,"gols_esp_fora":ae,
                "prob_casa_%":round(probs["home_win"]*100,1),"prob_empate_%":round(probs["draw"]*100,1),
                "prob_fora_%":round(probs["away_win"]*100,1),"prob_over25_%":round(probs["over_2_5"]*100,1),
                "mercado":m,"odd":odd,"prob_calculada_%":vb["prob_calc"],"prob_implicita_%":vb["prob_impl"],
                "valor_esperado":vb["ev"],"value_bet":"SIM" if vb["is_vb"] else "NÃO",
                "fonte_odds":"simuladas","casas_aposta":"(simuladas)"})
        print(f"\n  {'─'*88}\n")
    pd.DataFrame(rows).to_csv("value_bets_demo.csv", index=False, encoding="utf-8-sig")
    print(f"  📊  Partidas analisadas:    {len(jogos)}")
    print(f"  🎯  Value bets encontrados: {total_vbs}")
    print(f"  💾  CSV gerado: value_bets_demo.csv\n")
    print("─"*72)
    print("\n  Modos de uso com dados reais:")
    print("  --odds manual    → você digita as odds da Bet365/Betano")
    print("  --odds api       → busca automática via The Odds API")
    print("  --odds simuladas → odds geradas automaticamente\n")


# ── CLI ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="⚽ Football Betting Value Analyzer")
    parser.add_argument("--demo",         action="store_true")
    parser.add_argument("--league",       type=str, default="BSA")
    parser.add_argument("--date",         type=str)
    parser.add_argument("--next-games",   type=int, default=10)
    parser.add_argument("--output",       type=str, default="value_bets.csv")
    parser.add_argument("--list-leagues", action="store_true")
    parser.add_argument("--odds",         type=str, default="auto",
                        choices=["auto","manual","api","simuladas"],
                        help="Fonte das odds: auto | manual | api | simuladas")
    args = parser.parse_args()

    if args.list_leagues:
        print("\nLigas disponíveis:")
        for code, info in LIGAS.items():
            print(f"  {code:6s}  {info['nome']}")
        print()
        return

    if args.demo or FOOTBALL_DATA_KEY == "SUA_CHAVE_FOOTBALL_DATA":
        if not args.demo:
            print("\n⚠️  Chave não configurada — executando modo demo.\n")
        demo_mode()
        return

    a = BettingAnalyzer(odds_mode=args.odds)
    a.run(args.league.upper(), args.next_games, args.date)
    a.print_report()
    a.save_csv(args.output)

if __name__ == "__main__":
    main()
