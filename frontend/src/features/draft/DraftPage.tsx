import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, type DraftCard, type DraftPick, type DraftView, type FormationSlot } from "../../lib/api";
import { Modal } from "../../components/Modal";
import { PlayerPhoto } from "../../components/PlayerPhoto";
import "./draft.css";

const POSITION = { GK: "GOL", DF: "DEF", MF: "MEI", ST: "ATA" } as const;
const ATTRS: [string, string][] = [["pace", "VEL"], ["shooting", "FIN"], ["passing", "PAS"], ["dribbling", "DRI"], ["defending", "DEF"], ["physical", "FÍS"]];

const positionLabel = (position: string) => POSITION[position as keyof typeof POSITION] ?? position;
const errorText = (error: unknown) => (error instanceof ApiError || error instanceof Error ? error.message : "Não foi possível concluir a ação.");

function useCountdown(deadline: number | null, serverNow: number | undefined) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (!deadline || serverNow === undefined) return null;
  const skew = serverNow - Date.now() / 1000;
  return Math.max(0, Math.round(deadline - (now + skew)));
}

/** A card of the draft: catalog data only, nothing invented. */
export function DraftCardView({ card, onPick, busy }: { card: DraftCard; onPick?: () => void; busy?: boolean }) {
  const tier = card.overall >= 84 ? "elite" : card.overall >= 77 ? "gold" : card.overall >= 70 ? "silver" : "bronze";
  const hasAttrs = ATTRS.some(([key]) => key in (card.attributes ?? {}));
  const club = card.club_name ?? card.club_code;
  const body = <>
    <header className="draft-card__head"><strong className="draft-card__overall">{card.overall}</strong><span className="draft-card__pos">{positionLabel(card.position)}{card.secondary_positions?.length ? <small> / {card.secondary_positions.map(positionLabel).join(" ")}</small> : null}</span></header>
    <div className="draft-card__photo"><PlayerPhoto name={card.name} photoUrl={card.photo_url ?? null} size="lg" /></div>
    <h3 className="draft-card__name">{card.name}</h3>
    <p className="draft-card__meta">{club}{card.nationality ? ` · ${card.nationality}` : ""}{card.age ? ` · ${card.age} anos` : ""}</p>
    {hasAttrs
      ? <dl className="draft-card__attrs">{ATTRS.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{card.attributes[key] ?? "–"}</dd></div>)}</dl>
      : <p className="draft-card__estimated">Atributos detalhados não disponíveis no catálogo. O jogo usa um perfil estimado pela posição.</p>}
    {card.source.includes("EDITORIAL") && <p className="draft-card__notice">Overall editorial próprio. Não é rating oficial da EA.</p>}
  </>;
  if (!onPick) return <article className={`draft-card draft-card--${tier}`}>{body}</article>;
  return <button type="button" className={`draft-card draft-card--${tier} draft-card--pickable`} onClick={onPick} disabled={busy} aria-label={`Escolher ${card.name}, overall ${card.overall}`}>{body}</button>;
}

function SlotChip({ slot, pick, onOpen, disabled }: { slot: { id: string; position: string }; pick: DraftPick | null; onOpen: () => void; disabled: boolean }) {
  if (pick) return <div className="draft-slot draft-slot--filled" title={pick.card.name}><b>{pick.card.overall}</b><span>{pick.card.name.split(" ").slice(-1)[0]}</span><small>{positionLabel(slot.position)}</small></div>;
  return <button type="button" className="draft-slot draft-slot--open" onClick={onOpen} disabled={disabled}><b>+</b><small>{positionLabel(slot.position)}</small></button>;
}

export function DraftPage({ roomId, isHost, clubCode }: { roomId: string; isHost: boolean; clubCode: string }) {
  const client = useQueryClient();
  const draft = useQuery({ queryKey: ["draft", roomId], queryFn: () => api.draft(roomId).then((r) => r.data), refetchInterval: 4000 });
  const [offer, setOffer] = useState<{ slot: string; cards: DraftCard[]; note: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = (data?: DraftView) => {
    if (data) client.setQueryData(["draft", roomId], data);
    void client.invalidateQueries({ queryKey: ["draft", roomId] });
    void client.invalidateQueries({ queryKey: ["room-state", roomId] });
  };
  const formation = useMutation({ mutationFn: (code: string) => api.draftFormation(roomId, code), onSuccess: ({ data }) => refresh(data), onError: (e) => setError(errorText(e)) });
  const open = useMutation({ mutationFn: (slot: string) => api.draftOffer(roomId, slot), onSuccess: ({ data }) => { setError(null); setOffer({ slot: data.slot_id, cards: data.cards, note: data.note }); }, onError: (e) => setError(errorText(e)) });
  const pick = useMutation({ mutationFn: ({ slot, id }: { slot: string; id: string }) => api.draftPick(roomId, slot, id), onSuccess: ({ data }) => { setOffer(null); refresh(data); }, onError: (e) => setError(errorText(e)) });
  const finish = useMutation({ mutationFn: () => api.draftComplete(roomId), onSuccess: () => refresh(), onError: (e) => setError(errorText(e)) });
  const view = draft.data;
  const remaining = useCountdown(view?.deadline ?? null, view?.server_now);
  const slots: FormationSlot[] = useMemo(() => view?.formations.find((f) => f.code === view.formation)?.slots ?? [], [view]);

  if (draft.isLoading) return <section className="draft-page"><p className="muted">Embaralhando as cartas…</p></section>;
  if (!view) return <section className="draft-page"><p className="feedback feedback--error" role="alert">{errorText(draft.error)}</p></section>;
  const startersDone = slots.length > 0 && slots.every((slot) => view.slots[slot.id]);
  const benchSlots = Array.from({ length: view.bench_size }, (_, index) => `bench-${index + 1}`);
  const nextBench = `bench-${view.bench.length + 1}`;
  const others = Object.entries(view.progress).filter(([club]) => club !== clubCode);

  return <section className="draft-page" aria-labelledby="draft-title">
    <header className="draft-page__intro">
      <div>
        <p className="section-kicker">MODO DRAFT · {view.catalog === "WORLD" ? "CATÁLOGO MUNDIAL" : "CATÁLOGO BRASILEIRÃO"}{view.min_overall ? ` · CARTAS ${view.min_overall}+` : ""}</p>
        <h1 id="draft-title">Monte seu time <em>carta por carta.</em></h1>
        <p>Toque numa posição: aparecem três cartas compatíveis, uma de cada faixa de qualidade. A escolha confirmada não volta. O mesmo craque pode estar no time de um amigo.</p>
      </div>
      <div className="draft-page__clock" aria-live="polite">{view.completed ? <strong>Draft encerrado</strong> : remaining !== null ? <><strong>{Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")}</strong><small>para escolhas automáticas</small></> : null}</div>
    </header>
    {error && <p className="feedback feedback--error" role="alert">{error}</p>}
    {view.completed && <p className="feedback">Todos os elencos estão prontos. A temporada já pode começar.</p>}

    {!view.formation ? <div className="draft-formations">
      <h2>1. Escolha a formação</h2>
      <div className="choice-grid choice-grid--four">{view.formations.map((f) => <button key={f.code} type="button" className="choice" disabled={formation.isPending} onClick={() => formation.mutate(f.code)}><strong>{f.code}</strong><small>{["GK", "DF", "MF", "ST"].map((p) => `${f.slots.filter((s) => s.position === p).length} ${positionLabel(p)}`).join(" · ")}</small></button>)}</div>
    </div> : <div className="draft-board">
      <div className="draft-pitch" role="group" aria-label={`Campo do Draft, formação ${view.formation}`}>
        <div className="draft-pitch__lines" aria-hidden />
        {slots.map((slot) => <div key={slot.id} className="draft-pitch__spot" style={{ left: `${slot.x}%`, top: `${slot.y}%` }}>
          <SlotChip slot={slot} pick={view.slots[slot.id] ?? null} disabled={view.completed || open.isPending} onOpen={() => open.mutate(slot.id)} />
        </div>)}
      </div>
      <aside className="draft-side">
        <h2>Reservas livres</h2>
        <p className="muted">{startersDone ? "Três cartas de qualquer posição por escolha. Você decide o banco." : "Complete os titulares para liberar o banco."}</p>
        <div className="draft-bench">{benchSlots.map((slot, index) => {
          const chosen = view.bench[index];
          return chosen
            ? <div key={slot} className="draft-slot draft-slot--filled"><b>{chosen.card.overall}</b><span>{chosen.card.name.split(" ").slice(-1)[0]}</span><small>{positionLabel(chosen.card.position)}</small></div>
            : <button key={slot} type="button" className="draft-slot draft-slot--open" disabled={!startersDone || slot !== nextBench || view.completed} onClick={() => open.mutate(slot)}><b>+</b><small>Banco {index + 1}</small></button>;
        })}</div>
        {view.warnings.map((warning) => <p key={warning} className="draft-warning">{warning}</p>)}
        <h2>Rivais</h2>
        <ul className="draft-progress">{others.map(([club, p]) => <li key={club}><span>{club}{p.bot ? " · bot" : ""}</span><meter min={0} max={p.total ?? 1} value={p.picks} aria-label={`${club}: ${p.picks} escolhas`} /><small>{p.total ? `${p.picks}/${p.total}` : "escolhendo formação"}</small></li>)}</ul>
        {isHost && !view.completed && <button type="button" className="button-secondary" disabled={finish.isPending} onClick={() => finish.mutate()}>Encerrar Draft agora (escolhas automáticas para quem faltar)</button>}
      </aside>
    </div>}

    {offer && <Modal className="draft-offer" titleId="draft-offer-title" onClose={() => setOffer(null)} closeDisabled={pick.isPending}>
      <p className="section-kicker">{offer.slot.startsWith("bench-") ? "RESERVA LIVRE" : `POSIÇÃO · ${positionLabel(slots.find((s) => s.id === offer.slot)?.position ?? "")}`}</p>
      <h2 id="draft-offer-title">Escolha uma carta</h2>
      {offer.note && <p className="muted">{offer.note}</p>}
      <div className="draft-offer__cards">{offer.cards.map((card) => <DraftCardView key={card.id} card={card} busy={pick.isPending} onPick={() => pick.mutate({ slot: offer.slot, id: card.id })} />)}</div>
      <p className="muted">Fechar não troca as cartas: ao voltar a esta posição, as mesmas três estarão aqui.</p>
    </Modal>}
  </section>;
}
