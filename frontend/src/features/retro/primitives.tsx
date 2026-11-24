import type { CSSProperties, ReactNode } from "react";
import { useConsoleScale } from "./useConsoleScale";
import "./retro.css";

/**
 * Retro Career shared pieces: stage (original stadium backdrop), frame, top plates,
 * horizontal navigation, tiles, footer hints and spatial keyboard navigation.
 * Presentation only: every action passed in is an existing handler of the app.
 */
export type StageView = "menu" | "career" | "squad";

export function RetroStage({ view }: { view: StageView }) {
  return <div className="rt-stage" aria-hidden="true">
    <div className="rt-stage__img" style={{ backgroundImage: `url(/retro/stadium-${view}.webp)` }} />
    <div className="rt-stage__veil" />
  </div>;
}

export function RetroFrame({ view, fit, top, nav, footer, children, label }: { view: StageView; fit?: boolean; top: ReactNode; nav?: ReactNode; footer?: ReactNode; children: ReactNode; label: string }) {
  const scale = useConsoleScale();
  return <div className="rt" style={{ "--rt-zoom": scale.toFixed(4) } as CSSProperties}>
    <RetroStage view={view} />
    <div className={`rt-frame ${fit ? "rt-frame--fit" : ""}`}>
      {top}
      {nav ?? <div />}
      <main className="rt-body" id="main-content" tabIndex={-1} aria-label={label}>{children}</main>
      {footer ?? <div />}
    </div>
  </div>;
}

export type NavItem<T extends string> = { id: T; label: string; badge?: number };
/** Horizontal tabs; ← → move between them when the bar has focus (roving focus). */
export function RetroNav<T extends string>({ items, current, onSelect, label }: { items: NavItem<T>[]; current: T; onSelect: (id: T) => void; label: string }) {
  return <nav className="rt-nav" aria-label={label} onKeyDown={(event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (i < 0) return;
    event.preventDefault();
    const next = buttons[(i + (event.key === "ArrowRight" ? 1 : buttons.length - 1)) % buttons.length];
    next.focus(); next.click();
  }}>
    {items.map((item) => <button key={item.id} type="button" aria-current={item.id === current ? "page" : undefined} tabIndex={item.id === current ? 0 : -1} onClick={() => onSelect(item.id)}>{item.label}{item.badge ? <span className="rt-badge">{item.badge}</span> : null}</button>)}
  </nav>;
}

export function RetroSubNav<T extends string>({ items, current, onSelect, label }: { items: NavItem<T>[]; current: T; onSelect: (id: T) => void; label: string }) {
  if (items.length < 2) return null;
  return <nav className="rt-subnav" aria-label={label}>{items.map((item) => <button key={item.id} type="button" aria-current={item.id === current ? "page" : undefined} onClick={() => onSelect(item.id)}>{item.label}</button>)}</nav>;
}

export type Hint = { key: string; label: string };
/** Only list shortcuts that are actually wired on the current screen. */
export function RetroFooter({ hints, right }: { hints: Hint[]; right?: ReactNode }) {
  return <footer className="rt-footer">{hints.map((h) => <span key={h.key + h.label}><b className="rt-key">{h.key}</b>{h.label}</span>)}{right && <span className="rt-footer__right">{right}</span>}</footer>;
}

/** Line-art icons for tiles (own drawings). */
export function TileArt({ kind }: { kind: "trophy" | "cards" | "bracket" | "survivor" | "pack" | "people" | "key" | "whistle" | "shirt" | "chart" | "inbox" | "news" | "money" | "calendar" | "pitch" }) {
  const s = { fill: "none", stroke: "currentColor", strokeWidth: 3, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return <svg className="rt-tile__art" viewBox="0 0 64 64" aria-hidden="true">
    {kind === "trophy" && <><path {...s} d="M20 10h24v12a12 12 0 0 1-24 0zM20 14h-8c0 8 4 12 10 12M44 14h8c0 8-4 12-10 12M32 34v10M22 54h20M26 44h12v10H26z" /></>}
    {kind === "cards" && <><rect {...s} x="8" y="14" width="22" height="34" /><rect {...s} x="34" y="10" width="22" height="34" /></>}
    {kind === "bracket" && <path {...s} d="M6 12h14v12h12M6 36h14V24M32 24h10v12h16M6 52h14V40h12M32 40h10" />}
    {kind === "survivor" && <><circle {...s} cx="16" cy="32" r="6" /><circle {...s} cx="32" cy="32" r="6" /><circle {...s} cx="48" cy="32" r="6" /><path {...s} d="M42 26l12 12" /></>}
    {kind === "pack" && <><rect {...s} x="16" y="8" width="32" height="48" /><path {...s} d="M16 20h32M32 30l3 7h7l-6 4 2 7-6-4-6 4 2-7-6-4h7z" /></>}
    {kind === "people" && <><circle {...s} cx="22" cy="22" r="8" /><circle {...s} cx="44" cy="24" r="7" /><path {...s} d="M8 52c2-10 8-14 14-14s12 4 14 14M36 50c2-8 5-11 9-11s8 3 10 11" /></>}
    {kind === "key" && <><circle {...s} cx="20" cy="32" r="10" /><path {...s} d="M30 32h26M48 32v8M56 32v6" /></>}
    {kind === "whistle" && <><circle {...s} cx="24" cy="38" r="12" /><path {...s} d="M34 30l22-10v12l-20 8M12 18l6 6" /></>}
    {kind === "shirt" && <path {...s} d="M22 8l-14 8 6 12 6-3v31h24V25l6 3 6-12-14-8c0 5-5 8-10 8s-10-3-10-8z" />}
    {kind === "chart" && <path {...s} d="M8 54h48M14 46l12-14 10 8 18-22M44 18h10v10" />}
    {kind === "inbox" && <path {...s} d="M8 36l8-24h32l8 24v16H8zM8 36h14l4 6h12l4-6h14" />}
    {kind === "news" && <><rect {...s} x="8" y="12" width="40" height="40" /><path {...s} d="M48 22h8v26a4 4 0 0 1-8 0M16 22h24M16 32h24M16 42h14" /></>}
    {kind === "money" && <><circle {...s} cx="32" cy="32" r="22" /><path {...s} d="M40 22c-2-3-5-4-8-4-5 0-8 3-8 6 0 8 16 5 16 14 0 4-4 7-8 7-4 0-7-2-9-5M32 14v4M32 46v4" /></>}
    {kind === "calendar" && <><rect {...s} x="8" y="12" width="48" height="42" /><path {...s} d="M8 24h48M20 6v10M44 6v10M18 34h6M30 34h6M42 34h6M18 44h6M30 44h6" /></>}
    {kind === "pitch" && <><rect {...s} x="6" y="12" width="52" height="40" /><path {...s} d="M32 12v40" /><circle {...s} cx="32" cy="32" r="7" /><path {...s} d="M6 24h8v16H6M58 24h-8v16h8" /></>}
  </svg>;
}

/** Simple shirt with club colours (kit stripes follow the colour pair, not an official kit). */
export function Shirt({ primary, secondary, label, size = 46, keeper }: { primary: string; secondary: string; label?: string | number; size?: number; keeper?: boolean }) {
  const body = keeper ? "#f2c230" : primary, trim = keeper ? "#1e2f3a" : secondary;
  const id = `sh-${body.replace("#", "")}-${trim.replace("#", "")}`;
  return <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" className="rt-shirt">
    <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".28" /><stop offset=".55" stopColor="#fff" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity=".18" /></linearGradient></defs>
    <path d="M15 5 4 11l4 10 5-2v24h22V19l5 2 4-10-11-6c-1 3-4 5-9 5s-8-2-9-5z" fill={body} stroke="rgba(0,0,0,.35)" strokeWidth="1" />
    {!keeper && <path d="M20 10h8v33h-8z" fill={trim} opacity=".85" />}
    <path d="M15 5c1 3 4 5 9 5s8-2 9-5" fill="none" stroke={trim} strokeWidth="2.2" />
    <path d="M15 5 4 11l4 10 5-2v24h22V19l5 2 4-10-11-6c-1 3-4 5-9 5s-8-2-9-5z" fill={`url(#${id})`} />
    {label !== undefined && <text x="24" y="31" textAnchor="middle" fontFamily="Barlow Condensed, Arial Narrow, sans-serif" fontWeight="700" fontSize="14" fill="#ffffff" stroke="#1e2f3a" strokeWidth="2.6" strokeLinejoin="round" paintOrder="stroke">{label}</text>}
  </svg>;
}

export function FormGuide({ list }: { list: string[] }) {
  if (!list.length) return <span className="rt-muted">—</span>;
  return <span className="rt-form">{list.map((r, i) => <i key={i} className={`form-${r}`} aria-label={r === "V" ? "Vitória" : r === "D" ? "Derrota" : "Empate"}>{r}</i>)}</span>;
}

export function Connection({ state }: { state: "connecting" | "online" | "reconnecting" | "offline" }) {
  const label = { connecting: "Conectando", online: "Conectado", reconnecting: "Reconectando", offline: "Sem conexão" }[state];
  return <span className="rt-iconbtn" role="status" aria-live="polite" style={{ cursor: "default" }}><i className={`rt-dot rt-dot--${state}`} aria-hidden="true" />{label}</span>;
}
