import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Squad, type Tactics } from "../../lib/api";

const GROUPS: { key: keyof Tactics; title: string; hint: string }[] = [
  { key: "mentality", title: "Mentalidade", hint: "Altura da linha, quantos jogadores apoiam o ataque e o risco aceito." },
  { key: "pressure", title: "Pressão", hint: "Onde e com quantos jogadores o time ataca a bola. Pressão alta cansa e gera faltas." },
  { key: "style", title: "Estilo de jogo", hint: "Como o time progride: passes curtos, bola longa, contra-ataque ou pelos lados." },
];

/** Starting plan for the next match. In-match changes go through the live commands. */
export function TacticsBoard({ roomId, locked }: { roomId: string; locked?: string | null }) {
  const client = useQueryClient();
  const squad = useQuery({ queryKey: ["squad", roomId], queryFn: () => api.squad(roomId).then((r) => r.data) });
  const [notice, setNotice] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (tactics: Tactics) => api.saveTactics(roomId, tactics),
    onSuccess: ({ data }) => {
      client.setQueryData<Squad>(["squad", roomId], (previous) => previous ? { ...previous, tactics: data.tactics, strategy: data.strategy } : previous);
      setNotice(data.ready_cancelled ? "Plano salvo. Sua prontidão foi cancelada — confirme de novo no pré-jogo." : "Plano de jogo salvo.");
      void client.invalidateQueries({ queryKey: ["preview", roomId] });
      void client.invalidateQueries({ queryKey: ["season", roomId] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Não foi possível salvar."),
  });
  const data = squad.data;
  if (!data) return <div className="panel-loading" role="status">Carregando a prancheta…</div>;
  const tactics = data.tactics;
  return <section className="tactics-board" aria-label="Táticas">
    {locked && <p className="cm-toast cm-toast--warn" role="status">{locked}</p>}
    {notice && <p className="cm-toast" role="status">{notice}</p>}
    {GROUPS.map((group) => <fieldset key={group.key} className="tactic-group" disabled={Boolean(locked) || save.isPending}>
      <legend>{group.title}</legend>
      <p className="hint">{group.hint}</p>
      <div className="tactic-cards">{data.tactics_options[group.key].map((option) => {
        const active = tactics[group.key] === option.code;
        return <button type="button" key={option.code} className={`tactic-card ${active ? "is-active" : ""}`} aria-pressed={active} onClick={() => !active && save.mutate({ ...tactics, [group.key]: option.code } as Tactics)}>
          <strong>{option.name}</strong><span>{option.effect}</span>
        </button>;
      })}</div>
    </fieldset>)}
    <p className="hint">Essas escolhas mudam o comportamento dos jogadores no motor da partida — não existe bônus de gol. Durante o jogo você pode mudar tudo pelo painel do técnico.</p>
  </section>;
}
