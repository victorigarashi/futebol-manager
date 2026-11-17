import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type MatchDuration, type RoomState } from "../lib/api";
import { MATCH_DURATIONS, durationLabel } from "../lib/matchDuration";

type Props = { room: RoomState; isHost: boolean; liveRound?: boolean; compact?: boolean };

/**
 * CONFIGURAÇÕES DA PARTIDA: the host picks the real length of every match (90 game
 * minutes condensed); everyone else sees the current value and is told when it changes.
 * The server is the authority — this only sends the request and shows its answer.
 */
export function MatchSettingsCard({ room, isHost, liveRound = false, compact = false }: Props) {
  const client = useQueryClient();
  const current = (room.match_duration_seconds ?? 60) as MatchDuration;
  const [notice, setNotice] = useState<string | null>(null);
  const previous = useRef(current);
  const mine = useRef(false);

  // Feedback for everyone when the authoritative value changes (host or guests).
  useEffect(() => {
    if (previous.current !== current) {
      setNotice(mine.current ? `Duração alterada para ${durationLabel(current)}. Vale a partir da próxima partida.` : `O anfitrião mudou a duração das partidas para ${durationLabel(current)}.`);
      mine.current = false;
      previous.current = current;
    }
  }, [current]);
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(null), 5000); return () => window.clearTimeout(timer); }, [notice]);

  const change = useMutation({
    mutationFn: (value: MatchDuration) => api.updateMatchSettings(room.id, value),
    onMutate: () => { mine.current = true; },
    onSuccess: ({ data }) => {
      client.setQueryData(["room-state", room.id], data);
      void client.invalidateQueries({ predicate: (query) => query.queryKey.includes(room.id) });
    },
    onError: (error) => { mine.current = false; setNotice(error instanceof Error ? error.message : "Não foi possível alterar a duração."); },
  });
  const locked = liveRound || change.isPending;

  return <section className={`match-settings ${compact ? "match-settings--compact" : ""}`} aria-labelledby={`match-settings-${room.id}`}>
    <p className="section-kicker" id={`match-settings-${room.id}`}>CONFIGURAÇÕES DA PARTIDA</p>
    <div className="match-settings__row">
      <span className="match-settings__label">Duração da partida</span>
      <div className="match-settings__choices" role="radiogroup" aria-label="Duração da partida">
        {MATCH_DURATIONS.map((option) => <button key={option.value} type="button" role="radio" aria-checked={current === option.value}
          className={current === option.value ? "is-active" : ""} disabled={!isHost || locked}
          title={option.hint} onClick={() => current !== option.value && change.mutate(option.value)}>{option.label}</button>)}
      </div>
    </div>
    <small className="match-settings__hint">
      {liveRound ? "Rodada em andamento: a duração só muda depois do apito final."
        : isHost ? `${MATCH_DURATIONS.find((d) => d.value === current)?.hint}. Os 90 minutos são mostrados como uma transmissão condensada.`
          : "Definida pelo anfitrião. Os 90 minutos são mostrados como uma transmissão condensada."}
    </small>
    {notice && <p className="match-settings__notice" role="status">{notice}</p>}
  </section>;
}
