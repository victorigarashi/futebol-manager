/** Minimal canvas line chart for the lab (no dependency). */
export type Series = { name: string; colour: string; points: [number, number][]; dash?: number[]; width?: number };
export type ChartSpec = { title: string; x: string; y: string; series: Series[]; xMax?: number; yMax?: number; yMin?: number; equalAxes?: boolean; marks?: { x: number; y: number; label: string }[] };

export function drawChart(canvas: HTMLCanvasElement, spec: ChartSpec): void {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const W = canvas.clientWidth || 420, H = canvas.clientHeight || 260;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const g = canvas.getContext("2d")!;
  g.scale(dpr, dpr);
  g.fillStyle = "#121a20"; g.fillRect(0, 0, W, H);
  const pad = { l: 46, r: 12, t: 28, b: 34 };
  const all = spec.series.flatMap((s) => s.points);
  let xMax = spec.xMax ?? Math.max(...all.map((p) => p[0]));
  let yMax = spec.yMax ?? Math.max(...all.map((p) => p[1])) * 1.08;
  let yMin = spec.yMin ?? Math.min(0, ...all.map((p) => p[1]));
  const xMin = Math.min(0, ...all.map((p) => p[0]));
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
  if (spec.equalAxes) { const sx = (xMax - xMin) / pw, sy = (yMax - yMin) / ph; if (sx > sy) { const c = (yMax + yMin) / 2; yMax = c + (sx * ph) / 2; yMin = c - (sx * ph) / 2; } else xMax = xMin + sy * pw; }
  const X = (x: number) => pad.l + ((x - xMin) / (xMax - xMin || 1)) * pw;
  const Y = (y: number) => pad.t + ph - ((y - yMin) / (yMax - yMin || 1)) * ph;
  g.font = "600 12.5px Inter, system-ui, sans-serif"; g.fillStyle = "#e6edf2"; g.fillText(spec.title, pad.l, 17);
  g.font = "11px Inter, system-ui, sans-serif"; g.fillStyle = "#8ea0ad"; g.strokeStyle = "#26313a"; g.lineWidth = 1;
  const nice = (span: number) => { const e = Math.pow(10, Math.floor(Math.log10(span / 5))); return [1, 2, 5, 10].map((m) => m * e).find((s) => span / s <= 6) ?? e * 10; };
  const sx = nice(xMax - xMin), sy = nice(yMax - yMin);
  for (let x = Math.ceil(xMin / sx) * sx; x <= xMax + 1e-9; x += sx) { g.beginPath(); g.moveTo(X(x), pad.t); g.lineTo(X(x), pad.t + ph); g.stroke(); g.fillText(`${+x.toFixed(2)}`, X(x) - 8, H - pad.b + 14); }
  for (let y = Math.ceil(yMin / sy) * sy; y <= yMax + 1e-9; y += sy) { g.beginPath(); g.moveTo(pad.l, Y(y)); g.lineTo(pad.l + pw, Y(y)); g.stroke(); g.fillText(`${+y.toFixed(2)}`, 6, Y(y) + 4); }
  g.fillText(spec.x, pad.l + pw - g.measureText(spec.x).width, H - 6);
  g.save(); g.translate(12, pad.t + 4); g.fillText(spec.y, 0, 0); g.restore();
  for (const s of spec.series) {
    g.strokeStyle = s.colour; g.lineWidth = s.width ?? 2; g.setLineDash(s.dash ?? []);
    g.beginPath();
    s.points.forEach(([x, y], i) => (i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))));
    g.stroke();
  }
  g.setLineDash([]);
  for (const m of spec.marks ?? []) { g.fillStyle = "#ffd166"; g.beginPath(); g.arc(X(m.x), Y(m.y), 3.5, 0, Math.PI * 2); g.fill(); g.fillText(m.label, X(m.x) + 6, Y(m.y) - 6); }
  // legend
  let lx = pad.l + 8; const ly = pad.t + 12;
  for (const s of spec.series) {
    if (s.name.startsWith("_")) continue;
    g.strokeStyle = s.colour; g.lineWidth = 2; g.setLineDash(s.dash ?? []); g.beginPath(); g.moveTo(lx, ly); g.lineTo(lx + 16, ly); g.stroke(); g.setLineDash([]);
    g.fillStyle = "#cfd9e0"; g.fillText(s.name, lx + 20, ly + 4); lx += 28 + g.measureText(s.name).width;
  }
}
