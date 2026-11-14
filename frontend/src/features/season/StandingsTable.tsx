import { useQuery } from "@tanstack/react-query";
import { api, type SeasonTableRow } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";

export function StandingsTable({ rows, ownClub, baseline, live = false }: {
  rows: SeasonTableRow[]; ownClub: string; baseline?: SeasonTableRow[]; live?: boolean;
}) {
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then(({ data }) => data) });
  return <><div className="standings-scroll" role="region" aria-label={live ? "Classificação provisória com rolagem horizontal" : "Classificação com rolagem horizontal"} tabIndex={0}><table className="sports-table"><caption className="sr-only">{live ? "Classificação ao vivo, resultados provisórios" : "Classificação oficial do Brasileirão"}. Os oito primeiros avançam aos playoffs.</caption><thead><tr><th scope="col">#</th><th scope="col">Clube</th>{live && <th scope="col"><abbr title="Mudança em relação à classificação oficial antes da rodada">Δ</abbr></th>}<th scope="col"><abbr title="Pontos">PTS</abbr></th><th scope="col"><abbr title="Jogos">J</abbr></th><th scope="col"><abbr title="Vitórias">V</abbr></th><th scope="col"><abbr title="Empates">E</abbr></th><th scope="col"><abbr title="Derrotas">D</abbr></th><th scope="col"><abbr title="Gols pró">GP</abbr></th><th scope="col"><abbr title="Gols contra">GC</abbr></th><th scope="col"><abbr title="Saldo de gols">SG</abbr></th></tr></thead><tbody>{rows.map((row) => {
    const club = clubs.data?.find((item) => item.code === row.club_code);
    const before = baseline?.find((item) => item.club_code === row.club_code);
    const change = before ? before.position - row.position : 0;
    return <tr key={row.club_code} className={`${row.club_code === ownClub ? "is-own-club" : ""} ${row.position <= 8 ? "is-qualifying" : ""}`}><td><span className="sports-table__position">{row.position}</span></td><th scope="row"><span className="sports-table__club">{club && <ClubCrest club={club} size="sm" />}<span>{club?.name ?? row.club_code}{row.club_code === ownClub && <small>Seu clube</small>}</span></span></th>{live && <td><span className={`position-change ${change > 0 ? "is-up" : change < 0 ? "is-down" : ""}`} aria-label={change > 0 ? `Subiu ${change} posições` : change < 0 ? `Caiu ${-change} posições` : "Manteve a posição"}>{change > 0 ? `↑ ${change}` : change < 0 ? `↓ ${-change}` : "—"}</span></td>}<td><b>{row.points}</b></td><td>{row.played}</td><td>{row.wins}</td><td>{row.draws}</td><td>{row.losses}</td><td>{row.goals_for}</td><td>{row.goals_against}</td><td>{row.goal_difference > 0 ? "+" : ""}{row.goal_difference}</td></tr>;
  })}</tbody></table></div><p className="standings-legend"><span aria-hidden="true">▰</span> 1º–8º: zona de classificação aos playoffs <span>·</span> Em telas pequenas, deslize a tabela para ver todos os números.</p></>;
}
