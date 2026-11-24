import { useEffect, useState } from "react";

/** Uniform console scale: 1 up to 1366×768, then grows with the smaller of width/1366 and height/768 (max 2). */
export function useConsoleScale(): number {
  const read = () => typeof window === "undefined" ? 1 : Math.max(1, Math.min(2, window.innerWidth / 1366, window.innerHeight / 768));
  const [scale, setScale] = useState(read);
  useEffect(() => { const sync = () => setScale(read()); window.addEventListener("resize", sync); return () => window.removeEventListener("resize", sync); }, []);
  return scale;
}
