import { AI_SCENARIOS, makeWorld, metrics, passSafety, pitchControl, seededRng, spotScore, step, type Agent, type World } from "../ai/tactics";
import { button, checkbox, el, select, slider } from "../stage";

/** Football AI Lab: top-down, deterministic scenarios with pitch control, lanes and decisions drawn live. */
export function mount(view: HTMLElement, panel: HTMLElement) {
  const canvas = el("canvas", { class: "fill" });
  view.append(canvas);
  const hud = el("div", { class: "hud" });
  view.append(hud);
  let def = AI_SCENARIOS[3];
  let seed = 1;
  let world: World = makeWorld(def, seed);
  let rng = seededRng(seed);
  let speed = 1, paused = false, showPC = true, showLanes = true, showTargets = true, showSpot: string | null = null, naive = false;
  let raf = 0, last = performance.now(), acc = 0;
  const DT = 1 / 30;
  const trails = new Map<string, { x: number; y: number }[]>();

  const reset = () => { world = makeWorld(def, seed); rng = seededRng(seed); trails.clear(); log.textContent = ""; renderInfo(); };
  const naiveStep = (w: World, dt: number) => {
    // baseline for comparison: everyone runs at the ball (what "artificial" football looks like)
    for (const a of w.agents) if (a.role !== "GK" && a.id !== w.ball.owner) { a.target = { ...w.ball.p }; a.task = "persegue"; }
    step(w, dt, rng);
    for (const a of w.agents) if (a.role !== "GK" && a.id !== w.ball.owner) a.target = { ...w.ball.p };
  };

  const frame = (now: number) => {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (!paused) { acc += dt * speed; while (acc >= DT) { if (naive) naiveStep(world, DT); else step(world, DT, rng); acc -= DT; for (const a of world.agents) { const tr = trails.get(a.id) ?? []; tr.push({ ...a.p }); if (tr.length > 90) tr.shift(); trails.set(a.id, tr); } } }
    draw();
    raf = requestAnimationFrame(frame);
  };

  const draw = () => {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const Wc = view.clientWidth, Hc = view.clientHeight;
    canvas.width = Wc * dpr; canvas.height = Hc * dpr;
    const g = canvas.getContext("2d")!;
    g.scale(dpr, dpr);
    const pad = 24, s = Math.min((Wc - 2 * pad) / world.L, (Hc - 2 * pad - 20) / world.W);
    const ox = (Wc - world.L * s) / 2, oy = (Hc - world.W * s) / 2 + 10;
    const X = (x: number) => ox + x * s, Y = (y: number) => oy + y * s;
    g.fillStyle = "#0f1418"; g.fillRect(0, 0, Wc, Hc);
    // grass stripes
    for (let i = 0; i < 12; i += 1) { g.fillStyle = i % 2 ? "#2f7d3a" : "#348a40"; g.fillRect(X((world.L * i) / 12), Y(0), (world.L * s) / 12 + 1, world.W * s); }
    // pitch control heat (attacking team)
    if (showPC || showSpot) {
      const cell = 2;
      const spotAgent = showSpot ? world.agents.find((a) => a.id === showSpot) : null;
      let lo = Infinity, hi = -Infinity;
      const vals: number[][] = [];
      for (let x = 0; x < world.L; x += cell) { const col: number[] = []; for (let y = 0; y < world.W; y += cell) { const v = spotAgent ? spotScore(world, spotAgent, { x: x + 1, y: y + 1 }) : pitchControl(world, { x: x + 1, y: y + 1 }); col.push(v); lo = Math.min(lo, v); hi = Math.max(hi, v); } vals.push(col); }
      vals.forEach((col, i) => col.forEach((v, j) => {
        const k = spotAgent ? (v - lo) / (hi - lo || 1) : v;
        g.fillStyle = spotAgent ? `rgba(255,${Math.round(200 * k)},40,${0.08 + 0.5 * k})` : k > 0.5 ? `rgba(80,160,255,${(k - 0.5) * 0.7})` : `rgba(255,80,80,${(0.5 - k) * 0.7})`;
        g.fillRect(X(i * cell), Y(j * cell), cell * s + 0.5, cell * s + 0.5);
      }));
    }
    // lines
    g.strokeStyle = "rgba(255,255,255,0.85)"; g.lineWidth = 1.5;
    g.strokeRect(X(0), Y(0), world.L * s, world.W * s);
    const by = world.W / 2;
    g.strokeRect(X(world.L - 16.5), Y(by - 20.16), 16.5 * s, 40.32 * s); g.strokeRect(X(world.L - 5.5), Y(by - 9.16), 5.5 * s, 18.32 * s);
    g.fillStyle = "#fff"; g.fillRect(X(world.L), Y(by - 3.66), 4, 7.32 * s);
    // offside line
    const lineX = Math.max(...world.agents.filter((a) => a.team === "D" && a.role !== "GK").map((a) => a.p.x));
    g.setLineDash([4, 4]); g.strokeStyle = "rgba(255,230,120,0.7)"; g.beginPath(); g.moveTo(X(lineX), Y(0)); g.lineTo(X(lineX), Y(world.W)); g.stroke(); g.setLineDash([]);
    // pass lanes from the carrier
    const c = world.ball.owner ? world.agents.find((a) => a.id === world.ball.owner) : null;
    if (showLanes && c) for (const m of world.agents) if (m.team === "A" && m.id !== c.id && m.role !== "GK") {
      const safe = passSafety(world, c.p, m.p, m);
      g.strokeStyle = `hsla(${Math.round(120 * safe)},90%,55%,${0.35 + safe * 0.5})`; g.lineWidth = 1 + safe * 2.5;
      g.beginPath(); g.moveTo(X(c.p.x), Y(c.p.y)); g.lineTo(X(m.p.x), Y(m.p.y)); g.stroke();
    }
    // trails and targets
    for (const a of world.agents) {
      const tr = trails.get(a.id) ?? [];
      g.strokeStyle = a.team === "A" ? "rgba(120,190,255,0.35)" : "rgba(255,140,140,0.35)"; g.lineWidth = 1.5;
      g.beginPath(); tr.forEach((p, i) => (i ? g.lineTo(X(p.x), Y(p.y)) : g.moveTo(X(p.x), Y(p.y)))); g.stroke();
      if (showTargets && a.role !== "GK") { g.setLineDash([3, 3]); g.strokeStyle = a.team === "A" ? "rgba(180,220,255,0.8)" : "rgba(255,190,190,0.7)"; g.beginPath(); g.moveTo(X(a.p.x), Y(a.p.y)); g.lineTo(X(a.target.x), Y(a.target.y)); g.stroke(); g.setLineDash([]); }
    }
    // players
    for (const a of world.agents) drawAgent(g, a, X, Y, s);
    // ball
    g.fillStyle = "#fff"; g.strokeStyle = "#111"; g.lineWidth = 1.5; g.beginPath(); g.arc(X(world.ball.p.x), Y(world.ball.p.y), Math.max(3.5, 0.4 * s), 0, Math.PI * 2); g.fill(); g.stroke();
    if (world.ball.inFlight) { g.setLineDash([6, 5]); g.strokeStyle = "#fff"; g.beginPath(); g.moveTo(X(world.ball.p.x), Y(world.ball.p.y)); g.lineTo(X(world.ball.inFlight.to.x), Y(world.ball.inFlight.to.y)); g.stroke(); g.setLineDash([]); g.beginPath(); g.arc(X(world.ball.inFlight.to.x), Y(world.ball.inFlight.to.y), 3.5, 0, Math.PI * 2); g.fillStyle = "#fff"; g.fill(); }
    const m = metrics(world);
    hud.textContent = `${def.label} · t=${world.t.toFixed(1)} s${world.done ? ` · FIM: ${world.done}` : ""}${naive ? " · BASELINE: todos perseguem" : ""}\n` +
      `Perseguidores da bola: ${m.chasers} · opções de passe seguras: ${m.options} · espaçamento mín./médio ${m.minSpacing.toFixed(1)}/${m.meanSpacing.toFixed(1)} m\n` +
      `Bloco defensivo: ${m.defLength.toFixed(1)} m de profundidade × ${m.defWidth.toFixed(1)} m de largura`;
    if (world.events.length !== logCount) { logCount = world.events.length; log.textContent = world.events.slice(-12).join("\n"); }
  };
  let logCount = 0;

  const scenSel = select("Cenário", AI_SCENARIOS.map((d) => d.id), def.id, (v) => { def = AI_SCENARIOS.find((d) => d.id === v)!; reset(); }, Object.fromEntries(AI_SCENARIOS.map((d) => [d.id, d.label])));
  const info = el("p", { class: "note" });
  const renderInfo = () => { info.textContent = def.note; spotSel.replaceChildren(el("option", { value: "", text: "(campo de controle)" }), ...world.agents.filter((a) => a.team === "A" && a.role !== "GK").map((a) => el("option", { value: a.id, text: `#${a.num} ${a.role}` }))); };
  const spotSel = el("select");
  spotSel.addEventListener("change", () => { showSpot = spotSel.value || null; });
  const log = el("pre", { style: "white-space:pre-wrap;font-size:11.5px;color:#b8c4cd;margin:4px 0" });
  panel.append(
    el("h3", { text: "Cenário" }), scenSel, info,
    el("div", { class: "btns" }, button("Reiniciar", reset), button("Pausar/continuar", () => { paused = !paused; }), button("Semente +1", () => { seed += 1; reset(); })),
    slider("Velocidade", 0.1, 3, 0.1, speed, (v) => { speed = v; }, (v) => `${v.toFixed(1)}×`),
    el("h3", { text: "Camadas" }),
    checkbox("Controle de campo (azul = ataque)", showPC, (v) => { showPC = v; }),
    checkbox("Linhas de passe (verde = seguro)", showLanes, (v) => { showLanes = v; }),
    checkbox("Alvos (para onde cada um corre)", showTargets, (v) => { showTargets = v; }),
    el("label", { class: "row" }, el("span", { text: "Decisão de" }), spotSel),
    el("h3", { text: "Comparação" }),
    checkbox("Baseline: todos perseguem a bola", naive, (v) => { naive = v; reset(); }),
    el("h3", { text: "Eventos" }), log,
    el("p", { class: "note", text: "Tudo determinístico por semente. Utility AI + tempo até interceptar + steering com aceleração e aderência limitadas. Linha amarela = linha de impedimento. Tracejado = alvo de corrida; legenda dos papéis: pressiona, cobertura, marca, zona, apoio, ruptura, ultrapassagem, passa e se move." }),
  );
  renderInfo();
  raf = requestAnimationFrame(frame);
  document.body.dataset.ready = "1";
  (window as unknown as { __lab: unknown }).__lab = {
    scenario: (id: string, sd = 1) => { def = AI_SCENARIOS.find((d) => d.id === id)!; seed = sd; reset(); scenSel.querySelector("select")!.value = id; },
    naive: (v: boolean) => { naive = v; reset(); }, speed: (v: number) => { speed = v; }, layers: (pc: boolean, lanes: boolean, targets: boolean) => { showPC = pc; showLanes = lanes; showTargets = targets; },
    spot: (id: string | null) => { showSpot = id; }, metrics: () => ({ ...metrics(world), t: world.t, done: world.done, events: world.events }),
  };
  return () => cancelAnimationFrame(raf);
}

function drawAgent(g: CanvasRenderingContext2D, a: Agent, X: (x: number) => number, Y: (y: number) => number, s: number) {
  const r = Math.max(7, 0.75 * s);
  const col = a.team === "A" ? (a.role === "GK" ? "#f5b83d" : "#1d6bff") : a.role === "GK" ? "#9b6bff" : "#e3342f";
  g.fillStyle = "rgba(0,0,0,0.3)"; g.beginPath(); g.ellipse(X(a.p.x) + 2, Y(a.p.y) + 3, r, r * 0.7, 0, 0, Math.PI * 2); g.fill();
  g.fillStyle = col; g.strokeStyle = "#fff"; g.lineWidth = 1.5; g.beginPath(); g.arc(X(a.p.x), Y(a.p.y), r, 0, Math.PI * 2); g.fill(); g.stroke();
  // facing / velocity
  const sp = Math.hypot(a.v.x, a.v.y);
  if (sp > 0.3) { g.strokeStyle = "#fff"; g.lineWidth = 2; g.beginPath(); g.moveTo(X(a.p.x), Y(a.p.y)); g.lineTo(X(a.p.x + a.v.x / sp * 1.4), Y(a.p.y + a.v.y / sp * 1.4)); g.stroke(); }
  g.fillStyle = "#fff"; g.font = `700 ${Math.round(r * 0.95)}px Inter, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(a.num), X(a.p.x), Y(a.p.y) + 0.5);
  if (a.task && a.role !== "GK") { g.font = "10.5px Inter, sans-serif"; g.fillStyle = "rgba(255,255,255,0.9)"; g.fillText(a.task, X(a.p.x), Y(a.p.y) - r - 7); }
  g.textAlign = "start"; g.textBaseline = "alphabetic";
}
