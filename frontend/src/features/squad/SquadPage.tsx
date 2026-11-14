import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { ClubCrest } from "../../components/ClubCrest";
import { LineupBoard } from "../career/LineupBoard";
import { TacticsBoard } from "../career/TacticsBoard";
import "../career/career.css";

/** Pre-season: the squad arrives from the market; set line-up and plan before round 1. */
export function SquadPage({ roomId, isHost, onStartSeason }: { roomId: string; isHost: boolean; onStartSeason: () => void; inSeason?: boolean }) {
  const [tab, setTab] = useState<"squad" | "tactics">("squad");
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((r) => r.data), staleTime: Infinity });
  const club = clubs.data?.find((c) => c.code === squad.data?.club_code);
  return <div className="career">
    <header className="career-head"><div className="career-head__club">{club && <ClubCrest club={club} size="md" />}<div><p className="kicker">PRÉ-TEMPORADA</p><h1>{club?.name ?? "Seu clube"}</h1><span>Monte o time titular e o plano de jogo antes da rodada 1.</span></div></div>
      <div className="career-head__cta">{isHost ? <button type="button" className="btn btn--primary btn--xl" disabled={!squad.data?.lineup} onClick={onStartSeason} title={squad.data?.lineup ? "" : "Salve sua escalação primeiro"}>Abrir rodada 1 →</button> : <p className="hint">O anfitrião abre a rodada 1 quando todos estiverem prontos.</p>}</div></header>
    <nav className="career-nav" aria-label="Pré-temporada">{([["squad", "Elenco e escalação"], ["tactics", "Táticas"]] as const).map(([id, label]) => <button key={id} type="button" className={tab === id ? "is-active" : ""} aria-current={tab === id ? "page" : undefined} onClick={() => setTab(id)}>{label}</button>)}</nav>
    <main className="career-body">{tab === "squad" ? <LineupBoard roomId={roomId} /> : <TacticsBoard roomId={roomId} />}</main>
  </div>;
}
