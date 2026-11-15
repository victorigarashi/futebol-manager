import { useEffect, useRef } from "react";

import type { EngineEvent } from "../../../lib/api";
import { inkOn } from "../clubColors";
import type { BroadcastView } from "./broadcastClock";
import type { FrameBuffer, Sample } from "./frameBuffer";

export type PitchPlayer = { index: number; number: number; name: string; side: "home" | "away"; role: string; id?: string };
type Props = {
  buffer: FrameBuffer;
  /** The broadcast moment to draw (live), or a plain fractional tick (replays). */
  driver: (deltaMs: number) => number | BroadcastView;
  players: PitchPlayer[];
  kits: { home: string; away: string };
  pitch: { length: number; width: number; goal: number; box: number };
  events: EngineEvent[];
  homeCode: string;
  ownSide?: "home" | "away" | null;
  selectedIndex?: number | null;
  onSelect?: (index: number | null) => void;
  label: string;
};

const FX_TICKS = 6;

/**
 * Top-down 2D broadcast view. Positions come exclusively from authoritative engine
 * frames; effects are triggered only by events the engine actually emitted. Cuts of
 * the condensed broadcast cross-fade between two real moments (nothing slides).
 */
export function PitchCanvas({ buffer, driver, players, kits, pitch, events, homeCode, ownSide, selectedIndex, onSelect, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const props = useRef({ driver, players, kits, pitch, events, homeCode, ownSide, selectedIndex });
  props.current = { driver, players, kits, pitch, events, homeCode, ownSide, selectedIndex };
  const lastSample = useRef<Sample | null>(null);
  const layout = useRef({ vertical: false, ox: 0, oy: 0, scale: 1 });

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const trail: { x: number; y: number; t: number }[] = [];
    let frame = 0;
    let last = performance.now();
    let lastPaint = 0;
    let grass: HTMLCanvasElement | null = null;
    let grassKey = "";
    // Adaptive quality: a slow device drops HiDPI, gradients and the ball trail (only the
    // drawing - never the simulation or the timeline), and gets them back when it copes.
    let lowQuality = false;
    let costAvg = 4;
    let intervalAvg = 16;
    let lastSwitch = 0;

    const draw = (now: number) => {
      const began = performance.now();
      const delta = Math.min(200, now - last);
      last = now;
      intervalAvg = intervalAvg * 0.95 + delta * 0.05;
      const { driver: drive, players: roster, kits: colours, pitch: dims, events: list, homeCode: home, ownSide: own, selectedIndex: selected } = props.current;
      const raw = drive(delta);
      const view: BroadcastView = typeof raw === "number" ? { tick: raw, kind: "PLAY", label: "", cut: null } : raw;
      if (reduced && now - lastPaint < 120) { frame = requestAnimationFrame(draw); return; }
      lastPaint = now;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      const ratio = lowQuality ? 1 : Math.min(2, window.devicePixelRatio || 1);
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      // Portrait screens get a vertical pitch (home attacks upward) for legibility.
      const vertical = height > width * 1.05;
      const margin = Math.max(14, Math.min(width, height) * 0.05);
      const longSide = vertical ? height - margin * 2 : width - margin * 2;
      const shortSide = vertical ? width - margin * 2 : height - margin * 2;
      const scale = Math.min(longSide / dims.length, shortSide / dims.width);
      const fieldLong = dims.length * scale;
      const fieldShort = dims.width * scale;
      const ox = (width - (vertical ? fieldShort : fieldLong)) / 2;
      const oy = (height - (vertical ? fieldLong : fieldShort)) / 2;
      layout.current = { vertical, ox, oy, scale };
      const at = (nx: number, ny: number): [number, number] => vertical
        ? [ox + ny * fieldShort, oy + (1 - nx) * fieldLong]
        : [ox + nx * fieldLong, oy + ny * fieldShort];
      const m = (metres: number) => metres * scale;

      const key = `${width}x${height}:${dims.length}:${vertical}:${ratio}`;
      if (key !== grassKey) { grass = paintPitch(width, height, ratio, ox, oy, vertical ? fieldShort : fieldLong, vertical ? fieldLong : fieldShort, vertical, dims, scale); grassKey = key; }
      context.clearRect(0, 0, width, height);
      if (grass) context.drawImage(grass, 0, 0, width, height);

      // Cuts: fade the last real moment out, then the next real moment in.
      let layers: { sample: Sample; alpha: number }[] = [];
      if (view.cut) {
        const { from, to, progress } = view.cut;
        const a = buffer.sample(from);
        const b = buffer.has(to) ? buffer.sample(to) : null;
        if (a && progress < 0.4) layers.push({ sample: a, alpha: 1 - progress / 0.4 });
        if (b && progress > 0.6) layers.push({ sample: b, alpha: (progress - 0.6) / 0.4 });
        context.fillStyle = `rgba(4, 12, 8, ${0.35 * Math.sin(Math.PI * progress)})`;
        context.fillRect(0, 0, width, height);
        trail.length = 0;
      } else {
        const sample = buffer.sample(view.tick);
        if (sample) layers = [{ sample, alpha: 1 }];
      }
      const main = layers[layers.length - 1]?.sample ?? null;
      lastSample.current = main;
      if (!main) { frame = requestAnimationFrame(draw); return; }

      // Event effects (only real engine events, only while the play is on screen).
      if (!view.cut) {
        for (const event of list) {
          const age = view.tick - event.tick;
          if (age < 0 || age > FX_TICKS) continue;
          const fade = 1 - age / FX_TICKS;
          const [ex, ey] = at(event.x, event.y);
          if (event.kind === "SHOT") {
            const [gx, gy] = at(event.team === home ? 1 : 0, 0.5);
            context.strokeStyle = `rgba(255, 236, 150, ${0.9 * fade})`;
            context.lineWidth = 2;
            context.setLineDash([5, 4]);
            context.beginPath(); context.moveTo(ex, ey); context.lineTo(gx, gy); context.stroke();
            context.setLineDash([]);
          } else if (event.kind === "GOAL") {
            for (let ring = 0; ring < 3; ring += 1) {
              context.strokeStyle = `rgba(255, 255, 255, ${fade * (1 - ring * 0.28)})`;
              context.lineWidth = 2.5 - ring * 0.6;
              context.beginPath(); context.arc(ex, ey, m(1.5 + age * 1.4 + ring * 1.8), 0, Math.PI * 2); context.stroke();
            }
          } else if (event.kind === "SAVE") {
            context.fillStyle = `rgba(255, 255, 255, ${0.3 * fade})`;
            context.beginPath(); context.arc(ex, ey, m(2.5), 0, Math.PI * 2); context.fill();
          } else if (event.kind === "CARD") {
            context.fillStyle = event.outcome === "YELLOW" ? `rgba(250, 204, 21, ${fade})` : `rgba(239, 68, 68, ${fade})`;
            roundRect(context, ex - 4, ey - 26, 8, 11, 1.5); context.fill();
          } else if (event.kind === "FOUL") {
            context.strokeStyle = `rgba(255, 180, 170, ${fade})`;
            context.lineWidth = 2;
            context.beginPath(); context.moveTo(ex - 4, ey - 4); context.lineTo(ex + 4, ey + 4); context.moveTo(ex + 4, ey - 4); context.lineTo(ex - 4, ey + 4); context.stroke();
          }
        }
      }

      // Who is shooting right now, and who just came on (from real events only).
      const shooter = view.cut ? null : list.find((e) => e.kind === "SHOT" && view.tick - e.tick >= -1.2 && view.tick - e.tick <= 1.5)?.player_id ?? null;
      const entering = new Set(view.cut ? [] : list.filter((e) => e.kind === "SUBSTITUTION" && view.tick - e.tick >= 0 && view.tick - e.tick < 12).map((e) => e.player_id ?? ""));
      const radius = Math.max(6, Math.min(11, m(dims.length > 60 ? 1.15 : 0.85)));
      for (const { sample, alpha: layerAlpha } of layers) {
        context.save();
        context.font = `800 ${Math.round(radius * 0.98)}px "Barlow Condensed", "Arial Narrow", sans-serif`;
        context.textAlign = "center";
        context.textBaseline = "middle";
        // Shadows first, so no shadow covers a neighbouring marker.
        context.fillStyle = "rgba(0, 0, 0, 0.32)";
        for (const player of roster) {
          const position = sample.players[player.index];
          if (!position) continue;
          const [px, py] = at(position[0], position[1]);
          context.globalAlpha = layerAlpha * (sample.alpha[player.index] ?? 1) * 0.8;
          context.beginPath(); context.ellipse(px + radius * 0.25, py + radius * 0.42, radius * 0.95, radius * 0.62, 0, 0, Math.PI * 2); context.fill();
        }
        for (const player of roster) {
          const position = sample.players[player.index];
          if (!position) continue;
          const markerAlpha = layerAlpha * (sample.alpha[player.index] ?? 1);
          if (markerAlpha <= 0.02) continue;
          const [px, py] = at(position[0], position[1]);
          context.globalAlpha = markerAlpha;
          const kit = player.side === "home" ? colours.home : colours.away;
          const fill = player.role === "GK" ? keeperKit(kit, player.side) : kit;
          if (lowQuality) {
            context.fillStyle = fill;
          } else {
            const body = context.createRadialGradient(px - radius * 0.35, py - radius * 0.4, radius * 0.1, px, py, radius);
            body.addColorStop(0, lighten(fill, 0.3));
            body.addColorStop(1, fill);
            context.fillStyle = body;
          }
          context.beginPath(); context.arc(px, py, radius, 0, Math.PI * 2); context.fill();
          context.lineWidth = player.side === own ? 2 : 1.2;
          context.strokeStyle = player.side === own ? "rgba(248, 250, 252, 0.95)" : "rgba(10, 14, 20, 0.75)";
          context.stroke();
          context.fillStyle = inkOn(fill);
          context.fillText(String(player.number), px, py + 0.5);
          if (sample.ball.owner === player.index && sample.ball.state === 0) {
            context.strokeStyle = "rgba(144, 252, 163, 0.95)";
            context.lineWidth = 1.8;
            context.beginPath(); context.arc(px, py, radius + 3.5, 0, Math.PI * 2); context.stroke();
          }
          if (shooter && player.id === shooter) {
            context.strokeStyle = "rgba(255, 236, 150, 0.95)";
            context.lineWidth = 2.2;
            context.beginPath(); context.arc(px, py, radius + 6 + Math.sin(now / 90) * 1.5, 0, Math.PI * 2); context.stroke();
          }
          if (player.id && entering.has(player.id)) {
            context.strokeStyle = "rgba(96, 165, 250, 0.95)";
            context.lineWidth = 2;
            context.setLineDash([3, 3]);
            context.beginPath(); context.arc(px, py, radius + 5, 0, Math.PI * 2); context.stroke();
            context.setLineDash([]);
          }
          if (selected === player.index) {
            context.strokeStyle = "#FDE68A";
            context.setLineDash([4, 3]);
            context.lineWidth = 2;
            context.beginPath(); context.arc(px, py, radius + 7, 0, Math.PI * 2); context.stroke();
            context.setLineDash([]);
            drawLabel(context, player.name, px, py - radius - 14);
          }
        }
        context.restore();
      }

      // Ball (newest layer), with a short trail while it travels.
      const ball = main.ball;
      const [bx, by] = at(ball.x, ball.y);
      const layerAlpha = layers[layers.length - 1].alpha;
      if (!reduced && !lowQuality && !view.cut && ball.state === 2) trail.push({ x: bx, y: by, t: now });
      while (trail.length && (now - trail[0].t > 260 || ball.state !== 2)) trail.shift();
      for (let index = 1; index < trail.length; index += 1) {
        context.strokeStyle = `rgba(255, 255, 255, ${(index / trail.length) * 0.45 * layerAlpha})`;
        context.lineWidth = Math.max(1, (index / trail.length) * 2.6);
        context.beginPath(); context.moveTo(trail[index - 1].x, trail[index - 1].y); context.lineTo(trail[index].x, trail[index].y); context.stroke();
      }
      const ballRadius = Math.max(3.2, m(dims.length > 60 ? 0.5 : 0.35));
      const lift = ball.state === 2 ? ballRadius * 0.9 : 0;
      context.save();
      context.globalAlpha = layerAlpha * ball.alpha;
      context.beginPath(); context.fillStyle = "rgba(0, 0, 0, 0.38)"; context.ellipse(bx + 1.5 + lift, by + 2 + lift, ballRadius, ballRadius * 0.7, 0, 0, Math.PI * 2); context.fill();
      context.beginPath(); context.fillStyle = "#FFFFFF"; context.arc(bx, by, ballRadius, 0, Math.PI * 2); context.fill();
      context.lineWidth = 1; context.strokeStyle = "#0D1117"; context.stroke();
      context.restore();
      costAvg = costAvg * 0.9 + (performance.now() - began) * 0.1;
      if (now - lastSwitch > 3000) {
        if (!lowQuality && (costAvg > 12 || intervalAvg > 34)) { lowQuality = true; lastSwitch = now; }
        else if (lowQuality && costAvg < 5 && intervalAvg < 20) { lowQuality = false; lastSwitch = now; }
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [buffer]);

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const sample = lastSample.current;
    const canvas = canvasRef.current;
    if (!sample || !canvas || !onSelect) return;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const { vertical, ox, oy, scale } = layout.current;
    const fieldLong = pitch.length * scale;
    const fieldShort = pitch.width * scale;
    let best: number | null = null;
    let bestDistance = 26 * 26;
    for (const player of players) {
      const position = sample.players[player.index];
      if (!position) continue;
      const px = vertical ? ox + position[1] * fieldShort : ox + position[0] * fieldLong;
      const py = vertical ? oy + (1 - position[0]) * fieldLong : oy + position[1] * fieldShort;
      const distance = (px - x) ** 2 + (py - y) ** 2;
      if (distance < bestDistance) { best = player.index; bestDistance = distance; }
    }
    onSelect(best);
  };

  return <canvas ref={canvasRef} className="pitch-canvas" onClick={handleClick} role="img" aria-label={label}>
    Seu navegador não exibe canvas. Acompanhe os lances pela linha do tempo.
  </canvas>;
}

function keeperKit(hex: string, side: "home" | "away"): string {
  // Keepers wear a contrasting kit: a deep shade of the club colour, or (on dark kits)
  // amber for the home keeper and cyan for the away keeper, so the two never match.
  const value = parseInt(hex.slice(1), 16);
  const luminance = (((value >> 16) & 255) * 0.299 + ((value >> 8) & 255) * 0.587 + (value & 255) * 0.114) / 255;
  if (luminance < 0.35) return side === "home" ? "#F59E0B" : "#22D3EE";
  return shade(hex, 0.5);
}

function shade(hex: string, factor: number): string {
  const value = parseInt(hex.slice(1), 16);
  const r = Math.max(0, ((value >> 16) & 255) * factor) | 0;
  const g = Math.max(0, ((value >> 8) & 255) * factor) | 0;
  const b = Math.max(0, (value & 255) * factor) | 0;
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

function lighten(hex: string, amount: number): string {
  const value = parseInt(hex.slice(1), 16);
  const mix = (c: number) => Math.min(255, Math.round(c + (255 - c) * amount));
  return `rgb(${mix((value >> 16) & 255)}, ${mix((value >> 8) & 255)}, ${mix(value & 255)})`;
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.quadraticCurveTo(x + w, y, x + w, y + r);
  g.lineTo(x + w, y + h - r); g.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  g.lineTo(x + r, y + h); g.quadraticCurveTo(x, y + h, x, y + h - r);
  g.lineTo(x, y + r); g.quadraticCurveTo(x, y, x + r, y);
  g.closePath();
}

function drawLabel(context: CanvasRenderingContext2D, text: string, x: number, y: number) {
  context.save();
  context.globalAlpha = 1;
  context.font = '700 12px "Inter", system-ui, sans-serif';
  const width = context.measureText(text).width + 12;
  context.fillStyle = "rgba(10, 14, 20, 0.9)";
  roundRect(context, x - width / 2, y - 9, width, 18, 4); context.fill();
  context.fillStyle = "#F8FAFC";
  context.fillText(text, x, y);
  context.restore();
}

/** Static layer: stadium surround, mown grass, proportional markings and goal nets. */
function paintPitch(width: number, height: number, ratio: number, ox: number, oy: number, fieldW: number, fieldH: number, vertical: boolean, dims: { length: number; width: number; goal: number; box: number }, scale: number): HTMLCanvasElement {
  const layer = document.createElement("canvas");
  layer.width = Math.round(width * ratio);
  layer.height = Math.round(height * ratio);
  const g = layer.getContext("2d");
  if (!g) return layer;
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  // Surround: dark apron with a soft floodlight glow toward the centre.
  const surround = g.createRadialGradient(width / 2, height / 2, Math.min(width, height) * 0.2, width / 2, height / 2, Math.max(width, height) * 0.7);
  surround.addColorStop(0, "#14532D");
  surround.addColorStop(1, "#0A2615");
  g.fillStyle = surround;
  g.fillRect(0, 0, width, height);
  const apron = Math.max(6, scale * 2.2);
  g.fillStyle = "#145C34";
  g.fillRect(ox - apron, oy - apron, fieldW + apron * 2, fieldH + apron * 2);
  // Mown stripes along the length of the pitch.
  const stripes = dims.length > 60 ? 18 : 10;
  for (let index = 0; index < stripes; index += 1) {
    g.fillStyle = index % 2 ? "#1B7A43" : "#1F8A4C";
    if (vertical) g.fillRect(ox, oy + (index * fieldH) / stripes, fieldW, fieldH / stripes + 0.5);
    else g.fillRect(ox + (index * fieldW) / stripes, oy, fieldW / stripes + 0.5, fieldH);
  }
  // Light from above: brighter centre, darker edges (depth without perspective tricks).
  const light = g.createRadialGradient(ox + fieldW / 2, oy + fieldH / 2, Math.min(fieldW, fieldH) * 0.15, ox + fieldW / 2, oy + fieldH / 2, Math.max(fieldW, fieldH) * 0.7);
  light.addColorStop(0, "rgba(255,255,255,0.06)");
  light.addColorStop(1, "rgba(0,0,0,0.22)");
  g.fillStyle = light;
  g.fillRect(ox, oy, fieldW, fieldH);
  // Grain: deterministic speckles so the texture is stable between frames.
  let seed = 7;
  for (let index = 0; index < (fieldW * fieldH) / 50; index += 1) {
    seed = (seed * 16807) % 2147483647;
    const x = ox + (seed % 10000) / 10000 * fieldW;
    seed = (seed * 16807) % 2147483647;
    const y = oy + (seed % 10000) / 10000 * fieldH;
    g.fillStyle = seed % 2 ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.05)";
    g.fillRect(x, y, 1.2, 1.2);
  }
  const at = (mx: number, my: number): [number, number] => vertical ? [ox + my * scale, oy + (dims.length - mx) * scale] : [ox + mx * scale, oy + my * scale];
  const rect = (x1: number, y1: number, x2: number, y2: number) => {
    const [ax, ay] = at(x1, y1); const [bx, by] = at(x2, y2);
    g.strokeRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
  };
  g.strokeStyle = "rgba(255,255,255,0.86)";
  g.lineWidth = Math.max(1.2, scale * 0.12);
  g.lineJoin = "round";
  const L = dims.length; const W = dims.width;
  const eleven = L > 60;
  rect(0, 0, L, W);
  const [m1x, m1y] = at(L / 2, 0); const [m2x, m2y] = at(L / 2, W);
  g.beginPath(); g.moveTo(m1x, m1y); g.lineTo(m2x, m2y); g.stroke();
  const [cx, cy] = at(L / 2, W / 2);
  g.beginPath(); g.arc(cx, cy, (eleven ? 9.15 : 3) * scale, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "rgba(255,255,255,0.9)";
  g.beginPath(); g.arc(cx, cy, Math.max(1.6, scale * 0.25), 0, Math.PI * 2); g.fill();
  const boxWidth = eleven ? 40.32 : Math.min(W * 0.6, dims.goal + 2 * dims.box);
  const smallDepth = eleven ? 5.5 : 0;
  const smallWidth = eleven ? 18.32 : 0;
  for (const side of [0, 1]) {
    const x0 = side === 0 ? 0 : L;
    const dir = side === 0 ? 1 : -1;
    rect(x0, (W - boxWidth) / 2, x0 + dir * dims.box, (W + boxWidth) / 2);
    if (smallDepth) rect(x0, (W - smallWidth) / 2, x0 + dir * smallDepth, (W + smallWidth) / 2);
    const spot = eleven ? 11 : 6;
    const [sx, sy] = at(x0 + dir * spot, W / 2);
    g.beginPath(); g.arc(sx, sy, Math.max(1.5, scale * 0.22), 0, Math.PI * 2); g.fill();
    if (eleven) {
      // Penalty arc: the part of the 9.15 m circle outside the area.
      const theta = Math.acos((dims.box - spot) / 9.15);
      const base = vertical ? (side === 0 ? -Math.PI / 2 : Math.PI / 2) : (side === 0 ? 0 : Math.PI);
      g.beginPath(); g.arc(sx, sy, 9.15 * scale, base - theta, base + theta); g.stroke();
    }
    // Goal: net mesh behind the line and a solid frame.
    const depth = eleven ? 2 : 1;
    const [n1x, n1y] = at(x0, (W - dims.goal) / 2);
    const [n2x, n2y] = at(x0 - dir * depth, (W + dims.goal) / 2);
    const nx = Math.min(n1x, n2x); const ny = Math.min(n1y, n2y);
    const nw = Math.abs(n2x - n1x); const nh = Math.abs(n2y - n1y);
    g.save();
    g.fillStyle = "rgba(255,255,255,0.10)";
    g.fillRect(nx, ny, nw, nh);
    g.strokeStyle = "rgba(255,255,255,0.28)";
    g.lineWidth = 0.6;
    const mesh = Math.max(3, scale * 0.6);
    for (let x = nx; x <= nx + nw; x += mesh) { g.beginPath(); g.moveTo(x, ny); g.lineTo(x, ny + nh); g.stroke(); }
    for (let y = ny; y <= ny + nh; y += mesh) { g.beginPath(); g.moveTo(nx, y); g.lineTo(nx + nw, y); g.stroke(); }
    g.strokeStyle = "rgba(255,255,255,0.98)";
    g.lineWidth = Math.max(2, scale * 0.24);
    g.strokeRect(nx, ny, nw, nh);
    g.restore();
  }
  for (const [x, y] of [[0, 0], [0, W], [L, 0], [L, W]]) {
    const [px, py] = at(x, y);
    g.beginPath(); g.arc(px, py, Math.max(3, scale), 0, Math.PI * 2); g.stroke();
  }
  return layer;
}
