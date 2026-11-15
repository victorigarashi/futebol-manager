import type { RoomState } from "../lib/api";
import { InviteCode } from "./InviteCode";
import { MatchSettingsCard } from "./MatchSettingsCard";
import { durationLabel } from "../lib/matchDuration";

type LeagueSettingsSummaryProps = { room: RoomState; isHost: boolean; hasClub: boolean; isStarting?: boolean; onEdit?: () => void; onStart: () => void };

export function LeagueSettingsSummary({ room, isHost, hasClub, isStarting, onEdit, onStart }: LeagueSettingsSummaryProps) {
  const isWaiting = room.phase === "WAITING";
  const roundPreparationLabel = room.round_preparation_duration_seconds < 3600
    ? `${room.round_preparation_duration_seconds / 60} minutos`
    : `${room.round_preparation_duration_seconds / 3600} horas`;
  const missingClubs = room.participants.filter((participant) => !participant.selected_club_code).length;
  const openPlaces = Math.max(0, room.team_count - room.participants.filter((participant) => participant.selected_club_code).length);
  const needsBots = room.team_count !== 20 && openPlaces > 0;
  const disabledReason = !isHost ? "Só o anfitrião pode alterar as regras e iniciar a temporada." : !hasClub ? "Escolha um clube antes de abrir a temporada." : missingClubs ? `Aguardando ${missingClubs} técnico(s) escolherem um clube.` : needsBots ? `Faltam ${openPlaces} clube(s): complete as vagas com bots para iniciar.` : !isWaiting ? "A temporada já está em andamento." : "";
  const coinMarket = room.market_mode === "COINS";
  return <aside className="league-summary"><p className="section-kicker">CHAMA OS PARÇAS</p><h2>O ingresso da resenha.</h2><InviteCode code={room.code} /><dl><div><dt>Estado</dt><dd>{isWaiting ? "Aguardando a galera" : "Temporada em andamento"}</dd></div><div><dt>Regras</dt><dd>até {room.max_human_participants} humano{room.max_human_participants > 1 ? "s" : ""} · {room.team_count === 20 ? "bots completam" : "o anfitrião completa com bots"}</dd></div><div><dt>Campeonato</dt><dd>{room.team_count} clubes · {room.double_round_robin ? "ida e volta" : "turno único"}</dd></div><div><dt>Técnicos e bots</dt><dd>{room.participants.filter((participant) => participant.role !== "BOT").length} técnico(s) · {room.bot_count ?? 0} bot(s)</dd></div><div><dt>Preparação do mercado</dt><dd>{room.initial_market_duration_seconds / 60} minutos</dd></div><div><dt>Prazo entre rodadas</dt><dd>{roundPreparationLabel} · pode confirmar antes</dd></div><div><dt>Duração da partida</dt><dd>{durationLabel(room.match_duration_seconds)} · 90 minutos condensados</dd></div><div><dt>Formato</dt><dd>{room.mode === "FIVE_A_SIDE" ? "Futebol 5 × 5" : "Futebol 11 × 11"}</dd></div><div><dt>Mercado</dt><dd>{coinMarket ? "100 coins por clube" : "Valores reais em R$"}</dd></div><div><dt>Orçamento</dt><dd>{coinMarket ? "100 coins" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }).format(room.initial_budget_cents / 100)}</dd></div><div><dt>Multa por desistir de uma contratação vencida</dt><dd>{coinMarket ? "0% no modo coins" : `${room.withdrawal_penalty_percent}% · somente ofertas compromissadas`}</dd></div></dl><MatchSettingsCard room={room} isHost={isHost} />{onEdit && <button type="button" className="button-secondary league-summary__edit" onClick={onEdit}>Configurações da liga</button>}<button type="button" className="button-primary" disabled={!isHost || !hasClub || !isWaiting || Boolean(missingClubs) || isStarting} onClick={onStart}>{isStarting ? "Apitando…" : "Começar a resenha"}</button>{disabledReason && <p className="league-summary__reason">{disabledReason}</p>}<p className="league-summary__line">Amizade à parte, hoje vale taça.</p></aside>;
}
