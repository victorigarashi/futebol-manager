import { useEffect, useRef } from "react";

import type { EngineEvent } from "../../../lib/api";
import { inkOn } from "../clubColors";
import type { FrameBuffer, Sample } from "./frameBuffer";

export type PitchPlayer = { index: number; number: number; name: string; side: "home" | "away"; role: string };
type Props = {
  buffer: FrameBuffer;
  /** Returns the (fractional) tick to draw, given elapsed ms since last frame. */
  driver: (deltaMs: number) => number;
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

const FX_TICKS = 40;

/**
 * Top-down 2D view. Positions come exclusively from authoritative engine frames;
 * visual effects are triggered only by events the engine actually emitted.
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
    const trail: { x: number; y: number }[] = [];
    let frame = 0;
    let last = performance.now();
    let lastPaint = 0;
    let grass: HTMLCanvasElement | null = null;
    let grassKey = "";

    const draw = (now: number) => {
      const delta = Math.min(200, now - last);
      last = now;
      const { driver: drive, players: roster, kits: colours, pitch: dims, events: list, homeCode: home, ownSide: own, selectedIndex: selected } = props.current;
      const tick = drive(delta);
      if (reduced && now - lastPaint < 200) { frame = requestAnimationFrame(draw); return; }
      lastPaint = now;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      // Portrait screens get a vertical pitch (home attacks upward) for legibility.
      const vertical = height > width * 1.05;
      const margin = Math.max(10, Math.min(width, height) * 0.04);
      const longSide = vertical ? height - margin * 2 : width - margin * 2;
      const shortSide = vertical ? width - margin * 2 : height - margin * 2;
      const scale = Math.min(longSide / dims.length, shortSide / dims.width);
      const fieldLong = dims.length * scale;
      const fieldShort = dims.width * scale;
      const ox = (width - (vertical ? fieldShort : fieldLong)) / 2;
      const oy = (height - (vertical ? fieldLong : fieldShort)) / 2;
      layout.current = { vertical, ox, oy, scale };
      // Normalised engine coords (x along length, y across) → screen.
      const at = (nx: number, ny: number): [number, number] => vertical
        ? [ox + ny * fieldShort, oy + (1 - nx) * fieldLong]
        : [ox + nx * fieldLong, oy + ny * fieldShort];
      const m = (metres: number) => metres * scale;

      const key = `${width}x${height}:${dims.length}:${vertical}`;
      if (key !== grassKey) { grass = paintGrass(width, height, ratio, ox, oy, vertical ? fieldShort : fieldLong, vertical ? fieldLong : fieldShort, vertical, dims, scale); grassKey = key; }
      context.clearRect(0, 0, width, height);
      if (grass) context.drawImage(grass, 0, 0, width, height);

      const sample = buffer.sample(tick);
      lastSample.current = sample;
      if (!sample) { frame = requestAnimationFrame(draw); return; }

      // Event effects (only real engine events within the last FX_TICKS ticks).
      for (const event of list) {
        const age = sample.tick - event.tick;
        if (age < 0 || age > FX_TICKS) continue;
        const fade = 1 - age / FX_TICKS;
        const [ex, ey] = at(event.x, event.y);
        const attackingHome = event.team === home;
        if (event.kind === "SHOT") {
          const [gx, gy] = at(attackingHome ? 1 : 0, 0.5);
          context.strokeStyle = `rgba(144, 252, 163, ${0.85 * fade})`;
          context.lineWidth = 2;
          context.setLineDash([6, 5]);
          context.beginPath(); context.moveTo(ex, ey); context.lineTo(gx, gy); context.stroke();
          context.setLineDash([]);
        } else if (event.kind === "GOAL") {
          for (let ring = 0; ring < 3; ring += 1) {
            context.strokeStyle = `rgba(255, 255, 255, ${fade * (1 - ring * 0.25)})`;
            context.lineWidth = 3 - ring;
            context.beginPath(); context.arc(ex, ey, m(2 + age * 0.35 + ring * 2.5), 0, Math.PI * 2); context.stroke();
          }
        } else if (event.kind === "SAVE") {
          context.fillStyle = `rgba(255, 255, 255, ${0.35 * fade})`;
          context.beginPath(); context.arc(ex, ey, m(3), 0, Math.PI * 2); context.fill();
        } else if (event.kind === "CARD") {
          context.fillStyle = event.outcome === "YELLOW" ? `rgba(250, 204, 21, ${fade})` : `rgba(239, 68, 68, ${fade})`;
          context.fillRect(ex - 4, ey - m(4) - 12, 8, 11);
        } else if (event.kind === "FOUL") {
          context.strokeStyle = `rgba(255, 170, 165, ${fade})`;
          context.lineWidth = 2;
          context.beginPath(); context.moveTo(ex - 5, ey - 5); context.lineTo(ex + 5, ey + 5); context.moveTo(ex + 5, ey - 5); context.lineTo(ex - 5, ey + 5); context.stroke();
        }
      }

      // Players.
      const radius = Math.max(7, Math.min(13, m(1.25)));
      context.font = `800 ${Math.round(radius * 0.95)}px "Barlow Condensed", "Arial Narrow", sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      for (const player of roster) {
        const position = sample.players[player.index];
        if (!position) continue;
        const [px, py] = at(position[0], position[1]);
        const kit = player.side === "home" ? colours.home : colours.away;
        context.beginPath();
        context.fillStyle = "rgba(0, 0, 0, 0.28)";
        context.ellipse(px + 1.5, py + 2.5, radius, radius * 0.8, 0, 0, Math.PI * 2);
        context.fill();
        context.beginPath();
        context.fillStyle = player.role === "GK" ? shade(kit) : kit;
        context.arc(px, py, radius, 0, Math.PI * 2);
        context.fill();
        context.lineWidth = player.side === own ? 2.2 : 1.4;
        context.strokeStyle = player.side === own ? "#F8FAFC" : "rgba(13, 17, 23, 0.85)";
        context.stroke();
        context.fillStyle = inkOn(player.role === "GK" ? shade(kit) : kit);
        context.fillText(String(player.number), px, py + 0.5);
        if (sample.ball.owner === player.index) {
          context.strokeStyle = "#90FCA3";
          context.lineWidth = 2;
          context.beginPath(); context.arc(px, py, radius + 4, 0, Math.PI * 2); context.stroke();
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

      // Ball with a short trail (skipped for reduced motion).
      const [bx, by] = at(sample.ball.x, sample.ball.y);
      if (!reduced) {
        trail.push({ x: bx, y: by });
        if (trail.length > 10) trail.shift();
        for (let index = 1; index < trail.length; index += 1) {
          context.strokeStyle = `rgba(255, 255, 255, ${(index / trail.length) * 0.35})`;
          context.lineWidth = Math.max(1, (index / trail.length) * 3);
          context.beginPath(); context.moveTo(trail[index - 1].x, trail[index - 1].y); context.lineTo(trail[index].x, trail[index].y); context.stroke();
        }
      }
      const ballRadius = Math.max(3.5, m(0.55));
      context.beginPath(); context.fillStyle = "rgba(0, 0, 0, 0.35)"; context.arc(bx + 2, by + 2.5, ballRadius, 0, Math.PI * 2); context.fill();
      context.beginPath(); context.fillStyle = "#FFFFFF"; context.arc(bx, by, ballRadius, 0, Math.PI * 2); context.fill();
      context.lineWidth = 1; context.strokeStyle = "#0D1117"; context.stroke();
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

function shade(hex: string): string {
  const value = parseInt(hex.slice(1), 16);
  const r = Math.max(0, ((value >> 16) & 255) * 0.55) | 0;
  const g = Math.max(0, ((value >> 8) & 255) * 0.55) | 0;
  const b = Math.max(0, (value & 255) * 0.55) | 0;
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

function drawLabel(context: CanvasRenderingContext2D, text: string, x: number, y: number) {
  context.save();
  context.font = '700 12px "Inter", system-ui, sans-serif';
  const width = context.measureText(text).width + 12;
  context.fillStyle = "rgba(13, 17, 23, 0.88)";
  context.fillRect(x - width / 2, y - 9, width, 18);
  context.fillStyle = "#F8FAFC";
  context.fillText(text, x, y);
  context.restore();
}

/** Static layer: striped grass with a subtle grain and proportional markings. */
function paintGrass(width: number, height: number, ratio: number, ox: number, oy: number, fieldW: number, fieldH: number, vertical: boolean, dims: { length: number; width: number; goal: number; box: number }, scale: number): HTMLCanvasElement {
  const layer = document.createElement("canvas");
  layer.width = Math.round(width * ratio);
  layer.height = Math.round(height * ratio);
  const g = layer.getContext("2d");
  if (!g) return layer;
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.fillStyle = "#0E3B24";
  g.fillRect(0, 0, width, height);
  const stripes = dims.length > 60 ? 14 : 8;
  for (let index = 0; index < stripes; index += 1) {
    g.fillStyle = index % 2 ? "#17663D" : "#1A7044";
    if (vertical) g.fillRect(ox, oy + (index * fieldH) / stripes, fieldW, fieldH / stripes + 0.5);
    else g.fillRect(ox + (index * fieldW) / stripes, oy, fieldW / stripes + 0.5, fieldH);
  }
  // Grain: deterministic speckles so the texture is stable between frames.
  let seed = 7;
  for (let index = 0; index < (fieldW * fieldH) / 60; index += 1) {
    seed = (seed * 16807) % 2147483647;
    const x = ox + (seed % 10000) / 10000 * fieldW;
    seed = (seed * 16807) % 2147483647;
    const y = oy + (seed % 10000) / 10000 * fieldH;
    g.fillStyle = seed % 2 ? "rgba(255,255,255,0.025)" : "rgba(0,0,0,0.05)";
    g.fillRect(x, y, 1.5, 1.5);
  }
  const at = (mx: number, my: number): [number, number] => vertical ? [ox + my * scale, oy + (dims.length - mx) * scale] : [ox + mx * scale, oy + my * scale];
  const rect = (x1: number, y1: number, x2: number, y2: number) => {
    const [ax, ay] = at(x1, y1); const [bx, by] = at(x2, y2);
    g.strokeRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
  };
  g.strokeStyle = "rgba(255,255,255,0.78)";
  g.lineWidth = Math.max(1, scale * 0.12);
  const L = dims.length; const W = dims.width;
  const eleven = L > 60;
  rect(0, 0, L, W);
  const [m1x, m1y] = at(L / 2, 0); const [m2x, m2y] = at(L / 2, W);
  g.beginPath(); g.moveTo(m1x, m1y); g.lineTo(m2x, m2y); g.stroke();
  const [cx, cy] = at(L / 2, W / 2);
  g.beginPath(); g.arc(cx, cy, (eleven ? 9.15 : 3) * scale, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "rgba(255,255,255,0.85)";
  g.beginPath(); g.arc(cx, cy, Math.max(1.5, scale * 0.25), 0, Math.PI * 2); g.fill();
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
      const [ax, ay] = at(x0 + dir * spot, W / 2);
      const theta = Math.acos((dims.box - spot) / 9.15);
      const base = vertical ? (side === 0 ? -Math.PI / 2 : Math.PI / 2) : (side === 0 ? 0 : Math.PI);
      g.beginPath(); g.arc(ax, ay, 9.15 * scale, base - theta, base + theta); g.stroke();
    }
    // Goal frame.
    g.save();
    g.strokeStyle = "rgba(255,255,255,0.95)";
    g.lineWidth = Math.max(2, scale * 0.25);
    rect(x0, (W - dims.goal) / 2, x0 - dir * (eleven ? 2 : 1), (W + dims.goal) / 2);
    g.restore();
  }
  // Corner arcs.
  for (const [x, y] of [[0, 0], [0, W], [L, 0], [L, W]]) {
    const [px, py] = at(x, y);
    g.beginPath(); g.arc(px, py, Math.max(3, scale), 0, Math.PI * 2); g.stroke();
  }
  // Soft vignette for depth.
  const gradient = g.createRadialGradient(width / 2, height / 2, Math.min(width, height) * 0.3, width / 2, height / 2, Math.max(width, height) * 0.75);
  gradient.addColorStop(0, "rgba(0,0,0,0)");
  gradient.addColorStop(1, "rgba(0,0,0,0.35)");
  g.fillStyle = gradient;
  g.fillRect(0, 0, width, height);
  return layer;
}
