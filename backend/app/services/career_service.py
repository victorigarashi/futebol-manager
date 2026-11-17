"""Career narrative and records, derived only from authoritative data.

Statistics, trophies, news, rivalries and special events are computed from the
committed match records (events, line-ups, ratings), the tables and the knockout
brackets - never invented. Matches still being broadcast are ignored, so nothing
here can count a goal twice or reveal one before it happens.
"""

from __future__ import annotations

from collections import defaultdict

from app.domain.knockout import STAGE_NAMES
from app.domain.season import standings

# Classic rivalries among the 20 clubs (name shown in the pre-match and the news).
RIVALRIES: dict[frozenset[str], str] = {
    frozenset(("FLA", "FLU")): "Fla-Flu", frozenset(("FLA", "VAS")): "Clássico dos Milhões",
    frozenset(("FLA", "BOT")): "Clássico da Rivalidade", frozenset(("FLU", "VAS")): "Clássico dos Gigantes",
    frozenset(("FLU", "BOT")): "Clássico Vovô", frozenset(("BOT", "VAS")): "Clássico da Amizade",
    frozenset(("COR", "PAL")): "Derby Paulista", frozenset(("COR", "SAO")): "Majestoso",
    frozenset(("COR", "SAN")): "Clássico Alvinegro", frozenset(("PAL", "SAO")): "Choque-Rei",
    frozenset(("PAL", "SAN")): "Clássico da Saudade", frozenset(("SAO", "SAN")): "San-São",
    frozenset(("CAM", "CRU")): "Clássico Mineiro", frozenset(("GRE", "INT")): "Gre-Nal",
    frozenset(("BAH", "VIT")): "Ba-Vi", frozenset(("CAP", "CFC")): "Atletiba",
    frozenset(("FLA", "PAL")): "Clássico do Brasil atual",
}


def rivalry(home: str, away: str) -> str | None:
    return RIVALRIES.get(frozenset((home, away)))


KNOCKOUT = ("PLAYOFF", "CUP")


def is_knockout(match: dict[str, object]) -> bool:
    return match.get("competition") in KNOCKOUT


def competition_of(season, match_id: str) -> str:
    match = season.matches.get(match_id) or {}
    return str(match.get("competition") or "LEAGUE")


def finished_matches(season) -> list[dict[str, object]]:
    """Committed matches only (a live round is never counted)."""
    live = set(season.live_round["match_ids"]) if season.live_round else set()
    return [m for mid, m in season.matches.items() if mid not in live and m.get("status") == "FINISHED"]


def compact_results(season) -> list[dict[str, object]]:
    rows = []
    for match in finished_matches(season):
        rows.append({"season": season.season_number, "id": match["id"], "competition": match.get("competition") or "LEAGUE",
                     "stage": match.get("stage"), "home": match["home"], "away": match["away"],
                     "home_goals": int(match["home_goals"]), "away_goals": int(match["away_goals"]),
                     "home_penalties": match.get("home_penalties"), "away_penalties": match.get("away_penalties")})
    return rows


def player_stats(season, competition: str | None = None) -> dict[str, dict[str, object]]:
    """Per player: appearances, minutes, goals, assists, average rating, saves, clean sheets."""
    stats: dict[str, dict[str, object]] = {}
    for match in finished_matches(season):
        if competition and (match.get("competition") or "LEAGUE") != competition:
            continue
        minutes = match.get("minutes") or {}
        conceded = {"home": int(match["away_goals"]), "away": int(match["home_goals"])}
        for side in ("home", "away"):
            club = match[side]
            for player in (match.get("lineups") or {}).get(side, []):
                pid = player.get("id")
                if pid not in minutes:
                    continue
                row = stats.setdefault(pid, {"player_id": pid, "name": player.get("name"), "club_code": club, "position": player.get("position"),
                                             "apps": 0, "minutes": 0, "goals": 0, "assists": 0, "rating_sum": 0.0, "saves": 0, "clean_sheets": 0})
                row["club_code"] = club
                row["apps"] = int(row["apps"]) + 1
                row["minutes"] = int(row["minutes"]) + int(minutes[pid])
                row["rating_sum"] = float(row["rating_sum"]) + float(player.get("rating") or 0) * int(minutes[pid])
                pstats = player.get("stats") or {}
                row["saves"] = int(row["saves"]) + int(pstats.get("saves", 0))
                if player.get("position") == "GK" and conceded[side] == 0 and int(minutes[pid]) >= 60:
                    row["clean_sheets"] = int(row["clean_sheets"]) + 1
        for event in match.get("events", []):
            if event.get("kind") != "GOAL":
                continue
            if event.get("player_id") in stats:
                stats[event["player_id"]]["goals"] = int(stats[event["player_id"]]["goals"]) + 1
            if event.get("secondary_player_id") in stats:
                stats[event["secondary_player_id"]]["assists"] = int(stats[event["secondary_player_id"]]["assists"]) + 1
    for row in stats.values():
        row["rating"] = round(float(row["rating_sum"]) / int(row["minutes"]), 2) if row["minutes"] else None
        row["goals_per_match"] = round(int(row["goals"]) / int(row["apps"]), 2) if row["apps"] else 0
        row.pop("rating_sum")
    return stats


def team_of_season(rows: list[dict[str, object]], min_apps: int) -> list[dict[str, object]]:
    """4-3-3 of the best average ratings with enough appearances."""
    eligible = [r for r in rows if int(r["apps"]) >= min_apps and r["rating"] is not None]
    lineup = []
    for position, count in (("GK", 1), ("DF", 4), ("MF", 3), ("ST", 3)):
        lineup.extend(sorted((r for r in eligible if r["position"] == position), key=lambda r: (-float(r["rating"]), str(r["player_id"])))[:count])
    return lineup


def records(results: list[dict[str, object]]) -> dict[str, object]:
    if not results:
        return {}
    biggest = max(results, key=lambda r: (abs(int(r["home_goals"]) - int(r["away_goals"])), int(r["home_goals"]) + int(r["away_goals"])))
    most = max(results, key=lambda r: int(r["home_goals"]) + int(r["away_goals"]))
    return {"biggest_win": biggest, "most_goals": most}


def head_to_head(results: list[dict[str, object]], a: str, b: str) -> dict[str, object]:
    meetings = [r for r in results if {r["home"], r["away"]} == {a, b}]
    wins = {a: 0, b: 0}
    draws = 0
    goals = {a: 0, b: 0}
    for r in meetings:
        home_goals, away_goals = int(r["home_goals"]), int(r["away_goals"])
        goals[str(r["home"])] += home_goals
        goals[str(r["away"])] += away_goals
        if home_goals == away_goals:
            if r.get("home_penalties") is not None:
                winner = r["home"] if int(r["home_penalties"]) > int(r["away_penalties"] or 0) else r["away"]
                wins[str(winner)] += 1
            else:
                draws += 1
        else:
            wins[str(r["home"] if home_goals > away_goals else r["away"])] += 1
    return {"meetings": len(meetings), "wins": wins, "draws": draws, "goals": goals, "last": meetings[-5:]}


def season_summary(season, clubs: tuple[str, ...], managers: dict[str, dict[str, str]]) -> dict[str, object]:
    """What a finished season leaves in history (compact)."""
    rows = list(player_stats(season).values())
    knockout = season.knockout
    best = max((r for r in rows if int(r["apps"]) >= 8 and r["rating"] is not None), key=lambda r: (float(r["rating"]), str(r["player_id"])), default=None)
    keeper = max((r for r in rows if r["position"] == "GK" and int(r["apps"]) >= 8), key=lambda r: (int(r["clean_sheets"]), int(r["saves"])), default=None)
    return {
        "season_number": season.season_number,
        "champion": season.playoffs.champion if season.playoffs else None,
        "runner_up": knockout.playoff_runner_up,
        "league_leader": standings(clubs, season.state.fixtures, season.state.results)[0]["club_code"],
        "cup_champion": knockout.cup_champion, "cup_runner_up": knockout.cup_runner_up,
        "table": standings(clubs, season.state.fixtures, season.state.results),
        "playoffs": season.playoffs.view() if season.playoffs else None,
        "managers": managers,
        "results": compact_results(season),
        "player_stats": sorted(rows, key=lambda r: (-int(r["goals"]), -int(r["apps"]), str(r["player_id"])))[:120],
        "best_player": best, "best_goalkeeper": keeper,
        "team_of_season": team_of_season(rows, 8),
    }


def trophies(history: list[dict[str, object]]) -> list[dict[str, object]]:
    """Every title and runner-up, with the club and the coach responsible at the time."""
    items = []
    for summary in history:
        managers = summary.get("managers") or {}
        for kind, club_key, place in (("BRASILEIRAO", "champion", "CHAMPION"), ("BRASILEIRAO", "runner_up", "RUNNER_UP"),
                                      ("COPA_DO_BRASIL", "cup_champion", "CHAMPION"), ("COPA_DO_BRASIL", "cup_runner_up", "RUNNER_UP")):
            club = summary.get(club_key)
            if not club:
                continue
            coach = managers.get(str(club)) or {}
            items.append({"season_number": summary["season_number"], "competition": kind, "place": place, "club_code": club,
                          "coach_user_id": coach.get("user_id"), "coach_name": coach.get("name")})
    return items


def news(season, history: list[dict[str, object]], clubs: tuple[str, ...], managers: dict[str, dict[str, str]],
         transfers: list[dict[str, object]], catalog_names: dict[str, str]) -> list[dict[str, object]]:
    """Career news from real events, with local templates (newest first)."""
    items: list[dict[str, object]] = []

    def add(kind: str, club_codes: list[str], title: str, body: str, order: float) -> None:
        items.append({"id": f"{season.season_number}:{kind}:{len(items)}", "season_number": season.season_number, "kind": kind,
                      "clubs": club_codes, "title": title, "body": body, "order": order})

    by_round: dict[int, list[dict[str, object]]] = defaultdict(list)
    fixture_round = {f.id: f.round_number for f in season.state.fixtures}
    for match in finished_matches(season):
        home, away = str(match["home"]), str(match["away"])
        hg, ag = int(match["home_goals"]), int(match["away_goals"])
        number = fixture_round.get(str(match["id"]), 99)
        order = number * 10 + (5 if is_knockout(match) else 0)
        by_round[number].append(match)
        classic = rivalry(home, away)
        winner = home if hg > ag else away if ag > hg else None
        label = f"{home} {hg} × {ag} {away}"
        if is_knockout(match):
            stage = STAGE_NAMES.get(str(match.get("stage")), match.get("stage"))
            name = "Copa do Brasil" if match["competition"] == "CUP" else "Playoffs"
            pens = f" (pênaltis {match['home_penalties']}–{match['away_penalties']})" if match.get("home_penalties") is not None else ""
            add("KNOCKOUT", [home, away], f"{name}: {label}{pens}", f"{stage} da {name}.", order)
        if classic:
            add("CLASSIC", [home, away], f"{classic}: {label}",
                "Empate no clássico." if winner is None else f"{winner} leva a melhor no {classic}.", order + 1)
        if abs(hg - ag) >= 4:
            add("ROUT", [home, away], f"Goleada: {label}", f"{winner} atropela e manda recado ao campeonato.", order + 2)
        scorers = defaultdict(int)
        for event in match.get("events", []):
            if event.get("kind") == "GOAL" and event.get("player_id"):
                scorers[(event["player_id"], event.get("player_name"), event.get("team"))] += 1
        for (_pid, name, team), goals in scorers.items():
            if goals >= 3:
                add("STAR", [str(team)], f"{name} marca {goals} vezes", f"Noite inspirada: {name} decide para o {team} em {label}.", order + 3)
    # Leadership and playoff race after each played league round.
    leader_before = None
    for number in sorted(n for n in by_round if n < 99):
        played = {fid: res for fid, res in season.state.results.items() if fixture_round.get(fid, 99) <= number}
        table = standings(clubs, season.state.fixtures, played)
        leader = table[0]["club_code"]
        if leader != leader_before:
            add("LEADER", [leader], f"{leader} assume a liderança", f"Depois da rodada {number}, {leader} lidera com {table[0]['points']} pontos.", number * 10 + 4)
        leader_before = leader
        if number >= max(1, len(set(fixture_round.values())) - 6) and len(table) >= 9:
            eighth, ninth = table[7], table[8]
            if int(eighth["points"]) - int(ninth["points"]) <= 2:
                add("RACE", [eighth["club_code"], ninth["club_code"]], "Briga pela vaga nos playoffs",
                    f"{eighth['club_code']} ({eighth['points']} pts) e {ninth['club_code']} ({ninth['points']} pts) disputam a 8ª vaga.", number * 10 + 4.5)
    league_champion = season.playoffs.champion if season.playoffs else None
    for champion, runner_up, key in ((league_champion, season.knockout.playoff_runner_up, "Brasileirão"),
                                     (season.knockout.cup_champion, season.knockout.cup_runner_up, "Copa do Brasil")):
        if champion:
            add("TITLE", [champion], f"{champion} é campeão {'do' if key == 'Brasileirão' else 'da'} {key}!",
                f"Título conquistado sobre o {runner_up}." if runner_up else "Título conquistado na tabela.", 1000 + (1 if key == "Brasileirão" else 0))
    for offer in transfers:
        player = catalog_names.get(str(offer.get("incoming_player_id")), str(offer.get("incoming_player_id")))
        if offer.get("status") == "ACCEPTED":
            add("TRANSFER", [str(offer["buyer_club"]), str(offer["seller_club"])], f"{player} acerta com o {offer['buyer_club']}",
                f"Negociação concluída entre {offer['buyer_club']} e {offer['seller_club']}.", 500)
        elif offer.get("status") in ("PENDING", "COUNTERED") and offer.get("origin") == "BOT":
            # Rumour: the interest is real; the amount of a negotiation is never revealed.
            add("RUMOR", [str(offer["buyer_club"]), str(offer["seller_club"])], f"Rumor: {offer['buyer_club']} de olho em {player}",
                f"O {offer['buyer_club']} teria procurado o {offer['seller_club']}.", 499)
    for record in season.development_records:
        if record.get("season_number") == season.season_number and int(record.get("delta", 0)) >= 3:
            name = catalog_names.get(str(record["player_id"]), str(record["player_id"]))
            add("GROWTH", [], f"{name} evolui {record['delta']} pontos", f"De {record['overall_before']} para {record['overall_after']} de overall.", 1100)
    return sorted(items, key=lambda item: -float(item["order"]))


def special_events(season, home: str, away: str, clubs: tuple[str, ...], competition: str | None,
                   stage: str | None, leg: int | None, legs: int | None, former_club_players: list[str]) -> list[dict[str, str]]:
    """Context for the pre-match presentation (never changes the match itself)."""
    events: list[dict[str, str]] = []
    classic = rivalry(home, away)
    if classic:
        events.append({"kind": "CLASSIC", "title": classic, "text": "Clássico: vale mais que três pontos."})
    if competition:
        if stage == "FINAL":
            events.append({"kind": "TITLE", "title": "Decisão de título", "text": "Quem vencer levanta a taça."})
        if legs == 2 and leg == 2:
            events.append({"kind": "DECISIVE", "title": "Jogo de volta", "text": "Placar agregado decide a vaga; empate leva aos pênaltis."})
        return events
    table = standings(clubs, season.state.fixtures, season.state.results)
    position = {row["club_code"]: index + 1 for index, row in enumerate(table)}
    if {position.get(home), position.get(away)} == {1, 2} and any(int(r["played"]) for r in table):
        events.append({"kind": "LEADERSHIP", "title": "Confronto pela liderança", "text": "Primeiro contra segundo."})
    if all(6 <= (position.get(club) or 0) <= 10 for club in (home, away)) and any(int(r["played"]) >= 10 for r in table):
        events.append({"kind": "RACE", "title": "Disputa por vaga nos playoffs", "text": "Duelo direto perto da linha dos oito."})
    for club in (home, away):
        streak = _streak(season, club)
        if streak >= 3:
            events.append({"kind": "STREAK", "title": f"{club} vem de {streak} vitórias", "text": "Sequência em jogo."})
        elif streak <= -3:
            events.append({"kind": "SLUMP", "title": f"{club} vem de {-streak} derrotas", "text": "Pressão por reação."})
    for name in former_club_players[:2]:
        events.append({"kind": "FORMER_CLUB", "title": f"{name} reencontra o ex-clube", "text": "Reencontro com a antiga casa."})
    return events


def _streak(season, club: str) -> int:
    """+N wins in a row / -N losses in a row in the league (0 otherwise)."""
    ordered = sorted((f for f in season.state.fixtures if f.id in season.state.results and club in (f.home, f.away)),
                     key=lambda f: f.round_number)
    streak = 0
    for fixture in reversed(ordered):
        result = season.state.results[fixture.id]
        own, other = (result.home_goals, result.away_goals) if fixture.home == club else (result.away_goals, result.home_goals)
        outcome = 1 if own > other else -1 if own < other else 0
        if outcome == 0 or (streak and (outcome > 0) != (streak > 0)):
            break
        streak += outcome
    return streak
