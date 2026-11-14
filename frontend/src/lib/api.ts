export type Club = { code: string; name: string; sort_order: number };
export type Room = {
  id: string;
  code: string;
  name: string;
  mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE";
  initial_budget_cents: number;
  max_human_participants: number;
  privacy: "PUBLIC" | "PRIVATE";
  initial_market_duration_seconds: number;
  round_preparation_duration_seconds: number;
  withdrawal_penalty_percent: 0 | 2 | 5 | 10;
  phase: string;
  revision: number;
  participant_count?: number;
  bot_count?: number;
};
export type Participant = {
  user_id: string;
  display_name: string;
  role: "HOST" | "MEMBER";
  selected_club_code: string | null;
};
export type RoomState = Room & { participants: Participant[] };
export type MarketPlayer = { for_sale?: boolean; base_overall?: number; overall_delta?: number; internal_market_value_cents?: number; id: string; name: string; club_code: string; age: number; position: string; overall: number; potential: number; market_value_cents: number };
export type MarketOffer = { id: string; player_id: string; amount_cents: number; status: string };
export type TransferOffer = { id: string; idempotency_key: string; buyer_club: string; seller_club: string; incoming_player_id: string; offered_player_id: string; amount_cents: number; status: string; counter_cents: number | null };
export type TransferClub = { club_code: string; players: MarketPlayer[] };
export type MarketState = { phase: string; ends_at: number; remaining_seconds: number; resolved: boolean; budget_cents: number; spent_cents: number; reserved_cents: number; available_cents: number; offer_limit: number; active_offer_count: number; withdrawal_penalty_percent: 0 | 2 | 5 | 10; roster: string[]; offers: MarketOffer[] };
export type MarketRight = { offer_id: string; classification: "COMPROMISSADA" | "EXCEDENTE SEM MULTA"; amount_cents: number; player: MarketPlayer };
export type MarketSelection = { phase: string; ends_at: number; remaining_seconds: number; confirmed: boolean; club_code: string; budget_cents: number; reserved_cents: number; available_cents: number; withdrawal_penalty_percent: 0 | 2 | 5 | 10; max_roster_size: number; committed: MarketRight[]; excess: MarketRight[] };
export type MarketSelectionPreview = { selected_offer_ids: string[]; purchase_cents: number; penalties: { offer_id: string; player_id: string; amount_cents: number; penalty_cents: number; percent: number; reason: string }[]; penalty_cents: number; reserved_release_cents: number; debit_cents: number; balance_after_cents: number; generic_players_needed: number; missing_positions: Record<string, number>; withdrawal_penalty_percent: number };
export type MarketReview = { entries: { number: number; total: number; player_id: string; player_name: string; position: string; overall: number; origin_club_code: string; buyer_club_code: string; manager_name: string; amount_cents: number }[]; summary: { player_count: number; total_spent_cents: number; generic_players_by_club: Record<string, number>; balances_cents: Record<string, number>; withdrawals_cents: Record<string, number> } };
export type FormationSlot = { id: string; position: string; x: number; y: number };
export type Formation = { code: string; slots: FormationSlot[] };
export type LineupEvaluation = { slot_id: string; player_id: string; target_position: string; effective_overall: number; improvised: boolean };
export type Lineup = { formation_code: string; assignments: Record<string, string>; evaluation: LineupEvaluation[] };
export type Strategy = { code: string; name: string; effect: string };
export type Squad = { club_code: string; budget_cents: number; players: MarketPlayer[]; formations: Formation[]; lineup: Lineup | null; strategy: string; strategies: Strategy[] };
export type SeasonTableRow = { position: number; club_code: string; points: number; played: number; wins: number; draws: number; losses: number; goals_for: number; goals_against: number; goal_difference: number; percentage: number };
export type MatchEvent = { event_id: string; match_id: string; kind: string; team: string | null; minute: number; animation_ms: number; x: number; y: number; outcome: string; player_id: string | null; player_name?: string; participant_ids: string[]; xg: number };
export type MatchFormation = { code: string; players: { id: string; name: string; x: number; y: number; number: number }[] };
export type LiveRound = { round_number: number; started_at: number; ends_at: number; duration_seconds: number; match_ids: string[] };
export type LiveView = { server_now: number; live_round: LiveRound | null; match: MatchReplay | null; scores: { id: string; home: string; away: string; home_goals: number; away_goals: number }[]; table: SeasonTableRow[]; official_table: SeasonTableRow[]; current_round: number; ready_clubs: string[] };
export type MatchReplay = { id: string; home: string; away: string; home_players: string[]; away_players: string[]; home_goals: number; away_goals: number; home_xg: number; away_xg: number; probabilities?: { home: number; draw: number; away: number }; status: "LIVE" | "FINISHED"; minute: number; started_at?: number; ends_at?: number; home_formation?: MatchFormation; away_formation?: MatchFormation; statistics: Record<string, Record<string, number>>; events: MatchEvent[] };
export type PlayoffMatch = { id: string; stage: string; home: string; away: string; home_goals: number; away_goals: number; winner: string; home_penalties: number | null; away_penalties: number | null };
export type PlayoffView = { qualifiers: string[]; quarterfinals: PlayoffMatch[]; semifinals: PlayoffMatch[]; final: PlayoffMatch | null; champion: string | null; next_stage: string };
export type DevelopmentRecord = { player_id: string; season_number: number; overall_before: number; overall_after: number; delta: number; internal_market_value_cents: number; minutes_played: number; goals: number; reasons: string[] };
export type SeasonTopScorer = { player_id: string; player_name: string; club_code: string; goals: number };
export type SeasonView = { live_round: LiveRound | null; server_now: number; live_table: SeasonTableRow[]; season_number: number; current_round: number; regular_season_complete: boolean; season_complete: boolean; progression_applied: boolean; champion: string | null; playoffs: PlayoffView | null; transfer_window_open: boolean; ready_clubs: string[]; table: SeasonTableRow[]; fixtures: { id: string; round_number: number; home: string; away: string; match_id?: string | null; result: { home_goals: number; away_goals: number } | null }[]; matches: { id: string; round_number: number; home: string; away: string; home_goals: number; away_goals: number }[]; top_scorers: SeasonTopScorer[]; development_records: DevelopmentRecord[]; season_history: { season_number: number; champion: string; table: SeasonTableRow[]; top_scorers?: SeasonTopScorer[] }[] };

export type CareerView = { club_code: string; season_number: number; budget_cents: number; reserved_transfer_cents: number; available_transfer_cents: number; financial_ledger: { operation_id?: string; type?: string; amount_cents?: number; description?: string; player_id?: string }[]; transfers: TransferOffer[]; development_records: DevelopmentRecord[]; season_history: SeasonView["season_history"]; players: MarketPlayer[] };
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = "ApiError"; }
}

type Envelope<T> = { data: T; meta: { revision?: number } };
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    credentials: "include",
    headers: { "content-type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(typeof body?.detail === "string" ? body.detail : "Confira os campos e tente novamente.", response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  catalogStatus: () => request<Envelope<{ loaded: boolean; demo: boolean; reason: string | null }>>("/catalog/status"),
  createGuest: () => request<Envelope<{ id: string; display_name: string }>>("/auth/guest", { method: "POST" }),
  me: () => request<Envelope<{ id: string; display_name: string }>>("/me"),
  updateMe: (display_name: string) => request<Envelope<{ id: string; display_name: string }>>("/me", { method: "PUT", body: JSON.stringify({ display_name }) }),
  clubs: () => request<Envelope<Club[]>>("/clubs"),
  rooms: () => request<Envelope<Room[]>>("/rooms"),
  myRooms: () => request<Envelope<RoomState[]>>("/rooms/mine"),
  state: (roomId: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/state`),
  createRoom: (payload: {
    name: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; initial_budget_cents: number;
    initial_market_duration_seconds: number; round_preparation_duration_seconds: number;
    max_human_participants: number; privacy: "PUBLIC" | "PRIVATE"; withdrawal_penalty_percent: 0 | 2 | 5 | 10;
  }) => request<Envelope<RoomState>>("/rooms", { method: "POST", body: JSON.stringify(payload) }),
  updateRoom: (roomId: string, payload: {
    name: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; initial_budget_cents: number;
    initial_market_duration_seconds: number; round_preparation_duration_seconds: number;
    max_human_participants: number; privacy: "PUBLIC" | "PRIVATE"; withdrawal_penalty_percent: 0 | 2 | 5 | 10;
  }) => request<Envelope<RoomState>>(`/rooms/${roomId}`, { method: "PUT", body: JSON.stringify(payload) }),
  startRoom: (roomId: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/start`, { method: "POST" }),
  market: (roomId: string) => request<Envelope<MarketState>>(`/rooms/${roomId}/market`),
  marketSelection: (roomId: string) => request<Envelope<MarketSelection>>(`/rooms/${roomId}/market/selection`),
  previewMarketSelection: (roomId: string, offer_ids: string[]) => request<Envelope<MarketSelectionPreview>>(`/rooms/${roomId}/market/selection/preview`, { method: "POST", body: JSON.stringify({ offer_ids }) }),
  confirmMarketSelection: (roomId: string, offer_ids: string[]) => request<Envelope<Record<string, unknown>>>(`/rooms/${roomId}/market/selection/confirm`, { method: "POST", body: JSON.stringify({ offer_ids }) }),
  marketReassignment: (roomId: string) => request<Envelope<{ phase: string; opportunity: { player_id: string; offer_id: string; club_code: string; amount_cents: number; player: MarketPlayer; ends_at: number; remaining_seconds: number } | null }>>(`/rooms/${roomId}/market/reassignment`),
  respondMarketReassignment: (roomId: string, offerId: string, accept: boolean) => request<Envelope<Record<string, unknown>>>(`/rooms/${roomId}/market/reassignment/${offerId}`, { method: "POST", body: JSON.stringify({ accept }) }),
  marketReview: (roomId: string) => request<Envelope<MarketReview>>(`/rooms/${roomId}/market/review`),
  completeMarketReview: (roomId: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/market/review/complete`, { method: "POST" }),
  marketPlayers: (roomId: string, filters: { query?: string; position?: string; min_overall?: number; max_overall?: number; min_price_cents?: number; max_price_cents?: number } = {}) => request<Envelope<MarketPlayer[]>>(`/rooms/${roomId}/market/players?${new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== undefined && value !== "").map(([key, value]) => [key, String(value)] as [string, string])).toString()}`),
  createOffer: (roomId: string, payload: { player_id: string; amount_cents: number; idempotency_key: string }) => request<Envelope<MarketOffer>>(`/rooms/${roomId}/market/offers`, { method: "POST", body: JSON.stringify(payload) }),
  marketPlayer: (roomId: string, playerId: string) => request<Envelope<MarketPlayer>>(`/rooms/${roomId}/market/players/${playerId}`),
  updateOffer: (roomId: string, offerId: string, amount_cents: number) => request<Envelope<MarketOffer>>(`/rooms/${roomId}/market/offers/${offerId}`, { method: "PUT", body: JSON.stringify({ amount_cents }) }),
  cancelOffer: (roomId: string, offerId: string) => request<Envelope<MarketOffer>>(`/rooms/${roomId}/market/offers/${offerId}`, { method: "DELETE" }),
  marketResult: (roomId: string) => request<Envelope<{ club_code: string; budget_cents: number; roster: MarketPlayer[]; offers: MarketOffer[] }>>(`/rooms/${roomId}/market/result`),
  squad: (roomId: string) => request<Envelope<Squad>>(`/rooms/${roomId}/squad`),
  saveLineup: (roomId: string, payload: { formation_code: string; assignments: Record<string, string> }) => request<Envelope<Lineup>>(`/rooms/${roomId}/squad/lineup`, { method: "PUT", body: JSON.stringify(payload) }),
  saveStrategy: (roomId: string, strategy: string) => request<Envelope<{ strategy: string; name: string; effect: string }>>(`/rooms/${roomId}/squad/strategy`, { method: "PUT", body: JSON.stringify({ strategy }) }),
  startSeason: (roomId: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/season/start`, { method: "POST" }),
  season: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season`),
  live: (roomId: string) => request<Envelope<LiveView>>(`/rooms/${roomId}/season/live`),
  readyForRound: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/ready`, { method: "POST" }),
  advanceRound: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/advance`, { method: "POST" }),
  closeTransferWindow: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/transfer-window/close`, { method: "POST" }),
  startNextSeason: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/next`, { method: "POST" }),
  career: (roomId: string) => request<Envelope<CareerView>>(`/rooms/${roomId}/career`),
  listTransferPlayer: (roomId: string, player_id: string, listed: boolean) => request<Envelope<{ player_id: string; listed: boolean }>>(`/rooms/${roomId}/transfers/listings`, { method: "PUT", body: JSON.stringify({ player_id, listed }) }),
  transferClubs: (roomId: string) => request<Envelope<TransferClub[]>>(`/rooms/${roomId}/transfers/clubs`),
  transferPlayers: (roomId: string) => request<Envelope<MarketPlayer[]>>(`/rooms/${roomId}/transfers/available`),
  transferOffers: (roomId: string) => request<Envelope<TransferOffer[]>>(`/rooms/${roomId}/transfers`),
  buyTransferPlayer: (roomId: string, payload: { incoming_player_id: string; replace_player_id: string; amount_cents: number; operation_id: string }) => request<Envelope<Record<string, unknown>>>(`/rooms/${roomId}/transfers/buy`, { method: "POST", body: JSON.stringify(payload) }),
  createTransferOffer: (roomId: string, payload: { incoming_player_id: string; offered_player_id: string; amount_cents: number; idempotency_key: string }) => request<Envelope<TransferOffer>>(`/rooms/${roomId}/transfers/offers`, { method: "POST", body: JSON.stringify(payload) }),
  acceptTransfer: (roomId: string, offerId: string) => request<Envelope<TransferOffer>>(`/rooms/${roomId}/transfers/offers/${offerId}/accept`, { method: "POST" }),
  rejectTransfer: (roomId: string, offerId: string) => request<Envelope<TransferOffer>>(`/rooms/${roomId}/transfers/offers/${offerId}/reject`, { method: "POST" }),
  cancelTransfer: (roomId: string, offerId: string) => request<Envelope<TransferOffer>>(`/rooms/${roomId}/transfers/offers/${offerId}/cancel`, { method: "POST" }),
  counterTransfer: (roomId: string, offerId: string, amount_cents: number) => request<Envelope<TransferOffer>>(`/rooms/${roomId}/transfers/offers/${offerId}/counter`, { method: "POST", body: JSON.stringify({ amount_cents }) }),
  match: (roomId: string, matchId: string) => request<Envelope<MatchReplay>>(`/rooms/${roomId}/matches/${matchId}`),
  joinRoom: (roomId: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/join`, { method: "POST" }),
  joinWithCode: (code: string) => request<Envelope<RoomState>>("/rooms/join", { method: "POST", body: JSON.stringify({ code }) }),
  chooseClub: (roomId: string, club_code: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/participants/me/club`, { method: "PUT", body: JSON.stringify({ club_code }) }),
};

export function roomSocketUrl(roomId: string): string {
  const url = new URL(baseUrl, globalThis.location?.origin ?? "http://localhost");
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/api/v1/ws/rooms/${roomId}`;
  return url.toString();
}
