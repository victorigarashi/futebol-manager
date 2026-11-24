import { useEffect, type RefObject } from "react";

/**
 * Spatial navigation among the tiles of a container ([data-rt-tile]): arrows move the
 * focus to the nearest tile in that direction; Enter/Space are the buttons' own. Text
 * fields and selects keep their arrow keys.
 */
export function useTileNav(ref: RefObject<HTMLElement | null>, onBack?: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if (event.key === "Escape" && onBack && !typing && !document.querySelector("[role=dialog]")) { event.preventDefault(); onBack(); return; }
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key) || typing) return;
      const root = ref.current;
      if (!root) return;
      if (target?.closest(".rt-nav, .rt-subnav, [role=listbox], [role=radiogroup]")) return;
      const tiles = Array.from(root.querySelectorAll<HTMLElement>("[data-rt-tile]")).filter((el) => el.offsetParent !== null);
      if (!tiles.length) return;
      const current = tiles.find((el) => el === document.activeElement || el.contains(document.activeElement));
      if (!current) { if (event.key === "ArrowDown" || event.key === "ArrowRight") { event.preventDefault(); tiles[0].focus(); } return; }
      const a = current.getBoundingClientRect();
      const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
      let best: HTMLElement | null = null, bestScore = Infinity;
      for (const el of tiles) {
        if (el === current) continue;
        const b = el.getBoundingClientRect();
        const bx = b.left + b.width / 2, by = b.top + b.height / 2;
        const dx = bx - ax, dy = by - ay;
        const ok = event.key === "ArrowRight" ? b.left >= a.right - 4 : event.key === "ArrowLeft" ? b.right <= a.left + 4 : event.key === "ArrowDown" ? b.top >= a.bottom - 4 : b.bottom <= a.top + 4;
        if (!ok) continue;
        const along = event.key === "ArrowLeft" || event.key === "ArrowRight" ? Math.abs(dx) : Math.abs(dy);
        const across = event.key === "ArrowLeft" || event.key === "ArrowRight" ? Math.abs(dy) : Math.abs(dx);
        const score = along + across * 2;
        if (score < bestScore) { bestScore = score; best = el; }
      }
      if (best) { event.preventDefault(); best.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ref, onBack]);
}

