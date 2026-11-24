import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type SquadPlayer } from "../../lib/api";
import { formatMoney } from "../../lib/format";
import { Shirt, TileArt } from "../retro/primitives";
import type { CareerTab } from "./ClubHub";
import { clubColors } from "./clubColors";
import { POSITION_LABEL } from "./labels";
import { autoPick, project, surname, teamStrength } from "./lineup";
import { PitchArt } from "./LineupBoard";
import "./squad-retro.css";

/**
 * Elenco · visão geral (FIFA 16 squad hub): the saved starting XI on a large tile that opens the
 * lineup editor, plus tiles for the other real squad areas. Read-only: every number comes from the
 * server's squad view; nothing here edits the lineup (that stays in LineupBoard).
 */
export function SquadHub({ roomId, shortMode, onGo }: { roomId: string; shortMode: boolean; onGo: (tab: CareerTab) => void }) {
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const data = squad.data;
  const view = useMemo(() => {
    if (!data) return null;
    const formation = data.formations.find((f) => f.code === data.lineup?.formation_code) ?? data.formations[0];
    const savedXI = data.lineup?.formation_code === formation.code;
    const assignments = savedXI ? data.lineup!.assignments : autoPick(formation, data.players);
    const byId = new Map(data.players.map((p) => [p.id, p]));
    const strength = teamStrength(formation, assignments, data.players);
    const n = data.players.length || 1;
    const avg = (f: (p: SquadPlayer) => number) => data.players.reduce((sum, p) => sum + f(p), 0) / n;
    const sectors = ["GK", "DF", "MF", "ST"].map((pos) => ({ pos, count: data.players.filter((p) => p.position === pos).length }));
    const top = [...data.players].sort((a, b) => b.overall - a.overall).slice(0, 3);
    const growth = [...data.players].filter((p) => p.age <= 25 && p.potential > p.overall).sort((a, b) => (b.potential - b.overall) - (a.potential - a.overall) || b.potential - a.potential).slice(0, 3);
    return { formation, savedXI, assignments, byId, strength, avgOverall: avg((p) => p.overall), avgAge: avg((p) => p.age), sectors, top, growth };
  }, [data]);

  if (squad.isPending) return <div className="panel-loading" role="status">Abrindo o vestiário…</div>;
  if (!data || !view) return <div className="panel-error" role="alert"><p>{squad.error?.message ?? "Elenco indisponível."}</p><button className="btn btn--ghost" type="button" onClick={() => void squad.refetch()}>Tentar novamente</button></div>;

  const kit = clubColors(data.club_code);
  const strategy = data.strategies.find((s) => s.code === data.strategy);
  const cohesion = data.cohesion;
  return <section className="sh" aria-label="Elenco: visão geral">
    <button type="button" data-rt-tile className="rt-tile sh-xi" onClick={() => onGo("squad")} aria-label={`Escalação ${view.formation.code}: abrir o editor de escalação`}>
      <header><p className="rt-kicker">{view.savedXI ? "Escalação salva" : "Sugestão automática (ainda não salva)"}</p><h2 className="rt-h rt-h--xl">Titulares <span>{view.formation.code}</span></h2></header>
      <div className="sh-pitch" aria-hidden="true">
        <PitchArt />
        {view.formation.slots.map((slot) => {
          const player = view.byId.get(view.assignments[slot.id]);
          const p = project(slot.x, slot.y);
          return <span key={slot.id} className="sh-slot" style={{ left: `${p.left}%`, top: `${p.top}%`, ["--depth" as string]: p.scale }}>
            <b>{player?.overall ?? "—"}</b>
            <Shirt primary={kit.primary} secondary={kit.secondary} keeper={slot.position === "GK"} label={player?.shirt_number ?? undefined} size={44} />
            <i>{player ? surname(player.name) : "Vaga"}</i>
          </span>;
        })}
      </div>
      <footer className="rt-tile__foot"><span className="sh-meter">Geral <b>{view.strength.overall.toFixed(1)}</b></span><span className="sh-meter">Def <b>{view.strength.defense.toFixed(0)}</b></span><span className="sh-meter">Meio <b>{view.strength.midfield.toFixed(0)}</b></span><span className="sh-meter">Atq <b>{view.strength.attack.toFixed(0)}</b></span><span className="sh-go">Editar escalação ▶</span></footer>
    </button>

    <div className="sh-grid">
      <button type="button" data-rt-tile className="rt-tile" onClick={() => onGo("tactics")}>
        <h3 className="rt-h">Táticas</h3>
        <p className="rt-sub">{strategy ? <><b>{strategy.name}</b> · {strategy.effect}</> : "Plano de jogo da equipe"}</p>
        <TileArt kind="whistle" />
      </button>
      <button type="button" data-rt-tile className="rt-tile" onClick={() => onGo("tactics")}>
        <h3 className="rt-h">Entrosamento</h3>
        {cohesion ? <p className="rt-sub">Sistema: <b>{cohesion.compatibility_label}</b><br />Familiaridade: <b>{cohesion.familiarity_label}</b></p> : <p className="rt-sub">Disponível depois de salvar a escalação.</p>}
        <TileArt kind="people" />
      </button>
      <div className="rt-tile sh-report" data-rt-tile tabIndex={0} aria-label="Relatório do elenco">
        <h3 className="rt-h">Relatório do elenco</h3>
        <dl><div><dt>Atletas</dt><dd>{data.players.length}</dd></div><div><dt>Média geral</dt><dd>{view.avgOverall.toFixed(1)}</dd></div><div><dt>Idade média</dt><dd>{view.avgAge.toFixed(1)}</dd></div></dl>
        <p className="sh-sectors">{view.sectors.map((s) => <span key={s.pos}><i className={`rt-pos rt-pos--${s.pos}`}>{POSITION_LABEL[s.pos]}</i>{s.count}</span>)}</p>
        <TileArt kind="chart" />
      </div>
      <div className="rt-tile sh-list" data-rt-tile tabIndex={0} aria-label="Destaques do elenco">
        <h3 className="rt-h">Destaques</h3>
        <ol>{view.top.map((p) => <li key={p.id}><i className={`rt-pos rt-pos--${p.position}`}>{POSITION_LABEL[p.position]}</i><span>{p.name}</span><b>{p.overall}</b></li>)}</ol>
      </div>
      <div className="rt-tile sh-list" data-rt-tile tabIndex={0} aria-label="Jovens promessas: até 25 anos, maior margem até o potencial">
        <h3 className="rt-h">Jovens promessas</h3>
        {view.growth.length ? <ol>{view.growth.map((p) => <li key={p.id}><i className={`rt-pos rt-pos--${p.position}`}>{POSITION_LABEL[p.position]}</i><span>{p.name} <small>{p.age} anos</small></span><b>{p.overall}<small>→{p.potential}</small></b></li>)}</ol> : <p className="rt-sub">Nenhum atleta de até 25 anos abaixo do potencial.</p>}
      </div>
      {!shortMode ? <button type="button" data-rt-tile className="rt-tile" onClick={() => onGo("market")}>
        <h3 className="rt-h">Mercado</h3>
        <p className="rt-sub">Orçamento <b>{formatMoney(data.budget_cents)}</b></p>
        <TileArt kind="money" />
      </button> : <div className="rt-tile" aria-disabled="true"><h3 className="rt-h">Mercado</h3><p className="rt-sub">Este modo não tem mercado.</p></div>}
    </div>
  </section>;
}
