import { useEffect, useRef, type ReactNode } from "react";

export function Modal({ titleId, onClose, children, className = "", closeDisabled = false }: {
  titleId: string; onClose: () => void; children: ReactNode; className?: string; closeDisabled?: boolean;
}) {
  const dialog = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  const disabled = useRef(closeDisabled);
  close.current = onClose;
  disabled.current = closeDisabled;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const element = dialog.current;
    const focusable = () => Array.from(element?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex="0"]',
    ) ?? []).filter((item) => item.getClientRects().length > 0);
    (element?.querySelector<HTMLElement>("[autofocus], input, select") ?? focusable()[0] ?? element)?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !disabled.current) { event.preventDefault(); close.current(); }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) { event.preventDefault(); element?.focus(); return; }
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || !element?.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !element?.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = previousOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return <div className="dialog-backdrop" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !closeDisabled) onClose();
  }}><section ref={dialog} className={`dialog ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
    <button className="dialog__close" type="button" onClick={onClose} disabled={closeDisabled} aria-label="Fechar diálogo">×</button>
    {children}
  </section></div>;
}
