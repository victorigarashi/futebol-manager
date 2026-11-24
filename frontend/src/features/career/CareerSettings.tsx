import type { RoomState } from "../../lib/api";
import { LeagueSettingsSummary } from "../../components/LeagueSettingsSummary";
import { ExperiencePicker } from "./interactive/ExperiencePicker";
import "../rooms/lobby-retro.css";

/**
 * Configurações (career): the settings that already exist, gathered in one place.
 * Match experience (2D/3D + graphics quality, per browser), coach profile and the league's
 * rules (the host can still change the match duration). No new setting is invented here.
 */
export function CareerSettings({ room, isHost, onEditProfile }: { room: RoomState; isHost: boolean; onEditProfile?: () => void }) {
  return <section className="lb cs" aria-label="Configurações">
    <section className="rt-panel lb-col lb-xp rt-scroll" aria-label="Experiência de partida"><ExperiencePicker /></section>
    <section className="rt-panel lb-col rt-scroll cs-profile" aria-label="Perfil do técnico">
      <h2 className="rt-h">Perfil do técnico</h2>
      <p className="rt-sub">O nome aparece para os outros técnicos, nas notícias e na sala de troféus.</p>
      {onEditProfile && <button type="button" className="rt-btn rt-btn--ghost" onClick={onEditProfile}>Editar nome do técnico</button>}
      <h2 className="rt-h cs-gap">Acessibilidade</h2>
      <p className="rt-sub">Navegação completa por teclado (Tab, Enter, setas e Esc), foco visível e animações reduzidas quando o sistema pede menos movimento.</p>
    </section>
    <section className="rt-panel lb-col lb-rules rt-scroll cs-rules" aria-label="Regras da liga">
      <LeagueSettingsSummary room={room} isHost={isHost} hasClub onStart={() => undefined} />
    </section>
  </section>;
}
