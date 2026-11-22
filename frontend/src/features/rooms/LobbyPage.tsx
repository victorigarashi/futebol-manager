import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Modal } from "../../components/Modal";
import { ExperiencePicker } from "../career/interactive/ExperiencePicker";
import { RoomToolbar } from "../../components/RoomToolbar";
import { LoadingState } from "../../components/ui/AsyncState";
import { readLocal, writeLocal, removeLocal } from "../../lib/storage";
import { AppHeader } from "../../components/AppHeader";
import { ClubSelectionGrid } from "../../components/ClubSelectionGrid";
import { RoomWizard, type LeagueDraft } from "../../components/RoomWizard";
import { MainMenu } from "../home/MainMenu";
import { PackPage } from "../pack/PackPage";
import { LeagueSettingsSummary } from "../../components/LeagueSettingsSummary";
import { LobbyParticipants } from "../../components/LobbyParticipants";
import { SelectedClubPanel } from "../../components/SelectedClubPanel";
import { MarketPage } from "../market/MarketPage";
import { MarketProgressPage } from "../market/MarketProgressPage";
import { SquadPage } from "../squad/SquadPage";
import { DraftPage } from "../draft/DraftPage";
import { SeasonPage } from "../season/SeasonPage";
import { RetroLobby } from "./RetroLobby";
import { api, ApiError, roomSocketUrl, type Club, type GameMode, type RoomState } from "../../lib/api";
import { useSession } from "../../stores/session";
import { ALL_ROOM_QUERIES, InvalidationBatcher, queriesForEvent } from "../../lib/roomEvents";
import { backoffDelay } from "../../lib/serverHealth";
import { BotSlotsCard } from "../../components/BotSlotsCard";
import { setSocketOnline } from "../../lib/socketBus";

const defaultDraft: LeagueDraft = { name: "Liga dos parças", mode: "FIVE_A_SIDE", initial_budget_cents: 5_000_000_000, market_mode: "TRADITIONAL", team_count: 20, double_round_robin: true, initial_market_duration_seconds: 300, round_preparation_duration_seconds: 300, withdrawal_penalty_percent: 5, max_human_participants: 4, privacy: "PUBLIC", match_duration_seconds: 60, sim_style: "REALISTIC", bot_difficulty: "COMPETITIVE", morale_enabled: false, copa_enabled: false, coach_moves_enabled: false, playoff_format: "SINGLE", execution_mode: "INTERACTIVE", ruleset: "ARCADE", decision_seconds: 10, decision_free_vs_bots: false };
type ConnectionState = "connecting" | "online" | "reconnecting" | "offline";
type LobbyPageProps = { needsProfile: boolean; onEditProfile: () => void; onSaveProfile: (name: string) => Promise<void> };

export function LobbyPage({ needsProfile, onEditProfile, onSaveProfile }: LobbyPageProps) {
  const queryClient = useQueryClient();
  const userId = useSession((state) => state.userId);
  const displayName = useSession((state) => state.displayName);
  const [activeRoom, setActiveRoom] = useState<RoomState | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [choosingClub, setChoosingClub] = useState(false);
  useEffect(() => {
    let active = true;
    const recover = async () => {
      const roomId = readLocal("bm_active_room");
      try {
        if (roomId) {
          const { data } = await api.state(roomId);
          if (active) setActiveRoom(data);
        } else {
          const { data } = await api.myRooms();
          if (active && data.length === 1) setActiveRoom(data[0]);
        }
      } catch (cause) {
        if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) removeLocal("bm_active_room");
        else if (active) setError("Não foi possível retomar a liga agora. Sua sessão foi preservada; tente novamente.");
      } finally { if (active) setRestoring(false); }
    };
    void recover();
    return () => { active = false; };
  }, []);
  useEffect(() => { if (activeRoom) writeLocal("bm_active_room", activeRoom.id); }, [activeRoom]);
  const [joinCode, setJoinCode] = useState(""); const [pendingClub, setPendingClub] = useState<Club | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("offline"); const [error, setError] = useState<string | null>(null);
  const [createMode, setCreateMode] = useState<GameMode | null>(null); const [settingsOpen, setSettingsOpen] = useState(false);
  const [profileName, setProfileName] = useState(""); const [profileError, setProfileError] = useState(""); const [isSavingProfile, setIsSavingProfile] = useState(false);
  const myRooms = useQuery({ queryKey: ["my-rooms"], queryFn: () => api.myRooms().then((result) => result.data), refetchInterval: 10000, enabled: !activeRoom });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.rooms().then((result) => result.data), refetchInterval: 5000, enabled: !activeRoom });
  const clubs = useQuery({ queryKey: ["clubs"], queryFn: () => api.clubs().then((result) => result.data) });
  const roomState = useQuery({ queryKey: ["room-state", activeRoom?.id], queryFn: () => api.state(activeRoom!.id).then((result) => result.data), enabled: Boolean(activeRoom), refetchInterval: 5000 });
  const state = roomState.data ?? activeRoom;
  const roomError = error ?? roomState.error?.message;
  const currentParticipant = useMemo(() => state?.participants.find((participant) => participant.user_id === userId) ?? null, [state?.participants, userId]);
  const selectedClub = useMemo(() => clubs.data?.find((club) => club.code === currentParticipant?.selected_club_code) ?? null, [clubs.data, currentParticipant?.selected_club_code]);

  const activeRoomId = activeRoom?.id;
  useEffect(() => {
    if (!activeRoomId) return;
    let stopped = false;
    let socket: WebSocket | undefined;
    let retry: number | undefined;
    let heartbeat: number | undefined;
    let attempts = 0;
    const refresh = () => {
      void queryClient.invalidateQueries({ predicate: (query) => query.queryKey.includes(activeRoomId) });
      void queryClient.invalidateQueries({ queryKey: ["rooms"] });
      void queryClient.invalidateQueries({ queryKey: ["my-rooms"] });
    };
    // Each event refreshes only what it changes, and bursts become one refresh.
    const batcher = new InvalidationBatcher((keys) => {
      if (keys.has(ALL_ROOM_QUERIES)) { refresh(); return; }
      void queryClient.invalidateQueries({ predicate: (query) => keys.has(String(query.queryKey[0])) && (query.queryKey.includes(activeRoomId) || query.queryKey.length === 1) });
    });
    const connect = () => {
      if (stopped) return;
      // A single socket per tab and room: never open a second one while one is alive.
      if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
      setConnection(attempts ? "reconnecting" : "connecting");
      socket = new WebSocket(roomSocketUrl(activeRoomId));
      socket.onopen = () => {
        // After a reconnection the server may have moved on: resynchronise everything once.
        attempts = 0; setConnection("online"); refresh();
        setSocketOnline(true, (text) => { if (socket?.readyState !== WebSocket.OPEN) return false; socket.send(text); return true; });
        heartbeat = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
        }, 25_000);
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as { type?: string };
          if (event.type === "live.frames") {
            // 2D frames go straight to the canvas buffer, never through React state.
            window.dispatchEvent(new CustomEvent("bm:frames", { detail: event }));
          } else if (event.type === "live.state" || event.type === "live.stats" || event.type === "live.resync") {
            // Sequenced match state: merged into the cached live view (no HTTP refetch).
            window.dispatchEvent(new CustomEvent("bm:live", { detail: event }));
          } else if (event.type === "season.sync" && "data" in event) {
            // The full live view arrives with the socket: use it instead of refetching.
            queryClient.setQueryData(["live", activeRoomId], (event as { data: unknown }).data);
          } else {
            batcher.add(queriesForEvent(event.type));
          }
        } catch { /* A malformed notification must not crash the current game. */ }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = (event) => {
        setSocketOnline(false, null);
        if (heartbeat) window.clearInterval(heartbeat);
        heartbeat = undefined;
        if (stopped) return;
        setConnection(attempts ? "reconnecting" : "offline");
        if (event.code === 1008) { setError("Não foi possível autenticar a conexão da sala. Tente retomar a liga ou recarregar a sessão."); return; }
        // Exponential backoff with jitter: clients do not reconnect in lockstep after a restart.
        retry = window.setTimeout(connect, backoffDelay(attempts, 800, 15_000));
        attempts += 1;
      };
    };
    const online = () => {
      if (!socket || socket.readyState === WebSocket.CLOSED) { window.clearTimeout(retry); connect(); }
      refresh();
    };
    const visible = () => { if (!document.hidden) online(); };
    window.addEventListener("online", online);
    document.addEventListener("visibilitychange", visible);
    connect();
    return () => {
      stopped = true; batcher.cancel(); setSocketOnline(false, null); window.clearTimeout(retry); if (heartbeat) window.clearInterval(heartbeat); socket?.close();
      window.removeEventListener("online", online); document.removeEventListener("visibilitychange", visible);
    };
  }, [activeRoomId, queryClient]);
  useEffect(() => { if (!pendingClub || !state) return; const owner = state.participants.find((participant) => participant.selected_club_code === pendingClub.code); if (owner && owner.user_id !== userId) { setPendingClub(null); setError(`${pendingClub.name} acabou de ser fechado por ${owner.display_name}. Escolha outro clube.`); } }, [pendingClub, state, userId]);
  const refreshRoom = (result: { data: RoomState }) => { setError(null); setActiveRoom(result.data); setChoosingClub(false); void queryClient.invalidateQueries({ queryKey: ["rooms"] }); void queryClient.invalidateQueries({ queryKey: ["room-state", result.data.id] }); };
  const showFailure = (cause: unknown, fallback: string) => setError(cause instanceof Error ? cause.message : fallback);
  const createRoom = useMutation({ mutationFn: (draft: LeagueDraft) => api.createRoom(draft), onSuccess: (result) => { refreshRoom(result); setCreateMode(null); }, onError: (cause) => showFailure(cause, "Não foi possível criar a liga.") });
  const updateRoom = useMutation({ mutationFn: (draft: LeagueDraft) => api.updateRoom(activeRoom!.id, draft), onSuccess: (result) => { refreshRoom(result); setSettingsOpen(false); }, onError: (cause) => showFailure(cause, "Não foi possível atualizar a liga.") });
  const startRoom = useMutation({ mutationFn: () => api.startRoom(activeRoom!.id), onSuccess: refreshRoom, onError: (cause) => showFailure(cause, "Não foi possível iniciar a temporada.") });
  const startSeason = useMutation({ mutationFn: () => api.startSeason(activeRoom!.id), onSuccess: refreshRoom, onError: (cause) => showFailure(cause, "Não foi possível abrir a primeira rodada.") });
  const joinRoom = useMutation({ mutationFn: (roomId: string) => api.joinRoom(roomId), onSuccess: refreshRoom, onError: (cause) => showFailure(cause, "Não foi possível entrar na sala.") });
  const joinByCode = useMutation({ mutationFn: (code: string) => api.joinWithCode(code), onSuccess: refreshRoom, onError: (cause) => showFailure(cause, "Código de sala inválido.") });
  const chooseClub = useMutation({ mutationFn: (clubCode: string) => api.chooseClub(activeRoom!.id, clubCode), onSuccess: (result) => { refreshRoom(result); setPendingClub(null); }, onError: (cause) => showFailure(cause, "Esse clube já não está disponível.") });
  const submitCode = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); joinByCode.mutate(joinCode); };
  const submitProfile = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const normalized = profileName.trim().replace(/\s+/g, " "); if (normalized.length < 3 || normalized.length > 24) { setProfileError("Use entre 3 e 24 caracteres."); return; } if (!/^[\p{L}\p{N} ]+$/u.test(normalized)) { setProfileError("Use apenas letras, números e espaços."); return; } setProfileError(""); setIsSavingProfile(true); void onSaveProfile(normalized).catch((cause: unknown) => setProfileError(cause instanceof Error ? cause.message : "Não foi possível salvar seu nome.")).finally(() => setIsSavingProfile(false)); };

  // A failure belongs to the phase where it happened: never carry it into the next screen.
  useEffect(() => { setError(null); }, [state?.phase]);
  const goHome = () => { setError(null); setActiveRoom(null); removeLocal("bm_active_room"); setPendingClub(null); setChoosingClub(false); void myRooms.refetch(); };
  if (needsProfile) return <main className="landing-shell" id="top"><AppHeader context="onboarding" /><section className="landing-hero" id="main-content"><div className="landing-hero__copy"><p className="section-kicker">O BRASIL INTEIRO. A SUA RESENHA.</p><h1>Futebol sério.<br /><em>Resenha garantida.</em></h1><div className="landing-hero__motto"><span>O futebol é sério.</span><strong>A resenha também.</strong></div><form className="landing-profile-form" onSubmit={submitProfile}><label htmlFor="manager-name">Antes da bola rolar, como a galera vai te chamar?</label><div><input id="manager-name" autoFocus value={profileName} minLength={3} maxLength={24} onChange={(event) => setProfileName(event.target.value)} placeholder="Seu nome de técnico" /><button className="button-primary" disabled={isSavingProfile}>{isSavingProfile ? "Entrando…" : "Bora jogar!"}<span aria-hidden>→</span></button></div>{profileError && <p className="field-error" role="alert">{profileError}</p>}<small>Sem cadastro. Sem VAR. Só chegar e jogar.</small></form><ul className="beta-home-facts"><li>20 clubes do Brasil</li><li>Elencos e táticas</li><li>Partidas ao vivo</li></ul></div><div className="landing-hero__visual" role="img" aria-label="Estádio iluminado e rivalidade entre amigos" /></section><footer className="landing-footer">Futebol se joga junto. A resenha também. <span>Brasileirão Manager © 2026</span></footer></main>;
  if (restoring) return <LoadingState label="Retomando sua carreira…" />;
  if (!activeRoom || !state) return <>{error && <p className="toast feedback--error" role="alert">{error}</p>}{(rooms.error || myRooms.error) && <div className="feedback feedback--error" role="alert"><p>Não foi possível atualizar a lista de ligas. Sua sessão continua preservada.</p><button className="button-secondary" type="button" onClick={() => { void rooms.refetch(); void myRooms.refetch(); }}>Recarregar ligas</button></div>}<MainMenu myRooms={myRooms.data ?? []} displayName={displayName} publicRooms={rooms.data} roomsLoading={rooms.isLoading} joinCode={joinCode} joining={joinByCode.isPending} onJoinCode={submitCode} onCodeChange={setJoinCode} onPickMode={(mode) => { setError(null); setCreateMode(mode); }} onJoinRoom={(id) => joinRoom.mutate(id)} onEditProfile={onEditProfile} />{createMode && <RoomWizard initial={defaultDraft} mode={createMode} isPending={createRoom.isPending} onClose={() => setCreateMode(null)} onChangeMode={() => setCreateMode(null)} onSave={(draft) => { setError(null); createRoom.mutate(draft); }} />}</>;
  if (state.phase === "INITIAL_MARKET") return <main className="app-shell app-shell--reference" id="top"><AppHeader context="room" onHome={goHome} onEditProfile={onEditProfile} /><RoomToolbar room={state} connection={connection} onHome={goHome} /><div id="main-content" tabIndex={-1} />{roomError && <p className="feedback feedback--error" role="alert">{roomError}</p>}<MarketPage roomId={state.id} /></main>;
  if (["MARKET_SELECTION", "MARKET_REASSIGNMENT", "MARKET_REVIEW"].includes(state.phase)) return <main className="app-shell app-shell--reference" id="top"><AppHeader context="room" onHome={goHome} onEditProfile={onEditProfile} /><RoomToolbar room={state} connection={connection} onHome={goHome} /><div id="main-content" tabIndex={-1} />{roomError && <p className="feedback feedback--error" role="alert">{roomError}</p>}<MarketProgressPage roomId={state.id} phase={state.phase} isHost={currentParticipant?.role === "HOST"} /></main>;
  if (state.phase === "DRAFT") return <main className="app-shell app-shell--reference" id="top"><AppHeader context="room" onHome={goHome} onEditProfile={onEditProfile} /><RoomToolbar room={state} connection={connection} onHome={goHome} /><div id="main-content" tabIndex={-1} />{roomError && <p className="feedback feedback--error" role="alert">{roomError}</p>}<DraftPage roomId={state.id} isHost={currentParticipant?.role === "HOST"} clubCode={currentParticipant?.selected_club_code ?? ""} /></main>;
  if (state.phase === "PACK") return <main className="app-shell app-shell--reference" id="top"><AppHeader context="room" onHome={goHome} onEditProfile={onEditProfile} /><RoomToolbar room={state} connection={connection} onHome={goHome} /><div id="main-content" tabIndex={-1} />{roomError && <p className="feedback feedback--error" role="alert">{roomError}</p>}<PackPage roomId={state.id} isHost={currentParticipant?.role === "HOST"} /></main>;
  if (state.phase === "SQUAD_MANAGEMENT") return <main className="app-shell app-shell--reference" id="top"><AppHeader context="room" onHome={goHome} onEditProfile={onEditProfile} /><RoomToolbar room={state} connection={connection} onHome={goHome} /><div id="main-content" tabIndex={-1} />{roomError && <p className="feedback feedback--error" role="alert">{roomError}</p>}<SquadPage roomId={state.id} isHost={currentParticipant?.role === "HOST"} onStartSeason={() => { if (!startSeason.isPending) startSeason.mutate(); }} /></main>;
  if (state.phase === "SEASON_PREPARATION" || state.phase === "TRANSFER_WINDOW") {
    // Retro Career: the career owns its console-style frame; live and post-match screens keep the legacy chrome.
    const legacyChrome = <><AppHeader context="room" onHome={goHome} onEditProfile={onEditProfile} /><RoomToolbar room={state} connection={connection} onHome={goHome} /></>;
    return <SeasonPage roomId={state.id} isHost={currentParticipant?.role === "HOST"} clubCode={currentParticipant?.selected_club_code ?? ""} chrome={{ legacy: legacyChrome, connection, onHome: goHome, onEditProfile, error: roomError }} />;
  }

  const isHost = currentParticipant?.role === "HOST";
  const isLobby = Boolean(selectedClub && !pendingClub && !choosingClub);
  const roomDraft: LeagueDraft = { name: state.name, mode: state.mode, initial_budget_cents: state.initial_budget_cents, market_mode: state.market_mode, team_count: state.team_count, double_round_robin: state.double_round_robin, initial_market_duration_seconds: state.initial_market_duration_seconds, round_preparation_duration_seconds: state.round_preparation_duration_seconds, withdrawal_penalty_percent: state.withdrawal_penalty_percent, max_human_participants: state.max_human_participants, privacy: state.privacy, match_duration_seconds: state.match_duration_seconds ?? 60 , sim_style: state.sim_style ?? "REALISTIC", bot_difficulty: state.bot_difficulty ?? "COMPETITIVE", morale_enabled: Boolean(state.morale_enabled), copa_enabled: Boolean(state.copa_enabled), coach_moves_enabled: Boolean(state.coach_moves_enabled), playoff_format: state.playoff_format ?? "SINGLE", game_mode: state.game_mode ?? "TRADITIONAL", draft_catalog: state.draft_catalog ?? "BRASILEIRAO", draft_min_overall: state.draft_min_overall ?? 0, survivor_eliminations: state.survivor_eliminations ?? 0, pack_luck: state.pack_luck ?? "BALANCED", execution_mode: state.execution_mode ?? "TECHNICAL", ruleset: state.ruleset ?? "ARCADE", decision_seconds: state.decision_seconds ?? 10, decision_free_vs_bots: Boolean(state.decision_free_vs_bots) };
  const settingsDialog = settingsOpen ? <RoomWizard initial={roomDraft} mode={state.game_mode ?? "TRADITIONAL"} editing isPending={updateRoom.isPending} onClose={() => setSettingsOpen(false)} onSave={(draft) => { setError(null); updateRoom.mutate(draft); }} /> : null;
  // Retro Career: the room lobby in the console identity (same components and handlers); club choice keeps the legacy page.
  if (isLobby) return <RetroLobby room={state} clubs={clubs.data ?? []} isHost={isHost} ownClub={selectedClub} managerName={displayName ?? ""} connection={connection} error={roomError} starting={startRoom.isPending} onStart={() => startRoom.mutate()} onEdit={isHost && state.phase === "WAITING" ? () => setSettingsOpen(true) : undefined} onChangeClub={() => setChoosingClub(true)} onHome={goHome} settingsDialog={settingsDialog} />;
  return <><main className="app-shell app-shell--reference" id="top"><AppHeader context="room" onHome={goHome} onEditProfile={onEditProfile} /><RoomToolbar room={state} connection={connection} onHome={goHome} /><div id="main-content" tabIndex={-1} />{roomError && <p className="feedback feedback--error" role="alert">{roomError}</p>}<div className="page-crumb">Vestiário <span>/</span> {isLobby ? "Sala da liga" : "Escolha do clube"}<small>Beta · Edição Resenha</small></div>{isLobby ? <section className="reference-lobby"><button className="back-link" type="button" onClick={() => setChoosingClub(true)}>← Trocar de clube</button><div className="reference-lobby__intro"><div><p className="section-kicker">02 / CONCENTRAÇÃO</p><h1>A galera tá <em>chegando.</em></h1><p>Enquanto isso, já pode ensaiar o discurso de campeão.</p></div><span className={`room-status room-status--${connection}`}>Sala {connection === "online" ? "aberta" : "conectando"}</span></div><div className="reference-lobby__grid"><div className="reference-lobby__column"><LobbyParticipants participants={state.participants} clubs={clubs.data ?? []} /><BotSlotsCard room={state} isHost={isHost} clubs={clubs.data ?? []} />{(state.execution_mode ?? "TECHNICAL") === "INTERACTIVE" && <ExperiencePicker />}</div><LeagueSettingsSummary room={state} isHost={isHost} hasClub={Boolean(selectedClub)} isStarting={startRoom.isPending} onEdit={isHost && state.phase === "WAITING" ? () => setSettingsOpen(true) : undefined} onStart={() => startRoom.mutate()} /></div></section> : <section className="reference-selection"><button className="back-link" type="button" onClick={selectedClub ? () => { setChoosingClub(false); setPendingClub(null); } : goHome}>← Voltar</button><div className="reference-selection__intro"><div><p className="section-kicker">01 / VISTA A CAMISA</p><h1>Qual é o seu <em>lado?</em></h1><p>Escolha quem você vai levar ao topo. A torcida já está esperando.</p></div><div><span className="available-badge">{Math.max(0, state.team_count - state.participants.filter((participant) => participant.selected_club_code).length)} vagas de clube</span><p>{state.name} · {state.mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11"} · {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }).format(state.initial_budget_cents / 100)}</p></div></div>{clubs.isLoading || roomState.isLoading ? <div className="club-loading">Carregando os escudos da rodada…</div> : <ClubSelectionGrid clubs={clubs.data ?? []} participants={state.participants} currentUserId={userId} isLoading={chooseClub.isPending} onSelect={(club) => { setError(null); setPendingClub(club); }} />}<p className="club-selection-help">Selecione um clube livre. Você confirma a escolha no próximo passo.</p>{pendingClub && <Modal className="club-confirm-dialog" titleId="club-confirm-title" onClose={() => setPendingClub(null)} closeDisabled={chooseClub.isPending}><h2 id="club-confirm-title">Seu lugar na resenha</h2><SelectedClubPanel club={pendingClub} managerName={displayName} isPending={chooseClub.isPending} onConfirm={() => chooseClub.mutate(pendingClub.code)} />{error && <p role="alert" className="feedback feedback--error">{error}</p>}</Modal>}</section>}</main>{settingsOpen && <RoomWizard initial={roomDraft} mode={state.game_mode ?? "TRADITIONAL"} editing isPending={updateRoom.isPending} onClose={() => setSettingsOpen(false)} onSave={(draft) => { setError(null); updateRoom.mutate(draft); }} />}</>;
}
