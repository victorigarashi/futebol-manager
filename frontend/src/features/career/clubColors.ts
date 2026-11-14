/** Home kit colours of each club (primary, secondary). Used for the 2D kits and celebrations. */
const COLORS: Record<string, [string, string]> = {
  FLA: ["#C8102E", "#111111"], PAL: ["#0B6B3A", "#FFFFFF"], COR: ["#F4F4F4", "#111111"], SAO: ["#E8E8E8", "#D7262B"],
  SAN: ["#F7F7F7", "#111111"], FLU: ["#7A1F3D", "#0F7A4D"], BOT: ["#1A1A1A", "#FFFFFF"], VAS: ["#111111", "#FFFFFF"],
  CRU: ["#1D4FA3", "#FFFFFF"], CAM: ["#1B1B1B", "#F5F5F5"], GRE: ["#1E8BD0", "#111111"], INT: ["#D11F2F", "#FFFFFF"],
  BAH: ["#1C4CA0", "#E2231A"], VIT: ["#D21F2A", "#111111"], CAP: ["#C8102E", "#111111"], CFC: ["#0E6B3A", "#FFFFFF"],
  RBB: ["#F4F4F4", "#D6182B"], MIR: ["#F2C230", "#0D6E3A"], CHA: ["#169E58", "#FFFFFF"], REM: ["#163A7A", "#FFFFFF"],
};

export function clubColors(code: string): { primary: string; secondary: string } {
  const [primary, secondary] = COLORS[code] ?? ["#26B47D", "#0D1117"];
  return { primary, secondary };
}

function luminance(hex: string): number {
  const value = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((offset) => {
    const channel = parseInt(value.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Readable number colour on top of a kit. */
export function inkOn(hex: string): string { return luminance(hex) > 0.4 ? "#0D1117" : "#FFFFFF"; }

/** Kits for a fixture: the away side switches to its secondary colour when both clash. */
export function matchKits(home: string, away: string): { home: string; away: string } {
  const h = clubColors(home);
  const a = clubColors(away);
  const clash = Math.abs(luminance(h.primary) - luminance(a.primary)) < 0.12 && h.primary.slice(1, 3) === a.primary.slice(1, 3);
  const similar = Math.abs(luminance(h.primary) - luminance(a.primary)) < 0.08;
  return { home: h.primary, away: clash || similar ? a.secondary : a.primary };
}
