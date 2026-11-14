import type { Club } from "../lib/api";
import { ClubCrest } from "./ClubCrest";

type SelectedClubPanelProps = {
  club: Club | null;
  managerName: string | null;
  isPending: boolean;
  onConfirm: () => void;
};

export function SelectedClubPanel({ club, managerName, isPending, onConfirm }: SelectedClubPanelProps) {
  return <aside className="selected-club-panel" aria-live="polite">
    <p className="section-kicker">MEU CLUBE</p>
    {club ? <>
      <ClubCrest club={club} size="lg" />
      <h2>{club.name}</h2>
      <p>Você vai comandar o {club.name}. Confere e fecha com esse time.</p>
      <dl><div><dt>Técnico</dt><dd>{managerName ?? "Visitante"}</dd></div><div><dt>Status</dt><dd>Escolha pendente</dd></div></dl>
      <button className="button-primary" type="button" disabled={isPending} onClick={onConfirm}>{isPending ? "Confirmando…" : "Fechar com esse time"}</button>
    </> : <>
      <div className="selected-club-panel__empty" aria-hidden="true">BM</div>
      <h2>Tá preparado pra comandar?</h2>
      <p>Escolha um escudo livre na grade. A confirmação acontece só no próximo passo.</p>
    </>}
  </aside>;
}
