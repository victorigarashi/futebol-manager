import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type PackCard, type PackView } from "../../lib/api";
import { PlayerPhoto } from "../../components/PlayerPhoto";
import "./pack.css";

const POS: Record<string, string> = { GK: "GOL", DF: "DEF", MF: "MEI", ST: "ATA" };
const TIER: Record<PackCard["tier"], string> = { OURO: "Ouro", PRATA: "Prata", BRONZE: "Bronze" };
const ATTRS: [string, string][] = [["pace", "VEL"], ["shooting", "FIN"], ["passing", "PAS"], ["dribbling", "DRI"], ["defending", "DEF"], ["physical", "FÍS"]];
const errorText = (error: unknown) => (error instanceof ApiError || error instanceof Error ? error.message : "Não foi possível concluir a ação.");

/** Pack & Play: open free packs, then build the squad with the cards you got. */
export function PackPage({ roomId, isHost }: { roomId: string; isHost: boolean }) {
  const client = useQueryClient();
  const view = useQuery({ queryKey: ["pack", roomId], queryFn: () => api.pack(roomId).then((r) => r.data), refetchInterval: 4000 });
  const set = (data: PackView) => client.setQueryData(["pack", roomId], data);
  const open = useMutation({ mutationFn: () => api.packOpen(roomId).then((r) => r.data), onSuccess: set });
  const data = view.data;
  if (!data) return <section className="pack-page"><p className="panel-loading" role="status">{view.error ? errorText(view.error) : "Preparando os pacotes…"}</p></section>;
  const countdown = data.deadline ? Math.max(0, Math.round(data.deadline - data.server_now)) : null;
  return <section className="pack-page">
    <header className="pack-head">
      <div><p className="section-kicker">PACK & PLAY</p><h1>{data.opened < data.packs_total ? "Abra seus pacotes" : data.confirmed ? "Time confirmado" : "Monte o seu time"}</h1>
        <p className="muted">Pacotes gratuitos desta sala · catálogo {data.catalog === "WORLD" ? "Mundial" : "Brasileirão"} · distribuição {data.luck === "LUCK" ? "sorte pura" : "equilibrada"}. As cartas ficam só nesta competição.</p></div>
      {countdown !== null && <div className="pack-timer"><span>Prazo</span><strong>{Math.floor(countdown / 60)}:{String(countdown % 60).padStart(2, "0")}</strong><small>Sem time no prazo: montagem automática</small></div>}
    </header>
    {(open.error) && <p className="feedback feedback--error" role="alert">{errorText(open.error)}</p>}
    {data.opened < data.packs_total || data.packs.length === 0
      ? <PackOpening data={data} opening={open.isPending} onOpen={() => open.mutate()} />
      : data.confirmed ? <Waiting data={data} roomId={roomId} isHost={isHost} /> : <SquadBuilder roomId={roomId} data={data} onChange={set} />}
  </section>;
}

function CardFace({ card, size = "md", selected, onClick, badge }: { card: PackCard; size?: "sm" | "md" | "lg"; selected?: boolean; onClick?: () => void; badge?: string }) {
  const body = <>
    <span className="pack-card__ovr">{card.overall}</span>
    <span className="pack-card__pos">{POS[card.position] ?? card.position}</span>
    {size !== "sm" && <PlayerPhoto name={card.name} photoUrl={card.photo_url ?? null} size={size === "lg" ? "lg" : "md"} />}
    <strong className="pack-card__name">{card.name}</strong>
    <small className="pack-card__meta">{TIER[card.tier]} · {card.club_code}</small>
    {badge && <em className="pack-card__badge">{badge}</em>}
  </>;
  const className = `pack-card pack-card--${card.tier.toLowerCase()} pack-card--${size} ${selected ? "is-selected" : ""}`;
  return onClick ? <button type="button" className={className} onClick={onClick} aria-pressed={selected}>{body}</button> : <div className={className}>{body}</div>;
}

/** The newest pack is revealed card by card (the best one last); can be skipped. */
function PackOpening({ data, opening, onOpen }: { data: PackView; opening: boolean; onOpen: () => void }) {
  const last = data.packs[data.packs.length - 1] ?? [];
  const [shown, setShown] = useState(0);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => { setShown(reduced ? last.length : 0); }, [data.opened]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (shown >= last.length) return;
    const timer = window.setTimeout(() => setShown((n) => n + 1), shown === last.length - 1 ? 900 : 420);
    return () => window.clearTimeout(timer);
  }, [shown, last.length]);
  const best = last.length ? last[last.length - 1] : null;
  const remaining = data.packs_total - data.opened;
  return <div className="pack-opening">
    {data.opened > 0 && <div className="pack-reveal" aria-live="polite">
      <div className="pack-reveal__row">{last.map((card, index) => <div key={card.id} className={`pack-slot ${index < shown ? "is-revealed" : ""} ${best && card.id === best.id ? "is-best" : ""}`}>
        {index < shown ? <CardFace card={card} size={best && card.id === best.id ? "lg" : "md"} badge={best && card.id === best.id ? "Destaque" : undefined} /> : <div className="pack-card pack-card--back" aria-hidden="true">BM</div>}
      </div>)}</div>
      {shown < last.length && <button type="button" className="text-action" onClick={() => setShown(last.length)}>Pular animação</button>}
    </div>}
    <div className="pack-stack">
      <div className="pack-stack__packs" aria-hidden="true">{Array.from({ length: remaining }, (_, i) => <i key={i} style={{ transform: `translate(${i * 6}px, ${-i * 6}px)` }} />)}</div>
      {remaining > 0
        ? <button type="button" className="button-primary pack-stack__open" disabled={opening || shown < last.length} onClick={onOpen}>{opening ? "Abrindo…" : `Abrir pacote ${data.opened + 1} de ${data.packs_total}`}</button>
        : <p className="muted">Todos os pacotes abertos.</p>}
    </div>
    {data.opened > 1 && <details className="pack-collection-preview"><summary>Cartas já tiradas ({data.packs.slice(0, -1).flat().length})</summary>
      <div className="pack-grid">{data.packs.slice(0, -1).flat().map((card) => <CardFace key={card.id} card={card} size="sm" />)}</div></details>}
  </div>;
}

function SquadBuilder({ roomId, data, onChange }: { roomId: string; data: PackView; onChange: (d: PackView) => void }) {
  const cards = useMemo(() => data.packs.flat(), [data.packs]);
  const byId = useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards]);
  const formation = data.formations.find((f) => f.code === data.formation) ?? null;
  const [slot, setSlot] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [compare, setCompare] = useState<string[]>([]);
  const call = useMutation({ mutationFn: (fn: () => Promise<{ data: PackView }>) => fn().then((r) => r.data), onSuccess: onChange });
  const used = new Set([...Object.values(data.slots).filter(Boolean) as string[], ...data.bench]);
  const slotPosition = formation?.slots.find((s) => s.id === slot)?.position;
  const visible = cards.filter((c) => !filter || c.position === filter).sort((a, b) => b.overall - a.overall);
  const pick = (card: PackCard) => {
    if (slot) { call.mutate(() => api.packPlace(roomId, slot, card.id)); setSlot(null); return; }
    setCompare((current) => current.includes(card.id) ? current.filter((id) => id !== card.id) : [...current.slice(-1), card.id]);
  };
  const toggleBench = (card: PackCard) => {
    const next = data.bench.includes(card.id) ? data.bench.filter((id) => id !== card.id) : [...data.bench, card.id].slice(0, data.bench_size);
    call.mutate(() => api.packBench(roomId, next));
  };
  return <div className="pack-builder">
    <section className="pack-pitch-panel">
      <label className="pack-formation">Formação<select value={data.formation ?? ""} onChange={(e) => call.mutate(() => api.packFormation(roomId, e.target.value))}>
        <option value="" disabled>Escolha…</option>{data.formations.map((f) => <option key={f.code} value={f.code}>{f.code}</option>)}</select></label>
      {formation ? <div className="pack-pitch" role="group" aria-label="Titulares">
        {formation.slots.map((s) => {
          const card = data.slots[s.id] ? byId.get(data.slots[s.id]!) : undefined;
          return <button key={s.id} type="button" className={`pack-pitch__slot ${slot === s.id ? "is-active" : ""} ${card ? "is-filled" : ""}`} style={{ left: `${s.x}%`, top: `${s.y}%` }}
            onClick={() => setSlot(slot === s.id ? null : s.id)} aria-label={`${POS[s.position]}: ${card ? card.name : "vazio"}`}>
            <b>{card ? card.overall : "+"}</b><span>{card ? card.name.split(" ").slice(-1)[0] : POS[s.position]}</span>
            {card && card.position !== s.position && !card.secondary_positions.includes(s.position) && <i title="Fora de posição">!</i>}
          </button>;
        })}
      </div> : <p className="muted">Escolha a formação para posicionar as cartas.</p>}
      <div className="pack-bench"><h3>Reservas ({data.bench.length}/{data.bench_size})</h3>
        <div className="pack-grid">{data.bench.map((id) => byId.get(id) && <CardFace key={id} card={byId.get(id)!} size="sm" onClick={() => toggleBench(byId.get(id)!)} />)}</div></div>
      {data.problems.length > 0 && <ul className="pack-problems">{data.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <button type="button" className="button-primary" disabled={call.isPending || data.problems.length > 0} onClick={() => call.mutate(() => api.packConfirm(roomId))}>Confirmar time</button>
      {call.error && <p className="feedback feedback--error" role="alert">{errorText(call.error)}</p>}
    </section>
    <section className="pack-collection">
      <header><h2>Sua coleção</h2><p className="muted">{slot ? `Escolha a carta para ${POS[slotPosition ?? ""] ?? "a posição"}.` : "Toque numa posição do campo e depois numa carta. Sem posição selecionada, as cartas entram na comparação."}</p>
        <div className="segmented" role="group" aria-label="Filtrar posição">{["", "GK", "DF", "MF", "ST"].map((p) => <button key={p} type="button" className={filter === p ? "is-active" : ""} aria-pressed={filter === p} onClick={() => setFilter(p)}>{p ? POS[p] : "Todas"}</button>)}</div></header>
      <div className="pack-grid">{visible.map((card) => <div key={card.id} className={`pack-collection__item ${used.has(card.id) ? "is-used" : ""}`}>
        <CardFace card={card} size="sm" selected={compare.includes(card.id)} onClick={() => pick(card)} badge={Object.values(data.slots).includes(card.id) ? "Titular" : data.bench.includes(card.id) ? "Reserva" : undefined} />
        {!Object.values(data.slots).includes(card.id) && <button type="button" className="text-action" onClick={() => toggleBench(card)}>{data.bench.includes(card.id) ? "Tirar do banco" : "Para o banco"}</button>}
      </div>)}</div>
      {compare.length === 2 && <Compare a={byId.get(compare[0])!} b={byId.get(compare[1])!} onClose={() => setCompare([])} />}
    </section>
  </div>;
}

function Compare({ a, b, onClose }: { a: PackCard; b: PackCard; onClose: () => void }) {
  const has = ATTRS.some(([k]) => k in a.attributes || k in b.attributes);
  return <aside className="pack-compare" aria-label="Comparação">
    <header><strong>{a.name}</strong><span>×</span><strong>{b.name}</strong><button type="button" className="text-action" onClick={onClose}>Fechar</button></header>
    <dl><div><dt>Overall</dt><dd className={a.overall >= b.overall ? "lead" : ""}>{a.overall}</dd><dd className={b.overall >= a.overall ? "lead" : ""}>{b.overall}</dd></div>
      {has ? ATTRS.map(([k, label]) => <div key={k}><dt>{label}</dt><dd className={(a.attributes[k] ?? 0) >= (b.attributes[k] ?? 0) ? "lead" : ""}>{a.attributes[k] ?? "–"}</dd><dd className={(b.attributes[k] ?? 0) >= (a.attributes[k] ?? 0) ? "lead" : ""}>{b.attributes[k] ?? "–"}</dd></div>)
        : <p className="muted">Sem atributos detalhados no catálogo: compare pelo overall e posição.</p>}</dl>
  </aside>;
}

function Waiting({ data, roomId, isHost }: { data: PackView; roomId: string; isHost: boolean }) {
  const force = useMutation({ mutationFn: () => api.packComplete(roomId) });
  return <div className="pack-waiting">
    <p>Seu time está confirmado. O torneio começa quando todos confirmarem ou o prazo acabar.</p>
    <ul>{data.managers.map((m) => <li key={m.club_code} className={m.confirmed ? "is-ready" : ""}><b>{m.club_code}</b><span>{m.bot ? "Bot" : "Técnico"} · {m.confirmed ? "Pronto" : `Abriu ${m.opened} pacotes`}</span></li>)}</ul>
    {isHost && <button type="button" className="button-secondary" disabled={force.isPending} onClick={() => force.mutate()}>Encerrar fase de pacotes agora</button>}
    {force.error && <p className="feedback feedback--error" role="alert">{errorText(force.error)}</p>}
  </div>;
}
