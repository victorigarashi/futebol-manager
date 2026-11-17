import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { Modal } from "./Modal";
import type { BotDifficulty, GameMode, LeagueRules, MatchStyle, PlayoffFormat, Room } from "../lib/api";
import { MATCH_DURATIONS, durationLabel } from "../lib/matchDuration";
import { modeInfo, survivorPath, tournamentStages, usesDraft } from "../lib/gameModes";

export type LeagueDraft = Pick<Room, "name" | "mode" | "initial_budget_cents" | "market_mode" | "team_count" | "double_round_robin" | "max_human_participants" | "privacy" | "initial_market_duration_seconds" | "round_preparation_duration_seconds" | "withdrawal_penalty_percent" | "match_duration_seconds"> & Partial<LeagueRules>;

type Props = { initial: LeagueDraft; mode: GameMode; editing?: boolean; isPending?: boolean; onClose: () => void; onSave: (draft: LeagueDraft) => void; onChangeMode?: () => void };

const BUDGETS = [5_000_000_000, 10_000_000_000, 15_000_000_000, 20_000_000_000, 30_000_000_000, 40_000_000_000, 50_000_000_000, 100_000_000_000];
const PREP = [{ value: 120, label: "2 minutos" }, { value: 180, label: "3 minutos" }, { value: 300, label: "5 minutos" }, { value: 600, label: "10 minutos" }, { value: 900, label: "15 minutos" }, { value: 1_200, label: "20 minutos" }, { value: 1_800, label: "30 minutos" }];
const ROUND_PREP = [{ value: 120, label: "2 minutos" }, { value: 180, label: "3 minutos" }, { value: 300, label: "5 minutos" }, { value: 600, label: "10 minutos" }];
const DRAFT_MINIMUMS = [0, 65, 70, 72, 75, 78, 80];
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1 });
const STYLES: { value: MatchStyle; label: string; hint: string }[] = [
  { value: "REALISTIC", label: "Realista", hint: "Placares de futebol de verdade" },
  { value: "EXCITING", label: "Emocionante", hint: "Mais chances e ataques intensos" },
];
const LEVELS: { value: BotDifficulty; label: string; hint: string }[] = [
  { value: "CASUAL", label: "Casual", hint: "Decisões simples" },
  { value: "COMPETITIVE", label: "Competitivo", hint: "Lê o adversário" },
  { value: "LEGENDARY", label: "Lendário", hint: "Adapta-se em jogo" },
];
const leagueRounds = (teams: number, double: boolean) => (teams - 1) * (double ? 2 : 1);

function Choice<T extends string | number | boolean>({ value, current, label, hint, onPick }: { value: T; current: T; label: ReactNode; hint?: string; onPick: (value: T) => void }) {
  const active = value === current;
  return <button type="button" aria-pressed={active} className={active ? "choice choice--active" : "choice"} onClick={() => onPick(value)}><strong>{label}</strong>{hint && <small>{hint}</small>}</button>;
}

function Toggle({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (value: boolean) => void; label: string; hint: string; disabled?: boolean }) {
  return <label className={`toggle-row ${disabled ? "is-disabled" : ""}`}><input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} /><span><b>{label}</b><small>{hint}</small></span></label>;
}

/** Room creation by steps: only what matters for the chosen mode is shown. */
export function RoomWizard({ initial, mode, editing = false, isPending, onClose, onSave, onChangeMode }: Props) {
  const info = modeInfo(mode);
  const [draft, setDraft] = useState<LeagueDraft>(() => normalise({ ...initial, game_mode: mode }, mode));
  useEffect(() => setDraft(normalise({ ...initial, game_mode: mode }, mode)), [initial, mode]);
  const [step, setStep] = useState(0);
  const patch = <K extends keyof LeagueDraft>(key: K, value: LeagueDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const steps = ["Competição", mode === "SURVIVOR" ? "Elencos" : usesDraft(mode) ? "Draft" : mode === "PACK" ? "Pacotes" : "Mercado", "Partidas e regras", "Revisão"];
  const last = step === steps.length - 1;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!last) { setStep(step + 1); return; }
    onSave({ ...draft, name: draft.name.trim().replace(/\s+/g, " ") });
  };
  const style = draft.sim_style ?? "REALISTIC";
  const level = draft.bot_difficulty ?? "COMPETITIVE";
  const duration = draft.match_duration_seconds ?? 60;
  const traditional = mode === "TRADITIONAL" || mode === "DRAFT";
  const cupAllowed = traditional && draft.team_count === 20;
  const bots = Math.max(0, draft.team_count - draft.max_human_participants);

  return <Modal className="league-dialog wizard" titleId="wizard-title" onClose={onClose} closeDisabled={isPending}>
    <header className="wizard__head" style={{ ["--mode-accent" as string]: info.accent }}>
      <p className="section-kicker">{editing ? "REGRAS DA SALA" : "NOVA SALA"} · {info.name.toUpperCase()}</p>
      <h2 id="wizard-title">{steps[step]}</h2>
      {!editing && onChangeMode && step === 0 && <button type="button" className="text-action" onClick={onChangeMode}>← Trocar modo</button>}
      <ol className="wizard__steps" aria-label="Etapas">{steps.map((label, index) => <li key={label} aria-current={index === step ? "step" : undefined} className={index < step ? "is-done" : ""}><button type="button" onClick={() => setStep(index)} disabled={isPending}><span>{index < step ? "✓" : index + 1}</span>{label}</button></li>)}</ol>
    </header>
    <form onSubmit={submit} className="wizard__body">
      {step === 0 && <section className="settings-section">
        <label>Nome da sala<input required minLength={3} maxLength={80} value={draft.name} onChange={(event) => patch("name", event.target.value)} /></label>
        <fieldset><legend>Formato da partida</legend><div className="choice-grid choice-grid--two">
          <Choice value="FIVE_A_SIDE" current={draft.mode} label="5 × 5" hint="Rápido e aberto" onPick={(v) => patch("mode", v)} />
          <Choice value="ELEVEN_A_SIDE" current={draft.mode} label="11 × 11" hint="Campo cheio" onPick={(v) => patch("mode", v)} />
        </div></fieldset>
        <fieldset><legend>{mode === "SURVIVOR" ? "Clubes no início" : isKnockout(mode) ? "Tamanho da chave" : "Clubes na liga"}</legend>
          <div className={`choice-grid ${info.sizes.length > 4 ? "choice-grid--four" : `choice-grid--${info.sizes.length === 3 ? "three" : "four"}`}`}>
            {info.sizes.map((size) => <Choice key={size} value={size} current={draft.team_count} label={`${size} clubes`} hint={isKnockout(mode) ? `${tournamentStages(size).length} fases` : mode === "SURVIVOR" ? `${survivorPath(size, draft.survivor_eliminations ?? 0).length - 1} rodadas` : `${leagueRounds(size, draft.double_round_robin)} rodadas`}
              onPick={(v) => setDraft((c) => ({ ...c, team_count: v, max_human_participants: Math.min(c.max_human_participants, v), copa_enabled: v === 20 ? c.copa_enabled : false }))} />)}
          </div>
        </fieldset>
        <label>Técnicos humanos<select value={draft.max_human_participants} onChange={(event) => patch("max_human_participants", Number(event.target.value))}>{Array.from({ length: draft.team_count }, (_, index) => index + 1).map((count) => <option value={count} key={count}>até {count}</option>)}</select><small>Vagas sem técnico viram bots ({bots} no mínimo).</small></label>
        {traditional && <>
          <fieldset><legend>Turnos</legend><div className="choice-grid choice-grid--two">
            <Choice value={false} current={draft.double_round_robin} label="Turno único" hint={`${leagueRounds(draft.team_count, false)} rodadas`} onPick={(v) => patch("double_round_robin", v)} />
            <Choice value={true} current={draft.double_round_robin} label="Ida e volta" hint={`${leagueRounds(draft.team_count, true)} rodadas`} onPick={(v) => patch("double_round_robin", v)} />
          </div></fieldset>
          {draft.team_count >= 8 && <fieldset><legend>Playoffs dos 8 primeiros</legend><div className="choice-grid choice-grid--two">
            <Choice value={"SINGLE" as PlayoffFormat} current={draft.playoff_format ?? "SINGLE"} label="Jogo único" hint="Empate nos pênaltis" onPick={(v) => patch("playoff_format", v)} />
            <Choice value={"TWO_LEGS" as PlayoffFormat} current={draft.playoff_format ?? "SINGLE"} label="Ida e volta" hint="Vale o agregado" onPick={(v) => patch("playoff_format", v)} />
          </div></fieldset>}
          <Toggle checked={Boolean(draft.copa_enabled) && cupAllowed} disabled={!cupAllowed} onChange={(v) => patch("copa_enabled", v)} label="Copa do Brasil" hint={cupAllowed ? "Mata-mata intercalado com o Brasileirão" : "Disponível com os 20 clubes"} />
        </>}
        {mode === "SURVIVOR" && <fieldset><legend>Eliminados por rodada</legend><div className="choice-grid choice-grid--three">
          {([0, 2, 4] as const).map((n) => <Choice key={n} value={n} current={draft.survivor_eliminations ?? 0} label={n ? `${n} por rodada` : "Automático"} hint={survivorPath(draft.team_count, n).join(" → ")} onPick={(v) => patch("survivor_eliminations", v)} />)}
        </div><small>Classificação da rodada: pontos, saldo, gols marcados, campanha e um sorteio fixo antes do início. Com 2 restantes, final com pênaltis.</small></fieldset>}
        {isKnockout(mode) && <p className="muted">Chave sorteada uma vez pelo servidor (metade mais forte contra a mais fraca), jogo único e pênaltis no empate: {tournamentStages(draft.team_count).join(" → ")}.</p>}
      </section>}

      {step === 1 && <section className="settings-section">
        {mode === "SURVIVOR" && <p className="muted">Cada clube entra com o seu <b>elenco real</b> (16 atletas do catálogo, 2 goleiros). Não há mercado: escolha o clube e jogue.</p>}
        {(usesDraft(mode) || mode === "PACK") && <>
          <fieldset><legend>Catálogo</legend><div className="choice-grid choice-grid--two">
            <Choice value="BRASILEIRAO" current={draft.draft_catalog ?? "BRASILEIRAO"} label="Brasileirão" hint="Atletas reais do catálogo nacional" onPick={(v) => patch("draft_catalog", v)} />
            <Choice value="WORLD" current={draft.draft_catalog ?? "BRASILEIRAO"} label="Mundial" hint="Overall editorial próprio, não é rating oficial" onPick={(v) => patch("draft_catalog", v)} />
          </div></fieldset>
          {usesDraft(mode) && <label>Overall mínimo das cartas<select value={draft.draft_min_overall ?? 0} onChange={(event) => patch("draft_min_overall", Number(event.target.value))}>{DRAFT_MINIMUMS.map((value) => <option value={value} key={value}>{value ? `${value}+` : "Sem mínimo"}</option>)}</select><small>Sorteio equilibrado: toda oferta traz uma carta de cada faixa de qualidade.</small></label>}
          {mode === "PACK" && <fieldset><legend>Distribuição dos pacotes</legend><div className="choice-grid choice-grid--two">
            <Choice value="BALANCED" current={draft.pack_luck ?? "BALANCED"} label="Equilibrada" hint="Todos recebem a mesma mistura Ouro/Prata/Bronze" onPick={(v) => patch("pack_luck", v)} />
            <Choice value="LUCK" current={draft.pack_luck ?? "BALANCED"} label="Sorte pura" hint="Cada carta sorteada: 15% Ouro, 35% Prata, 50% Bronze" onPick={(v) => patch("pack_luck", v)} />
          </div><small>Pacotes gratuitos, só desta sala. {draft.mode === "ELEVEN_A_SIDE" ? "4 pacotes de 6 cartas" : "3 pacotes de 4 cartas"}, com goleiros e todas as posições garantidos.</small></fieldset>}
          <label>{mode === "PACK" ? "Tempo para abrir e montar o time" : "Tempo para montar o time no Draft"}<select value={draft.initial_market_duration_seconds} onChange={(event) => patch("initial_market_duration_seconds", Number(event.target.value))}>{PREP.map((o) => <option value={o.value} key={o.value}>{o.label}</option>)}</select><small>Quem não terminar no prazo recebe um time automático.</small></label>
        </>}
        {mode === "TRADITIONAL" && <>
          <fieldset><legend>Tipo de mercado</legend><div className="choice-grid choice-grid--two">
            <Choice value="TRADITIONAL" current={draft.market_mode} label="Dinheiro" hint="Orçamento em R$" onPick={(v) => patch("market_mode", v)} />
            <Choice value="COINS" current={draft.market_mode} label="100 moedas" hint="Lances inteiros e secretos" onPick={(v) => patch("market_mode", v)} />
          </div></fieldset>
          {draft.market_mode === "TRADITIONAL" && <fieldset><legend>Orçamento por clube</legend><div className="choice-grid choice-grid--four">{BUDGETS.map((b) => <Choice key={b} value={b} current={draft.initial_budget_cents} label={money.format(b / 100)} onPick={(v) => patch("initial_budget_cents", v)} />)}</div></fieldset>}
          <div className="settings-row">
            <label>Duração do mercado inicial<select value={draft.initial_market_duration_seconds} onChange={(event) => patch("initial_market_duration_seconds", Number(event.target.value))}>{PREP.map((o) => <option value={o.value} key={o.value}>{o.label}</option>)}</select></label>
            <label>Multa por desistir<select disabled={draft.market_mode === "COINS"} value={draft.market_mode === "COINS" ? 0 : draft.withdrawal_penalty_percent} onChange={(event) => patch("withdrawal_penalty_percent", Number(event.target.value) as LeagueDraft["withdrawal_penalty_percent"])}>{[0, 2, 5, 10].map((p) => <option value={p} key={p}>{p}%</option>)}</select></label>
          </div>
          <p className="muted">Janelas de transferência na metade do campeonato e entre temporadas.</p>
        </>}
        {mode === "DRAFT" && <fieldset><legend>Orçamento do clube na temporada</legend><div className="choice-grid choice-grid--four">{BUDGETS.slice(0, 4).map((b) => <Choice key={b} value={b} current={draft.initial_budget_cents} label={money.format(b / 100)} onPick={(v) => patch("initial_budget_cents", v)} />)}</div></fieldset>}
      </section>}

      {step === 2 && <section className="settings-section">
        <fieldset><legend>Duração de cada partida</legend><div className="choice-grid choice-grid--four">{MATCH_DURATIONS.map((o) => <Choice key={o.value} value={o.value} current={duration} label={o.label} hint={o.hint} onPick={(v) => patch("match_duration_seconds", v)} />)}</div>
          <small>Os 90 minutos são uma transmissão condensada com os lances que importam.</small></fieldset>
        <fieldset><legend>Estilo da simulação</legend><div className="choice-grid choice-grid--two">{STYLES.map((o) => <Choice key={o.value} value={o.value} current={style} label={o.label} hint={o.hint} onPick={(v) => patch("sim_style", v)} />)}</div></fieldset>
        <fieldset><legend>Bots</legend><div className="choice-grid choice-grid--three">{LEVELS.map((o) => <Choice key={o.value} value={o.value} current={level} label={o.label} hint={o.hint} onPick={(v) => patch("bot_difficulty", v)} />)}</div>
          <small>A dificuldade muda a qualidade das decisões — nunca atributos ou sorte.</small></fieldset>
        <label>Prazo entre rodadas<select value={draft.round_preparation_duration_seconds} onChange={(event) => patch("round_preparation_duration_seconds", Number(event.target.value))}>{ROUND_PREP.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select><small>A rodada começa antes se todos confirmarem.</small></label>
        {traditional && <div className="toggle-list">
          <Toggle checked={Boolean(draft.morale_enabled)} onChange={(v) => patch("morale_enabled", v)} label="Moral e condicionamento" hint="Desgaste e moral com efeitos moderados" />
          <Toggle checked={Boolean(draft.coach_moves_enabled)} onChange={(v) => patch("coach_moves_enabled", v)} label="Troca de clube entre temporadas" hint="O histórico acompanha o técnico" />
        </div>}
      </section>}

      {step === 3 && <section className="settings-section">
        <fieldset><legend>Quem pode entrar</legend><div className="choice-grid choice-grid--two">
          <Choice value="PUBLIC" current={draft.privacy} label="Pública" hint="Aparece na lista de salas" onPick={(v) => patch("privacy", v)} />
          <Choice value="PRIVATE" current={draft.privacy} label="Privada" hint="Só com o código" onPick={(v) => patch("privacy", v)} />
        </div></fieldset>
        <aside className="league-preview" aria-label="Resumo">
          <p className="section-kicker">RESUMO</p>
          <strong className="league-preview__name">{draft.name.trim() || "Sua sala"}</strong>
          <ul>
            <li><b>{info.name}</b> · {draft.mode === "FIVE_A_SIDE" ? "5 × 5" : "11 × 11"} · {draft.team_count} clubes, até {draft.max_human_participants} humano{draft.max_human_participants > 1 ? "s" : ""}</li>
            <li>{summaryCompetition(mode, draft)}</li>
            <li>{summarySquads(mode, draft)}</li>
            <li>Partidas de <b>{durationLabel(duration)}</b> · {STYLES.find((s) => s.value === style)?.label} · bots {LEVELS.find((l) => l.value === level)?.label}</li>
            {traditional && draft.morale_enabled && <li>Moral e condicionamento</li>}
            {traditional && draft.coach_moves_enabled && <li>Troca de clube entre temporadas</li>}
          </ul>
        </aside>
      </section>}

      <footer className="wizard__foot">
        <button type="button" className="button-secondary" disabled={isPending} onClick={() => (step ? setStep(step - 1) : onClose())}>{step ? "Voltar" : "Cancelar"}</button>
        <button type="submit" className="button-primary" disabled={isPending}>{isPending ? "Salvando…" : last ? (editing ? "Salvar regras" : "Criar sala") : "Continuar →"}</button>
      </footer>
    </form>
  </Modal>;
}

const isKnockout = (mode: GameMode) => mode === "DRAFT_KNOCKOUT" || mode === "PACK";

/** A draft coming from another mode is clamped to what this mode accepts. */
function normalise(draft: LeagueDraft, mode: GameMode): LeagueDraft {
  const info = modeInfo(mode);
  const team_count = (info.sizes as readonly number[]).includes(draft.team_count) ? draft.team_count : info.defaultSize;
  return { ...draft, game_mode: mode, team_count, max_human_participants: Math.min(draft.max_human_participants, team_count),
    market_mode: mode === "TRADITIONAL" ? draft.market_mode : "TRADITIONAL", copa_enabled: team_count === 20 && (mode === "TRADITIONAL" || mode === "DRAFT") ? draft.copa_enabled : false };
}

function summaryCompetition(mode: GameMode, d: LeagueDraft): ReactNode {
  if (mode === "SURVIVOR") return <>Sobrevivência: <b>{survivorPath(d.team_count, d.survivor_eliminations ?? 0).join(" → ")}</b> → campeão</>;
  if (isKnockout(mode)) return <>Mata-mata: <b>{tournamentStages(d.team_count).join(" → ")}</b> · jogo único</>;
  const rounds = leagueRounds(d.team_count, d.double_round_robin);
  return <><b>{rounds}</b> rodadas ({d.double_round_robin ? "ida e volta" : "turno único"}){d.team_count >= 8 ? ` + playoffs ${d.playoff_format === "TWO_LEGS" ? "ida e volta" : "jogo único"}` : ""}{d.copa_enabled && d.team_count === 20 ? " + Copa do Brasil" : ""}</>;
}

function summarySquads(mode: GameMode, d: LeagueDraft): ReactNode {
  const catalog = d.draft_catalog === "WORLD" ? "Mundial" : "Brasileirão";
  if (mode === "SURVIVOR") return "Elencos reais dos clubes";
  if (mode === "PACK") return <>Pacotes gratuitos · catálogo {catalog} · distribuição {d.pack_luck === "LUCK" ? "sorte pura" : "equilibrada"}</>;
  if (usesDraft(mode)) return <>Draft · catálogo {catalog}{d.draft_min_overall ? ` · cartas ${d.draft_min_overall}+` : ""}</>;
  return d.market_mode === "COINS" ? <>Mercado por moedas · <b>100 moedas</b></> : <>Mercado · <b>{money.format(d.initial_budget_cents / 100)}</b> por clube</>;
}
