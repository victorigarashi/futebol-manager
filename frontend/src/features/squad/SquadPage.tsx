import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Formation, type MarketPlayer, type Squad } from "../../lib/api";

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const positionNames: Record<string, string> = { GK: "Goleiro", DF: "Defensor", MF: "Meio-campo", ST: "Atacante" };

function defaultAssignments(formation: Formation, players: MarketPlayer[]): Record<string, string> {
  const unused = [...players];
  return Object.fromEntries(formation.slots.map((slot) => {
    const index = unused.findIndex((player) => player.position === slot.position);
    const player = unused.splice(index >= 0 ? index : 0, 1)[0];
    return [slot.id, player?.id ?? ""];
  }));
}

function Pitch({ formation, players, assignments }: { formation: Formation; players: MarketPlayer[]; assignments: Record<string, string> }) {
  const byId = useMemo(() => new Map(players.map((player) => [player.id, player])), [players]);
  return <div className="squad-pitch" role="img" aria-label={`Campo tático com formação ${formation.code}. Use a lista de titulares abaixo para trocar jogadores.`}>
    {formation.slots.map((slot, index) => <div className="squad-slot" key={slot.id} style={{ left: `${slot.x}%`, top: `${slot.y}%` }}><span>{index + 1} · {slot.position}</span><strong>{byId.get(assignments[slot.id])?.name ?? "Vaga em aberto"}</strong></div>)}
  </div>;
}

export function SquadPage({ roomId, isHost, onStartSeason, inSeason = false }: { roomId: string; isHost: boolean; onStartSeason: () => void; inSeason?: boolean }) {
  const client = useQueryClient();
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((result) => result.data) });
  const [formationCode, setFormationCode] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Record<string, string> | null>(null);
  const [strategy, setStrategy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const data = squad.data;
  const formation = data?.formations.find((item) => item.code === (formationCode ?? data.lineup?.formation_code ?? data.formations[0]?.code));
  const activeAssignments = assignments ?? (data && formation ? (data.lineup?.formation_code === formation.code ? data.lineup.assignments : defaultAssignments(formation, data.players)) : {});
  const dirty = assignments !== null || formationCode !== null;
  const save = useMutation({ mutationFn: () => api.saveLineup(roomId, { formation_code: formation!.code, assignments: activeAssignments }), onSuccess: ({ data: lineup }) => {
    client.setQueryData<Squad>(["squad", roomId], (previous) => previous ? { ...previous, lineup } : previous);
    setAssignments(null); setFormationCode(null); setNotice("Escalação salva e validada pelo servidor."); void client.invalidateQueries({ queryKey: ["squad", roomId] });
  } });
  const saveTactic = useMutation({ mutationFn: (value: string) => api.saveStrategy(roomId, value), onSuccess: ({ data: result }) => {
    client.setQueryData<Squad>(["squad", roomId], (previous) => previous ? { ...previous, strategy: result.strategy } : previous);
    setStrategy(null); setNotice("Estratégia salva."); void client.invalidateQueries({ queryKey: ["squad", roomId] });
  }, onError: () => setStrategy(null) });
  if (squad.isLoading) return <section className="squad-page"><p className="muted" role="status">Montando o elenco…</p></section>;
  if (!data || !formation) return <section className="squad-page"><p className="feedback feedback--error" role="alert">{squad.error?.message ?? "Não foi possível carregar o elenco."}</p><button className="button-secondary" onClick={() => void squad.refetch()}>Tentar novamente</button></section>;
  const chooseFormation = (code: string) => { setFormationCode(code); const next = data.formations.find((item) => item.code === code); setAssignments(next ? defaultAssignments(next, data.players) : {}); setNotice(""); };
  const assign = (slot: string, player: string) => {
    const previousSlot = Object.entries(activeAssignments).find(([key, value]) => key !== slot && value === player)?.[0];
    setAssignments({ ...activeAssignments, [slot]: player, ...(previousSlot ? { [previousSlot]: activeAssignments[slot] ?? "" } : {}) });
    setNotice("");
  };
  const selectedStrategy = data.strategies.find((item) => item.code === (strategy ?? data.strategy));
  const assigned = new Set(Object.values(activeAssignments));
  const valid = formation.slots.every((slot) => data.players.some((player) => player.id === activeAssignments[slot.id])) && assigned.size === formation.slots.length;
  const bench = data.players.filter((player) => !assigned.has(player.id));
  return <section className="squad-page"><header className="squad-header"><div><p className="section-kicker">GESTÃO ESPORTIVA / {data.club_code}</p><h1>Seu time, <em>sua prancheta.</em></h1><p>{formation.slots.length} titulares e {data.players.length - formation.slots.length} reservas. Troque atletas na lista sem precisar arrastar.</p></div><dl><div><dt>Saldo do clube</dt><dd>{money.format(data.budget_cents / 100)}</dd></div><div><dt>Elenco</dt><dd>{data.players.length} atletas</dd></div></dl></header>
    {notice && <p className="feedback" role="status">{notice}</p>}{dirty && <p className="feedback" role="status">Prancheta alterada. Salve para validar as posições e o overall efetivo.</p>}
    <div className="squad-layout"><section className="squad-board"><div className="squad-board__toolbar"><label>Formação<select value={formation.code} disabled={save.isPending} onChange={(event) => chooseFormation(event.target.value)}>{data.formations.map((item) => <option key={item.code}>{item.code}</option>)}</select></label><button className="button-primary" type="button" disabled={save.isPending || !valid} onClick={() => save.mutate()}>{save.isPending ? "Salvando…" : "Salvar escalação"}</button></div>
      <Pitch formation={formation} players={data.players} assignments={activeAssignments} />
      <section className="squad-assignment-list"><h2>Titulares</h2><p>Selecionar outro titular troca os dois atletas de vaga. Improvisações serão avaliadas pelo servidor.</p>{formation.slots.map((slot, index) => {
        const player = data.players.find((item) => item.id === activeAssignments[slot.id]);
        const evaluation = !dirty ? data.lineup?.evaluation.find((row) => row.slot_id === slot.id && row.player_id === player?.id) : undefined;
        return <div className="squad-assignment-row" key={slot.id}><label htmlFor={`slot-${slot.id}`}><span>{index + 1}. {positionNames[slot.position] ?? slot.position}</span><select id={`slot-${slot.id}`} disabled={save.isPending} value={activeAssignments[slot.id] ?? ""} onChange={(event) => assign(slot.id, event.target.value)}><option value="">Escolher atleta</option>{data.players.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.position} · OVR {item.overall}</option>)}</select></label><span className={`squad-effective ${evaluation?.improvised ? "is-improvised" : ""}`}>{evaluation ? `OVR efetivo ${evaluation.effective_overall}${evaluation.improvised ? " · Improvisado" : " · Posição válida"}` : "Salve para avaliar a posição"}</span></div>;
      })}</section>
      <section className="squad-tactics"><label>Estratégia<select value={strategy ?? data.strategy} disabled={saveTactic.isPending} onChange={(event) => { setStrategy(event.target.value); saveTactic.mutate(event.target.value); }}>{data.strategies.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label><p>{selectedStrategy?.effect}</p>{saveTactic.isPending && <p role="status">Salvando estratégia…</p>}{saveTactic.error && <p className="feedback feedback--error" role="alert">{saveTactic.error.message}</p>}</section>
      {save.error && <p className="feedback feedback--error" role="alert">{save.error.message}</p>}{!valid && <p className="feedback feedback--error" role="alert">Preencha cada vaga com um atleta diferente do seu elenco antes de salvar.</p>}
    </section><aside className="squad-roster"><section className="squad-bench"><h2>Banco de reservas <small>{bench.length}</small></h2>{bench.map((player) => <article key={player.id}><b>{player.position}</b><div><strong>{player.name}</strong><span>Reserva · Potencial {player.potential}</span></div><em>{player.overall}</em></article>)}</section><h2>Elenco completo</h2>{data.players.map((player) => <article key={player.id}><b>{player.position}</b><div><strong>{player.name}</strong><span>{assigned.has(player.id) ? "Titular" : "Reserva"} · Potencial {player.potential}</span>{player.overall_delta !== undefined && player.overall_delta !== 0 && <small>Evolução: {player.overall_delta > 0 ? "+" : ""}{player.overall_delta} OVR</small>}</div><em>{player.overall}</em></article>)}
    {!inSeason && (isHost ? <button className="button-primary squad-start" type="button" disabled={save.isPending || saveTactic.isPending || dirty || !valid} onClick={onStartSeason}>Abrir rodada 1 →</button> : <p className="muted" role="status">Aguardando o anfitrião abrir a rodada.</p>)}</aside></div>
  </section>;
}
