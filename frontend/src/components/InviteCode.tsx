import { useEffect, useRef, useState } from "react";

export function InviteCode({ code }: { code: string }) {
  const [message, setMessage] = useState("");
  const timer = useRef<number>();
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(code);
      setMessage("Código copiado!");
    } catch {
      input.current?.focus(); input.current?.select();
      setMessage("Selecione e copie o código exibido.");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(""), 4000);
  };
  return <div className="invite-code"><label htmlFor={`invite-${code}`}>Convite</label><input id={`invite-${code}`} ref={input} value={code} readOnly aria-label="Código de convite da liga" /><button type="button" onClick={() => void copy()} aria-label="Copiar código de convite">Copiar</button><span role="status" className="invite-code__status">{message}</span></div>;
}
