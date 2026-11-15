import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type Club, type RoomState } from "../lib/api";
import { ClubCrest } from "./ClubCrest";

type Props = { room: RoomState; isHost: boolean; clubs: Club[] };

/**
 * Club places of the league: people, bots and open places. In a custom league
 * (fewer than 20 clubs) the host fills the open places with bots before starting;
 * in the classic 20-club league the free clubs still become bots automatically.
 */
export function BotSlotsCard({ room, isHost, clubs }: Props) {
  const client = useQueryClient();
  const byCode = new Map(clubs.map((club) => [club.code, club]));
  const people = room.participants.filter((p) => p.role !== "BOT");
  const bots = room.participants.filter((p) => p.role === "BOT");
  const taken = room.participants.filter((p) => p.selected_club_code).length;
  const open = Math.max(0, room.team_count - taken);
  const waitingClub = people.filter((p) => !p.selected_club_code).length;
  const autoFill = room.team_count === 20;
  const editable = isHost && room.phase === "WAITING";
  const apply = ({ data }: { data: RoomState }) => {
    client.setQueryData(["room-state", room.id], data);
    void client.invalidateQueries({ queryKey: ["rooms"] });
  };
  const add = useMutation({ mutationFn: () => api.addBot(room.id), onSuccess: apply });
  const fill = useMutation({
    // One bot per request: the server validates every place (no club is ever taken twice).
    mutationFn: async () => {
      let last: { data: RoomState } | null = null;
      for (let index = 0; index < Math.max(0, open - waitingClub); index += 1) last = await api.addBot(room.id);
      return last;
    },
    onSuccess: (result) => { if (result) apply(result); },
  });
  const remove = useMutation({ mutationFn: (club: string) => api.removeBot(room.id, club), onSuccess: apply });
  const busy = add.isPending || fill.isPending || remove.isPending;
  const error = add.error ?? fill.error ?? remove.error;

  return <section className="bot-slots" aria-labelledby={`bot-slots-${room.id}`}>
    <p className="section-kicker" id={`bot-slots-${room.id}`}>VAGAS DO CAMPEONATO</p>
    <dl className="bot-slots__counts">
      <div><dt>Técnicos</dt><dd>{people.length}</dd></div>
      <div><dt>Bots</dt><dd>{bots.length}</dd></div>
      <div><dt>Vagas livres</dt><dd>{open}</dd></div>
      <div><dt>Clubes</dt><dd>{room.team_count}</dd></div>
    </dl>
    {autoFill
      ? <small className="bot-slots__hint">Liga de 20 clubes: os clubes sem técnico viram bots automaticamente ao iniciar.</small>
      : <small className="bot-slots__hint">{open === 0 ? "Todas as vagas estão preenchidas." : `Faltam ${open} clube(s). ${waitingClub ? `${waitingClub} técnico(s) ainda escolhendo clube. ` : ""}Complete com bots ou aguarde a galera.`}</small>}
    {bots.length > 0 && <ul className="bot-slots__list">{bots.map((bot) => {
      const club = bot.selected_club_code ? byCode.get(bot.selected_club_code) : undefined;
      return <li key={bot.user_id}>{club && <ClubCrest club={club} size="sm" />}<span><b>{club?.name ?? bot.selected_club_code}</b><small>Treinador virtual</small></span>
        {editable && <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => remove.mutate(bot.selected_club_code!)} aria-label={`Remover bot do ${club?.name ?? bot.selected_club_code}`}>Remover</button>}</li>;
    })}</ul>}
    {editable && !autoFill && open > 0 && <div className="bot-slots__actions">
      <button type="button" className="button-secondary" disabled={busy || open - waitingClub <= 0} onClick={() => add.mutate()}>{add.isPending ? "Adicionando…" : "+ Adicionar bot"}</button>
      <button type="button" className="button-primary" disabled={busy || open - waitingClub <= 0} onClick={() => fill.mutate()}>{fill.isPending ? "Completando…" : `Completar com bots (${Math.max(0, open - waitingClub)})`}</button>
    </div>}
    {error && <p className="feedback feedback--error" role="alert">{error.message}</p>}
  </section>;
}
