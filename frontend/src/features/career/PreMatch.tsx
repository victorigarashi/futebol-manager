import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type Club, type PreviewSide, type RoomState, type SeasonView } from "../../lib/api";
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
  if (season.regular_season_complete) return <section className="prematch prematch--blocked"><h2>Fase de mata-mata</h2><p>Os confrontos de playoffs são disputados pelo anfitrião na aba Temporada, com as escalações e táticas salvas de cada clube.</p></section>;
  if (!data?.fixture || !data.home || !data.away) return <div className="panel-loading" role="status">{preview.error ? preview.error.message : "Montando o confronto…"}</div>;
  const ownSide = data.home.club_code === clubCode ? data.home : data.away;

  return <section className="prematch" aria-label="Pré-jogo">
    <header className="matchup">
      <p className="kicker">BRASILEIRÃO · RODADA {data.fixture.round_number} · {room.mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11"}</p>
      <div className="matchup__teams">
        <TeamHead side={data.home} club={club(data.home.club_code)} own={data.home.club_code === clubCode} label="Mandante" />
        <div className="matchup__vs"><b>×</b><span>{formatDuration(remaining)}</span></div>
        <TeamHead side={data.away} club={club(data.away.club_code)} own={data.away.club_code === clubCode} label="Visitante" />
      </div>
      <SectorCompare home={data.home} away={data.away} />
    </header>
    <MatchSettingsCard room={room} isHost={isHost} liveRound={Boolean(season.live_round)} compact />

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
