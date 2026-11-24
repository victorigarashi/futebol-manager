import { type FormEvent, useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type GameMode, type RoomState } from "../../lib/api";
import { GAME_MODES, modeInfo } from "../../lib/gameModes";
import { useSession } from "../../stores/session";
import { ClubCrest } from "../../components/ClubCrest";
import { Modal } from "../../components/Modal";
import { ExperiencePicker } from "../career/interactive/ExperiencePicker";
import { RetroFooter, RetroFrame, RetroNav, TileArt } from "../retro/primitives";
import { useTileNav } from "../retro/useTileNav";
import "./menu-retro.css";

type PublicRoom = { id: string; name: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; participant_count?: number; game_mode?: GameMode };
type Tab = "home" | "play" | "online" | "custom";

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
  WAITING: "Aguardando técnicos", INITIAL_MARKET: "Mercado inicial", MARKET_SELECTION: "Confirmando contratações", MARKET_REASSIGNMENT: "Redistribuição", MARKET_REVIEW: "Apresentação do elenco",
  DRAFT: "Draft em andamento", PACK: "Abrindo pacotes", SQUAD_MANAGEMENT: "Montando o time", SEASON_PREPARATION: "Em competição", TRANSFER_WINDOW: "Janela de transferências",
};
const fmt = (mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE") => (mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11");
const ART: Record<GameMode, "trophy" | "cards" | "bracket" | "survivor" | "pack"> = { TRADITIONAL: "trophy", DRAFT: "cards", DRAFT_KNOCKOUT: "bracket", SURVIVOR: "survivor", PACK: "pack" };
const TABS: { id: Tab; label: string }[] = [{ id: "home", label: "Início" }, { id: "play", label: "Jogar" }, { id: "online", label: "Online" }, { id: "custom", label: "Personalizar" }];

/**
 * Main menu, console style: categories on a horizontal bar, a dominant tile for the most
 * likely action and secondary tiles. Every tile is an existing action of the app; nothing
 * is shown that the game cannot do.
 */
export function MainMenu(props: Props) {
  const { displayName, myRooms, onJoinRoom, onEditProfile, onPickMode } = props;
  const userId = useSession((s) => s.userId);
  const [tab, setTab] = useState<Tab>("home");
  const [experienceOpen, setExperienceOpen] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const back = useCallback(() => { if (tab !== "home") setTab("home"); }, [tab]);
  useTileNav(body, back);
  const latest = myRooms[0];

  return <RetroFrame view="menu" fit label="Menu principal"
    top={<header className="rt-top">
      <div className="rt-plate"><span className="rt-brand">resenha<i>.</i></span><div className="rt-plate__text" style={{ marginLeft: 18 }}><strong>MENU PRINCIPAL</strong><span>Brasileirão Manager · Edição Resenha</span></div></div>
      <div className="rt-plate rt-plate--right">
        <div className="rt-stat"><small>Técnico</small><b>{displayName || "—"}</b></div>
        {myRooms.length > 0 && <div className="rt-stat"><small>Suas salas</small><b>{myRooms.length}</b></div>}
        <button type="button" className="rt-iconbtn" onClick={onEditProfile}>Editar perfil</button>
      </div>
    </header>}
    nav={<RetroNav label="Categorias do menu" items={TABS} current={tab} onSelect={setTab} />}
    footer={<RetroFooter hints={[{ key: "Enter", label: "Selecionar" }, ...(tab !== "home" ? [{ key: "Esc", label: "Voltar" }] : []), { key: "↑↓←→", label: "Navegar" }]} right="Futebol se joga junto. A resenha também." />}>
    <div ref={body} className="mm" key={tab}>
      {tab === "home" && <HomeTiles latest={latest} userId={userId} rooms={myRooms} onJoinRoom={onJoinRoom} onTab={setTab} onPickMode={onPickMode} />}
      {tab === "play" && <div className="mm-modes">{GAME_MODES.map((mode) => <button key={mode.id} type="button" data-rt-tile className={`rt-tile mm-mode ${mode.id === "TRADITIONAL" ? "mm-mode--lead" : ""}`} onClick={() => onPickMode(mode.id)}>
        <p className="rt-kicker">{mode.tagline}</p><h2 className="rt-h">{mode.name}</h2><p className="rt-sub">{mode.description}</p>
        <dl className="mm-facts"><div><dt>Clubes</dt><dd>{mode.sizes.length > 4 ? `${mode.sizes[0]} a ${mode.sizes[mode.sizes.length - 1]}` : mode.sizes.join(", ")}</dd></div><div><dt>Duração</dt><dd>{mode.length}</dd></div><div><dt>Elencos</dt><dd>{mode.squads}</dd></div></dl>
        <span className="mm-cta">Criar sala →</span><TileArt kind={ART[mode.id]} />
      </button>)}</div>}
      {tab === "online" && <OnlineTiles {...props} />}
      {tab === "custom" && <div className="mm-custom">
        <button type="button" data-rt-tile className="rt-tile mm-big" onClick={onEditProfile}><p className="rt-kicker">Perfil</p><h2 className="rt-h rt-h--xl">Nome do técnico</h2><p className="rt-sub">Como os amigos veem você nas salas, na classificação e nas notícias. Atual: <b>{displayName || "—"}</b>.</p><TileArt kind="whistle" /></button>
        <button type="button" data-rt-tile className="rt-tile mm-big" onClick={() => setExperienceOpen(true)}><p className="rt-kicker">Modo Jogável</p><h2 className="rt-h rt-h--xl">Visual da partida</h2><p className="rt-sub">Escolha entre o 2D e o 3D e a qualidade gráfica deste aparelho. A escolha é só sua e não altera o resultado.</p><TileArt kind="pitch" /></button>
      </div>}
    </div>
    {experienceOpen && <Modal className="rt-modal" titleId="experience-title" onClose={() => setExperienceOpen(false)}><h2 id="experience-title">Visual da partida</h2><ExperiencePicker /></Modal>}
  </RetroFrame>;
}

function HomeTiles({ latest, userId, rooms, onJoinRoom, onTab, onPickMode }: { latest?: RoomState; userId: string | null; rooms: RoomState[]; onJoinRoom: (id: string) => void; onTab: (t: Tab) => void; onPickMode: (m: GameMode) => void }) {
  const mine = latest?.participants.find((p) => p.user_id === userId);
  const clubCode = mine?.selected_club_code ?? undefined;
  const info = latest ? modeInfo(latest.game_mode) : null;
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((r) => r.data), staleTime: Infinity });
  const club = clubCode ? clubs.data?.find((c) => c.code === clubCode) ?? { code: clubCode, name: clubCode, sort_order: 0 } : null;
  return <div className="mm-home">
    {latest && info ? <button type="button" data-rt-tile className="rt-tile mm-hero" autoFocus onClick={() => onJoinRoom(latest.id)}>
      <div className="mm-hero__art" aria-hidden="true" />
      <div className="mm-hero__copy">
        <p className="rt-kicker">Continuar · {info.name}</p>
        <h2 className="rt-h rt-h--xl">Continuar carreira</h2>
        <p className="rt-sub">Retorne à sua sala, onde ela parou.</p>
      </div>
      <div className="mm-hero__room">
        {club && <ClubCrest club={club} size="lg" />}
        <div><strong>{club ? club.name : latest.name}</strong>{club && <em>{latest.name}</em>}<span>{PHASES[latest.phase] ?? "Em andamento"} · {fmt(latest.mode)} · {latest.team_count} clubes</span></div>
        <span className="rt-btn rt-btn--lime">Entrar em campo →</span>
      </div>
    </button> : <button type="button" data-rt-tile className="rt-tile mm-hero" autoFocus onClick={() => onPickMode("TRADITIONAL")}>
      <div className="mm-hero__art" aria-hidden="true" />
      <div className="mm-hero__copy"><p className="rt-kicker">Comece por aqui</p><h2 className="rt-h rt-h--xl">Nova carreira</h2><p className="rt-sub">Escolha um clube, monte o elenco no mercado e dispute o Brasileirão com os amigos.</p></div>
      <div className="mm-hero__room"><span className="rt-btn rt-btn--lime">Criar sala →</span></div>
    </button>}
    <div className="mm-side">
      {latest && <button type="button" data-rt-tile className="rt-tile" onClick={() => onPickMode("TRADITIONAL")}><h2 className="rt-h">Nova carreira</h2><p className="rt-sub">Monte sua equipe e crie uma nova sala</p><TileArt kind="trophy" /></button>}
      <button type="button" data-rt-tile className="rt-tile" onClick={() => onTab("online")}><h2 className="rt-h">Jogar com amigos</h2><p className="rt-sub">Entre com um código ou numa sala aberta</p><TileArt kind="people" /></button>
      <button type="button" data-rt-tile className="rt-tile" onClick={() => onPickMode("DRAFT")}><h2 className="rt-h">Draft</h2><p className="rt-sub">Três cartas por posição</p><TileArt kind="cards" /></button>
      <button type="button" data-rt-tile className="rt-tile" onClick={() => onTab("play")}><h2 className="rt-h">Torneios e modos</h2><p className="rt-sub">Mata-mata, sobrevivência e pacotes</p><TileArt kind="bracket" /></button>
      {rooms.length > 1 && <button type="button" data-rt-tile className="rt-tile" onClick={() => onTab("online")}><h2 className="rt-h">Minhas salas</h2><p className="rt-sub">{rooms.length} salas em andamento</p><TileArt kind="key" /></button>}
    </div>
  </div>;
}

function OnlineTiles({ joinCode, joining, onCodeChange, onJoinCode, publicRooms, roomsLoading, onJoinRoom, myRooms }: Props) {
  return <div className="mm-online">
    <section className="rt-panel mm-join">
      <p className="rt-kicker">Convite</p><h2 className="rt-h rt-h--xl">Entrar com código</h2>
      <p className="rt-sub">Peça o código de 6 letras ao anfitrião da sala.</p>
      <form onSubmit={onJoinCode}>
        <label htmlFor="join-code" className="sr-only">Código da sala</label>
        <input id="join-code" value={joinCode} maxLength={6} placeholder="ABC123" autoComplete="off" onChange={(event) => onCodeChange(event.target.value.toUpperCase())} required />
        <button type="submit" className="rt-btn rt-btn--lime" disabled={joining}>{joining ? "Entrando…" : "Entrar"}</button>
      </form>
      {myRooms.length > 0 && <><h3 className="mm-subhead">Minhas salas</h3><ul className="mm-rooms">{myRooms.map((room) => <li key={room.id}><button type="button" data-rt-tile className="rt-tile mm-room" onClick={() => onJoinRoom(room.id)}><b>{room.name}</b><span>{modeInfo(room.game_mode).name} · {fmt(room.mode)} · {PHASES[room.phase] ?? "Em andamento"}</span></button></li>)}</ul></>}
    </section>
    <section className="rt-panel mm-public">
      <p className="rt-kicker">Salas abertas</p><h2 className="rt-h rt-h--xl">Jogar online</h2>
      {roomsLoading ? <p className="rt-sub">Procurando salas…</p> : publicRooms?.length ? <ul className="mm-rooms rt-scroll">{publicRooms.map((room) => <li key={room.id}><button type="button" data-rt-tile className="rt-tile mm-room" onClick={() => onJoinRoom(room.id)}><b>{room.name}</b><span>{modeInfo(room.game_mode).name} · {fmt(room.mode)} · {room.participant_count ?? 0} técnicos</span></button></li>)}</ul>
        : <p className="rt-sub">Nenhuma sala pública aberta agora. Crie a sua em <b>Jogar</b>.</p>}
    </section>
  </div>;
}
