export function LoadingState({ label = "Preparando o vestiário…" }: { label?: string }) {
  return <div className="async-state" role="status"><div className="skeleton skeleton--line" /><div className="skeleton skeleton--line" /><p>{label}</p></div>;
}
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <section className="async-state async-state--error" role="alert"><h2>O jogo precisa de mais uma tentativa.</h2><p>{message}</p>{onRetry && <button className="button-secondary" type="button" onClick={onRetry}>Tentar novamente</button>}</section>;
}
