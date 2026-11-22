import { reportServerHealth } from "./serverHealth";
import { readLocal, writeLocal } from "./storage";

export type MatchDuration = 60 | 90 | 120 | 180;
export type MatchStyle = "REALISTIC" | "EXCITING";
export type BotDifficulty = "CASUAL" | "COMPETITIVE" | "LEGENDARY";
export type PlayoffFormat = "SINGLE" | "TWO_LEGS";
/** League rules chosen when the room is created (editable until the season starts). */
export type GameMode = "TRADITIONAL" | "DRAFT" | "DRAFT_KNOCKOUT" | "SURVIVOR" | "PACK";
export type LeagueRules = { game_mode: GameMode; sim_style: MatchStyle; bot_difficulty: BotDifficulty; morale_enabled: boolean; copa_enabled: boolean; coach_moves_enabled: boolean; playoff_format: PlayoffFormat; draft_catalog: "BRASILEIRAO" | "WORLD"; draft_min_overall: number; survivor_eliminations: 0 | 2 | 4; pack_luck: "BALANCED" | "LUCK"; execution_mode: ExecutionMode; ruleset: Ruleset; decision_seconds: DecisionSeconds; decision_free_vs_bots: boolean };
/** Modo Jogável (decisive moments) or the technical 2D simulation. */
export type ExecutionMode = "TECHNICAL" | "INTERACTIVE";
export type Ruleset = "ARCADE" | "TRADITIONAL";
export type DecisionSeconds = 5 | 10 | 15 | 20;
export type InteractiveActionType = "PASS" | "LOFT" | "CARRY" | "SHOT";
/**
 * One physics frame in normalised pitch units (roster order).
 * Layout "v6": [t, ballX, ballY, ballZ, x0, y0, x1, y1, ...].
 * Layout "v7": [t, ballX, ballY, ballZ, x0, y0, facing0, act0, x1, y1, facing1, act1, ...]
 * (facing in radians in pitch metres; act = action state code, see render/presentation.ts).
 */
export type InteractiveFrame = number[];
export type InteractiveStep = { by: "HUMAN" | "AI" | "TIMEOUT" | "AI_TAKEOVER" | "AI_CONTROL"; type: InteractiveActionType; aim: { x: number; y: number }; power: number; carrier: string; outcome: string; detail: string; frames: InteractiveFrame[]; duration: number; starts_at: number; receiver: string | null;
  shooter?: string | null; post?: boolean; layout?: "v6" | "v7" | "v8";
  /** Timed moments of the action (seconds from its start) for animation and sound: KICK, CONTROL, SAVE, POST, GOAL, TACKLE, HEADER, DIVE… */
  cues?: InteractiveCue[] };
export type MatchKit = { id: string; shirt: string; shorts: string; socks: string; trim: string; number: string; pattern: "plain" | "stripes" | "hoops" | "sash"; generic: boolean };
export type InteractiveCue = { t: number; kind: string; id: string | null; action?: InteractiveActionType; power?: number; hold?: boolean; dy?: number; past?: string; windup?: number; level?: "low" | "mid" | "high"; high?: boolean; touched?: boolean };
export type InteractiveOpportunity = {
  id: string; kind: string; label: string; attacking: string; defending: string; minute: number; status: string; result: string | null;
  actions: number; max_actions: number; carrier: string; roster: { id: string; name: string; number: number; team: "A" | "D"; role: string }[];
  positions: [number, number][]; ball: [number, number]; last: InteractiveStep | null; replay: InteractiveStep[] | null; opened_at: number;
  /** V7: [facing (rad, pitch metres), speed m/s] per athlete at the decision (frozen in motion). */
  motion?: [number, number][];
  /** Real direction of the attacking club in this half (true = towards x = 1). Every coordinate is already on the real pitch. */
  right?: boolean;
};
export type InteractiveView = {
  match_id: string | null; unchanged?: boolean; home: string; away: string; state: "NONE" | "CLOCK" | "DECISION" | "EXECUTING" | "REPLAY" | "OUTCOME" | "HALF_TIME" | "FINISHED";
  revision: number; minute: number; clock_rate: number; score: { home: number; away: number }; server_now: number; deadline: number | null;
  decision_seconds: number; state_until: number | null; grace_until: number | null; you: string | null; your_turn: boolean; controller: "HUMAN" | "AI" | null;
  ai_control: string[]; humans: string[]; connected: Record<string, boolean>; opportunity: InteractiveOpportunity | null; ruleset: Ruleset;
  pitch: { length: number; width: number; goal: number; box: number; post?: number };
  half?: 1 | 2; attacks_right?: Record<string, boolean>;
  /** Official kit selection of the match (chosen by the server, identical in 2D and 3D). */
  kits?: { home: MatchKit; away: MatchKit; home_gk: MatchKit; away_gk: MatchKit };
  physics: { pass: [number, number]; loft?: [number, number]; loft_range: [number, number]; shot: [number, number]; carry: [number, number]; decel: number; assist_angle?: number;
    /** V7 physics model: rolling resistance [constant m/s², drag 1/m] — the forecast integrates the same equation. */
    model?: "v7"; roll?: [number, number]; loft_angle?: [number, number] };
  engine?: "v6" | "v7" | "v8"; difficulty?: "EASY" | "NORMAL" | "HARD";
  events: MatchEvent[]; stats: Record<string, Record<string, number>>;
};
export type InteractiveActionPayload = { action_id: string; opportunity_id: string; revision: number; type: InteractiveActionType; x: number; y: number; power: number };
export type SurvivorRow = { club_code: string; position: number; points: number; gf: number; ga: number; gd: number; total_points: number; total_gd: number };
export type SurvivorView = {
  seed: string; clubs: string[]; configured: number; active: string[]; remaining: number; path: number[];
  eliminated: { club: string; round: number; position: number }[];
  rounds: { number: number; pairs: string[][]; results: Record<string, number[]>; table: SurvivorRow[]; eliminated: string[]; final: boolean }[];
  totals: Record<string, number[]>; champion: string | null; runner_up: string | null;
};
export type PackCard = { id: string; name: string; position: string; secondary_positions: string[]; overall: number; club_code: string; photo_url?: string | null; tier: "OURO" | "PRATA" | "BRONZE"; attributes: Record<string, number> };
export type PackView = {
  club: string; packs_total: number; opened: number; packs: PackCard[][]; formation: string | null; slots: Record<string, string | null>; bench: string[];
  confirmed: boolean; bench_size: number; problems: string[]; formations: Formation[]; deadline: number | null; server_now: number; completed: boolean;
  luck: "BALANCED" | "LUCK"; catalog: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; managers: { club_code: string; confirmed: boolean; opened: number; bot: boolean }[];
};
export type Club = { code: string; name: string; sort_order: number };
export type Room = {
  id: string;
  code: string;
  name: string;
  mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE";
  initial_budget_cents: number;
  /** Traditional BRL-budget market or the equal 100-coin draft market. */
  market_mode: "TRADITIONAL" | "COINS";
  team_count: 4 | 6 | 8 | 10 | 12 | 16 | 20;
  double_round_robin: boolean;
  max_human_participants: number;
  privacy: "PUBLIC" | "PRIVATE";
  initial_market_duration_seconds: number;
  round_preparation_duration_seconds: number;
  withdrawal_penalty_percent: 0 | 2 | 5 | 10;
  /** Real duration of each live match (90 game minutes condensed): 60, 90, 120 or 180 s. */
  match_duration_seconds?: MatchDuration;
  phase: string;
} & Partial<LeagueRules> & {
  revision: number;
  participant_count?: number;
  bot_count?: number;
  available_slots?: number;
};
export type Participant = {
  user_id: string;
  display_name: string;
  role: "HOST" | "MEMBER" | "BOT";
  selected_club_code: string | null;
};
export type RoomState = Room & { participants: Participant[] };
export type MarketPlayer = { for_sale?: boolean; base_overall?: number; overall_delta?: number; internal_market_value_cents?: number; id: string; name: string; club_code: string; age: number; position: string; overall: number; potential: number; market_value_cents: number; photo_url?: string | null; shirt_number?: number | null; squad_role?: "STARTER" | "RESERVE" | null };
export type MarketOffer = { id: string; player_id: string; amount_cents: number; status: string };
export type TransferOffer = { id: string; idempotency_key: string; buyer_club: string; seller_club: string; incoming_player_id: string; offered_player_id: string; amount_cents: number; status: string; counter_cents: number | null; origin?: "HUMAN" | "BOT"; expires_at?: number | null; kind?: "TRADE" | "PURCHASE" | "LOAN"; reason?: string | null };
export type TransferClub = { club_code: string; players: MarketPlayer[] };
export type MarketState = { phase: string; ends_at: number; remaining_seconds: number; resolved: boolean; market_mode: "TRADITIONAL" | "COINS"; currency: "CENTS" | "COINS"; budget_cents: number; spent_cents: number; reserved_cents: number; available_cents: number; offer_limit: number; active_offer_count: number; withdrawal_penalty_percent: 0 | 2 | 5 | 10; roster: string[]; offers: MarketOffer[] };
export type MarketRight = { offer_id: string; classification: "COMPROMISSADA" | "EXCEDENTE SEM MULTA"; amount_cents: number; player: MarketPlayer };
export type MarketSelection = { phase: string; ends_at: number; remaining_seconds: number; confirmed: boolean; club_code: string; budget_cents: number; reserved_cents: number; available_cents: number; withdrawal_penalty_percent: 0 | 2 | 5 | 10; max_roster_size: number; committed: MarketRight[]; excess: MarketRight[] };
export type MarketSelectionPreview = { selected_offer_ids: string[]; purchase_cents: number; penalties: { offer_id: string; player_id: string; amount_cents: number; penalty_cents: number; percent: number; reason: string }[]; penalty_cents: number; reserved_release_cents: number; debit_cents: number; balance_after_cents: number; generic_players_needed: number; missing_positions: Record<string, number>; withdrawal_penalty_percent: number };
export type MarketReview = { entries: { number: number; total: number; player_id: string; player_name: string; position: string; overall: number; origin_club_code: string; buyer_club_code: string; manager_name: string; amount_cents: number }[]; summary: { player_count: number; total_spent_cents: number; generic_players_by_club: Record<string, number>; balances_cents: Record<string, number>; withdrawals_cents: Record<string, number> } };
export type FormationSlot = { id: string; position: string; x: number; y: number };
export type Formation = { code: string; slots: FormationSlot[] };
export type LineupEvaluation = { slot_id: string; player_id: string; target_position: string; effective_overall: number; improvised: boolean };
export type Lineup = { formation_code: string; assignments: Record<string, string>; evaluation: LineupEvaluation[] };
export type Strategy = { code: string; name: string; effect: string };
export type Tactics = { mentality: Mentality; pressure: Pressure; style: PlayStyle };
export type Mentality = "VERY_DEFENSIVE" | "DEFENSIVE" | "BALANCED" | "ATTACKING" | "VERY_ATTACKING";
export type Pressure = "LOW" | "MEDIUM" | "HIGH";
export type PlayStyle = "POSSESSION" | "COUNTER" | "DIRECT" | "SHORT_BUILDUP" | "WIDE";
export type TacticOption = { code: string; name: string; effect: string };
export type TacticsOptions = { mentality: TacticOption[]; pressure: TacticOption[]; style: TacticOption[] };
export type SquadPlayer = MarketPlayer & { provenance?: { overall: string; attributes: string }; secondary_positions?: string[]; attributes?: Record<string, number>; match_attributes?: Record<string, number>; attributes_derived?: boolean; nationality?: string | null };
export type Squad = { club_code: string; budget_cents: number; players: SquadPlayer[]; formations: Formation[]; lineup: Lineup | null; strategy: string; strategies: Strategy[]; tactics: Tactics; tactics_options: TacticsOptions; instructions?: Record<string, string>; instruction_options?: InstructionOptions; cohesion?: CohesionView | null };
export type SeasonTableRow = { position: number; club_code: string; points: number; played: number; wins: number; draws: number; losses: number; goals_for: number; goals_against: number; goal_difference: number; percentage: number };
export type MatchEvent = { event_id: string; match_id: string; kind: string; team: string | null; minute: number; animation_ms: number; x: number; y: number; outcome: string; player_id: string | null; player_name?: string; participant_ids: string[]; xg: number };
export type MatchFormation = { code: string; players: { id: string; name: string; x: number; y: number; number: number }[] };
export type LiveRound = { kind?: "LEAGUE" | "PLAYOFF" | "CUP" | "TOURNAMENT" | "SURVIVOR"; stage?: string; leg?: number; legs?: number; label?: string; round_number: number; announced_at?: number; started_at: number; ends_at: number; duration_seconds: number; match_seconds?: MatchDuration; match_ids: string[]; human_clubs?: string[] };
export type MatchPhase = "PRESENTATION" | "FIRST_HALF" | "HALF_TIME" | "SECOND_HALF" | "FULL_TIME";
export type LiveClock = { tick: number; minute: number; phase: MatchPhase; server_now: number; match_seconds?: MatchDuration; segment?: BroadcastSegment["k"] | null; halftime_ends_at: number | null; ends_at: number; kickoff_at: number };
export type PlayerStats = { passes: number; passes_completed: number; key_passes: number; shots: number; shots_on_target: number; goals: number; assists: number; tackles: number; interceptions: number; fouls: number; saves: number; dribbles: number; losses: number; distance: number };
export type MatchPlayer = { id: string; name: string; number: number; role: string; position: string; overall: number; index: number; on_pitch: boolean; sent_off: boolean; yellow_cards: number; stamina: number; entered_tick: number | null; left_tick: number | null; available: boolean; rating: number; stats: PlayerStats; attributes: Record<string, number> };
export type CommandStatus = { command_id: string; kind: "TACTICS" | "SUBSTITUTION" | "FORMATION"; formation_code?: string; status: "PENDING" | "APPLIED" | "REJECTED"; applied_tick?: number; requested_tick?: number; out_player_id?: string; in_player_id?: string; tactics?: Tactics; reason?: string };
export type EngineEvent = { event_id: string; match_id: string; kind: string; team: string | null; tick: number; minute: number; x: number; y: number; outcome: string; player_id: string | null; player_name: string | null; secondary_player_id?: string | null; secondary_player_name?: string | null; xg: number; score?: { home: number; away: number }; header?: boolean; tactics?: Tactics | null };
export type LiveMatch = { id: string; home: string; away: string; tick: number; minute: number; phase: MatchPhase; home_goals: number; away_goals: number; home_xg: number; away_xg: number; status: "LIVE" | "FINISHED"; statistics: Record<string, Record<string, number>>; events: EngineEvent[]; tactics: { home: Tactics | null; away: Tactics | null }; formations: { home: string; away: string }; lineups: { home: MatchPlayer[]; away: MatchPlayer[] }; substitutions: { home: { used: number; windows_used: number; pending: number }; away: { used: number; windows_used: number; pending: number }; max: number; windows: number | null }; ball_in_play: boolean; pitch: { length: number; width: number; goal: number; box: number }; you: "home" | "away" | null; commands?: CommandStatus[]; ordered_tactics?: Tactics; clock?: LiveClock; player_of_the_match?: { id: string; name: string; rating: number } | null; home_penalties?: number | null; away_penalties?: number | null };
/** b = [x, y, owner index or -1, ball state (0 live, 1 dead ball, 2 in flight)]. */
export type FrameRow = { t: number; b: [number, number, number, number?]; p: number[] };
/** One stretch of the condensed broadcast: ticks t0→t1 shown between server times r0→r1. */
export type BroadcastSegment = { k: "PLAY" | "CUT" | "BREAK"; t0: number; t1: number; r0: number; r1: number; label: string };
export type FramesView = { match_id?: string; tick: number | null; phase?: MatchPhase; finished?: boolean; server_now?: number; score?: { home: number; away: number }; event_count?: number; frames: FrameRow[]; broadcast?: BroadcastSegment[] };
export type PreviewSide = { club_code: string; formation_code: string; starters: { id: string; name: string; position: string; slot_position: string; overall: number; improvised: boolean; number: number }[]; bench_size: number; tactics: Tactics | null; average: number; sectors: Record<string, number>; ready: boolean; human: boolean | null; manager?: string | null };
export type SpecialEvent = { kind: string; title: string; text: string };
export type HeadToHead = { meetings: number; wins: Record<string, number>; draws: number; goals: Record<string, number>; last: { home: string; away: string; home_goals: number; away_goals: number; season?: number; competition?: string }[] };
export type MatchPreview = { next_round_starts_at?: number | null; server_now?: number;
  fixture: { id: string; round_number: number; home: string; away: string; competition?: "PLAYOFF" | "CUP" | "TOURNAMENT" | "SURVIVOR"; stage?: string; stage_name?: string; leg?: number | null; legs?: number | null } | null;
  home?: PreviewSide; away?: PreviewSide; waiting?: boolean; next_round?: NextRoundView;
  classic?: string | null; head_to_head?: HeadToHead; special_events?: SpecialEvent[]; morale?: Record<string, number> | null;
};
export type Competition = "PLAYOFF" | "CUP" | "TOURNAMENT" | "SURVIVOR";
export type TieView = {
  id: string; competition: Competition; stage: string; stage_name: string; high: string; low: string; legs: 1 | 2; order: number;
  leg_scores: number[][]; penalties: number[] | null; winner: string | null; aggregate: [number, number]; match_ids: string[]; fixtures: string[][];
};
export type KnockoutRoundView = { id: string; competition: Competition; stage: string; leg: number; after_round: number; tie_ids: string[]; status: "PENDING" | "DONE"; stage_name: string; competition_name: string };
export type DrawRecord = { competition: Competition; stage: string; stage_name: string; pairs: string[][]; kind: string; pot1?: string[]; pot2?: string[]; rule?: string; seed?: string };
export type KnockoutView = {
  ties: Record<string, TieView>; rounds: KnockoutRoundView[]; draws: DrawRecord[];
  cup_enabled: boolean; cup_seeds: string[]; cup_champion: string | null; cup_runner_up: string | null; playoff_runner_up: string | null;
};
/** The server is authoritative about the next fixture.  Short modes use the same
 * shape as league/playoff rounds, but identify their own competition here. */
export type NextRoundView = { kind: "LEAGUE" | "PLAYOFF" | "CUP" | "TOURNAMENT" | "SURVIVOR"; round_number?: number; stage?: string; stage_name?: string; leg?: number; fixtures?: { id: string; home: string; away: string; tie_id: string }[] } | null;
export type PlayerSeasonStats = { player_id: string; name: string; club_code: string; position: string; apps: number; minutes: number; goals: number; assists: number; rating: number | null; goals_per_match: number; saves: number; clean_sheets: number };
export type CareerStats = {
  season_number: number; competition: string | null; scorers: PlayerSeasonStats[]; assists: PlayerSeasonStats[]; ratings: PlayerSeasonStats[]; goalkeepers: PlayerSeasonStats[];
  team_of_season: PlayerSeasonStats[]; records: { biggest_win?: CompactResult; most_goals?: CompactResult };
  coaches: { club_code: string; coach: string; played: number; wins: number; draws: number; losses: number }[];
  rivals: ({ clubs: string[] } & HeadToHead)[];
  development: (DevelopmentRecord & { name?: string })[];
  history: { season_number: number; champion: string | null; runner_up: string | null; cup_champion: string | null; league_leader: string | null; best_player: PlayerSeasonStats | null; best_goalkeeper: PlayerSeasonStats | null }[];
};
export type CompactResult = { season: number; id: string; competition: string; stage: string | null; home: string; away: string; home_goals: number; away_goals: number };
export type Trophy = { season_number: number; competition: "BRASILEIRAO" | "COPA_DO_BRASIL"; place: "CHAMPION" | "RUNNER_UP"; club_code: string; coach_user_id: string | null; coach_name: string | null };
export type NewsItem = { id: string; season_number: number; kind: string; clubs: string[]; title: string; body: string };
export type LiveCommandPayload = { kind: "TACTICS"; mentality?: Mentality; pressure?: Pressure; style?: PlayStyle } | { kind: "SUBSTITUTION"; out_player_id: string; in_player_id: string } | { kind: "FORMATION"; formation_code: string };
/** Entrosamento tático: compatibility + familiarity → bounded engine factor (see docs/ENTROSAMENTO.md). */
export type CohesionView = { compatibility: number; compatibility_label: string; familiarity: number; familiarity_label: string; factor: number; players: { player_id: string; fit: number; estimated: boolean }[]; estimated_share: number; notes: string[]; style: PlayStyle; familiarity_by_style: Record<PlayStyle, number>; formation_code: string; instructions: Record<string, string> };
export type InstructionOption = { code: string; name: string; effect: string };
export type InstructionOptions = Record<"GK" | "FB" | "CB" | "MF" | "ST", InstructionOption[]>;
export type DraftCard = { id: string; name: string; overall: number; potential: number; position: string; secondary_positions: string[]; club_code: string; club_name?: string | null; nationality?: string | null; age?: number | null; attributes: Record<string, number>; photo_url?: string | null; source: string; verification_status?: string | null };
export type DraftPick = { instance_id: string; catalog_id: string; card: DraftCard };
export type DraftView = { formations: Formation[]; room_id: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; catalog: "BRASILEIRAO" | "WORLD"; min_overall: number; deadline: number | null; server_now: number; completed: boolean; bench_size: number; formation: string | null; slots: Record<string, DraftPick | null>; bench: DraftPick[]; open_offers: Record<string, DraftCard[]>; warnings: string[]; complete: boolean; progress: Record<string, { picks: number; total: number | null; bot: boolean }> };
export type LiveView = { round_state?: RoundState; recovering?: boolean; server_now: number; live_round: LiveRound | null; clock?: LiveClock | null; broadcast?: BroadcastSegment[] | null; match: LiveMatch | null; scores: { id: string; home: string; away: string; home_goals: number; away_goals: number; minute?: number; status?: string }[]; table: SeasonTableRow[]; official_table: SeasonTableRow[]; current_round: number; ready_clubs: string[]; interactive?: string | null };
export type MatchReplay = { id: string; home: string; away: string; home_players: string[]; away_players: string[]; home_goals: number; away_goals: number; home_xg: number; away_xg: number; probabilities?: { home: number; draw: number; away: number }; status: "LIVE" | "FINISHED"; minute: number; started_at?: number; ends_at?: number; home_formation?: MatchFormation; away_formation?: MatchFormation; statistics: Record<string, Record<string, number>>; events: MatchEvent[] };
export type PlayoffMatch = { id: string; stage: string; home: string; away: string; home_goals: number; away_goals: number; winner: string; home_penalties: number | null; away_penalties: number | null };
export type PlayoffView = { qualifiers: string[]; quarterfinals: PlayoffMatch[]; semifinals: PlayoffMatch[]; final: PlayoffMatch | null; champion: string | null; next_stage: string };
export type DevelopmentRecord = { player_id: string; season_number: number; overall_before: number; overall_after: number; delta: number; internal_market_value_cents: number; minutes_played: number; goals: number; reasons: string[] };
export type SeasonTopScorer = { player_id: string; player_name: string; club_code: string; goals: number };
export type ScheduleRow = { id: string; round_number: number; home: string; away: string; result: { home_goals: number; away_goals: number } | null };
export type RoundState = "PREPARING" | "READY" | "STARTING" | "LIVE" | "FINISHED" | "RECOVERING";
export type SeasonView = { game_mode?: GameMode; survivor?: SurvivorView | null; knockout?: KnockoutView; next_round?: NextRoundView; rules?: Partial<LeagueRules>; preseason_window?: boolean; total_rounds?: number; round_state?: RoundState; human_clubs?: string[]; recovering?: boolean; live_round: LiveRound | null; server_now: number; preparation_opened_at?: number | null; schedule?: ScheduleRow[]; live_table: SeasonTableRow[]; season_number: number; current_round: number; regular_season_complete: boolean; season_complete: boolean; progression_applied: boolean; champion: string | null; playoffs: PlayoffView | null; transfer_window_open: boolean; ready_clubs: string[]; table: SeasonTableRow[]; fixtures: { id: string; round_number: number; home: string; away: string; match_id?: string | null; result: { home_goals: number; away_goals: number } | null }[]; matches: { id: string; round_number: number; home: string; away: string; home_goals: number; away_goals: number }[]; top_scorers: SeasonTopScorer[]; development_records: DevelopmentRecord[]; season_history: { season_number: number; champion: string; table: SeasonTableRow[]; top_scorers?: SeasonTopScorer[] }[] };

export type CareerView = { club_code: string; season_number: number; budget_cents: number; reserved_transfer_cents: number; available_transfer_cents: number; financial_ledger: { operation_id?: string; type?: string; amount_cents?: number; description?: string; player_id?: string }[]; transfers: TransferOffer[]; development_records: DevelopmentRecord[]; season_history: SeasonView["season_history"]; players: MarketPlayer[] };
/** network: no answer at all · unavailable: proxy/server down (502/503/504) · client: the game said no (4xx). */
export type ApiErrorKind = "network" | "unavailable" | "server" | "client";
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = "ApiError"; }
  get kind(): ApiErrorKind {
    if (this.status === 0) return "network";
    if (this.status === 502 || this.status === 503 || this.status === 504) return "unavailable";
    return this.status >= 500 ? "server" : "client";
  }
  /** Worth retrying automatically (the request may succeed in a moment). */
  get transient(): boolean { return this.kind !== "client" || this.status === 408 || this.status === 429; }
}

const UNAVAILABLE = "O servidor está reiniciando ou indisponível. Tentando de novo automaticamente…";
const OFFLINE = "Sem conexão com o servidor. Verifique sua internet; tentando de novo…";

type Envelope<T> = { data: T; meta: { revision?: number } };
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const SESSION_TOKEN_KEY = "bm_session_token";

type Identity = { id: string; display_name: string; session_token?: string };

function accessToken(): string | null { return readLocal(SESSION_TOKEN_KEY); }
function rememberToken(identity: Identity): Identity {
  if (identity.session_token) writeLocal(SESSION_TOKEN_KEY, identity.session_token);
  return identity;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      credentials: "include",
      headers: { "content-type": "application/json", ...(accessToken() ? { authorization: `Bearer ${accessToken()}` } : {}), ...init?.headers },
      ...init,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    // fetch() only rejects when there is no HTTP answer at all. (A 502 from the proxy
    // has no CORS headers, so browsers also report it this way, as a "CORS error".)
    reportServerHealth("network");
    throw new ApiError(OFFLINE, 0);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    const error = new ApiError(typeof body?.detail === "string" ? body.detail : "Confira os campos e tente novamente.", response.status);
    if (error.kind === "unavailable" || error.kind === "server") {
      reportServerHealth("unavailable");
      throw new ApiError(UNAVAILABLE, response.status);
    }
    reportServerHealth("ok");
    throw error;
  }
  reportServerHealth("ok");
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  catalogStatus: () => request<Envelope<{ loaded: boolean; demo: boolean; reason: string | null }>>("/catalog/status"),
  createGuest: () => request<Envelope<Identity>>("/auth/guest", { method: "POST" }).then((result) => ({ ...result, data: rememberToken(result.data) })),
  me: () => request<Envelope<Identity>>("/me"),
  updateMe: (display_name: string) => request<Envelope<Identity>>("/me", { method: "PUT", body: JSON.stringify({ display_name }) }).then((result) => ({ ...result, data: rememberToken(result.data) })),
  clubs: () => request<Envelope<Club[]>>("/clubs"),
  rooms: () => request<Envelope<Room[]>>("/rooms"),
  myRooms: () => request<Envelope<RoomState[]>>("/rooms/mine"),
  state: (roomId: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/state`),
  createRoom: (payload: {
    name: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; initial_budget_cents: number;
    market_mode: "TRADITIONAL" | "COINS"; team_count: 4 | 6 | 8 | 10 | 12 | 16 | 20; double_round_robin: boolean;
    initial_market_duration_seconds: number; round_preparation_duration_seconds: number;
    max_human_participants: number; privacy: "PUBLIC" | "PRIVATE"; withdrawal_penalty_percent: 0 | 2 | 5 | 10; match_duration_seconds?: MatchDuration;
  } & Partial<LeagueRules>) => request<Envelope<RoomState>>("/rooms", { method: "POST", body: JSON.stringify(payload) }),
  updateRoom: (roomId: string, payload: {
    name: string; mode: "FIVE_A_SIDE" | "ELEVEN_A_SIDE"; initial_budget_cents: number;
    market_mode: "TRADITIONAL" | "COINS"; team_count: 4 | 6 | 8 | 10 | 12 | 16 | 20; double_round_robin: boolean;
    initial_market_duration_seconds: number; round_preparation_duration_seconds: number;
    max_human_participants: number; privacy: "PUBLIC" | "PRIVATE"; withdrawal_penalty_percent: 0 | 2 | 5 | 10; match_duration_seconds?: MatchDuration;
  } & Partial<LeagueRules>) => request<Envelope<RoomState>>(`/rooms/${roomId}`, { method: "PUT", body: JSON.stringify(payload) }),
  updateMatchSettings: (roomId: string, match_duration_seconds: MatchDuration) => request<Envelope<RoomState>>(`/rooms/${roomId}/match-settings`, { method: "PUT", body: JSON.stringify({ match_duration_seconds }) }),
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
  saveLineup: (roomId: string, payload: { formation_code: string; assignments: Record<string, string> }) => request<Envelope<Lineup & { ready_cancelled?: boolean }>>(`/rooms/${roomId}/squad/lineup`, { method: "PUT", body: JSON.stringify(payload) }),
  saveInstructions: (roomId: string, instructions: Record<string, string>) => request<Envelope<{ instructions: Record<string, string>; ready_cancelled: boolean }>>(`/rooms/${roomId}/squad/instructions`, { method: "PUT", body: JSON.stringify({ instructions }) }),
  cohesion: (roomId: string) => request<Envelope<CohesionView>>(`/rooms/${roomId}/squad/cohesion`),
  pack: (roomId: string) => request<Envelope<PackView>>(`/rooms/${roomId}/pack`),
  packOpen: (roomId: string) => request<Envelope<PackView>>(`/rooms/${roomId}/pack/open`, { method: "POST" }),
  packFormation: (roomId: string, formation_code: string) => request<Envelope<PackView>>(`/rooms/${roomId}/pack/formation`, { method: "PUT", body: JSON.stringify({ formation_code }) }),
  packPlace: (roomId: string, slot_id: string, catalog_id: string | null) => request<Envelope<PackView>>(`/rooms/${roomId}/pack/slot`, { method: "PUT", body: JSON.stringify({ slot_id, catalog_id }) }),
  packBench: (roomId: string, catalog_ids: string[]) => request<Envelope<PackView>>(`/rooms/${roomId}/pack/bench`, { method: "PUT", body: JSON.stringify({ catalog_ids }) }),
  packConfirm: (roomId: string) => request<Envelope<PackView>>(`/rooms/${roomId}/pack/confirm`, { method: "POST" }),
  packComplete: (roomId: string) => request<Envelope<{ completed: boolean }>>(`/rooms/${roomId}/pack/complete`, { method: "POST" }),
  draft: (roomId: string) => request<Envelope<DraftView>>(`/rooms/${roomId}/draft`),
  draftFormation: (roomId: string, formation_code: string) => request<Envelope<DraftView>>(`/rooms/${roomId}/draft/formation`, { method: "PUT", body: JSON.stringify({ formation_code }) }),
  draftOffer: (roomId: string, slot_id: string) => request<Envelope<{ slot_id: string; cards: DraftCard[]; note: string | null }>>(`/rooms/${roomId}/draft/offer`, { method: "POST", body: JSON.stringify({ slot_id }) }),
  draftPick: (roomId: string, slot_id: string, catalog_id: string) => request<Envelope<DraftView & { completed?: boolean }>>(`/rooms/${roomId}/draft/pick`, { method: "POST", body: JSON.stringify({ slot_id, catalog_id }) }),
  draftComplete: (roomId: string) => request<Envelope<{ completed: boolean }>>(`/rooms/${roomId}/draft/complete`, { method: "POST" }),
  saveTactics: (roomId: string, tactics: Tactics) => request<Envelope<{ tactics: Tactics; strategy: string; ready_cancelled: boolean }>>(`/rooms/${roomId}/squad/tactics`, { method: "PUT", body: JSON.stringify(tactics) }),
  preview: (roomId: string) => request<Envelope<MatchPreview>>(`/rooms/${roomId}/season/preview`),
  liveFrames: (roomId: string, since: number) => request<Envelope<FramesView>>(`/rooms/${roomId}/season/live/frames?since=${since}`),
  liveCommand: (roomId: string, payload: LiveCommandPayload, idempotency_key: string) => request<Envelope<{ command: CommandStatus; match: LiveMatch }>>(`/rooms/${roomId}/season/live/commands`, { method: "POST", body: JSON.stringify({ ...payload, idempotency_key }) }),
  matchFrames: (roomId: string, matchId: string, start: number, end: number) => request<Envelope<{ match_id: string; start: number; end: number; frames: FrameRow[] }>>(`/rooms/${roomId}/matches/${matchId}/frames?start=${start}&end=${end}`),
  finishedMatch: (roomId: string, matchId: string) => request<Envelope<LiveMatch>>(`/rooms/${roomId}/matches/${matchId}`),
  saveStrategy: (roomId: string, strategy: string) => request<Envelope<{ strategy: string; name: string; effect: string }>>(`/rooms/${roomId}/squad/strategy`, { method: "PUT", body: JSON.stringify({ strategy }) }),
  startSeason: (roomId: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/season/start`, { method: "POST" }),
  season: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season`),
  live: (roomId: string) => request<Envelope<LiveView>>(`/rooms/${roomId}/season/live`),
  interactive: (roomId: string, revision?: number) => request<Envelope<InteractiveView>>(`/rooms/${roomId}/season/interactive${revision !== undefined ? `?revision=${revision}` : ""}`),
  labCreate: (body: { kind: string; mode: "ELEVEN_A_SIDE" | "FIVE_A_SIDE"; home?: string; away?: string; seed?: number; second_half?: boolean; engine?: "v6" | "v7" | "v8"; difficulty?: "EASY" | "NORMAL" | "HARD" }) => request<Envelope<{ id: string; match: InteractiveView }>>("/lab/sessions", { method: "POST", body: JSON.stringify(body) }),
  labState: (id: string, revision?: number) => request<Envelope<InteractiveView>>(`/lab/sessions/${id}${revision !== undefined ? `?revision=${revision}` : ""}`),
  labAction: (id: string, payload: InteractiveActionPayload) => request<Envelope<{ status: string; revision: number; match: InteractiveView }>>(`/lab/sessions/${id}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  interactiveAction: (roomId: string, payload: InteractiveActionPayload) => request<Envelope<{ status: string; revision: number; match: InteractiveView }>>(`/rooms/${roomId}/season/interactive/actions`, { method: "POST", body: JSON.stringify(payload) }),
  addBot: (roomId: string, clubCode?: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/bots`, { method: "POST", body: JSON.stringify(clubCode ? { club_code: clubCode } : {}) }),
  removeBot: (roomId: string, clubCode: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/bots/${clubCode}`, { method: "DELETE" }),
  readyForRound: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/ready`, { method: "POST" }),
  advanceRound: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/advance`, { method: "POST" }),
  closeTransferWindow: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/transfer-window/close`, { method: "POST" }),
  careerStats: (roomId: string, competition?: string) => request<Envelope<CareerStats>>(`/rooms/${roomId}/career/stats${competition ? `?competition=${competition}` : ""}`),
  careerTrophies: (roomId: string) => request<Envelope<{ trophies: Trophy[] }>>(`/rooms/${roomId}/career/trophies`),
  careerNews: (roomId: string, filters: { club?: string; kind?: string; season_number?: number } = {}) => request<Envelope<{ items: NewsItem[] }>>(`/rooms/${roomId}/career/news?${new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString()}`),
  changeCoachClub: (roomId: string, clubCode: string) => request<Envelope<RoomState>>(`/rooms/${roomId}/coach/change`, { method: "POST", body: JSON.stringify({ club_code: clubCode }) }),
  startNextSeason: (roomId: string) => request<Envelope<SeasonView>>(`/rooms/${roomId}/season/next`, { method: "POST" }),
  career: (roomId: string) => request<Envelope<CareerView>>(`/rooms/${roomId}/career`),
  listTransferPlayer: (roomId: string, player_id: string, listed: boolean) => request<Envelope<{ player_id: string; listed: boolean }>>(`/rooms/${roomId}/transfers/listings`, { method: "PUT", body: JSON.stringify({ player_id, listed }) }),
  transferClubs: (roomId: string) => request<Envelope<TransferClub[]>>(`/rooms/${roomId}/transfers/clubs`),
  transferPlayers: (roomId: string) => request<Envelope<MarketPlayer[]>>(`/rooms/${roomId}/transfers/available`),
  transferOffers: (roomId: string) => request<Envelope<TransferOffer[]>>(`/rooms/${roomId}/transfers`),
  buyTransferPlayer: (roomId: string, payload: { incoming_player_id: string; replace_player_id: string; amount_cents: number; operation_id: string }) => request<Envelope<Record<string, unknown>>>(`/rooms/${roomId}/transfers/buy`, { method: "POST", body: JSON.stringify(payload) }),
  createTransferOffer: (roomId: string, payload: { incoming_player_id: string; offered_player_id: string; amount_cents: number; idempotency_key: string; kind?: "TRADE" | "PURCHASE" | "LOAN" }) => request<Envelope<TransferOffer>>(`/rooms/${roomId}/transfers/offers`, { method: "POST", body: JSON.stringify(payload) }),
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
  const token = accessToken();
  if (token) url.searchParams.set("access_token", token);
  return url.toString();
}
