import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <main className="async-state async-state--error" role="alert"><h1>Vamos recuperar o vestiário.</h1><p>A interface encontrou um erro. Sua sala continua no servidor enquanto a sessão estiver ativa.</p><button className="button-primary" onClick={() => window.location.reload()}>Reabrir o jogo</button></main>;
    return this.props.children;
  }
}
