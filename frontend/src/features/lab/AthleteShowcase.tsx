import { useEffect, useRef, useState } from "react";

/** #lab-atleta — the 3D athlete prototype: front, back, side, close-up, run, kick and keeper dive. */
export function AthleteShowcase() {
  const host = useRef<HTMLDivElement | null>(null);
  const params = new URLSearchParams(window.location.search);
  const [keeper, setKeeper] = useState(params.get("gk") === "1");
  const [style, setStyle] = useState<"human" | "voxel">(params.get("style") === "voxel" ? "voxel" : "human");
  useEffect(() => {
    let dispose: (() => void) | null = null, cancelled = false;
    void import("../career/interactive/render/renderer3d").then(({ mountAthleteShowcase }) => {
      if (cancelled || !host.current) return;
      dispose = mountAthleteShowcase(host.current, { keeper, style, angle: Number(params.get("angle") ?? 0), zoom: Number(params.get("zoom") ?? 1), pose: params.get("pose") ?? undefined, autoRotate: params.get("rotate") !== "0" });
    });
    return () => { cancelled = true; dispose?.(); };
  }, [keeper, style]); // eslint-disable-line react-hooks/exhaustive-deps
  return <main style={{ position: "fixed", inset: 0, display: "grid", gridTemplateRows: "auto 1fr", background: "#0d1117", color: "#fff" }}>
    <header style={{ display: "flex", gap: "1rem", alignItems: "center", padding: ".6rem 1rem" }}>
      <b>Protótipo de atleta 3D</b>
      <label><input type="checkbox" checked={keeper} onChange={(e) => setKeeper(e.target.checked)} /> Goleiro</label>
      <label><input type="checkbox" checked={style === "voxel"} onChange={(e) => setStyle(e.target.checked ? "voxel" : "human")} /> Comparar com o modelo anterior (voxel)</label>
      <a href="#lab" style={{ color: "#c6f24e" }}>Voltar ao Lab</a>
    </header>
    <div ref={host} style={{ position: "relative", minHeight: 0 }} />
  </main>;
}
