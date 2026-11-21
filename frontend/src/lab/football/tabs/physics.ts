import { drawChart, type ChartSpec } from "../charts";
import { BALL_DEFAULTS, newBall, simulate, strike, v6Path } from "../physics/ball";
import { carryGap, cutPath, diagonalAccel, sprintCurve, splitTime, v6LoftProfile, V6 } from "../physics/player";
import { el, slider } from "../stage";

/**
 * Physics Research: the current V6 rules (replicated from highlights.py) against the
 * proposed physical models, on the same inputs. Every curve is computed live from code.
 */
const C = { v6: "#ff9f43", lab: "#5fd68a", lab2: "#7cc8ff", lab3: "#c6a2ff", ref: "#ffd166" };

export function mount(view: HTMLElement, panel: HTMLElement) {
  view.style.overflow = "auto";
  const grid = el("div", { style: "display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:10px;padding:10px" });
  view.append(grid);
  let pace = 80, dribbling = 75;
  const charts: { canvas: HTMLCanvasElement; spec: () => ChartSpec }[] = [];
  const add = (spec: () => ChartSpec) => { const c = el("canvas", { style: "width:100%;height:270px;border:1px solid #26313a;border-radius:6px" }); grid.append(c); charts.push({ canvas: c, spec }); };
  const R = BALL_DEFAULTS.radius;

  // 1. ground pass distance-time
  add(() => {
    const series: ChartSpec["series"] = [];
    for (const [v0, col] of [[10, C.lab], [15, C.lab2], [20, C.lab3]] as const) {
      // passes are struck with partial forward roll (side-foot ~ 40 % of rolling spin)
      const { v, w } = strike(v0, 0, 0, (v0 / R) * 0.4);
      const path = simulate(newBall({ x: 0, y: 0, z: R }, v, w), 12, 0.05).path;
      series.push({ name: `Lab ${v0} m/s`, colour: col, points: path.map((s) => [s.t, s.p.x]) });
      series.push({ name: v0 === 10 ? "V6 (5 m/s² constante)" : `_v6${v0}`, colour: C.v6, dash: [5, 4], points: v6Path(v0, V6.GROUND_DECEL).map((s) => [s.t, s.x]) });
    }
    return { title: "Passe rasteiro: distância × tempo", x: "s", y: "m", series, xMax: 8 };
  });
  // 2. shot speed vs distance
  add(() => {
    const series: ChartSpec["series"] = [];
    for (const [v0, col] of [[25, C.lab], [32, C.lab2]] as const) {
      const { v, w } = strike(v0, 0, 0.08, 10);
      const path = simulate(newBall({ x: 0, y: 0, z: R }, v, w), 3, 0.01).path.filter((s) => s.p.x <= 35);
      series.push({ name: `Lab ${v0}`, colour: col, points: path.map((s) => [s.p.x, Math.hypot(s.v.x, s.v.y, s.v.z)]) });
      const v6 = v6Path(v0, V6.SHOT_DECEL, 0.01).filter((s) => s.x <= 35);
      series.push({ name: v0 === 25 ? "V6 (1,5 m/s²)" : "_v6", colour: C.v6, dash: [5, 4], points: v6.map((s) => [s.x, s.v]) });
    }
    return { title: "Chute: velocidade × distância (arrasto do ar)", x: "m", y: "m/s", series, xMax: 35, yMin: 10 };
  });
  // 3. lofted ball height profile
  add(() => {
    const series: ChartSpec["series"] = [];
    for (const [dist, col, spin] of [[30, C.lab, -8], [45, C.lab2, -6]] as const) {
      // find elevation/speed for this distance with backspin (lofted pass)
      let best = { speed: 18, elev: 0.6, err: 1e9 };
      for (let sp = 14; sp <= 28; sp += 0.5) for (let el2 = 0.35; el2 <= 0.8; el2 += 0.025) {
        const k = strike(sp, 0, el2, spin);
        const path = simulate(newBall({ x: 0, y: 0, z: R }, k.v, k.w), 4, 0.02, BALL_DEFAULTS, [], (b) => b.p.z <= R + 1e-3 && b.v.z <= 0 && b.t > 0.2).path;
        const land = path[path.length - 1].p.x;
        const err = Math.abs(land - dist) + Math.abs(el2 - 0.55) * 4;
        if (err < best.err) best = { speed: sp, elev: el2, err };
      }
      const k = strike(best.speed, 0, best.elev, spin);
      const path = simulate(newBall({ x: 0, y: 0, z: R }, k.v, k.w), 4, 0.02, BALL_DEFAULTS, [], (b) => b.p.z <= R + 1e-3 && b.v.z <= 0 && b.t > 0.2).path;
      series.push({ name: `Lab ${dist} m (${best.speed} m/s, ${(best.elev * 57.3).toFixed(0)}°)`, colour: col, points: path.map((s) => [s.p.x, s.p.z]) });
      const power = Math.max(0, Math.min(1, (dist - V6.LOFT_RANGE[0]) / V6.LOFT_RANGE[1]));
      series.push({ name: dist === 30 ? "V6 (parábola fixa 3,2 m)" : "_v6", colour: C.v6, dash: [5, 4], points: v6LoftProfile(dist, power).map((p) => [p.x, p.z]) });
    }
    return { title: "Lançamento: altura × distância", x: "m", y: "m", series, xMax: 50 };
  });
  // 4. sprint
  add(() => {
    const lab = sprintCurve("model", pace), v6 = sprintCurve("v6", pace);
    return {
      title: `Arrancada do repouso (ritmo ${pace})`, x: "s", y: "m", xMax: 5,
      series: [{ name: "Proposto (força-velocidade)", colour: C.lab, points: lab.map((p) => [p.t, p.x]) }, { name: "V6", colour: C.v6, dash: [5, 4], points: v6.map((p) => [p.t, p.x]) }],
      marks: [{ x: 1.75, y: 10, label: "ref. 10 m ≈ 1,7–1,8 s" }, { x: 4.1, y: 30, label: "ref. 30 m ≈ 4,0–4,2 s" }],
    };
  });
  // 5. cut (top view)
  add(() => {
    const lab = cutPath("model", pace, 7), v6 = cutPath("v6", pace, 7);
    return { title: "Corte de 90° a 7 m/s (vista de cima)", x: "x (m)", y: "y (m)", equalAxes: true,
      series: [{ name: "Proposto (aderência ≤ 7,5 m/s²)", colour: C.lab, points: lab.map((p) => [p.x, p.y]) }, { name: "V6 (limite por eixo)", colour: C.v6, dash: [5, 4], points: v6.map((p) => [p.x, p.y]) }] };
  });
  // 6. dribble gap
  add(() => {
    const v6 = carryGap("v6", 6, dribbling), touch = carryGap("touch", 6, dribbling);
    return { title: `Condução a 6 m/s: distância bola–pé (drible ${dribbling})`, x: "s", y: "m", yMin: -0.2,
      series: [{ name: "Toques (bola solta)", colour: C.lab, points: touch.map((p) => [p.t, p.gap]) }, { name: "V6 (dente de serra preso ao jogador)", colour: C.v6, dash: [5, 4], points: v6.map((p) => [p.t, p.gap]) }] };
  });
  // 7. bounce + spin
  add(() => {
    const drop = simulate(newBall({ x: 0, y: 0, z: 2.5 }, { x: 6, y: 0, z: 0 }), 5, 0.01).path;
    const back = simulate(newBall({ x: 0, y: 0, z: 2.5 }, { x: 6, y: 0, z: 0 }, { x: 0, y: -40, z: 0 }), 5, 0.01).path;
    const top = simulate(newBall({ x: 0, y: 0, z: 2.5 }, { x: 6, y: 0, z: 0 }, { x: 0, y: 60, z: 0 }), 5, 0.01).path;
    return { title: "Quique: sem efeito, backspin e topspin", x: "m", y: "m", xMax: 16,
      series: [{ name: "sem efeito", colour: C.lab, points: drop.map((s) => [s.p.x, s.p.z]) }, { name: "backspin", colour: C.lab2, points: back.map((s) => [s.p.x, s.p.z]) }, { name: "topspin", colour: C.lab3, points: top.map((s) => [s.p.x, s.p.z]) }] };
  });
  // 8. curl (top view)
  add(() => {
    const series: ChartSpec["series"] = [];
    for (const [side, col] of [[0, C.lab], [25, C.lab2], [50, C.lab3]] as const) {
      const k = strike(25, 0, 0.12, 0, side);
      const p = simulate(newBall({ x: 0, y: 0, z: R }, k.v, k.w), 1.2, 0.01).path.filter((s) => s.p.x < 25);
      series.push({ name: `efeito ${side} rad/s`, colour: col, points: p.map((s) => [s.p.x, s.p.y]) });
    }
    return { title: "Chute colocado: curva (vista de cima)", x: "m", y: "desvio (m)", series, xMax: 25 };
  });

  const redraw = () => { for (const c of charts) drawChart(c.canvas, c.spec()); renderTable(); };
  const table = el("table");
  const renderTable = () => {
    const lab = sprintCurve("model", pace), v6 = sprintCurve("v6", pace);
    const pass = (v0: number) => { const k = strike(v0, 0, 0, (v0 / R) * 0.4); const p = simulate(newBall({ x: 0, y: 0, z: R }, k.v, k.w), 15, 0.02).path; return p[p.length - 1].p.x; };
    const rows: [string, string, string][] = [
      ["Passe 15 m/s: alcance", `${(15 * 15 / (2 * V6.GROUND_DECEL)).toFixed(1)} m`, `${pass(15).toFixed(1)} m`],
      ["Passe 20 m/s: alcance", `${(400 / (2 * V6.GROUND_DECEL)).toFixed(1)} m`, `${pass(20).toFixed(1)} m`],
      ["10 m (arrancada)", `${splitTime(v6, 10)?.toFixed(2)} s`, `${splitTime(lab, 10)?.toFixed(2)} s`],
      ["30 m (arrancada)", `${splitTime(v6, 30)?.toFixed(2)} s`, `${splitTime(lab, 30)?.toFixed(2)} s`],
      ["Aceleração na diagonal", `${diagonalAccel("v6", pace).toFixed(1)} m/s²`, `${diagonalAccel("model", pace).toFixed(1)} m/s²`],
      ["Altura máx. do lançamento", "3,2 m (fixa)", "depende de v, ângulo, efeito"],
    ];
    table.replaceChildren(el("tr", {}, el("th", { text: "Medida" }), el("th", { text: "V6" }), el("th", { text: "Proposto" })), ...rows.map((r) => el("tr", {}, ...r.map((c) => el("td", { text: c })))));
  };
  panel.append(
    el("h3", { text: "Parâmetros" }),
    slider("Ritmo (pace)", 30, 100, 1, pace, (v) => { pace = v; redraw(); }, (v) => `${v}`),
    slider("Drible", 30, 100, 1, dribbling, (v) => { dribbling = v; redraw(); }, (v) => `${v}`),
    el("h3", { text: "Números (mesmas entradas)" }), table,
    el("p", { class: "note", text: "Laranja tracejado = regra atual (highlights.py), recalculada aqui com as mesmas constantes. Verde/azul/lilás = modelos propostos (physics/ball.ts e physics/player.ts). As referências de arrancada são valores típicos de atletas profissionais (aproximados), não medições deste projeto." }),
  );
  requestAnimationFrame(redraw);
  const ro = new ResizeObserver(() => redraw());
  ro.observe(view);
  (window as unknown as { __lab: unknown }).__lab = { redraw, setPace: (v: number) => { pace = v; redraw(); } };
  return () => ro.disconnect();
}
