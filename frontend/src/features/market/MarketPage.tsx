import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type MarketOffer, type MarketPlayer } from "../../lib/api";
import { Modal } from "../../components/Modal";

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const positions: Record<string, string> = { GK: "Goleiro", DF: "Defensor", MF: "Meio-campo", ST: "Atacante" };
const PAGE_SIZE = 24;
const statuses: Record<string, string> = { ACTIVE: "Ativa", CANCELLED: "Cancelada", WON: "Vencida", LOST: "Não vencida" };

export function MarketPage({ roomId }: { roomId: string }) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("");
  const [minOverall, setMinOverall] = useState("");
  const [maxOverall, setMaxOverall] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [pagination, setPagination] = useState({ filterKey: "", page: 0 });
  const [selected, setSelected] = useState<MarketPlayer | null>(null);
  const [editing, setEditing] = useState<MarketOffer | null>(null);
  const [offer, setOffer] = useState("");
  const [notice, setNotice] = useState("");
  const [openError, setOpenError] = useState("");
  const keyRef = useRef("");
  const knownPlayers = useRef(new Map<string, MarketPlayer>());
  useEffect(() => { const timer = window.setTimeout(() => setSearch(query), 250); return () => window.clearTimeout(timer); }, [query]);
  const state = useQuery({ queryKey: ["market", roomId], queryFn: () => api.market(roomId).then((result) => result.data), refetchInterval: 1000 });
  const players = useQuery({ queryKey: ["market-players", roomId, search, position, minOverall, maxOverall, maxPrice], queryFn: async () => {
    const result = await api.marketPlayers(roomId, { query: search, position, min_overall: minOverall === "" ? undefined : Number(minOverall), max_overall: maxOverall === "" ? undefined : Number(maxOverall), max_price_cents: maxPrice === "" ? undefined : Math.round(Number(maxPrice) * 100) });
    for (const player of result.data) knownPlayers.current.set(player.id, player);
    return result.data;
  } });
  const filterKey = JSON.stringify([query, position, minOverall, maxOverall, maxPrice]);
  const totalPlayers = players.data?.length ?? 0;
  const pageCount = Math.max(1, Math.ceil(totalPlayers / PAGE_SIZE));
  const page = Math.min(pagination.filterKey === filterKey ? pagination.page : 0, pageCount - 1);
  const pagePlayers = players.data?.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE) ?? [];
  const changePage = (nextPage: number) => setPagination({ filterKey, page: nextPage });
  const refresh = () => { void client.invalidateQueries({ queryKey: ["market", roomId] }); };
  const close = useCallback(() => { setSelected(null); setEditing(null); }, []);
  const save = useMutation({ mutationFn: () => editing
    ? api.updateOffer(roomId, editing.id, Math.round(Number(offer) * 100))
    : api.createOffer(roomId, { player_id: selected!.id, amount_cents: Math.round(Number(offer) * 100), idempotency_key: keyRef.current }),
  onSuccess: () => { setNotice(editing ? "Proposta atualizada. A nova reserva foi confirmada pelo servidor." : "Proposta secreta enviada. Só você pode ver esse valor."); close(); refresh(); } });
  const cancel = useMutation({ mutationFn: (id: string) => api.cancelOffer(roomId, id), onSuccess: () => { setNotice("Proposta cancelada e reserva liberada."); refresh(); } });
  const open = async (item: MarketOffer) => {
    setOpenError("");
    try {
      const player = knownPlayers.current.get(item.player_id) ?? (await api.marketPlayer(roomId, item.player_id)).data;
      knownPlayers.current.set(player.id, player); setSelected(player); setEditing(item); setOffer(String(item.amount_cents / 100)); save.reset();
    } catch (error) { setOpenError(error instanceof Error ? error.message : "Não foi possível abrir a proposta."); }
  };
  const summary = useMemo(() => [
    ["Orçamento", money.format((state.data?.budget_cents ?? 0) / 100)], ["Reservado", money.format((state.data?.reserved_cents ?? 0) / 100)],
    ["Disponível", money.format((state.data?.available_cents ?? 0) / 100)], ["Propostas ativas", `${state.data?.active_offer_count ?? 0}/${state.data?.offer_limit ?? "—"}`],
  ], [state.data]);
  const remaining = Math.max(0, Math.ceil(state.data?.remaining_seconds ?? 0));
  const unavailable = !state.data || state.data.resolved || remaining === 0;
  const amount = Math.round(Number(offer) * 100);
  const invalidAmount = !Number.isSafeInteger(amount) || amount <= 0 || amount < (selected?.market_value_cents ?? 0);
  if (state.isError && !state.data) return <section className="market-page"><p className="feedback feedback--error" role="alert">{state.error.message}</p><button className="button-secondary" onClick={() => void state.refetch()}>Tentar novamente</button></section>;
  return <section className="market-page"><header className="market-page__header"><div><p className="section-kicker">MERCADO INICIAL / PROPOSTAS SECRETAS</p><h1>Monte seu <em>esquadrão.</em></h1><p>Escolha os reforços. O valor de cada proposta fica entre você e o servidor.</p><p className="market-rule">Multa por desistir de uma contratação vencida: {state.data?.withdrawal_penalty_percent ?? "—"}%.</p></div><div className="market-timer" role="timer" aria-label="Tempo restante do mercado"><span>{remaining ? "Mercado aberto" : "Encerrando mercado"}</span><strong>{String(Math.floor(remaining / 60)).padStart(2, "0")}:{String(remaining % 60).padStart(2, "0")}</strong></div></header>
    {notice && <p className="feedback" role="status">{notice}</p>}{(cancel.error || openError || state.error) && <p className="feedback feedback--error" role="alert">{cancel.error?.message || openError || state.error?.message}</p>}
    <section className="market-summary" aria-label="Seu orçamento">{summary.map(([label, value]) => <div key={label}><span>{label}</span><strong>{state.isLoading ? "Carregando…" : value}</strong></div>)}</section>
    <section className="market-layout"><div><div className="market-filters"><input aria-label="Buscar atleta por nome" value={query} onChange={(event) => { setQuery(event.target.value); setPagination({ filterKey: "", page: 0 }); }} placeholder="Buscar atleta" /><select aria-label="Filtrar por posição" value={position} onChange={(event) => { setPosition(event.target.value); setPagination({ filterKey: "", page: 0 }); }}><option value="">Todas as posições</option>{Object.entries(positions).map(([code, label]) => <option value={code} key={code}>{label}</option>)}</select><input type="number" min="1" max="99" aria-label="Overall mínimo" placeholder="OVR mín." value={minOverall} onChange={(event) => { setMinOverall(event.target.value); setPagination({ filterKey: "", page: 0 }); }} /><input type="number" min="1" max="99" aria-label="Overall máximo" placeholder="OVR máx." value={maxOverall} onChange={(event) => { setMaxOverall(event.target.value); setPagination({ filterKey: "", page: 0 }); }} /><input type="number" min="0" aria-label="Preço máximo em reais" placeholder="Preço máx. (R$)" value={maxPrice} onChange={(event) => { setMaxPrice(event.target.value); setPagination({ filterKey: "", page: 0 }); }} /></div>
      {players.isError ? <p className="feedback feedback--error" role="alert">{players.error.message}</p> : players.isLoading ? <p className="muted" role="status">Consultando o olheiro…</p> : players.data?.length ? <><p className="muted" role="status">Mostrando {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, totalPlayers)} de {totalPlayers} atletas</p><div className="market-player-grid">{pagePlayers.map((player) => <button type="button" className="market-player" key={player.id} disabled={unavailable} onClick={() => { const existing = state.data?.offers.find((item) => item.player_id === player.id && item.status === "ACTIVE"); setSelected(player); setEditing(existing ?? null); setOffer(String((existing?.amount_cents ?? player.market_value_cents) / 100)); keyRef.current = crypto.randomUUID(); save.reset(); }}><span className="beta-player-portrait" aria-hidden="true">{player.name.split(" ").filter(Boolean).map((word) => word[0]).slice(0, 2).join("")}</span><b>{positions[player.position] ?? player.position}</b><strong>{player.name}</strong><span>{player.club_code} · {player.age} anos</span><small>OVR <b>{player.overall}</b> · POT {player.potential}</small><em>{money.format(player.market_value_cents / 100)}</em></button>)}</div><nav className="market-pagination season-actions" aria-label="Páginas de atletas"><button type="button" className="button-secondary" disabled={page === 0} onClick={() => changePage(page - 1)}>Página anterior</button><span aria-live="polite" aria-atomic="true">Página {page + 1} de {pageCount}</span><button type="button" className="button-secondary" disabled={page + 1 >= pageCount} onClick={() => changePage(page + 1)}>Próxima página</button></nav></> : <p className="empty-state">Nenhum atleta corresponde aos filtros. Tente outro nome ou posição.</p>}
    </div><aside className="market-offers"><p className="section-kicker">MINHAS PROPOSTAS / VALORES PRIVADOS</p>{state.data?.offers.length ? state.data.offers.map((item, index) => <article key={item.id}><small>Prioridade de envio {index + 1}</small><strong>{knownPlayers.current.get(item.player_id)?.name ?? `Atleta ${item.player_id}`}</strong><span>{money.format(item.amount_cents / 100)} · {statuses[item.status] ?? item.status}</span>{item.status === "ACTIVE" && <div className="market-offer-actions"><button type="button" disabled={unavailable || cancel.isPending} onClick={() => void open(item)}>Alterar valor</button><button type="button" disabled={unavailable || cancel.isPending} onClick={() => cancel.mutate(item.id)}>Cancelar</button></div>}</article>) : <p className="muted">Seu olheiro está esperando. Selecione um atleta para enviar a primeira proposta.</p>}</aside></section>
    {selected && <Modal titleId="offer-title" onClose={close} closeDisabled={save.isPending}><p className="section-kicker">{editing ? "ALTERAR PROPOSTA SECRETA" : "FICHA DO ATLETA"}</p><h2 id="offer-title">{selected.name}</h2><p>{positions[selected.position]} · OVR {selected.overall} · potencial {selected.potential}</p><p>Valor de mercado: <b>{money.format(selected.market_value_cents / 100)}</b></p><form onSubmit={(event) => { event.preventDefault(); if (!invalidAmount && !unavailable) save.mutate(); }}><label htmlFor="offer-amount">Sua proposta em reais (R$)</label><input id="offer-amount" type="number" min={selected.market_value_cents / 100} step="0.01" inputMode="decimal" value={offer} onChange={(event) => setOffer(event.target.value)} required aria-describedby="offer-impact" /><p className="market-offer-impact" id="offer-impact">Reserva solicitada: <strong>{Number.isFinite(amount) ? money.format(amount / 100) : "Informe um valor válido"}</strong>. {editing && <>A reserva anterior de {money.format(editing.amount_cents / 100)} será substituída. </>}O servidor valida saldo e limite antes de aceitar.</p>{save.error && <p className="field-error" role="alert">{save.error.message}</p>}<button className="button-primary" type="submit" disabled={save.isPending || invalidAmount || unavailable || (!editing && (state.data?.active_offer_count ?? 0) >= (state.data?.offer_limit ?? 0))}>{save.isPending ? "Enviando…" : editing ? "Salvar novo valor" : "Enviar proposta secreta"}</button></form></Modal>}
  </section>;
}
