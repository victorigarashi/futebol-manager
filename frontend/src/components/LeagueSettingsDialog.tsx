import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { Modal } from "./Modal";
import type { BotDifficulty, LeagueRules, MatchStyle, PlayoffFormat, Room } from "../lib/api";
import { MATCH_DURATIONS, durationLabel } from "../lib/matchDuration";

export type LeagueDraft = Pick<Room, "name" | "mode" | "initial_budget_cents" | "market_mode" | "team_count" | "double_round_robin" | "max_human_participants" | "privacy" | "initial_market_duration_seconds" | "round_preparation_duration_seconds" | "withdrawal_penalty_percent" | "match_duration_seconds"> & Partial<LeagueRules>;

type LeagueSettingsDialogProps = { initial: LeagueDraft; title: string; submitLabel: string; isPending?: boolean; onClose: () => void; onSave: (draft: LeagueDraft) => void };
const BUDGETS = [5_000_000_000, 10_000_000_000, 15_000_000_000, 20_000_000_000, 30_000_000_000, 40_000_000_000, 50_000_000_000, 100_000_000_000];
const durationOptions = [{ value: 120, label: "2 minutos" }, { value: 180, label: "3 minutos" }, { value: 300, label: "5 minutos" }, { value: 600, label: "10 minutos" }, { value: 900, label: "15 minutos" }, { value: 1_200, label: "20 minutos" }, { value: 1_800, label: "30 minutos" }];
const roundPreparationOptions = [{ value: 120, label: "2 minutos" }, { value: 180, label: "3 minutos" }, { value: 300, label: "5 minutos" }, { value: 600, label: "10 minutos" }];
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1 });
const STYLES: { value: MatchStyle; label: string; hint: string }[] = [
  { value: "REALISTIC", label: "Realista", hint: "Placares de futebol de verdade; construção paciente" },
  { value: "EXCITING", label: "Emocionante", hint: "Mais chances, ataques intensos, mais viradas" },
];
const LEVELS: { value: BotDifficulty; label: string; hint: string }[] = [
  { value: "CASUAL", label: "Casual", hint: "Decisões simples, negocia com calma" },
  { value: "COMPETITIVE", label: "Competitivo", hint: "Lê o adversário e reforça o elenco" },
  { value: "LEGENDARY", label: "Lendário", hint: "Adapta-se em jogo e disputa contratações" },
];
const FORMATS: { value: PlayoffFormat; label: string; hint: string }[] = [
  { value: "SINGLE", label: "Jogo único", hint: "Empate leva aos pênaltis" },
  { value: "TWO_LEGS", label: "Ida e volta", hint: "Agregado, sem gol fora; empate nos pênaltis" },
];

const leagueRounds = (teams: number, double: boolean) => (teams - 1) * (double ? 2 : 1);

function Choice<T extends string | number | boolean>({ value, current, label, hint, onPick }: { value: T; current: T; label: ReactNode; hint?: string; onPick: (value: T) => void }) {
  const active = value === current;
  return <button type="button" aria-pressed={active} className={active ? "choice choice--active" : "choice"} onClick={() => onPick(value)}><strong>{label}</strong>{hint && <small>{hint}</small>}</button>;
}

function Toggle({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (value: boolean) => void; label: string; hint: string; disabled?: boolean }) {
  return <label className={`toggle-row ${disabled ? "is-disabled" : ""}`}><input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} /><span><b>{label}</b><small>{hint}</small></span></label>;
}

export function LeagueSettingsDialog({ initial, title, submitLabel, isPending, onClose, onSave }: LeagueSettingsDialogProps) {
  const [draft, setDraft] = useState<LeagueDraft>(initial);
  useEffect(() => setDraft(initial), [initial]);
  const patch = <K extends keyof LeagueDraft>(key: K, value: LeagueDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); onSave({ ...draft, name: draft.name.trim().replace(/\s+/g, " ") }); };
  const teamCounts = [4, 6, 8, 10, 12, 16, 20] as const;
  const style = draft.sim_style ?? "REALISTIC";
  const level = draft.bot_difficulty ?? "COMPETITIVE";
  const format = draft.playoff_format ?? "SINGLE";
  const duration = draft.match_duration_seconds ?? 60;
  const cupAllowed = draft.team_count === 20;
  const rounds = leagueRounds(draft.team_count, draft.double_round_robin);
  const bots = Math.max(0, draft.team_count - draft.max_human_participants);

  return <Modal className="league-dialog" titleId="league-settings-title" onClose={onClose} closeDisabled={isPending}>
    <p className="section-kicker">REGRAS DA RESENHA</p>
    <h2 id="league-settings-title">{title}</h2>
    <form onSubmit={submit}>
      <section className="settings-section" aria-labelledby="settings-championship">
        <h3 id="settings-championship">Configurações do campeonato</h3>
        <label>Nome da liga<input required minLength={3} maxLength={80} value={draft.name} onChange={(event) => patch("name", event.target.value)} /></label>
        <fieldset><legend>Como a bola vai rolar?</legend><div className="choice-grid choice-grid--two">
          <Choice value="FIVE_A_SIDE" current={draft.mode} label="5 × 5" hint="Jogo rápido" onPick={(v) => patch("mode", v)} />
          <Choice value="ELEVEN_A_SIDE" current={draft.mode} label="11 × 11" hint="Campo cheio" onPick={(v) => patch("mode", v)} />
        </div></fieldset>
        <div className="settings-row">
          <label>Times participantes<select value={draft.team_count} onChange={(event) => { const teamCount = Number(event.target.value) as LeagueDraft["team_count"]; setDraft((current) => ({ ...current, team_count: teamCount, max_human_participants: Math.min(current.max_human_participants, teamCount), copa_enabled: teamCount === 20 ? current.copa_enabled : false })); }}>{teamCounts.map((count) => <option value={count} key={count}>{count} clubes</option>)}</select></label>
          <label>Técnicos humanos<select value={draft.max_human_participants} onChange={(event) => patch("max_human_participants", Number(event.target.value))}>{Array.from({ length: draft.team_count }, (_, index) => index + 1).map((count) => <option value={count} key={count}>até {count}</option>)}</select><small>As vagas restantes viram bots.</small></label>
        </div>
        <fieldset><legend>Formato de confrontos</legend><div className="choice-grid choice-grid--two">
          <Choice value={false} current={draft.double_round_robin} label="Turno único" hint={`${leagueRounds(draft.team_count, false)} rodadas`} onPick={(v) => patch("double_round_robin", v)} />
          <Choice value={true} current={draft.double_round_robin} label="Ida e volta" hint={`${leagueRounds(draft.team_count, true)} rodadas, mando invertido`} onPick={(v) => patch("double_round_robin", v)} />
        </div></fieldset>
        <fieldset><legend>Duração das partidas</legend><div className="choice-grid choice-grid--four">{MATCH_DURATIONS.map((option) => <Choice key={option.value} value={option.value} current={duration} label={option.label} hint={option.hint} onPick={(v) => patch("match_duration_seconds", v)} />)}</div>
          <small>Tempo real de cada partida; os 90 minutos são uma transmissão condensada.</small></fieldset>
        <fieldset><legend>Estilo das partidas</legend><div className="choice-grid choice-grid--two">{STYLES.map((option) => <Choice key={option.value} value={option.value} current={style} label={option.label} hint={option.hint} onPick={(v) => patch("sim_style", v)} />)}</div></fieldset>
        <fieldset><legend>Dificuldade dos bots</legend><div className="choice-grid choice-grid--three">{LEVELS.map((option) => <Choice key={option.value} value={option.value} current={level} label={option.label} hint={option.hint} onPick={(v) => patch("bot_difficulty", v)} />)}</div>
          <small>A dificuldade muda a qualidade das decisões dos bots — nunca atributos, dinheiro ou chances de gol.</small></fieldset>
        <fieldset><legend>Playoffs (8 primeiros)</legend><div className="choice-grid choice-grid--two">{FORMATS.map((option) => <Choice key={option.value} value={option.value} current={format} label={option.label} hint={option.hint} onPick={(v) => patch("playoff_format", v)} />)}</div>
          {draft.team_count < 8 && <small>Ligas com menos de 8 clubes terminam na tabela, sem playoffs.</small>}</fieldset>
        <div className="toggle-list">
          <Toggle checked={Boolean(draft.copa_enabled) && cupAllowed} disabled={!cupAllowed} onChange={(v) => patch("copa_enabled", v)} label="Copa do Brasil" hint={cupAllowed ? "Mata-mata intercalado com o Brasileirão (preliminar + oitavas até a final)" : "Disponível só com os 20 clubes"} />
          <Toggle checked={Boolean(draft.morale_enabled)} onChange={(v) => patch("morale_enabled", v)} label="Moral e condicionamento" hint="Desgaste entre rodadas e moral pelos resultados, com efeitos moderados" />
          <Toggle checked={Boolean(draft.coach_moves_enabled)} onChange={(v) => patch("coach_moves_enabled", v)} label="Troca de clube entre temporadas" hint="Técnicos podem assumir um clube sem técnico humano; o histórico acompanha o técnico" />
        </div>
        <label>Prazo entre rodadas<select value={draft.round_preparation_duration_seconds} onChange={(event) => patch("round_preparation_duration_seconds", Number(event.target.value))}>{roundPreparationOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
          <small>Os técnicos podem confirmar antes. A partida começa quando todos estiverem prontos.</small></label>
      </section>

      <section className="settings-section" aria-labelledby="settings-market">
        <h3 id="settings-market">Configurações do mercado</h3>
        <fieldset><legend>Tipo de mercado</legend><div className="choice-grid choice-grid--two">
          <Choice value="TRADITIONAL" current={draft.market_mode} label="Tradicional — dinheiro" hint="Orçamento em R$ e valores internos dos atletas" onPick={(v) => patch("market_mode", v)} />
          <Choice value="COINS" current={draft.market_mode} label="Mercado de moedas" hint="100 moedas por técnico; lances inteiros e secretos" onPick={(v) => patch("market_mode", v)} />
        </div></fieldset>
        {draft.market_mode === "TRADITIONAL"
          ? <fieldset><legend>Orçamento inicial por clube</legend><div className="choice-grid choice-grid--four">{BUDGETS.map((budget) => <Choice key={budget} value={budget} current={draft.initial_budget_cents} label={money.format(budget / 100)} onPick={(v) => patch("initial_budget_cents", v)} />)}</div></fieldset>
          : <p className="muted">Cada clube recebe exatamente <strong>100 moedas</strong>, válidas só nesta sala. Não há multa por cancelar lance nesse modo.</p>}
        <div className="settings-row">
          <label>Preparação do mercado inicial<select value={draft.initial_market_duration_seconds} onChange={(event) => patch("initial_market_duration_seconds", Number(event.target.value))}>{durationOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
          <label>Multa por desistir de uma contratação vencida<select disabled={draft.market_mode === "COINS"} value={draft.market_mode === "COINS" ? 0 : draft.withdrawal_penalty_percent} onChange={(event) => patch("withdrawal_penalty_percent", Number(event.target.value) as LeagueDraft["withdrawal_penalty_percent"])}>{[0, 2, 5, 10].map((percent) => <option value={percent} key={percent}>{percent}%</option>)}</select></label>
        </div>
        <p className="muted">Janelas de transferência: na metade do campeonato e entre temporadas. Bots também fazem propostas pelos seus atletas.</p>
        <fieldset><legend>Entrada na liga</legend><div className="choice-grid choice-grid--two">
          <Choice value="PUBLIC" current={draft.privacy} label="Pública" hint="Aparece para todos" onPick={(v) => patch("privacy", v)} />
          <Choice value="PRIVATE" current={draft.privacy} label="Privada" hint="Só com código" onPick={(v) => patch("privacy", v)} />
        </div></fieldset>
      </section>

      <aside className="league-preview" aria-label="Resumo da liga">
        <p className="section-kicker">RESUMO</p>
        <strong className="league-preview__name">{draft.name.trim() || "Sua liga"}</strong>
        <ul>
          <li><b>{draft.team_count}</b> clubes · até {draft.max_human_participants} humano{draft.max_human_participants > 1 ? "s" : ""} · {bots} bot{bots === 1 ? "" : "s"} no mínimo</li>
          <li><b>{rounds}</b> rodadas ({draft.double_round_robin ? "ida e volta" : "turno único"}){draft.team_count >= 8 ? ` + playoffs em ${format === "TWO_LEGS" ? "ida e volta" : "jogo único"}` : ""}{draft.copa_enabled && cupAllowed ? " + Copa do Brasil" : ""}</li>
          <li>Partidas de <b>{durationLabel(duration)}</b> · estilo {STYLES.find((s) => s.value === style)?.label} · bots {LEVELS.find((l) => l.value === level)?.label}</li>
          <li>{draft.market_mode === "COINS" ? <>Mercado por moedas · saldo inicial <b>100 moedas</b> por técnico</> : <>Mercado tradicional · <b>{money.format(draft.initial_budget_cents / 100)}</b> por clube</>}</li>
          {draft.morale_enabled && <li>Moral e condicionamento ativados</li>}
          {draft.coach_moves_enabled && <li>Troca de clube entre temporadas permitida</li>}
        </ul>
      </aside>
      <button className="button-primary dialog__submit" disabled={isPending}>{isPending ? "Salvando…" : submitLabel}</button>
    </form>
  </Modal>;
}
