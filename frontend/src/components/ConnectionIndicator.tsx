type ConnectionState = "connecting" | "online" | "reconnecting" | "offline";

const labels: Record<ConnectionState, string> = {
  connecting: "Conectando",
  online: "Conectado",
  reconnecting: "Reconectando",
  offline: "Sem conexão",
};

export function ConnectionIndicator({ state }: { state: ConnectionState }) {
  return <span className={`connection connection--${state}`}><i aria-hidden="true" />{labels[state]}</span>;
}
