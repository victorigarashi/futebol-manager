import * as THREE from "three";
import { createAthlete } from "../athlete/athlete";
import { KIT_AWAY, KIT_KEEPER } from "../athlete/kit";
import { applyPose } from "../athlete/rig";
import { CLIPS, samplePose } from "../anim/clips";
import { fkRig, worldOf } from "../anim/fk";
import { KeeperAnimator, frameAt } from "../keeper/animate";
import { aimShot, KEEPER_DEFAULTS, keeperFromRating, lineCrossing, scenarios, setPosition, simulateShot, v6KeeperOutcome, type KeeperParams, type KeeperResult, type Shot } from "../keeper/sim";
import { BALL_DEFAULTS, newBall, simulate, strike } from "../physics/ball";
import { Aim, makeBall, makeBoxLines, makeGoal, toThree } from "../props";
import { button, checkbox, createStage, el, slider } from "../stage";

/**
 * Goalkeeper Lab: repeatable shots against the physical keeper. Drag from the ball to shoot
 * (minimal aim: dashed line + dot where the ball crosses the goal line); presets and a batch
 * table compare keeper ratings and the current V6 rule.
 */
export function mount(view: HTMLElement, panel: HTMLElement) {
  const stage = createStage(view, { shadows: true, groundSize: 160 });
  stage.scene.add(makeGoal(), makeBoxLines());
  stage.sun.position.set(-8, 14, 12);
  const keeper = createAthlete({ kit: KIT_KEEPER, keeper: true, detail: "high", shadows: true, seed: 5 });
  const shooter = createAthlete({ kit: KIT_AWAY, detail: "high", shadows: true, seed: 23 });
  stage.scene.add(keeper.group, shooter.group);
  const anim = new KeeperAnimator(keeper);
  const ball = makeBall();
  stage.scene.add(ball);
  const aim = new Aim("#ffffff");
  stage.scene.add(aim.group);
  const trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: "#ffd166" }));
  const comTrail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: "#7cc8ff" }));
  const contactDot = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), new THREE.MeshBasicMaterial({ color: "#ff3b3b", depthTest: false }));
  contactDot.renderOrder = 9;
  stage.scene.add(trail, comTrail, contactDot);
  const hud = el("div", { class: "hud" });
  const hud2 = el("div", { class: "hud right" });
  view.append(hud, hud2);

  let params: KeeperParams = keeperFromRating(85);
  let slow = 1, heightBias = 0.35, showTrails = false;
  let shot: Shot = scenarios()[1].shot;
  let res: KeeperResult | null = null;
  let t = -1.2;
  let label = "";
  const defaultFrom = () => ({ x: 17, y: -3, z: BALL_DEFAULTS.radius });
  let from = defaultFrom();

  // shooter placement: his instep meets the ball at the strike frame (FK contact offset)
  const contact = (() => { const rig = fkRig(); applyPose(rig, samplePose(CLIPS.shot, CLIPS.shot.meta.contact!.u)); const p = worldOf(rig, "toeR", new THREE.Vector3(0, 0, 0.03)); return new THREE.Vector3(p.x, 0, p.z + 0.1); })();
  const placeShooter = (heading: number, tt: number) => {
    shooter.group.rotation.set(0, heading, 0);
    const off = contact.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), heading);
    const b = toThree(from);
    shooter.group.position.set(b.x - off.x, 0, b.z - off.z);
    const ct = CLIPS.shot.meta.contact!.time;
    const u = (tt + ct) / CLIPS.shot.meta.duration;
    shooter.setPose(u < 0 ? samplePose(CLIPS.run, ((u * CLIPS.shot.meta.duration / 0.66) % 1 + 1) % 1) : u <= 1 ? samplePose(CLIPS.shot, u) : samplePose(CLIPS.idle, 0));
  };

  const run = (s: Shot, name: string) => {
    shot = s; from = { ...s.from }; label = name;
    res = simulateShot(s, { keeper: params, seed: 7 });
    t = -0.75;
    // debug trails
    const bp = res.frames.map((f) => toThree(f.ball));
    trail.geometry.dispose(); trail.geometry = new THREE.BufferGeometry().setFromPoints(bp);
    comTrail.geometry.dispose(); comTrail.geometry = new THREE.BufferGeometry().setFromPoints(res.frames.map((f) => toThree(f.com)));
    contactDot.visible = false;
    renderResult();
  };

  const pill = (o: string) => { const s = el("span", { class: `pill ${o.startsWith("SAVE") ? "PARRY" : o}`, text: o }); return s; };
  const renderResult = () => {
    if (!res) return;
    const v6 = v6KeeperOutcome(shot, Math.round(55 + (0.34 - params.reaction) / 0.14 * 45));
    const at = res.ballAtLine ?? lineCrossing(shot);
    hud2.replaceChildren(
      el("div", {}, el("b", { text: label + "  " }), pill(res.outcome)),
      el("div", { text: res.detail }),
      el("div", { text: `Plano: ${res.plan?.reason ?? "—"}` }),
      el("div", { text: `Chute ${shot.speed.toFixed(0)} m/s · cruza a linha em ${at ? `(${at.y.toFixed(2)}, ${at.z.toFixed(2)}) m` : "—"}` }),
      el("div", { text: `Reação ${params.reaction.toFixed(2)} s · impulsão ${res.takeoff !== null ? res.takeoff.toFixed(2) + " s" : "—"} · contato ${res.contact ? res.contact.t.toFixed(2) + " s" : "—"}` }),
      el("div", { text: `Vel. máx. do CG ${res.maxComSpeed.toFixed(2)} m/s (sem teleporte)` }),
      el("div", { text: `Regra V6 no mesmo chute: ${v6.result === "MAYBE" ? `sorteio ${Math.round(v6.probability * 100)}%` : v6.result === "SAVE" ? "defesa garantida" : "não alcança"}` }),
    );
  };

  // ---- drag to shoot (minimal aim)
  const ray = new THREE.Raycaster();
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  let dragging = false, dragStart = { x: 0, y: 0 }, pending: Shot | null = null;
  const groundAt = (ev: PointerEvent) => {
    const r = stage.canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), stage.camera);
    return ray.ray.intersectPlane(plane, new THREE.Vector3());
  };
  stage.canvas.addEventListener("pointerdown", (ev) => {
    const g = groundAt(ev);
    if (!g || g.distanceTo(toThree(from).setY(0)) > 3) return;
    dragging = true; dragStart = { x: ev.clientX, y: ev.clientY }; stage.controls.enabled = false;
    res = null; t = -1.2;
  });
  stage.canvas.addEventListener("pointermove", (ev) => {
    if (!dragging) return;
    const g = groundAt(ev);
    if (!g) return;
    const b = toThree(from);
    const heading = Math.atan2(g.x - b.x, g.z - b.z);    // lab heading (x = three Z, y = three X)
    const power = Math.max(0.1, Math.min(1, Math.hypot(ev.clientX - dragStart.x, ev.clientY - dragStart.y) / 260));
    const speed = 14 + 20 * power;
    const elev = 0.03 + heightBias * 0.28 + Math.max(0, power - 0.6) * 0.12;
    pending = { from: { ...from }, speed, heading, elevation: elev };
    // dot = where the ball crosses the goal line (or where it ends if it never gets there)
    const cross = lineCrossing(pending);
    let end: THREE.Vector3;
    if (cross) end = toThree(cross);
    else { const k = strike(speed, heading, elev); const p = simulate(newBall(from, k.v, k.w), 1.2, 0.05).path; end = toThree(p[p.length - 1].p); }
    aim.set([b.clone(), end]);
    hud.textContent = `Potência ${(power * 100).toFixed(0)}% · ${speed.toFixed(0)} m/s`;
  });
  window.addEventListener("pointerup", () => {
    if (!dragging) return;
    dragging = false; stage.controls.enabled = true; aim.hide();
    if (pending) run(pending, "Chute livre");
    pending = null;
  });

  // ---- frame loop
  stage.onFrame((dt) => {
    t += dt * slow;
    if (res) {
      const end = res.frames[res.frames.length - 1].t + 1.2;
      if (t > end) t = -0.75;
      anim.apply(res, t, dt * slow);
      const f = frameAt(res.frames, Math.max(0, t));
      if (t < 0) toThree(from, ball.position); else toThree(f.ball, ball.position);
      ball.rotation.x += (f.ballSpin?.y ?? 0) * dt * slow; ball.rotation.z -= (f.ballSpin?.x ?? 0) * dt * slow;
      placeShooter(shot.heading, t);
      if (res.contact && t >= res.contact.t) { contactDot.visible = true; toThree(res.contact.at, contactDot.position); }
      else contactDot.visible = false;
      hud.textContent = `t = ${t.toFixed(2)} s desde o chute · ${f.phase} · câmera lenta ${slow.toFixed(2)}×\nArraste a partir da bola para chutar (linha tracejada + ponto)`;
    } else {
      anim.idle(t);
      const p = setPosition(from, params);
      keeper.group.position.set(toThree(p).x, 0, toThree(p).z);
      toThree(from, ball.position);
      const g = toThree({ x: 0, y: 0, z: 0 }).sub(toThree(from));
      placeShooter(Math.atan2(g.x, g.z), -0.6);
      if (!dragging) hud.textContent = "Arraste a partir da bola para chutar (linha tracejada + ponto no destino)";
    }
    trail.visible = comTrail.visible = showTrails && !!res;
  });

  // ---- panel
  const scen = scenarios();
  const scenBtns = el("div", { class: "btns" });
  for (const s of scen) scenBtns.append(button(s.label, () => run(s.shot, s.label), { title: s.note, "data-s": s.id }));
  const table = el("table");
  const batch = () => {
    const rows = [el("tr", {}, ...["Cenário", "GK 45", "GK 70", "GK 92", "V6 (70)"].map((h) => el("th", { text: h })))];
    for (const s of scen) {
      const cells = [45, 70, 92].map((r) => simulateShot(s.shot, { keeper: keeperFromRating(r), seed: 7 }).outcome);
      const v6 = v6KeeperOutcome(s.shot, 70);
      rows.push(el("tr", {}, el("td", { text: s.label }), ...cells.map((o) => el("td", {}, pill(o))), el("td", { text: v6.result === "MAYBE" ? `${Math.round(v6.probability * 100)}%` : v6.result })));
    }
    table.replaceChildren(...rows);
  };
  const sliders = el("div");
  const renderSliders = () => sliders.replaceChildren(
    slider("Reação", 0.12, 0.45, 0.01, params.reaction, (v) => { params = { ...params, reaction: v }; }, (v) => `${v.toFixed(2)} s`),
    slider("Impulsão lateral", 2.5, 5.5, 0.1, params.diveSpeed, (v) => { params = { ...params, diveSpeed: v }; }, (v) => `${v.toFixed(1)} m/s`),
    slider("Impulsão vertical", 1.8, 3.4, 0.1, params.jumpSpeed, (v) => { params = { ...params, jumpSpeed: v }; }, (v) => `${v.toFixed(1)} m/s`),
    slider("Alcance (braço)", 0.9, 1.3, 0.01, params.reach, (v) => { params = { ...params, reach: v }; }, (v) => `${v.toFixed(2)} m`),
    slider("Encaixe até", 10, 30, 0.5, params.catchMaxSpeed, (v) => { params = { ...params, catchMaxSpeed: v }; }, (v) => `${v.toFixed(0)} m/s`),
    slider("Preparação", 0.06, 0.2, 0.01, params.load, (v) => { params = { ...params, load: v }; }, (v) => `${v.toFixed(2)} s`),
    slider("Ruído percep.", 0, 0.5, 0.01, params.perceptionNoise, (v) => { params = { ...params, perceptionNoise: v }; }, (v) => `${v.toFixed(2)} m`),
    slider("Saída do gol", 0.3, 2.5, 0.05, params.offLine, (v) => { params = { ...params, offLine: v }; }, (v) => `${v.toFixed(2)} m`),
  );
  renderSliders();
  const cam = (p: [number, number, number], tg: [number, number, number]) => { stage.camera.position.set(...p); stage.controls.target.set(...tg); };
  panel.append(
    el("h3", { text: "Cenários" }), scenBtns,
    el("div", { class: "btns" }, button("Repetir", () => run(shot, label)), button("Rodar todos (tabela)", batch)),
    el("h3", { text: "Goleiro" }),
    el("div", { class: "btns" }, ...[45, 70, 85, 92].map((r) => button(`Nota ${r}`, () => { params = keeperFromRating(r); renderSliders(); }))),
    sliders,
    el("h3", { text: "Chute livre" }),
    slider("Altura", 0, 1, 0.01, heightBias, (v) => { heightBias = v; }, (v) => `${Math.round(v * 100)}%`),
    el("div", { class: "btns" }, button("Posição: frente", () => { from = { x: 16, y: 0, z: 0.11 }; res = null; }), button("Posição: diagonal", () => { from = defaultFrom(); res = null; }), button("Posição: perto", () => { from = { x: 9, y: 2, z: 0.11 }; res = null; })),
    el("h3", { text: "Visual" }),
    slider("Câmera lenta", 0.1, 1, 0.05, slow, (v) => { slow = v; }, (v) => `${v.toFixed(2)}×`),
    checkbox("Trajetórias (bola e CG)", showTrails, (v) => { showTrails = v; }),
    el("div", { class: "btns" }, button("Atrás do atacante", () => cam([-5, 3.2, 26], [0, 1.2, 0])), button("Atrás do gol", () => cam([1.5, 2.4, -6.5], [0, 1, 6])), button("Lateral", () => cam([12, 2.2, 3], [0, 1.1, 2])), button("TV", () => cam([-14, 9, 15], [0, 1, 4]))),
    el("h3", { text: "Comparação" }), table,
    el("p", { class: "note", text: "O resultado sai da física: reação, impulsão limitada, alcance dos braços e contato real com a bola. Não há sorteio de defesa. A coluna V6 mostra a regra atual de highlights.py para o mesmo chute (porcentagem = sorteio)." }),
  );
  cam([-5, 3.2, 26], [0, 1.2, 0]);

  (window as unknown as { __lab: unknown }).__lab = {
    stage, cam, batch,
    run: (id: string, rating?: number) => { if (rating) { params = keeperFromRating(rating); renderSliders(); } const s = scen.find((x) => x.id === id)!; run(s.shot, s.label); },
    shoot: (fx: number, fy: number, ty: number, tz: number, speed: number) => { from = { x: fx, y: fy, z: 0.11 }; run(aimShot(from, { y: ty, z: tz }, speed), "Chute"); },
    slow: (v: number) => { slow = v; }, setT: (v: number) => { t = v; }, trails: (v: boolean) => { showTrails = v; },
    result: () => res && { outcome: res.outcome, detail: res.detail, plan: res.plan?.kind, takeoff: res.takeoff, contact: res.contact?.t },
    params: () => params, defaults: () => KEEPER_DEFAULTS,
  };
  return () => { keeper.dispose(); shooter.dispose(); stage.dispose(); };
}
