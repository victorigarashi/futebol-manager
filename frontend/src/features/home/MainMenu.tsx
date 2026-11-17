import { type FormEvent, type KeyboardEvent, useRef, useState } from "react";

import type { GameMode, RoomState } from "../../lib/api";
import { GAME_MODES, type ModeInfo, modeInfo } from "../../lib/gameModes";
import "./home.css";

type PublicRoom = { id: string; name: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; participant_count?: number; game_mode?: GameMode };
type View = "menu" | "modes" | "join" | "history";

type Props = {
  displayName: string | null;
  myRooms: RoomState[];
  publicRooms: PublicRoom[] | undefined;
  roomsLoading: boolean;
  joinCode: string;
  joining: boolean;
  onCodeChange: (code: string) => void;
  onJoinCode: (event: FormEvent<HTMLFormElement>) => void;
  onJoinRoom: (roomId: string) => void;
  onPickMode: (mode: GameMode) => void;
  onEditProfile: () => void;
};

const PHASES: Record<string, string> = {
  WAITING: "Aguardando técnicos", INITIAL_MARKET: "Mercado inicial", DRAFT: "Draft em andamento", PACK: "Abrindo pacotes",
  SQUAD_MANAGEMENT: "Montando o time", SEASON_PREPARATION: "Em competição", TRANSFER_WINDOW: "Janela de transferências",
};
const fmt = (mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE") => (mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11");

/** Main menu: continue, new game, join, history, settings — nothing else up front. */
export function MainMenu(props: Props) {
  const { displayName, myRooms, onJoinRoom, onEditProfile } = props;
  const [view, setView] = useState<View>("menu");
  const latest = myRooms[0];
  const items: { id: string; label: string; hint: string; action: () => void; primary?: boolean }[] = [
    ...(latest ? [{ id: "continue", label: "Continuar", hint: latest.name, action: () => onJoinRoom(latest.id), primary: true }] : []),
    { id: "new", label: "Nova partida", hint: "Escolha um modo de jogo", action: () => setView("modes"), primary: !latest },
    { id: "join", label: "Entrar numa sala", hint: "Com código ou salas abertas", action: () => setView("join") },
    ...(myRooms.length > 1 ? [{ id: "history", label: "Minhas salas", hint: `${myRooms.length} salas`, action: () => setView("history") }] : []),
    { id: "settings", label: "Configurações", hint: "Nome do técnico", action: onEditProfile },
  ];
  const list = useRef<HTMLUListElement>(null);
  const onKey = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const buttons = Array.from(list.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[(index + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length]?.focus();
  };

  return <main className="menu-shell" id="top">
    <div className="menu-stadium" aria-hidden="true"><i className="menu-stadium__light menu-stadium__light--l" /><i className="menu-stadium__light menu-stadium__light--r" /><i className="menu-stadium__pitch" /></div>
    <header className="menu-brand">
      <span className="menu-brand__mark">BM</span>
      <div><strong>Brasileirão Manager</strong><small>Edição Resenha</small></div>
      <button type="button" className="menu-brand__coach" onClick={onEditProfile}>Técnico <b>{displayName || "—"}</b></button>
    </header>

    <div id="main-content" tabIndex={-1} />
    {view === "menu" && <section className="menu-main">
      <nav aria-label="Menu principal"><ul ref={list} className="menu-list" onKeyDown={onKey}>
        {items.map((item) => <li key={item.id}><button type="button" className={item.primary ? "is-primary" : ""} onClick={item.action}><span>{item.label}</span><small>{item.hint}</small></button></li>)}
      </ul></nav>
      {latest ? <ContinueCard room={latest} onOpen={() => onJoinRoom(latest.id)} /> : <WelcomeCard onStart={() => setView("modes")} />}
    </section>}

    {view === "modes" && <ModeSelect onBack={() => setView("menu")} onPick={props.onPickMode} />}
    {view === "join" && <JoinView {...props} onBack={() => setView("menu")} />}
    {view === "history" && <section className="menu-panel"><BackButton onBack={() => setView("menu")} /><h1>Minhas salas</h1>
      <ul className="menu-rooms">{myRooms.map((room) => <li key={room.id}><RoomLine room={room} /><button type="button" className="button-primary" onClick={() => onJoinRoom(room.id)}>Abrir</button></li>)}</ul>
    </section>}
  </main>;
}

function BackButton({ onBack }: { onBack: () => void }) {
  return <button type="button" className="menu-back" onClick={onBack}>← Menu</button>;
}

function RoomLine({ room }: { room: RoomState }) {
  const info = modeInfo(room.game_mode);
  return <div className="menu-room"><i style={{ background: info.accent }} aria-hidden="true" /><div><strong>{room.name}</strong><span>{info.name} · {fmt(room.mode)} · {PHASES[room.phase] ?? "Em andamento"}</span></div></div>;
}

function ContinueCard({ room, onOpen }: { room: RoomState; onOpen: () => void }) {
  const info = modeInfo(room.game_mode);
  return <article className="menu-feature" style={{ ["--mode-accent" as string]: info.accent }}>
    <p className="menu-feature__kicker">CONTINUAR · {info.name.toUpperCase()}</p>
    <h1>{room.name}</h1>
    <p>{PHASES[room.phase] ?? "Em andamento"} · {fmt(room.mode)} · {room.team_count} clubes</p>
    <button type="button" className="button-primary menu-feature__cta" onClick={onOpen}>Entrar em campo <span aria-hidden="true">→</span></button>
  </article>;
}

function WelcomeCard({ onStart }: { onStart: () => void }) {
  return <article className="menu-feature">
    <p className="menu-feature__kicker">BEM-VINDO AO VESTIÁRIO</p>
    <h1>Seu clube.<br />Sua resenha.</h1>
    <p>Carreira completa, Draft, mata-mata relâmpago, sobrevivência ou pacotes: escolha o jeito de jogar com os amigos.</p>
    <button type="button" className="button-primary menu-feature__cta" onClick={onStart}>Começar <span aria-hidden="true">→</span></button>
  </article>;
}

/** Large, distinct cards; the specific settings only appear after a mode is chosen. */
export function ModeSelect({ onBack, onPick }: { onBack: () => void; onPick: (mode: GameMode) => void }) {
  return <section className="menu-panel menu-modes" aria-labelledby="modes-title">
    <BackButton onBack={onBack} />
    <h1 id="modes-title">Escolha o modo</h1>
    <div className="mode-grid">{GAME_MODES.map((mode) => <ModeCard key={mode.id} mode={mode} onPick={() => onPick(mode.id)} />)}</div>
  </section>;
}

function ModeCard({ mode, onPick }: { mode: ModeInfo; onPick: () => void }) {
  return <article className="mode-card" style={{ ["--mode-accent" as string]: mode.accent }}>
    <ModeArt id={mode.id} />
    <div className="mode-card__body">
      <h2>{mode.name}</h2>
      <p className="mode-card__tagline">{mode.tagline}</p>
      <p>{mode.description}</p>
      <dl><div><dt>Clubes</dt><dd>{mode.sizes.length > 4 ? `${mode.sizes[0]} a ${mode.sizes[mode.sizes.length - 1]}` : mode.sizes.join(", ")}</dd></div><div><dt>Duração</dt><dd>{mode.length}</dd></div><div><dt>Elencos</dt><dd>{mode.squads}</dd></div></dl>
      <button type="button" className="button-primary" onClick={onPick}>Criar sala <span aria-hidden="true">→</span></button>
    </div>
  </article>;
}

/** Simple vector previews (own drawings, no third-party marks). */
function ModeArt({ id }: { id: GameMode }) {
  return <svg className="mode-card__art" viewBox="0 0 160 90" aria-hidden="true">
    <rect x="1" y="1" width="158" height="88" rx="8" fill="none" stroke="currentColor" strokeOpacity=".25" />
    {id === "TRADITIONAL" && <><path d="M48 70h64M60 70V52h40v18M70 52c0-14-10-14-10-26h40c0 12-10 12-10 26" fill="none" stroke="currentColor" strokeWidth="3" /><circle cx="80" cy="20" r="4" fill="currentColor" /></>}
    {id === "DRAFT" && [0, 1, 2].map((i) => <rect key={i} x={38 + i * 30} y={22 - (i === 1 ? 6 : 0)} width="26" height="40" rx="4" fill="none" stroke="currentColor" strokeWidth={i === 1 ? 3 : 2} />)}
    {id === "DRAFT_KNOCKOUT" && <path d="M20 20h22v20h22M20 60h22V40M64 40h20v10h22M20 80h0M64 60h20V50M106 50h34" fill="none" stroke="currentColor" strokeWidth="3" />}
    {id === "SURVIVOR" && [0, 1, 2, 3, 4, 5].map((i) => <circle key={i} cx={30 + i * 20} cy="45" r={i < 4 ? 7 : 7} fill={i < 3 ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" opacity={i < 3 ? 1 : 0.35} />)}
    {id === "PACK" && <><rect x="52" y="14" width="56" height="64" rx="6" fill="none" stroke="currentColor" strokeWidth="3" /><path d="M52 30h56M80 14v16" stroke="currentColor" strokeWidth="2" /><path d="M80 44l5 10h11l-9 7 3 11-10-6-10 6 3-11-9-7h11z" fill="currentColor" /></>}
  </svg>;
}

function JoinView({ joinCode, joining, onCodeChange, onJoinCode, publicRooms, roomsLoading, onJoinRoom, onBack }: Props & { onBack: () => void }) {
  return <section className="menu-panel"><BackButton onBack={onBack} /><h1>Entrar numa sala</h1>
    <form className="menu-join" onSubmit={onJoinCode}>
      <label htmlFor="join-code">Código da sala</label>
      <div><input id="join-code" value={joinCode} maxLength={6} placeholder="ABC123" autoComplete="off" onChange={(event) => onCodeChange(event.target.value.toUpperCase())} required />
        <button type="submit" className="button-primary" disabled={joining}>{joining ? "Entrando…" : "Entrar"}</button></div>
    </form>
    <h2 className="menu-subtitle">Salas abertas</h2>
    {roomsLoading ? <p className="muted">Procurando salas…</p> : publicRooms?.length ? <ul className="menu-rooms">{publicRooms.map((room) => {
      const info = modeInfo(room.game_mode);
      return <li key={room.id}><div className="menu-room"><i style={{ background: info.accent }} aria-hidden="true" /><div><strong>{room.name}</strong><span>{info.name} · {fmt(room.mode)} · {room.participant_count ?? 0} técnicos</span></div></div><button type="button" className="button-secondary" onClick={() => onJoinRoom(room.id)}>Entrar</button></li>;
    })}</ul> : <p className="muted">Nenhuma sala pública aberta agora. Crie a sua em “Nova partida”.</p>}
  </section>;
}
