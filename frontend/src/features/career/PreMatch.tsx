import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type Club, type MatchPreview, type PreviewSide, type RoomState, type SeasonView } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { MatchSettingsCard } from "../../components/MatchSettingsCard";
import { POSITION_LABEL, tacticSummary } from "./labels";

type Props = { roomId: string; room: RoomState; season: SeasonView; clubCode: string; clubs: Club[]; onGo: (tab: "squad" | "tactics") => void; isHost?: boolean };

/** Pre-match: matchup, both projected line-ups, plan summary and the ready check. */
export function PreMatch({ roomId, room, season, clubCode, clubs, onGo, isHost = false }: Props) {
  const client = useQueryClient();
  const preview = useQuery({ queryKey: ["preview", roomId, season.current_round], queryFn: () => api.preview(roomId).then((r) => r.data), refetchInterval: 8000 });
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  // The server answers READY with the authoritative season: show it at once (the button
  // must not fall back to "Confirmar" just because a later refetch failed). Confirming
  // twice is harmless: the server treats READY as idempotent.
  const ready = useMutation({
    mutationFn: () => api.readyForRound(roomId),
    onSuccess: ({ data }) => {
      client.setQueryData(["season", roomId], data);
      void client.invalidateQueries({ queryKey: ["preview", roomId] });
      if (data.live_round) void client.invalidateQueries({ queryKey: ["live", roomId] });
    },
  });
  const [, tick] = useState(0);
  useEffect(() => { const timer = window.setInterval(() => tick((v) => v + 1), 1000); return () => window.clearInterval(timer); }, []);
  const club = (code: string) => clubs.find((c) => c.code === code) ?? { code, name: code, sort_order: 0 };
  const data = preview.data;
  const humans = room.participants.filter((p) => p.selected_club_code);
  const isReady = season.ready_clubs.includes(clubCode);
  const readyError = ready.error instanceof ApiError ? ready.error : null;
  const starting = season.round_state === "READY" || season.round_state === "STARTING" || Boolean(season.live_round);
  const deadline = season.preparation_opened_at ? season.preparation_opened_at + room.round_preparation_duration_seconds : null;
  const offset = season.server_now - Date.now() / 1000;
  const remaining = deadline ? Math.max(0, deadline - (Date.now() / 1000 + offset)) : null;
  const hasLineup = Boolean(squad.data?.lineup);

  if (season.transfer_window_open) return <section className="prematch prematch--blocked"><h2>Janela de transferências aberta</h2><p>A rodada {season.current_round} começa depois que o anfitrião encerrar a janela. Aproveite para reforçar o elenco na aba Mercado.</p></section>;
  if (season.season_complete) return <section className="prematch prematch--blocked"><h2>Temporada encerrada</h2><p>{season.champion ? `O campeão foi definido. ` : ""}Veja a Sala de Troféus e aguarde o anfitrião abrir a próxima temporada.</p></section>;
  if (season.regular_season_complete && !Object.values(season.knockout?.ties ?? {}).some((t) => t.competition === "PLAYOFF")) return <section className="prematch prematch--blocked"><h2>Sorteio dos playoffs</h2><p>A fase de pontos terminou. O anfitrião realiza o sorteio dos potes na aba Temporada; depois cada confronto é jogado ao vivo, com sua escalação e tática.</p></section>;
  if (data?.waiting) return <section className="prematch prematch--blocked"><h2>{data.next_round?.kind === "CUP" ? "Copa do Brasil" : "Mata-mata"} · {data.next_round?.stage_name ?? ""}</h2><p>Seu clube não disputa esta rodada. Acompanhe os confrontos na aba {data.next_round?.kind === "CUP" ? "Copa" : "Temporada"}; a próxima partida aparece aqui quando chegar a sua vez.</p></section>;
  if (!data?.fixture || !data.home || !data.away) return <div className="panel-loading" role="status">{preview.error ? preview.error.message : "Montando o confronto…"}</div>;
  const ownSide = data.home.club_code === clubCode ? data.home : data.away;

  return <section className="prematch" aria-label="Pré-jogo">
    <header className="matchup">
      <p className="kicker">{competitionLabel(data.fixture)} · {room.mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11"}</p>
      {data.classic && <p className="matchup__classic">🔥 {data.classic}</p>}
      <div className="matchup__teams">
        <TeamHead side={data.home} club={club(data.home.club_code)} own={data.home.club_code === clubCode} label="Mandante" />
        <div className="matchup__vs"><b>×</b><span>{formatDuration(remaining)}</span></div>
        <TeamHead side={data.away} club={club(data.away.club_code)} own={data.away.club_code === clubCode} label="Visitante" />
      </div>
      <SectorCompare home={data.home} away={data.away} />
    </header>
    <MatchSettingsCard room={room} isHost={isHost} liveRound={Boolean(season.live_round)} compact />
    <MatchContext data={data} club={club} />

    <ol className="prematch-steps" aria-label="Preparação">
      <li className={hasLineup ? "is-done" : ""}><b>1</b><div><strong>Escalação</strong><span>{hasLineup ? `${ownSide.formation_code} salva` : `Sugestão automática (${ownSide.formation_code}) — revise e salve`}</span></div><button type="button" className="btn btn--ghost" onClick={() => onGo("squad")}>{hasLineup ? "Revisar" : "Montar"}</button></li>
      <li className="is-done"><b>2</b><div><strong>Táticas</strong><span>{ownSide.tactics ? tacticSummary(ownSide.tactics) : "—"}</span></div><button type="button" className="btn btn--ghost" onClick={() => onGo("tactics")}>Ajustar</button></li>
      <li className={isReady ? "is-done" : "is-current"}><b>3</b><div><strong>Confirmar equipe</strong><span>{isReady ? "Você está pronto. Alterar escalação ou tática cancela a confirmação." : "Quando todos os técnicos confirmarem, a partida é apresentada e começa."}</span></div>
        <button type="button" className={`btn btn--primary ${isReady ? "is-confirmed" : ""}`} disabled={isReady || ready.isPending || starting} aria-live="polite" onClick={() => ready.mutate()}>{ready.isPending ? "Confirmando…" : starting ? "Iniciando partida…" : isReady ? "✓ Pronto" : "Confirmar equipe"}</button></li>
    </ol>
    {ready.error && <p className="cm-toast cm-toast--error" role="alert">{readyError?.transient ? "Não foi possível confirmar agora: o servidor não respondeu. Sua equipe não foi marcada como pronta — tente de novo em instantes." : ready.error.message} <button type="button" className="btn btn--ghost" onClick={() => ready.mutate()}>Tentar de novo</button></p>}

    <div className="prematch__grid">
      <LineupColumn side={data.home} club={club(data.home.club_code)} />
      <section className="ready-board" aria-label="Prontidão dos técnicos"><h3>Vestiários</h3>
        <ul>{humans.map((p) => <li key={p.user_id} className={season.ready_clubs.includes(p.selected_club_code!) ? "is-ready" : ""}><ClubCrest club={club(p.selected_club_code!)} size="sm" /><span><b>{p.display_name}</b><small>{club(p.selected_club_code!).name}</small></span><em>{season.ready_clubs.includes(p.selected_club_code!) ? "Pronto" : "Preparando"}</em></li>)}</ul>
        <p className="hint">{season.ready_clubs.length} de {humans.length} técnicos prontos. Clubes sem técnico jogam com escalação automática e treinador virtual, que usa os mesmos comandos que você.</p>
        {remaining !== null && <p className="hint">Prazo da rodada: se acabar, quem não confirmou entra com a escalação e a tática salvas.</p>}
      </section>
      <LineupColumn side={data.away} club={club(data.away.club_code)} />
    </div>
  </section>;
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds > 3600 * 2) return `prazo em ${Math.floor(seconds / 3600)}h`;
  const h = Math.floor(seconds / 3600); const m = Math.floor((seconds % 3600) / 60); const s = Math.floor(seconds % 60);
  return `prazo ${h ? `${h}:` : ""}${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function TeamHead({ side, club, own, label }: { side: PreviewSide; club: Club; own: boolean; label: string }) {
  return <div className={`matchup__team ${own ? "is-you" : ""}`}><ClubCrest club={club} size="md" /><strong>{club.name}</strong><small>{label} · {side.manager ?? "Treinador virtual"}{own ? " (você)" : ""}</small><span className="matchup__avg">OVR médio <b>{side.average.toFixed(1)}</b> · {side.formation_code}</span>{side.ready && <em className="badge badge--applied">Pronto</em>}</div>;
}

function SectorCompare({ home, away }: { home: PreviewSide; away: PreviewSide }) {
  const rows: [string, string][] = [["GK", "Goleiro"], ["DF", "Defesa"], ["MF", "Meio"], ["ST", "Ataque"]];
  return <div className="sector-compare" aria-label="Comparação por setor">{rows.filter(([key]) => home.sectors[key] || away.sectors[key]).map(([key, label]) => {
    const h = home.sectors[key] ?? 0; const a = away.sectors[key] ?? 0;
    return <div key={key}><b className={h >= a ? "lead" : ""}>{h.toFixed(0)}</b><span>{label}</span><b className={a >= h ? "lead" : ""}>{a.toFixed(0)}</b><i aria-hidden="true"><em style={{ width: `${(h / (h + a || 1)) * 100}%` }} /></i></div>;
  })}</div>;
}

function LineupColumn({ side, club }: { side: PreviewSide; club: Club }) {
  return <section className="lineup-column" aria-label={`Titulares do ${club.name}`}><h3><ClubCrest club={club} size="sm" />{club.name} <small>{side.formation_code}</small></h3>
    <ol>{side.starters.map((p) => <li key={p.id} className={p.improvised ? "is-improvised" : ""}><span className="pos">{POSITION_LABEL[p.slot_position]}</span><b>{p.name}</b><span className="ovr">{p.overall}</span>{p.improvised && <small className="warn" title="Fora de posição">⚠</small>}</li>)}</ol>
    <p className="hint">{side.bench_size} no banco</p>
  </section>;
}

function competitionLabel(fixture: NonNullable<MatchPreview["fixture"]>): string {
  if (!fixture.competition) return `BRASILEIRÃO · RODADA ${fixture.round_number}`;
  const name = fixture.competition === "CUP" ? "COPA DO BRASIL" : "PLAYOFFS";
  const leg = fixture.legs === 2 ? ` · ${fixture.leg === 1 ? "IDA" : "VOLTA"}` : "";
  return `${name} · ${(fixture.stage_name ?? "").toUpperCase()}${leg}`;
}

/** Story of the match: derby, decisive context and head-to-head (real records only). */
function MatchContext({ data, club }: { data: MatchPreview; club: (code: string) => Club }) {
  const events = data.special_events ?? [];
  const h2h = data.head_to_head;
  const fixture = data.fixture!;
  if (!events.length && !h2h?.meetings && !data.morale) return null;
  return <section className="match-context" aria-label="Contexto da partida">
    {events.length > 0 && <ul className="match-context__events">{events.map((e, i) => <li key={`${e.kind}-${i}`} className={`event-chip event-chip--${e.kind.toLowerCase()}`}><b>{e.title}</b><span>{e.text}</span></li>)}</ul>}
    {h2h && h2h.meetings > 0 && <div className="match-context__h2h"><h3>Retrospecto</h3>
      <p><b>{club(fixture.home).name}</b> {h2h.wins[fixture.home] ?? 0} · {h2h.draws} empates · {h2h.wins[fixture.away] ?? 0} <b>{club(fixture.away).name}</b> <small>({h2h.meetings} jogos)</small></p>
      <ol>{h2h.last.map((m, i) => <li key={i}>{m.home} {m.home_goals} × {m.away_goals} {m.away}</li>)}</ol></div>}
    {data.morale && <p className="hint">Moral: {club(fixture.home).name} {moraleLabel(data.morale[fixture.home])} · {club(fixture.away).name} {moraleLabel(data.morale[fixture.away])}</p>}
  </section>;
}

const moraleLabel = (value = 0) => value >= 2 ? "em alta" : value <= -2 ? "abalada" : "estável";
