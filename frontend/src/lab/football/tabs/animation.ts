import * as THREE from "three";
import { createAthlete } from "../athlete/athlete";
import { KIT_HOME, KIT_KEEPER } from "../athlete/kit";
import { applyPose, lerpPose, mirrorPose, type Pose } from "../athlete/rig";
import { CLIP_DEFS, CLIPS, clipMetadata, contactSpeed, samplePose, type ClipDef, type ContactPart } from "../anim/clips";
import { fkRig, worldOf } from "../anim/fk";
import { Locomotion, RootDriver, type LocoMode, type PathKind } from "../anim/locomotion";
import { BALL_DEFAULTS, newBall, stepBall, strike, type BallState } from "../physics/ball";
import { makeBall } from "../props";
import { button, checkbox, createStage, el, select, slider } from "../stage";

type Mode = "clip" | "loco" | "blend";
const PART_BONE: Record<ContactPart, string> = { footR: "toeR", footL: "toeL", head: "head", chest: "chest", hands: "handL", handL: "handL", handR: "handR", thighR: "shinR" };
/** Ball launch per action at the contact frame (forward = facing). Visual only: the engine decides the real ball. */
const LAUNCH: Record<string, { speed: number; elev: number; heading?: number; top?: number; side?: number; incoming?: { speed: number; height: number } }> = {
  shot: { speed: 26, elev: 0.1, top: 8 }, first_time: { speed: 24, elev: 0.12, top: 6, incoming: { speed: 9, height: 0 } },
  pass_short: { speed: 11, elev: 0, top: 60 }, pass_long: { speed: 21, elev: 0.48, top: -10 }, cross: { speed: 21, elev: 0.32, heading: 0.2, side: 12 },
  dribble: { speed: 5, elev: 0 }, receive: { speed: 0.8, elev: 0, incoming: { speed: 9, height: 0 } }, chest_control: { speed: 1.2, elev: -0.6, incoming: { speed: 8, height: 2.5 } },
  header: { speed: 12, elev: 0.05, incoming: { speed: 12, height: 3.2 } }, stand_tackle: { speed: 6, elev: 0, heading: -0.6 }, slide_tackle: { speed: 7, elev: 0.1, heading: 0.4 },
  gk_throw: { speed: 15, elev: 0.18 }, gk_catch: { speed: 0, elev: 0, incoming: { speed: 16, height: 1.2 } },
};

export function mount(view: HTMLElement, panel: HTMLElement) {
  const stage = createStage(view, { shadows: true });
  stage.camera.position.set(3.4, 1.7, 4.2);
  const hud = el("div", { class: "hud" });
  view.append(hud);
  let athlete = createAthlete({ kit: KIT_HOME, detail: "high", shadows: true, seed: 11 });
  stage.scene.add(athlete.group);
  const ball = makeBall();
  stage.scene.add(ball);
  const marker = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 8), new THREE.MeshBasicMaterial({ color: "#ffeb3b", depthTest: false }));
  marker.renderOrder = 5;
  stage.scene.add(marker);
  const prints = new THREE.Group();
  stage.scene.add(prints);
  const printGeo = new THREE.CircleGeometry(0.05, 12).rotateX(-Math.PI / 2);
  const printMat = { L: new THREE.MeshBasicMaterial({ color: "#1b4fd6" }), R: new THREE.MeshBasicMaterial({ color: "#d61b3a" }) };

  let mode: Mode = "clip";
  let clip: ClipDef = CLIPS.shot;
  let playing = true, mirror = false, timeScale = 1, u = 0, loopAll = true, showBall = true, freezeAtContact = false;
  const loco = new Locomotion();
  let driver = new RootDriver("figure8", 4.5);
  let follow = true;
  let blendA: ClipDef = CLIPS.run, blendB: ClipDef = CLIPS.shot, blendDur = 0.2, blendT = -1, tA = 0, tB = 0;
  let ballSim: BallState | null = null;
  let ballHeld: "hands" | "handR" | null = null;
  let contactFired = false;

  const metaTable = el("table");
  const contactInfo = el("div", { class: "note" });
  const renderMeta = () => {
    const m = clip.meta;
    const fs = contactSpeed(clip);
    metaTable.replaceChildren(
      ...[["Duração", `${m.duration.toFixed(2)} s`], ["Loop", m.loop ? "sim" : "não"], ["Contato", m.contact ? `${m.contact.time.toFixed(2)} s (u=${m.contact.u.toFixed(2)}) · ${m.contact.part}` : "—"],
        ["Apoio", m.plant ? `${m.plant.foot} em ${m.plant.time.toFixed(2)} s` : "—"], ["Recuperação", m.recovery ? `${m.recovery.toFixed(2)} s` : "—"],
        ["Velocidade raiz", m.speed ? `${m.speed[0]}–${m.speed[1]} m/s` : "—"], ["Direção", m.direction + (m.rootDriven ? " (física move a raiz)" : "")],
        ["Vel. no contato", fs ? `${fs.toFixed(1)} m/s (FK)` : "—"]].map(([k, v]) => el("tr", {}, el("td", { text: k }), el("td", { text: v }))));
    contactInfo.textContent = m.notes ?? "";
  };

  const setAthlete = (keeper: boolean) => {
    stage.scene.remove(athlete.group); athlete.dispose();
    athlete = createAthlete({ kit: keeper ? KIT_KEEPER : KIT_HOME, keeper, detail: "high", shadows: true, seed: keeper ? 5 : 11 });
    stage.scene.add(athlete.group);
  };
  const pickClip = (name: string) => {
    clip = CLIPS[name]; u = 0; contactFired = false; ballSim = null; ballHeld = null;
    setAthlete(clip.meta.category === "keeper");
    renderMeta();
  };

  /** Contact point of a clip in model space (FK at the contact frame): where the ball must be. */
  const contactPoint = (def: ClipDef, mir: boolean): THREE.Vector3 | null => {
    const c = def.meta.contact;
    if (!c) return null;
    const rig = fkRig();
    const p = samplePose(def, c.u);
    applyPose(rig, mir ? mirrorPose(p) : p);
    let bone = PART_BONE[c.part];
    if (mir) bone = bone.endsWith("L") ? bone.slice(0, -1) + "R" : bone.endsWith("R") ? bone.slice(0, -1) + "L" : bone;
    const local = c.part === "head" ? new THREE.Vector3(0, 0.2, 0.1) : c.part === "chest" ? new THREE.Vector3(0, 0.12, 0.16) : c.part.startsWith("foot") ? new THREE.Vector3(0, 0.0, 0.03) : new THREE.Vector3(0, -0.12, 0.02);
    return worldOf(rig, bone as never, local);
  };
  const toLab = (v: THREE.Vector3) => ({ x: v.z, y: v.x, z: v.y });
  const fromLab = (p: { x: number; y: number; z: number }, out: THREE.Vector3) => out.set(p.y, p.z, p.x);

  const resetBallForClip = () => {
    ballSim = null; ballHeld = null; contactFired = false;
    const cp = contactPoint(clip, mirror);
    if (!cp || !showBall) { ball.visible = false; return; }
    ball.visible = true;
    const groundBall = clip.meta.contact!.part.startsWith("foot");
    const at = new THREE.Vector3(cp.x, groundBall ? BALL_DEFAULTS.radius : cp.y, cp.z + (groundBall ? 0.1 : 0.08));
    athlete.group.updateMatrixWorld(true);
    at.applyMatrix4(athlete.group.matrixWorld);
    ball.position.copy(at);
    ball.userData.contactAt = at.clone();
    if (clip.meta.name === "gk_throw") ballHeld = "handR";
  };

  const updateBallForClip = (dt: number, time: number) => {
    const c = clip.meta.contact;
    if (!c || !showBall) return;
    const L = LAUNCH[clip.meta.name] ?? { speed: 10, elev: 0.1 };
    const at = ball.userData.contactAt as THREE.Vector3 | undefined;
    if (!at) return;
    if (ballHeld) {
      const hand = new THREE.Vector3();
      if (ballHeld === "hands") { athlete.rig.bones.handL.getWorldPosition(hand); const r = new THREE.Vector3(); athlete.rig.bones.handR.getWorldPosition(r); hand.add(r).multiplyScalar(0.5); hand.y -= 0.05; }
      else { athlete.rig.bones[mirror ? "handL" : "handR"].getWorldPosition(hand); hand.y -= 0.08; }
      ball.position.copy(hand);
    }
    if (!contactFired && time < c.time) {
      if (L.incoming) {
        // the incoming ball reaches the contact point exactly at the contact frame
        const before = c.time - time;
        const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(athlete.group.quaternion);
        ball.position.copy(at).addScaledVector(dir, before * L.incoming.speed);
        ball.position.y = at.y + (L.incoming.height - at.y) * Math.min(1, before / 0.9);
      } else if (!ballHeld) ball.position.copy(at);
    }
    if (!contactFired && time >= c.time) {
      contactFired = true;
      marker.position.copy(ball.position); marker.visible = true;
      if (clip.meta.name === "gk_catch") { ballHeld = "hands"; return; }
      ballHeld = null;
      const yaw = athlete.group.rotation.y + (L.heading ?? 0) * (mirror ? -1 : 1);
      const k = strike(L.speed, 0, L.elev, L.top ?? 0, (L.side ?? 0) * (mirror ? -1 : 1));
      // rotate the lab velocity (forward = +x) by the athlete's yaw (lab x = three Z, lab y = three X)
      const fwd = { x: Math.cos(yaw), y: Math.sin(yaw) };
      const v = { x: k.v.x * fwd.x - k.v.y * fwd.y, y: k.v.x * fwd.y + k.v.y * fwd.x, z: k.v.z };
      const w = { x: k.w.x * fwd.x - k.w.y * fwd.y, y: k.w.x * fwd.y + k.w.y * fwd.x, z: k.w.z };
      ballSim = newBall(toLab(ball.position), v, w);
    }
    if (ballSim) { stepBall(ballSim, dt); fromLab(ballSim.p, ball.position); ball.rotation.x += ballSim.w.y * dt; ball.rotation.z -= ballSim.w.x * dt; }
  };

  stage.onFrame((dtRaw) => {
    const dt = dtRaw * timeScale;
    if (mode === "clip") {
      const m = clip.meta;
      if (playing && !(freezeAtContact && m.contact && contactFired && Math.abs(u * m.duration - m.contact.time) < 0.05)) u += dt / m.duration;
      if (u >= 1 && (m.loop || loopAll)) { u = m.loop ? u % 1 : 0; if (!m.loop) { resetBallForClip(); marker.visible = false; } }
      u = Math.min(m.loop ? u : 1, u);
      const p = samplePose(clip, u);
      athlete.setPose(mirror ? mirrorPose(p) : p);
      athlete.group.position.set(0, 0, 0); athlete.group.rotation.set(0, 0, 0);
      athlete.group.updateMatrixWorld(true);
      updateBallForClip(dt, u * m.duration);
      hud.textContent = `${m.label} · t=${(u * m.duration).toFixed(2)} s / ${m.duration.toFixed(2)} s · u=${u.toFixed(2)} · escala ${timeScale.toFixed(2)}×` + (m.contact ? `\ncontato em ${m.contact.time.toFixed(2)} s (${m.contact.part})${contactFired ? "  ● contato" : ""}` : "");
      prints.visible = false;
    } else if (mode === "loco") {
      prints.visible = true; marker.visible = false;
      driver.step(dt);
      athlete.group.position.copy(driver.pos);
      athlete.group.rotation.set(0, driver.yaw, 0);
      athlete.group.updateMatrixWorld(true);
      loco.update(athlete, dt, driver.speed, driver.yaw);
      if (loco.dribble && ballSim) { stepBall(ballSim, dt); fromLab(ballSim.p, ball.position); ball.rotation.x += ballSim.w.y * dt; ball.rotation.z -= ballSim.w.x * dt; }
      ball.visible = loco.dribble;
      while (prints.children.length < loco.footPlants.length) {
        const fp = loco.footPlants[prints.children.length];
        const m = new THREE.Mesh(printGeo, printMat[fp.side]); m.position.set(fp.at.x, 0.012, fp.at.z); prints.add(m);
      }
      while (prints.children.length > 60) { prints.remove(prints.children[0]); loco.footPlants.shift(); }
      if (follow) { const d = new THREE.Vector3().subVectors(stage.camera.position, stage.controls.target); stage.controls.target.set(driver.pos.x, 0.95, driver.pos.z); stage.camera.position.copy(stage.controls.target).add(d); }
      hud.textContent = `Locomoção (${loco.mode}) · ${driver.speed.toFixed(2)} m/s · passada ${loco.lastStride.toFixed(2)} m/ciclo · cadência ${(loco.lastCadence * 2).toFixed(2)} passos/s\n` +
        `Deslizamento médio dos pés apoiados: ${loco.slideMean().toFixed(1)} cm/s · máx ${(loco.slide.max * 100).toFixed(0)} cm/s` + (loco.dribble ? "\nCondução: 1 toque por ciclo (bola solta, rola pela física)" : "");
    } else {
      prints.visible = false;
      tA += dt; if (blendT >= 0) { blendT += dt; tB += dt; }
      const pa = samplePose(blendA, blendA.meta.loop ? (tA / blendA.meta.duration) % 1 : Math.min(1, tA / blendA.meta.duration));
      let pose: Pose = pa;
      if (blendT >= 0) {
        const w = Math.min(1, blendT / Math.max(0.001, blendDur));
        const pb = samplePose(blendB, Math.min(1, tB / blendB.meta.duration));
        pose = lerpPose(pa, pb, w * w * (3 - 2 * w));
        if (tB >= blendB.meta.duration + 0.4) { blendT = -1; tB = 0; }
      }
      athlete.setPose(pose);
      athlete.group.position.set(0, 0, 0); athlete.group.rotation.set(0, 0, 0);
      hud.textContent = `Blend: ${blendA.meta.label} → ${blendB.meta.label} · transição ${blendDur.toFixed(2)} s` + (blendT >= 0 ? ` · peso ${(Math.min(1, blendT / blendDur)).toFixed(2)}` : "\n(aperte \"Disparar\")");
    }
  });

  loco.onTouch = () => {
    // dribble touch: push the loose ball ahead of the player (it then rolls and slows on its own)
    const yaw = driver.yaw;
    const toe = new THREE.Vector3(); athlete.rig.bones.toeR.getWorldPosition(toe);
    const ahead = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw));
    const p = toe.clone().addScaledVector(ahead, 0.25); p.y = BALL_DEFAULTS.radius;
    const sp = driver.speed * 1.2 + 0.5;   // close-control touch (see physics/player.ts carryGap)
    ballSim = newBall(toLab(p), { x: ahead.z * sp, y: ahead.x * sp, z: 0 }, { x: -ahead.x * sp / 0.11, y: ahead.z * sp / 0.11, z: 0 });
  };

  // ---- panel
  const groups: Record<string, string[]> = {};
  for (const d of CLIP_DEFS) (groups[d.meta.category] ??= []).push(d.meta.name);
  const clipSelect = el("select");
  for (const [g, names] of Object.entries(groups)) {
    const og = el("optgroup", { label: g });
    for (const n of names) og.append(el("option", { value: n, text: CLIPS[n].meta.label }));
    clipSelect.append(og);
  }
  clipSelect.value = clip.meta.name;
  clipSelect.addEventListener("change", () => { pickClip(clipSelect.value); resetBallForClip(); });
  const scrub = el("input", { type: "range", min: "0", max: "1", step: "0.001", value: "0" });
  scrub.addEventListener("input", () => { playing = false; u = Number(scrub.value); contactFired = u * clip.meta.duration >= (clip.meta.contact?.time ?? 99); });
  const modeBtns = el("div", { class: "btns" });
  const clipBox = el("div", {},
    el("label", { class: "row" }, el("span", { text: "Clip" }), clipSelect),
    el("div", { class: "btns" }, button("Play/Pause", () => { playing = !playing; }), button("Reiniciar", () => { u = 0; resetBallForClip(); marker.visible = false; playing = true; }),
      button("Ir ao contato", () => { if (clip.meta.contact) { u = clip.meta.contact.u; playing = false; } })),
    el("label", { class: "row" }, el("span", { text: "Tempo (u)" }), scrub),
    slider("Velocidade", 0.05, 2, 0.05, timeScale, (v) => { timeScale = v; }, (v) => `${v.toFixed(2)}×`),
    checkbox("Espelhar (perna esquerda)", mirror, (v) => { mirror = v; resetBallForClip(); }),
    checkbox("Bola sincronizada no contato", showBall, (v) => { showBall = v; resetBallForClip(); }),
    checkbox("Pausar no contato", freezeAtContact, (v) => { freezeAtContact = v; }),
    checkbox("Repetir clips sem loop", loopAll, (v) => { loopAll = v; }),
    el("h3", { text: "Metadados" }), metaTable, contactInfo,
  );
  const locoBox = el("div", { style: "display:none" },
    select("Trajeto", ["figure8", "circle", "zigzag", "straight", "stopgo"] as const, "figure8", (v: PathKind) => { driver = new RootDriver(v, driver.maxSpeed); loco.resetMeter(); }),
    slider("Vel. máxima", 0.5, 9, 0.1, 4.5, (v) => { driver.maxSpeed = v; loco.resetMeter(); }, (v) => `${v.toFixed(1)} m/s`),
    select("Sincronia", ["synced+ik", "synced", "naive"] as const, "synced+ik", (v: LocoMode) => { loco.mode = v; loco.resetMeter(); }, { naive: "ingênua (clip no ritmo autoral)", synced: "sincronizada (passada medida)", "synced+ik": "sincronizada + IK de pé" }),
    checkbox("Conduzir a bola (toques)", false, (v) => { loco.dribble = v; ballSim = null; }),
    checkbox("Câmera segue", follow, (v) => { follow = v; }),
    button("Zerar medidor", () => loco.resetMeter()),
    el("p", { class: "note", text: "A raiz é movida por um 'motor' com aceleração e aderência limitadas (como highlights.py). A animação só escolhe a pose: fase = velocidade ÷ passada medida por FK; o pé apoiado é travado no gramado por IK de dois ossos. Pegadas: azul = esquerdo, vermelho = direito." }),
  );
  const names = CLIP_DEFS.map((d) => d.meta.name);
  const blendBox = el("div", { style: "display:none" },
    select("De (A)", names, blendA.meta.name, (v) => { blendA = CLIPS[v]; tA = 0; }),
    select("Para (B)", names, blendB.meta.name, (v) => { blendB = CLIPS[v]; }),
    slider("Transição", 0, 0.6, 0.01, blendDur, (v) => { blendDur = v; }, (v) => `${v.toFixed(2)} s`),
    el("div", { class: "btns" }, button("Disparar A → B", () => { blendT = 0; tB = 0; })),
    el("p", { class: "note", text: "Blend em espaço de parâmetros anatômicos (graus), com easing. Para chute em corrida, ~0,15–0,2 s evita o 'estalo' sem atrasar o contato." }),
  );
  const setMode = (m: Mode) => {
    mode = m;
    for (const b of modeBtns.querySelectorAll("button")) b.classList.toggle("on", b.dataset.m === m);
    clipBox.style.display = m === "clip" ? "" : "none"; locoBox.style.display = m === "loco" ? "" : "none"; blendBox.style.display = m === "blend" ? "" : "none";
    if (m !== "clip") { setAthlete(false); ball.visible = false; }
    if (m === "loco") { driver.reset(); loco.resetMeter(); prints.clear(); loco.footPlants.length = 0; stage.camera.position.set(4, 3.2, -5); }
    if (m === "clip") { pickClip(clip.meta.name); resetBallForClip(); stage.controls.target.set(0, 0.95, 0); stage.camera.position.set(3.4, 1.7, 4.2); }
  };
  for (const [m, label] of [["clip", "Clips"], ["loco", "Locomoção"], ["blend", "Blend"]] as const) modeBtns.append(button(label, () => setMode(m), { "data-m": m }));
  panel.append(el("h3", { text: "Modo" }), modeBtns, clipBox, locoBox, blendBox);
  setMode("clip");

  (window as unknown as { __lab: unknown }).__lab = {
    stage, setMode, pickClip: (n: string) => { pickClip(n); resetBallForClip(); clipSelect.value = n; }, setU: (x: number) => { u = x; },
    play: (p: boolean) => { playing = p; }, timeScale: (v: number) => { timeScale = v; }, mirror: (v: boolean) => { mirror = v; },
    loco: (opts: { path?: PathKind; speed?: number; mode?: LocoMode; dribble?: boolean }) => { if (opts.path) driver = new RootDriver(opts.path, opts.speed ?? driver.maxSpeed); if (opts.speed) driver.maxSpeed = opts.speed; if (opts.mode) loco.mode = opts.mode; if (opts.dribble !== undefined) loco.dribble = opts.dribble; loco.resetMeter(); },
    slide: () => ({ mean: loco.slideMean(), max: loco.slide.max * 100, speed: driver.speed }),
    metadata: () => clipMetadata(),
    blend: (a: string, b: string, d: number) => { blendA = CLIPS[a]; blendB = CLIPS[b]; blendDur = d; blendT = 0; tB = 0; },
    cam: (p: [number, number, number], t: [number, number, number]) => { stage.camera.position.set(...p); stage.controls.target.set(...t); },
  };
  return () => { athlete.dispose(); stage.dispose(); };
}
