import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type MarketSelection } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { Modal } from "../../components/Modal";

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const countdown = (seconds: number) => `${Math.floor(Math.max(0, seconds) / 60)}:${String(Math.ceil(Math.max(0, seconds)) % 60).padStart(2, "0")}`;

type Props = { roomId: string; phase: string; isHost: boolean };

export function MarketProgressPage({ roomId, phase, isHost }: Props) {
  const client = useQueryClient();
  const [selectedDraft, setSelected] = useState<string[] | null>(null);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [autoPlay, setAutoPlay] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const closeConfirm = useCallback(() => setConfirmOpen(false), []);
  const selection = useQuery({ queryKey: ["market-selection", roomId], queryFn: () => api.marketSelection(roomId).then((result) => result.data), enabled: phase === "MARKET_SELECTION", refetchInterval: 1000 });
  // Preserve won commitments by default: an untouched screen must not opt into withdrawal fines.
  const selected = selectedDraft ?? selection.data?.committed.map((right) => right.offer_id) ?? [];
  const preview = useQuery({ queryKey: ["market-selection-preview", roomId, selected], queryFn: () => api.previewMarketSelection(roomId, selected).then((result) => result.data), enabled: phase === "MARKET_SELECTION" && Boolean(selection.data) && !selection.data?.confirmed });
  const reassignment = useQuery({ queryKey: ["market-reassignment", roomId], queryFn: () => api.marketReassignment(roomId).then((result) => result.data), enabled: phase === "MARKET_REASSIGNMENT", refetchInterval: 1000 });
  const review = useQuery({ queryKey: ["market-review", roomId], queryFn: () => api.marketReview(roomId).then((result) => result.data), enabled: phase === "MARKET_REVIEW" });
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((result) => result.data), enabled: phase === "MARKET_REVIEW" });
  const reviewEntriesLength = review.data?.entries.length ?? 0;
  const refresh = () => { void client.invalidateQueries({ predicate: (query) => query.queryKey.includes(roomId) }); };
  const confirm = useMutation({ mutationFn: () => api.confirmMarketSelection(roomId, selected), onSuccess: () => { closeConfirm(); client.setQueryData<MarketSelection>(["market-selection", roomId], (previous) => previous ? { ...previous, confirmed: true } : previous); refresh(); } });
  const decide = useMutation({ mutationFn: ({ offerId, accept }: { offerId: string; accept: boolean }) => api.respondMarketReassignment(roomId, offerId, accept), onSuccess: refresh });
  const finish = useMutation({ mutationFn: () => api.completeMarketReview(roomId), onSuccess: (result) => { client.setQueryData(["room-state", roomId], result.data); refresh(); } });

  useEffect(() => {
    if (phase !== "MARKET_REVIEW" || !autoPlay || !reviewEntriesLength || reviewIndex >= reviewEntriesLength) return;
    const timer = window.setTimeout(() => setReviewIndex((index) => Math.min(index + 1, reviewEntriesLength)), 3500);
    return () => window.clearTimeout(timer);
  }, [phase, autoPlay, reviewEntriesLength, reviewIndex]);

  if (phase === "MARKET_SELECTION") {
    const data = selection.data;
    if (!data) return <section className="market-progress">{selection.error ? <><p className="feedback feedback--error" role="alert">{selection.error.message}</p><button className="button-secondary" onClick={() => void selection.refetch()}>Tentar novamente</button></> : <p role="status">Carregando seus direitos de contratação…</p>}</section>;
    const rights = [...data.committed, ...data.excess];
    const toggle = (offerId: string) => setSelected((current) => { const ids = current ?? selected; return ids.includes(offerId) ? ids.filter((id) => id !== offerId) : ids.length < data.max_roster_size ? [...ids, offerId] : ids; });
    const moneyPreview = preview.data;
    const previewReady = Boolean(moneyPreview) && !preview.isFetching && !preview.isError;
    const penaltyIds = new Map((moneyPreview?.penalties ?? []).map((item) => [item.offer_id, item.penalty_cents]));
    return <section className="market-progress"><header><p className="section-kicker">MERCADO INICIAL / ESCOLHA</p><h1>Os reforços <em>são seus.</em></h1><p>Escolha até {data.max_roster_size} atletas. O preço só será debitado ao confirmar.</p><p>Ofertas compromissadas estão selecionadas inicialmente. A desistência voluntária pode gerar multa de <strong>{data.withdrawal_penalty_percent}%</strong>.</p><span className="market-progress__timer" role="timer">Prazo restante: {countdown(data.remaining_seconds)}</span></header>
      <section className="market-progress__summary"><strong>{selected.length} de {data.max_roster_size} vagas selecionadas</strong><span>Reservado: {money.format(data.reserved_cents / 100)}</span><span>Disponível: {money.format(data.available_cents / 100)}</span></section>
      {data.confirmed ? <p className="feedback" role="status">Elenco confirmado. Aguardando os outros técnicos.</p> : <>
        <section className="market-right-grid" aria-label="Atletas com direito de contratação">{rights.map((right) => <label className={`market-right market-right--${right.classification === "COMPROMISSADA" ? "committed" : "excess"}`} key={right.offer_id}><input type="checkbox" checked={selected.includes(right.offer_id)} disabled={confirm.isPending || (selected.length >= data.max_roster_size && !selected.includes(right.offer_id))} onChange={() => toggle(right.offer_id)} /><span><small>{right.classification}</small><strong>{right.player.name}</strong><span>{right.player.position} · OVR {right.player.overall} · {right.player.club_code}</span><b>{money.format(right.amount_cents / 100)}</b>{penaltyIds.has(right.offer_id) && !selected.includes(right.offer_id) ? <em>Multa prevista: {money.format((penaltyIds.get(right.offer_id) ?? 0) / 100)}</em> : null}</span></label>)}</section>
        {rights.length === 0 && <p className="empty-state">Nenhuma oferta foi vencida. Você pode confirmar: o servidor completará o elenco com atletas elegíveis do clube e genéricos identificados, quando necessário.</p>}
        {preview.isError && <p className="feedback feedback--error" role="alert">{preview.error.message}</p>}
        {moneyPreview && <section className="market-financial-preview" aria-busy={preview.isFetching}><h2>Prévia validada pelo servidor</h2>{preview.isFetching && <p role="status">Atualizando valores…</p>}<dl><div><dt>Contratações</dt><dd>{money.format(moneyPreview.purchase_cents / 100)}</dd></div><div><dt>Multas por desistência</dt><dd>{money.format(moneyPreview.penalty_cents / 100)}</dd></div><div><dt>Total a debitar</dt><dd>{money.format(moneyPreview.debit_cents / 100)}</dd></div><div><dt>Reservas liberadas</dt><dd>{money.format(moneyPreview.reserved_release_cents / 100)}</dd></div><div><dt>Saldo após confirmação</dt><dd>{money.format(moneyPreview.balance_after_cents / 100)}</dd></div><div><dt>Genéricos necessários</dt><dd>{moneyPreview.generic_players_needed}</dd></div></dl><p>O elenco final terá {data.max_roster_size <= 8 ? "5 titulares e 3 reservas" : "11 titulares e 5 reservas"}. Titulares serão definidos na prancheta após o mercado.</p>{Object.entries(moneyPreview.missing_positions).some(([, count]) => count > 0) && <p>Vagas por posição ainda precisam de reposição. O servidor valida os atletas elegíveis antes de completar o elenco.</p>}{moneyPreview.penalties.length > 0 && <ul>{moneyPreview.penalties.map((item) => <li key={item.offer_id}>{rights.find((right) => right.offer_id === item.offer_id)?.player.name}: {money.format(item.penalty_cents / 100)} — {item.reason}</li>)}</ul>}</section>}
        {confirm.error && <p className="feedback feedback--error" role="alert">{confirm.error.message}</p>}<button className="button-primary" type="button" disabled={confirm.isPending || !previewReady || data.remaining_seconds <= 0} onClick={() => setConfirmOpen(true)}>{confirm.isPending ? "Confirmando…" : "Revisar e confirmar elenco"}</button>
        {confirmOpen && moneyPreview && <Modal titleId="confirm-roster-title" onClose={closeConfirm} closeDisabled={confirm.isPending}><h2 id="confirm-roster-title">Confirmar este elenco?</h2><p>{selected.length} contratação(ões) selecionada(s). A composição final e o saldo serão validados pelo servidor.</p><dl><div><dt>Compra e multas</dt><dd>{money.format(moneyPreview.debit_cents / 100)}</dd></div><div><dt>Multas incluídas</dt><dd>{money.format(moneyPreview.penalty_cents / 100)}</dd></div><div><dt>Saldo previsto</dt><dd>{money.format(moneyPreview.balance_after_cents / 100)}</dd></div></dl><p>Após confirmar, sua escolha fica encerrada para esta etapa.</p>{confirm.error && <p className="feedback feedback--error" role="alert">{confirm.error.message}</p>}<button type="button" className="button-secondary" disabled={confirm.isPending} onClick={closeConfirm}>Voltar e ajustar</button><button className="button-primary" type="button" disabled={confirm.isPending || !previewReady} onClick={() => confirm.mutate()}>{confirm.isPending ? "Confirmando…" : "Confirmar contratação e valores"}</button></Modal>}
      </>}
    </section>;
  }

  if (phase === "MARKET_REASSIGNMENT") {
    const opportunity = reassignment.data?.opportunity;
    return <section className="market-progress"><header><p className="section-kicker">MERCADO / SEGUNDA OPORTUNIDADE</p><h1>Um reforço <em>voltou ao mercado.</em></h1><p>Aceite pelo valor da sua proposta original. Recusar ou deixar o prazo passar não gera multa.</p></header>{reassignment.isLoading ? <p role="status">Consultando as oportunidades do seu clube…</p> : opportunity ? <article className="market-opportunity"><span className="beta-player-portrait" aria-hidden="true">{opportunity.player.position}</span><p>{opportunity.player.position} · OVR {opportunity.player.overall}</p><h2>{opportunity.player.name}</h2><p>Oferta original: {money.format(opportunity.amount_cents / 100)}</p><p role="timer">Prazo: {countdown(opportunity.remaining_seconds)}</p><button className="button-primary" type="button" disabled={decide.isPending || opportunity.remaining_seconds <= 0} onClick={() => decide.mutate({ offerId: opportunity.offer_id, accept: true })}>Aceitar e contratar</button><button className="button-secondary" type="button" disabled={decide.isPending} onClick={() => decide.mutate({ offerId: opportunity.offer_id, accept: false })}>Recusar sem multa</button></article> : <p className="feedback" role="status">Sem oportunidade pendente para seu clube. A redistribuição continua no servidor.</p>}{(decide.error || reassignment.error) && <p className="feedback feedback--error" role="alert">{decide.error?.message || reassignment.error?.message}</p>}</section>;
  }

  const entries = review.data?.entries ?? [];
  const current = entries[reviewIndex];
  const buyer = clubs.data?.find((club) => club.code === current?.buyer_club_code);
  return <section className="market-progress market-review"><header><p className="section-kicker">MERCADO / REVELAÇÃO PÚBLICA</p><h1>Reforços para <em>a resenha.</em></h1><p>Compras confirmadas, na ordem oficial. Ofertas perdedoras continuam secretas.</p></header>{review.error ? <p className="feedback feedback--error" role="alert">{review.error.message}</p> : review.isLoading ? <p role="status">Carregando contratações…</p> : current ? <article className="market-review__card" key={current.number}><span>CONTRATAÇÃO {current.number} DE {current.total}</span>{buyer && <div className="market-review__crest"><ClubCrest club={buyer} size="lg" /></div>}<h2>{current.player_name}</h2><p>É DO <strong>{buyer?.name ?? current.buyer_club_code}!</strong></p><div className="market-review__stats"><strong>OVR {current.overall}</strong><span>{current.position}</span></div><p>Clube anterior: {current.origin_club_code}</p><p>Técnico: {current.manager_name}</p><b>{money.format(current.amount_cents / 100)}</b></article> : entries.length ? <section className="market-review__card"><span>ELENCOS REFORÇADOS</span><h2>O mercado fechou.</h2><p>As {entries.length} contratações estão confirmadas. A próxima decisão é sua escalação.</p></section> : <p className="feedback">Nenhum atleta foi contratado por oferta. Os elencos foram completados com atletas elegíveis do clube e genéricos identificados, quando necessário.</p>}
    {entries.length > 0 && <nav className="market-review__controls" aria-label="Controles da apresentação"><button type="button" disabled={reviewIndex >= entries.length} onClick={() => setAutoPlay((value) => !value)}>{autoPlay ? "Pausar apresentação" : "Reproduzir apresentação"}</button><button type="button" disabled={reviewIndex === 0} onClick={() => { setAutoPlay(false); setReviewIndex((index) => Math.max(0, index - 1)); }}>Anterior</button><button type="button" disabled={reviewIndex >= entries.length} onClick={() => { setAutoPlay(false); setReviewIndex((index) => Math.min(entries.length, index + 1)); }}>Próxima contratação</button><button type="button" disabled={reviewIndex >= entries.length} onClick={() => { setAutoPlay(false); setReviewIndex(entries.length); }}>Pular para o resumo</button><button type="button" onClick={() => { setReviewIndex(0); setAutoPlay(true); }}>Rever apresentação</button></nav>}
    {review.data && (!current || !entries.length) && <section className="market-review__summary"><h2>Resumo do mercado</h2><p>{review.data.summary.player_count} contratações · {money.format(review.data.summary.total_spent_cents / 100)} movimentados</p><p>Genéricos por clube: {Object.entries(review.data.summary.generic_players_by_club).filter(([, count]) => count > 0).map(([club, count]) => `${club}: ${count}`).join(" · ") || "nenhum"}</p></section>}
    {isHost ? <button className="button-primary" type="button" disabled={finish.isPending || !review.data || review.isError} onClick={() => finish.mutate()}>{finish.isPending ? "Concluindo…" : "Concluir review e ir ao elenco"}</button> : <p className="feedback" role="status">O anfitrião libera a prancheta ao concluir a review.</p>}{finish.error && <p className="feedback feedback--error" role="alert">{finish.error.message}</p>}
  </section>;
}
