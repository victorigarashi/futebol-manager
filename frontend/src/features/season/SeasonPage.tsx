import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type MatchReplay, type SeasonTableRow } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { CareerPanel } from "../../components/CareerPanel";
import { LiveMatchPage } from "./LiveMatchPage";
import { MatchReplayView } from "./MatchReplay";
import { StandingsTable } from "./StandingsTable";
import { TransferHub } from "./TransferHub";
import { SquadPage } from "../squad/SquadPage";
import "./season-beta.css";

const STAGES: Record<string, string> = { QUARTERFINALS: "Quartas de final", SEMIFINALS: "Semifinais", FINAL: "Final", COMPLETE: "Temporada encerrada" };

function PostMatchSummary({ match, roundNumber, ownClub, nextOpponent, position, previousPosition }: {
  match: MatchReplay; roundNumber?: number; ownClub: string; nextOpponent?: string; position?: number; previousPosition?: number;
}) {
  const goals = match.events.filter((event) => event.kind === "GOAL");
  const home = ownClub === match.home;
  const ourGoals = home ? match.home_goals : match.away_goals;
  const theirGoals = home ? match.away_goals : match.home_goals;
  const result = ourGoals > theirGoals ? "Vitória na conta!" : ourGoals < theirGoals ? "É hora de reagir." : "Um ponto na bagagem.";
  const move = position && previousPosition ? previousPosition - position : 0;
  return <section className="post-match-summary" aria-labelledby="post-match-title">
    <header><div><p className="section-kicker">APITO FINAL {roundNumber ? roundNumber <= 38 ? `/ RODADA ${roundNumber}` : "/ MATA-MATA" : ""}</p><h2 id="post-match-title">{result}</h2></div><span className="sports-badge">RESULTADO OFICIAL</span></header>
    <div className="post-match-summary__score"><strong>{match.home}</strong><b>{match.home_goals} <span>×</span> {match.away_goals}</b><strong>{match.away}</strong></div>
    <div className="post-match-summary__content"><section><h3>Quem balançou a rede</h3>{goals.length ? <ul>{goals.map((goal) => <li key={goal.event_id}><time>{goal.minute}′</time><span>{goal.player_name ?? goal.player_id ?? "Gol registrado"}</span><b>{goal.team}</b></li>)}</ul> : <p>Ninguém tirou o zero do placar.</p>}</section><dl><div><dt>Sua posição</dt><dd>{position ? `${position}º` : "—"}{previousPosition !== undefined && <small>{move > 0 ? `↑ Subiu ${move}` : move < 0 ? `↓ Caiu ${-move}` : "Manteve a posição"}</small>}</dd></div><div><dt>Finalizações</dt><dd>{match.statistics[ownClub]?.shots ?? 0}<small>{match.statistics[ownClub]?.shots_on_target ?? 0} no alvo</small></dd></div><div><dt>Próximo compromisso</dt><dd>{nextOpponent ?? "Aguarde a próxima etapa"}</dd></div></dl></div>
    <a className="text-action" href="#season-replays">Ver estatísticas e replay da partida ↓</a>
  </section>;
}

export function SeasonPage({ roomId, isHost, clubCode }: { roomId: string; isHost: boolean; clubCode: string }) {
  const queryClient = useQueryClient();
  const [showSquad, setShowSquad] = useState(false);
  const [selectedMatch, setSelectedMatch] = useState<string | null>(null);
  const baselineRef = useRef<SeasonTableRow[]>([]);
  const season = useQuery({ queryKey: ["season", roomId], queryFn: () => api.season(roomId).then(({ data }) => data), refetchInterval: 5000 });
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then(({ data }) => data) });
  const room = useQuery({ queryKey: ["room-state", roomId], queryFn: () => api.state(roomId).then(({ data }) => data) });
  const refresh = () => void queryClient.invalidateQueries({ predicate: (query) => query.queryKey.includes(roomId) });
  const ready = useMutation({ mutationFn: () => api.readyForRound(roomId), onSuccess: refresh });
  const advance = useMutation({ mutationFn: () => api.advanceRound(roomId), onSuccess: refresh });
  const closeWindow = useMutation({ mutationFn: () => api.closeTransferWindow(roomId), onSuccess: refresh });
  const nextSeason = useMutation({ mutationFn: () => api.startNextSeason(roomId), onSuccess: () => { setSelectedMatch(null); baselineRef.current = []; refresh(); } });
  const live = useQuery({ queryKey: ["live", roomId], queryFn: () => api.live(roomId).then(({ data }) => data), refetchInterval: 1000 });
  useEffect(() => { if (live.data?.live_round) baselineRef.current = live.data.official_table; }, [live.data]);
  const ownMatches = season.data?.matches.filter((match) => match.home === clubCode || match.away === clubCode) ?? [];
  // The live endpoint is the primary stream. Keep a second, authorized read of
  // the coach's own match as a recovery path while a new deployment or a
  // reconnect catches up with the round broadcast.
  const ownLiveMatchId = live.data?.live_round
    ? ownMatches.find((match) => live.data?.live_round?.match_ids.includes(match.id))?.id
      ?? season.data?.fixtures.find((fixture) => (fixture.home === clubCode || fixture.away === clubCode)
        && live.data?.live_round?.match_ids.includes(fixture.id))?.match_id
      ?? null
    : null;
  const liveFallback = useQuery({
    queryKey: ["live-match-fallback", roomId, ownLiveMatchId],
    queryFn: () => api.match(roomId, ownLiveMatchId!).then(({ data }) => data),
    enabled: Boolean(live.data?.live_round && !live.data.match && ownLiveMatchId),
    refetchInterval: 1000,
  });
  const matchId = ownMatches.find((match) => match.id === selectedMatch)?.id ?? ownMatches.at(-1)?.id ?? null;
  // A replay request also returns the currently released event prefix while a
  // match is live. Never leave the page in an indefinite loading state just
  // because a transient live-round response omitted its own-match payload.
  const replay = useQuery({ queryKey: ["match", roomId, matchId], queryFn: () => api.match(roomId, matchId!).then(({ data }) => data), enabled: Boolean(matchId), refetchInterval: live.data?.live_round ? 1000 : false });
  const recentId = ownMatches.at(-1)?.id;
  const recent = useQuery({ queryKey: ["match", roomId, recentId], queryFn: () => api.match(roomId, recentId!).then(({ data }) => data), enabled: Boolean(recentId), refetchInterval: live.data?.live_round ? 1000 : false });
  const liveMatch = live.data?.match ?? liveFallback.data ?? replay.data;
  if (live.data?.live_round && liveMatch) return <>{(live.error || liveFallback.error) && <p role="status" className="feedback">Reconectando à transmissão… O relógio continua no servidor.</p>}<LiveMatchPage data={{ ...live.data, match: liveMatch }} clubCode={clubCode} /></>;
  if (!season.data) return <section className="season-page" aria-busy={season.isPending}>{season.error ? <div className="feedback feedback--error" role="alert"><p>{season.error.message}</p><button type="button" className="button-secondary" onClick={() => void season.refetch()}>Tentar novamente</button></div> : <p role="status" className="muted">Preparando a rodada e a classificação…</p>}</section>;
  const data = season.data;
  const actionError = ready.error ?? advance.error ?? closeWindow.error ?? nextSeason.error;
  const club = (code: string) => clubs.data?.find((item) => item.code === code);
  const name = (code: string) => club(code)?.name ?? code;
  const nextFixture = !data.regular_season_complete ? data.fixtures.find((fixture) => fixture.home === clubCode || fixture.away === clubCode) : undefined;
  const nextOpponent = nextFixture ? name(nextFixture.home === clubCode ? nextFixture.away : nextFixture.home) : undefined;
  const latest = recent.data?.status === "FINISHED" ? recent.data : live.data?.match?.status === "FINISHED" ? live.data.match : undefined;
  const latestRound = data.matches.find((match) => match.id === latest?.id)?.round_number;
  const championClub = data.champion ? club(data.champion) : undefined;
  const championManager = room.data?.participants.find((participant) => participant.selected_club_code === data.champion)?.display_name;
  const development = data.development_records.filter((record) => record.season_number === data.season_number);
  const humanCount = room.data?.participants.filter((participant) => participant.selected_club_code).length;
  return <section className="season-page season-page--beta">
    <header className="season-header"><div><p className="section-kicker">BRASILEIRÃO / TEMPORADA {data.season_number}</p><h1>{data.season_complete ? "A taça tem dono." : data.regular_season_complete ? "Agora é mata-mata." : <>Rodada <em>{data.current_round}</em></>}</h1><p>{data.transfer_window_open ? "Mercado aberto: prepare seu elenco para o returno." : data.regular_season_complete ? data.playoffs ? STAGES[data.playoffs.next_stage] ?? data.playoffs.next_stage : "Os oito melhores avançam para as quartas de final." : `${data.ready_clubs.length}${humanCount !== undefined ? ` de ${humanCount}` : ""} técnicos prontos. Quando todos confirmarem, a bola rola.`}</p></div><div className="season-actions">
      {!data.regular_season_complete && !data.transfer_window_open && <button className="button-primary" type="button" disabled={ready.isPending || data.ready_clubs.includes(clubCode) || Boolean(data.live_round)} onClick={() => ready.mutate()}>{ready.isPending ? "Confirmando…" : data.ready_clubs.includes(clubCode) ? "✓ Você está pronto" : "Estou pronto"}</button>}
      {isHost && data.transfer_window_open && <button className="button-primary" type="button" disabled={closeWindow.isPending} onClick={() => closeWindow.mutate()}>{closeWindow.isPending ? "Encerrando…" : "Encerrar janela e seguir →"}</button>}
      {isHost && data.regular_season_complete && !data.season_complete && !data.transfer_window_open && <button className="button-primary" type="button" disabled={advance.isPending} onClick={() => advance.mutate()}>{advance.isPending ? "Disputando…" : `Disputar ${data.playoffs?.next_stage === "SEMIFINALS" ? "semifinais" : data.playoffs?.next_stage === "FINAL" ? "a final" : "quartas"} →`}</button>}
      {isHost && data.season_complete && <button className="button-primary" type="button" disabled={nextSeason.isPending} onClick={() => nextSeason.mutate()}>{nextSeason.isPending ? "Preparando…" : "Começar próxima temporada →"}</button>}
    </div></header>
    {actionError && <p className="feedback feedback--error" role="alert">{actionError.message}</p>}
    {season.error && <p className="feedback" role="status">Os dados podem estar desatualizados. Tentando reconectar…</p>}
    {data.live_round && !live.data?.match && <p className="feedback" role="status">A bola já vai rolar. Conectando sua transmissão…</p>}
    {!data.live_round && !data.transfer_window_open && !data.season_complete && <button type="button" className="button-secondary season-squad-toggle" aria-expanded={showSquad} aria-controls="season-squad" onClick={() => setShowSquad((value) => !value)}>{showSquad ? "Fechar prancheta" : "Abrir prancheta · escalação e estratégia"}</button>}
    {showSquad && !data.live_round && !data.transfer_window_open && !data.season_complete && <div id="season-squad"><SquadPage roomId={roomId} isHost={false} onStartSeason={() => {}} inSeason /></div>}
    {latest && <><p className="match-finished" role="status">{data.regular_season_complete ? "Resultados oficiais disponíveis. Confira a corrida pela taça." : "Apito final. Os dez resultados da rodada foram oficializados."}</p><PostMatchSummary match={latest} roundNumber={latestRound} ownClub={clubCode} nextOpponent={nextOpponent} position={data.table.find((row) => row.club_code === clubCode)?.position} previousPosition={baselineRef.current.find((row) => row.club_code === clubCode)?.position} /></>}
    {data.season_complete && <section className="champion-celebration" aria-labelledby="champion-title"><span className="champion-celebration__trophy" aria-hidden="true">🏆</span><div><p className="section-kicker">CAMPEÃO BRASILEIRO / TEMPORADA {data.season_number}</p><h2 id="champion-title">{data.champion ? name(data.champion) : "Campeão"}</h2><p>{championManager ? `Sob o comando de ${championManager}.` : "Comandado pelo técnico do clube no jogo."} Uma campanha para entrar na história.</p></div>{championClub && <ClubCrest club={championClub} size="lg" />}</section>}
    <nav className="season-section-nav" aria-label="Navegação da temporada"><a href="#season-table">Classificação</a><a href="#season-fixtures">Rodada</a><a href="#season-replays">Seus jogos</a>{data.playoffs && <a href="#season-playoffs">Playoffs</a>}{data.season_history.length > 0 && <a href="#season-history">Histórico</a>}</nav>
    <div className="season-grid"><section id="season-table" className="season-table"><header className="sports-section-heading"><div><p className="section-kicker">A CORRIDA PELA TAÇA</p><h2>Classificação</h2></div><span className="sports-badge">OFICIAL</span></header><StandingsTable rows={data.table} ownClub={clubCode} /></section><section id="season-fixtures" className="season-fixtures"><h2>{data.regular_season_complete ? "Última rodada regular" : `Jogos da rodada ${data.current_round}`}</h2>{data.fixtures.map((fixture) => <article className={fixture.home === clubCode || fixture.away === clubCode ? "is-own-match" : ""} key={fixture.id}><strong title={name(fixture.home)}>{fixture.home}</strong><b>{fixture.result ? `${fixture.result.home_goals} × ${fixture.result.away_goals}` : "×"}</b><strong title={name(fixture.away)}>{fixture.away}</strong></article>)}{nextOpponent && <p className="season-next-opponent">Seu próximo adversário: <strong>{nextOpponent}</strong></p>}</section></div>
    {data.transfer_window_open && <TransferHub roomId={roomId} />}
    {data.playoffs && <section id="season-playoffs" className="playoff-bracket"><header><div><p className="section-kicker">MATA-MATA / JOGO ÚNICO</p><h2>O caminho até a taça</h2></div><span className="sports-badge">8 CLUBES · 1 CAMPEÃO</span></header><div className="playoff-bracket__rounds">{([["QUARTAS", data.playoffs.quarterfinals], ["SEMIFINAIS", data.playoffs.semifinals], ["FINAL", data.playoffs.final ? [data.playoffs.final] : []]] as const).map(([stage, matches]) => <section key={stage}><h3>{stage}</h3>{matches.length ? matches.map((match) => <article className="playoff-match" key={match.id}>{([match.home, match.away] as const).map((code) => <p key={code} className={match.winner === code ? "is-winner" : ""}><span>{club(code) && <ClubCrest club={club(code)!} size="sm" />}{name(code)}{match.winner === code && <small>✓ Vencedor</small>}</span><b>{code === match.home ? match.home_goals : match.away_goals}</b></p>)}{match.home_penalties !== null && <small className="playoff-penalties">Pênaltis: {match.home_penalties} × {match.away_penalties}</small>}</article>) : <p className="playoff-awaiting">Confrontos definidos após a fase anterior.</p>}</section>)}</div></section>}
    {data.season_complete && <section className="career-summary"><div><p className="section-kicker">A TEMPORADA EM NÚMEROS</p><h2>Quem fez a diferença</h2><p>Premiações e evolução são aplicadas pelo servidor ao encerrar a temporada.</p><h3>Artilharia</h3>{data.top_scorers.length ? data.top_scorers.slice(0, 5).map((scorer) => <p className="career-scorer" key={`${scorer.player_id}-${scorer.club_code}`}><strong>{scorer.player_name}</strong><span>{scorer.club_code} · {scorer.goals} {scorer.goals === 1 ? "gol" : "gols"}</span></p>) : <p>Nenhum gol registrado.</p>}</div><dl><div><dt>Subiram</dt><dd>{development.filter((record) => record.delta > 0).length}</dd></div><div><dt>Regrediram</dt><dd>{development.filter((record) => record.delta < 0).length}</dd></div><div><dt>Estáveis</dt><dd>{development.filter((record) => record.delta === 0).length}</dd></div></dl></section>}
    {data.season_history.length > 0 && <section id="season-history" className="career-history"><h2>A história da sua liga</h2>{data.season_history.map((item) => <article key={item.season_number}><p><span>Temporada {item.season_number}</span><strong>🏆 {name(item.champion)}</strong></p>{item.top_scorers?.[0] && <small>Artilheiro: {item.top_scorers[0].player_name} · {item.top_scorers[0].goals} gols</small>}</article>)}</section>}
    <CareerPanel roomId={roomId} />
    <section id="season-replays" className="season-replays">{ownMatches.length > 0 ? <><div className="season-replays__heading"><div><p className="section-kicker">SEUS JOGOS / REPLAY OFICIAL</p><h2>A partida, lance a lance</h2></div><label>Escolha um jogo<select value={matchId ?? ""} onChange={(event) => setSelectedMatch(event.target.value)}>{[...ownMatches].reverse().map((match) => <option value={match.id} key={match.id}>{match.round_number <= 38 ? `R${match.round_number}` : "Playoffs"} · {match.home} {match.home_goals} × {match.away_goals} {match.away}</option>)}</select></label></div>{replay.data ? <MatchReplayView key={`${data.season_number}:${replay.data.id}`} match={replay.data} /> : replay.error ? <div className="feedback feedback--error" role="alert"><p>{replay.error.message}</p><button type="button" className="button-secondary" onClick={() => void replay.refetch()}>Recarregar replay</button></div> : <p className="muted" role="status">Carregando os lances oficiais…</p>}</> : <div className="season-empty-match"><span aria-hidden="true">◎</span><h2>Seu clube está a um apito de começar.</h2><p>Prepare a escalação e confirme que está pronto. Os replays do seu time ficam salvos aqui depois de cada partida.</p></div>}</section>
  </section>;
}
