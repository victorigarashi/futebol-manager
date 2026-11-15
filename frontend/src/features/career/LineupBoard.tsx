import { useMemo, useState, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Formation, type Squad, type SquadPlayer } from "../../lib/api";
import { formatMoney } from "../../lib/format";
import { ATTRIBUTE_LABEL, POSITION_LABEL, POSITION_NAME } from "./labels";
import { autoPick, carryOver, fit, teamStrength } from "./lineup";
import { PlayerPhoto } from "../../components/PlayerPhoto";

type Pick = { kind: "slot"; id: string } | { kind: "player"; id: string } | null;

/**
 * Squad screen: formation on a pitch, click-to-swap (drag-and-drop also works),
 * fit-by-position, team strength and attribute comparison. The server validates on save.
 */
export function LineupBoard({ roomId, locked, onSaved }: { roomId: string; locked?: string | null; onSaved?: (readyCancelled: boolean) => void }) {
  const client = useQueryClient();
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const [draft, setDraft] = useState<{ formation: string; assignments: Record<string, string> } | null>(null);
  const [pick, setPick] = useState<Pick>(null);
  const [inspect, setInspect] = useState<string | null>(null);
  const [compare, setCompare] = useState<string | null>(null);
  const [notice, setNoticeState] = useState<{ text: string; error: boolean } | null>(null);
  const setNotice = (text: string | null, error = false) => setNoticeState(text ? { text, error } : null);
  const data = squad.data;

  const saved = useMemo(() => {
    if (!data) return null;
    const formation = data.formations.find((f) => f.code === data.lineup?.formation_code) ?? data.formations[0];
    const assignments = data.lineup?.formation_code === formation.code ? data.lineup.assignments : autoPick(formation, data.players);
    return { formation: formation.code, assignments };
  }, [data]);
  const current = draft ?? saved;
  const formation: Formation | undefined = data?.formations.find((f) => f.code === current?.formation);
  const dirty = draft !== null;

  const save = useMutation({
    mutationFn: () => api.saveLineup(roomId, { formation_code: current!.formation, assignments: current!.assignments }),
    onSuccess: ({ data: lineup }) => {
      client.setQueryData<Squad>(["squad", roomId], (previous) => previous ? { ...previous, lineup } : previous);
      setDraft(null);
      setNotice(lineup.ready_cancelled ? "Escalação salva. Sua confirmação de prontidão foi cancelada — confirme de novo no pré-jogo." : "Escalação salva e validada pelo servidor.");
      onSaved?.(Boolean(lineup.ready_cancelled));
      void client.invalidateQueries({ queryKey: ["preview", roomId] });
      void client.invalidateQueries({ queryKey: ["season", roomId] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Não foi possível salvar.", true),
  });

  if (squad.isPending) return <div className="panel-loading" role="status">Abrindo o vestiário…</div>;
  if (!data || !formation || !current) return <div className="panel-error" role="alert"><p>{squad.error?.message ?? "Elenco indisponível."}</p><button className="btn btn--ghost" type="button" onClick={() => void squad.refetch()}>Tentar novamente</button></div>;

  const byId = new Map(data.players.map((p) => [p.id, p]));
  const assigned = new Set(Object.values(current.assignments));
  const bench = data.players.filter((p) => !assigned.has(p.id)).sort((a, b) => "GKDFMFST".indexOf(a.position) - "GKDFMFST".indexOf(b.position) || b.overall - a.overall);
  const strength = teamStrength(formation, current.assignments, data.players);
  const valid = formation.slots.every((slot) => byId.has(current.assignments[slot.id])) && assigned.size === formation.slots.length;
  const disabled = Boolean(locked) || save.isPending;

  const update = (assignments: Record<string, string>, formationCode = current.formation) => { setDraft({ formation: formationCode, assignments }); setNotice(null); };
  const swapSlots = (a: string, b: string) => update({ ...current.assignments, [a]: current.assignments[b], [b]: current.assignments[a] });
  const putPlayer = (slot: string, playerId: string) => {
    const from = Object.entries(current.assignments).find(([, id]) => id === playerId)?.[0];
    if (from) swapSlots(slot, from); else update({ ...current.assignments, [slot]: playerId });
  };
  const choose = (next: Exclude<Pick, null>) => {
    if (disabled) return;
    const playerOf = (p: Exclude<Pick, null>) => p.kind === "slot" ? current.assignments[p.id] : p.id;
    setInspect(playerOf(next));
    if (!pick) { setPick(next); return; }
    if (pick.kind === next.kind && pick.id === next.id) { setPick(null); return; }
    if (pick.kind === "slot" && next.kind === "slot") swapSlots(pick.id, next.id);
    else if (pick.kind === "slot" && next.kind === "player") putPlayer(pick.id, next.id);
    else if (pick.kind === "player" && next.kind === "slot") putPlayer(next.id, pick.id);
    else { setPick(next); return; }
    setPick(null);
  };
  const onDrop = (slot: string) => (event: DragEvent) => {
    event.preventDefault();
    const raw = event.dataTransfer.getData("text/plain");
    if (disabled || !raw) return;
    const [kind, id] = raw.split(":");
    if (kind === "slot") swapSlots(id, slot); else putPlayer(slot, id);
    setPick(null);
  };
  const inspected = inspect ? byId.get(inspect) : undefined;
  const compared = compare ? byId.get(compare) : undefined;

  return <section className="lineup" aria-label="Escalação">
    <header className="lineup__bar">
      <label className="field"><span>Formação</span><select value={current.formation} disabled={disabled} onChange={(event) => {
        const next = data.formations.find((f) => f.code === event.target.value)!;
        update(carryOver(next, current.assignments, formation, data.players), next.code); setPick(null);
      }}>{data.formations.map((f) => <option key={f.code} value={f.code}>{f.code}</option>)}</select></label>
      <div className="strength" aria-label="Força da equipe"><Meter label="Geral" value={strength.overall} big /><Meter label="Defesa" value={strength.defense} /><Meter label="Meio" value={strength.midfield} /><Meter label="Ataque" value={strength.attack} /></div>
      <div className="lineup__actions">
        <button type="button" className="btn btn--ghost" disabled={disabled} onClick={() => update(autoPick(formation, data.players))} title="Escolhe os melhores por posição">Escalação automática</button>
        <button type="button" className="btn btn--ghost" disabled={!dirty || disabled} onClick={() => { setDraft(null); setPick(null); setNotice("Escolhas restauradas para a última escalação salva."); }}>Restaurar</button>
        <button type="button" className="btn btn--primary" disabled={!dirty || !valid || disabled} onClick={() => save.mutate()}>{save.isPending ? "Validando…" : "Salvar escalação"}</button>
      </div>
    </header>
    {locked && <p className="cm-toast cm-toast--warn" role="status">{locked}</p>}
    {notice && <p className={`cm-toast ${notice.error ? "cm-toast--error" : ""}`} role={notice.error ? "alert" : "status"}>{notice.text}</p>}
    {dirty && !notice && <p className="cm-toast cm-toast--info" role="status">Prancheta alterada — salve para o servidor validar.</p>}
    {strength.improvised > 0 && <p className="cm-toast cm-toast--warn" role="status">{strength.improvised} jogador(es) fora de posição: rendem menos em campo.</p>}

    <div className="lineup__grid">
      <div className="formation-pitch" role="group" aria-label={`Campo com a formação ${formation.code}. Selecione um jogador e depois outra posição ou um reserva para trocar.`}>
        <div className="formation-pitch__lines" aria-hidden="true"><i className="box box--top" /><i className="box box--bottom" /><i className="circle" /><i className="half" /></div>
        {formation.slots.map((slot) => {
          const player = byId.get(current.assignments[slot.id]);
          const result = player ? fit(player, slot.position) : null;
          const active = pick?.kind === "slot" && pick.id === slot.id;
          return <button type="button" key={slot.id} className={`slot slot--${result?.kind ?? "empty"} ${active ? "is-picked" : ""}`} style={{ left: `${slot.x}%`, top: `${slot.y}%` }}
            draggable={!disabled && Boolean(player)} onDragStart={(event) => event.dataTransfer.setData("text/plain", `slot:${slot.id}`)} onDragOver={(event) => event.preventDefault()} onDrop={onDrop(slot.id)}
            onClick={() => choose({ kind: "slot", id: slot.id })} aria-pressed={active} aria-label={`${POSITION_NAME[slot.position]}: ${player ? `${player.name}, overall efetivo ${result?.rating}${result?.kind === "improvised" ? ", improvisado" : ""}` : "vaga em aberto"}`}>
            <span className="slot__shirt">{result?.rating ?? "—"}</span>
            <span className="slot__name">{player?.name.split(" ").slice(-1)[0] ?? "Vaga"}</span>
            <span className="slot__pos">{POSITION_LABEL[slot.position]}{result?.kind === "improvised" ? " ⚠" : ""}</span>
          </button>;
        })}
      </div>

      <aside className="bench-panel">
        <h3>Reservas <small>{bench.length}</small></h3>
        <p className="hint">{pick ? "Agora escolha com quem trocar." : "Toque em um titular e depois em um reserva (ou arraste)."}</p>
        <ul className="bench-list">{bench.map((player) => {
          const active = pick?.kind === "player" && pick.id === player.id;
          const target = pick?.kind === "slot" ? formation.slots.find((s) => s.id === pick.id) : undefined;
          const targetFit = target ? fit(player, target.position) : null;
          return <li key={player.id}><button type="button" className={`bench-item ${active ? "is-picked" : ""}`} draggable={!disabled} onDragStart={(event) => event.dataTransfer.setData("text/plain", `player:${player.id}`)} onClick={() => choose({ kind: "player", id: player.id })} aria-pressed={active}>
            <PlayerPhoto name={player.name} photoUrl={player.photo_url} size="xs" /><span className="pos">{POSITION_LABEL[player.position]}</span><b>{player.name}</b><span className="ovr">{player.overall}</span>
            {targetFit && <small className={`fit fit--${targetFit.kind}`}>{targetFit.kind === "natural" ? "Posição ideal" : targetFit.kind === "secondary" ? "Posição secundária" : `Improvisado (${targetFit.rating})`}</small>}
          </button></li>;
        })}</ul>
      </aside>

      <aside className="player-sheet" aria-live="polite">
        {inspected ? <PlayerSheet player={inspected} other={compared} slotPosition={formation.slots.find((s) => current.assignments[s.id] === inspected.id)?.position} players={data.players} onCompare={setCompare} compareId={compare} /> : <div className="player-sheet__empty"><b>Ficha do atleta</b><p>Selecione um jogador para ver atributos, adequação à posição e comparar com outro atleta.</p></div>}
      </aside>
    </div>
  </section>;
}

function Meter({ label, value, big }: { label: string; value: number; big?: boolean }) {
  return <div className={`meter ${big ? "meter--big" : ""}`}><span>{label}</span><b>{value ? value.toFixed(big ? 1 : 0) : "—"}</b><i aria-hidden="true"><em style={{ width: `${Math.max(0, Math.min(100, (value - 40) * 2))}%` }} /></i></div>;
}

function PlayerSheet({ player, other, slotPosition, players, onCompare, compareId }: { player: SquadPlayer; other?: SquadPlayer; slotPosition?: string; players: SquadPlayer[]; onCompare: (id: string | null) => void; compareId: string | null }) {
  const attributes = player.match_attributes ?? player.attributes ?? {};
  const keys = player.position === "GK" ? ["keeping", "physical", "passing", "pace"] : ["pace", "passing", "shooting", "dribbling", "defending", "physical"];
  const otherAttributes = other ? other.match_attributes ?? other.attributes ?? {} : {};
  const positionFit = slotPosition ? fit(player, slotPosition) : null;
  return <>
    <header><PlayerPhoto name={player.name} photoUrl={player.photo_url} size="md" /><span className="pos">{POSITION_LABEL[player.position]}</span><h3>{player.name}</h3><b className="ovr ovr--big">{player.overall}</b></header>
    <dl className="mini-stats"><div><dt>Idade</dt><dd>{player.age ?? "—"}</dd></div><div><dt>Potencial</dt><dd>{player.potential}</dd></div><div><dt>Valor</dt><dd>{formatMoney(player.internal_market_value_cents ?? player.market_value_cents)}</dd></div>{player.overall_delta ? <div><dt>Evolução</dt><dd>{player.overall_delta > 0 ? "+" : ""}{player.overall_delta}</dd></div> : null}</dl>
    {positionFit && <p className={`fit fit--${positionFit.kind}`}>{positionFit.kind === "natural" ? "Jogando na posição ideal" : positionFit.kind === "secondary" ? "Posição secundária, sem perda" : `Improvisado: rende como ${positionFit.rating}`}</p>}
    <label className="field field--inline"><span>Comparar com</span><select value={compareId ?? ""} onChange={(event) => onCompare(event.target.value || null)}><option value="">—</option>{players.filter((p) => p.id !== player.id).map((p) => <option key={p.id} value={p.id}>{POSITION_LABEL[p.position]} · {p.name} ({p.overall})</option>)}</select></label>
    <ul className="attr-list">{keys.map((key) => {
      const value = attributes[key] ?? 0;
      const rival = otherAttributes[key];
      return <li key={key}><span>{ATTRIBUTE_LABEL[key]}</span><i aria-hidden="true"><em style={{ width: `${value}%` }} />{rival !== undefined && <u style={{ left: `${rival}%` }} />}</i><b>{value}</b>{rival !== undefined && <small className={rival > value ? "down" : rival < value ? "up" : ""}>{rival}</small>}</li>;
    })}</ul>
    {player.attributes_derived && <p className="hint">O catálogo não traz atributos detalhados deste atleta: os valores acima são o perfil que o motor deriva do overall e da posição.</p>}
  </>;
}
