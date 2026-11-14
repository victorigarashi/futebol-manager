import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { formatMoney } from "../lib/format";
import { LoadingState, ErrorState } from "./ui/AsyncState";

const ledgerLabels: Record<string, string> = { PURCHASE: "Contratação", TRANSFER: "Transferência", AWARD: "Premiação", WITHDRAWAL_PENALTY: "Multa por desistência", INITIAL_PURCHASE: "Mercado inicial", PENALTY: "Multa" };
const offerLabels: Record<string, string> = { PENDING: "Aguardando resposta", COUNTERED: "Contraproposta", ACCEPTED: "Concluída", COMPLETED: "Concluída", REJECTED: "Recusada", BOT_REJECTED: "Recusada pelo bot", CANCELLED: "Cancelada", EXPIRED: "Encerrada" };
export function CareerPanel({ roomId }: { roomId: string }) {
  const [opened, setOpened] = useState(false);
  const [tab, setTab] = useState<"finances" | "players" | "transfers">("finances");
  const id = useId();
  const career = useQuery({ queryKey: ["career", roomId], queryFn: () => api.career(roomId).then((result) => result.data), enabled: opened });
  const data = career.data;
  const playerName = (playerId?: string) => data?.players.find((player) => player.id === playerId)?.name ?? playerId ?? "";
  return <section className="career-panel" id="career-records"><header><div><p className="section-kicker">DENTRO DO CLUBE</p><h2>Sua gestão, temporada a temporada.</h2><p>Movimentações e evolução registradas na carreira.</p></div><button type="button" className="button-secondary" aria-expanded={opened} aria-controls={id} onClick={() => setOpened((value) => !value)}>{opened ? "Recolher histórico" : "Abrir histórico do clube"}</button></header>{opened && <div id={id}>
    <nav className="sports-tabs" aria-label="Histórico do clube">{([["finances", "Caixa do clube"], ["players", "Evolução do elenco"], ["transfers", "Negociações"]] as const).map(([key, label]) => <button className={tab === key ? "is-active" : ""} aria-pressed={tab === key} type="button" key={key} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {career.isPending ? <LoadingState label="Buscando os registros do clube…" /> : career.error || !data ? <ErrorState message="Não foi possível abrir o histórico do clube." onRetry={() => void career.refetch()} /> : <>
      <dl className="career-balance"><div><dt>Saldo do clube</dt><dd>{formatMoney(data.budget_cents)}</dd></div><div><dt>Reservado em negociações</dt><dd>{formatMoney(data.reserved_transfer_cents)}</dd></div><div><dt>Disponível</dt><dd>{formatMoney(data.available_transfer_cents)}</dd></div></dl>
      {tab === "finances" && (data.financial_ledger.length ? <div className="table-scroll" role="region" aria-label="Histórico do clube com rolagem horizontal" tabIndex={0}><table className="career-ledger"><caption>Entradas e saídas oficiais — temporada {data.season_number}</caption><thead><tr><th scope="col">Movimentação</th><th scope="col">Detalhes</th><th scope="col">Valor</th></tr></thead><tbody>{[...data.financial_ledger].reverse().map((entry, index) => <tr key={`${entry.operation_id ?? "entry"}-${index}`}><th scope="row">{ledgerLabels[entry.type ?? ""] ?? entry.type ?? "Registro"}</th><td>{entry.description ?? (playerName(entry.player_id) || "Operação registrada pelo servidor")}</td><td>{(entry.amount_cents ?? 0) > 0 ? "+ " : ""}{formatMoney(entry.amount_cents ?? 0)}</td></tr>)}</tbody></table></div> : <p className="empty-copy">Nenhuma movimentação financeira registrada até agora.</p>)}
      {tab === "players" && <div className="table-scroll" role="region" aria-label="Histórico do clube com rolagem horizontal" tabIndex={0}><table className="career-ledger"><caption>Elenco atual e evolução registrada</caption><thead><tr><th scope="col">Atleta</th><th scope="col">OVR atual</th><th scope="col">Evolução</th><th scope="col">Valor interno</th></tr></thead><tbody>{data.players.map((player) => <tr key={player.id}><th scope="row">{player.name}<small>{player.position}</small></th><td>{player.overall}</td><td>{(player.overall_delta ?? 0) > 0 ? "+" : ""}{player.overall_delta ?? 0}</td><td>{formatMoney(player.internal_market_value_cents ?? player.market_value_cents)}</td></tr>)}</tbody></table>{!data.development_records.length && <p className="empty-copy">A primeira evolução será calculada pelo servidor ao encerrar a temporada.</p>}</div>}
      {tab === "transfers" && (data.transfers.length ? <div className="career-transfer-list">{data.transfers.map((offer) => <article key={offer.id}><div><b>{offer.buyer_club} ↔ {offer.seller_club}</b><span>{playerName(offer.incoming_player_id)} por {playerName(offer.offered_player_id)}</span></div><strong>{formatMoney(offer.amount_cents)}</strong><span className="sports-badge">{offerLabels[offer.status] ?? offer.status}</span></article>)}</div> : <p className="empty-copy">As propostas de transferência do seu clube aparecerão aqui.</p>)}
    </>}
  </div>}</section>;
}
