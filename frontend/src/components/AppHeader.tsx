import { useSession } from "../stores/session";

type AppHeaderProps = { onEditProfile?: () => void; onHome?: () => void; context?: "home" | "room" | "onboarding" };
export function AppHeader({ onEditProfile, onHome, context = "home" }: AppHeaderProps) {
  const displayName = useSession((state) => state.displayName);
  const profileLabel = !displayName || displayName.startsWith("Técnico ") ? "Seu perfil" : displayName;
  return <><a className="skip-link" href="#main-content">Pular para o jogo</a><header className="app-header">
    <a className="brand" href="#top" onClick={onHome ? (event) => { event.preventDefault(); onHome(); } : undefined} aria-label="Brasileirão Manager, início"><span className="brand__crest" aria-hidden="true">BM</span><span>BRASILEIRÃO<br />MANAGER</span><small>EDIÇÃO RESENHA</small></a>
    {context !== "onboarding" && <nav className="app-header__nav" aria-label="Navegação principal">{context === "room" ? <><button className="text-action" type="button" onClick={onHome}>Minhas ligas</button><a href="#room-top">Minha liga</a></> : <><a href="#top">Início</a><a href="#como-funciona">O jogo</a><a href="#salas">Ligas abertas</a></>}</nav>}
    <div className="app-header__right"><span className="prototype-badge">BETA · EDIÇÃO RESENHA</span>{context !== "onboarding" && <button className="app-header__profile" type="button" onClick={onEditProfile} aria-label="Editar perfil do técnico"><span>técnico · editar</span><strong>{profileLabel}</strong></button>}</div>
  </header></>;
}
