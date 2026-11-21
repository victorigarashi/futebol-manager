import { readLocal, writeLocal } from "../../../lib/storage";

/**
 * Match sounds, synthesised with WebAudio (original, no audio files): kick, pass, post,
 * save, whistle, goal roar and a soft crowd bed. The context is created on the first user
 * gesture (browser autoplay rules) and every call is a no-op without it.
 */
type Settings = { volume: number; muted: boolean };
const KEY = "bm_match_sound";

class MatchSound {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private crowd: GainNode | null = null;
  private noise: AudioBuffer | null = null;
  settings: Settings = (() => {
    try { const raw = JSON.parse(readLocal(KEY) ?? "null"); if (raw && typeof raw.volume === "number") return { volume: Math.max(0, Math.min(1, raw.volume)), muted: Boolean(raw.muted) }; } catch { /* default */ }
    return { volume: 0.6, muted: false };
  })();

  unlock(): void {
    if (this.ctx) { if (this.ctx.state === "suspended") void this.ctx.resume(); return; }
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    try {
      this.ctx = new Ctor();
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
      this.apply();
      const length = this.ctx.sampleRate * 2;
      this.noise = this.ctx.createBuffer(1, length, this.ctx.sampleRate);
      const data = this.noise.getChannelData(0);
      for (let i = 0; i < length; i += 1) data[i] = Math.random() * 2 - 1;
      this.startCrowd();
    } catch { this.ctx = null; }
  }

  set(next: Partial<Settings>): void {
    this.settings = { ...this.settings, ...next };
    writeLocal(KEY, JSON.stringify(this.settings));
    this.apply();
  }

  private apply(): void {
    if (this.master && this.ctx) this.master.gain.setTargetAtTime(this.settings.muted ? 0 : this.settings.volume, this.ctx.currentTime, 0.05);
  }

  private source(filterType: BiquadFilterType, freq: number, q = 1): { src: AudioBufferSourceNode; gain: GainNode; filter: BiquadFilterNode } | null {
    if (!this.ctx || !this.master || !this.noise) return null;
    const src = this.ctx.createBufferSource(); src.buffer = this.noise; src.loop = true;
    const filter = this.ctx.createBiquadFilter(); filter.type = filterType; filter.frequency.value = freq; filter.Q.value = q;
    const gain = this.ctx.createGain(); gain.gain.value = 0;
    src.connect(filter); filter.connect(gain); gain.connect(this.master);
    return { src, gain, filter };
  }

  private tone(freq: number, type: OscillatorType, start: number, dur: number, peak: number, endFreq?: number): void {
    if (!this.ctx || !this.master) return;
    const osc = this.ctx.createOscillator(); osc.type = type; osc.frequency.setValueAtTime(freq, start);
    if (endFreq) osc.frequency.exponentialRampToValueAtTime(endFreq, start + dur);
    const gain = this.ctx.createGain(); gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(peak, start + 0.008); gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
    osc.connect(gain); gain.connect(this.master); osc.start(start); osc.stop(start + dur + 0.02);
  }

  private burst(filterType: BiquadFilterType, freq: number, dur: number, peak: number, attack = 0.004): void {
    const s = this.source(filterType, freq); if (!s || !this.ctx) return;
    const t = this.ctx.currentTime;
    s.gain.gain.setValueAtTime(0.0001, t); s.gain.gain.exponentialRampToValueAtTime(peak, t + attack); s.gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.src.start(t, Math.random()); s.src.stop(t + dur + 0.05);
  }

  private startCrowd(): void {
    const s = this.source("bandpass", 650, 0.6); if (!s || !this.ctx) return;
    s.gain.gain.value = 0.045; s.src.start(); this.crowd = s.gain;
  }

  /** Crowd swell for big moments (0..1). */
  swell(level: number, seconds = 1.5): void {
    if (!this.crowd || !this.ctx) return;
    const t = this.ctx.currentTime;
    this.crowd.gain.cancelScheduledValues(t);
    this.crowd.gain.setTargetAtTime(0.045 + level * 0.16, t, 0.15);
    this.crowd.gain.setTargetAtTime(0.045, t + seconds, 0.6);
  }

  kick(power = 0.6): void {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.tone(150, "sine", t, 0.12, 0.35 + power * 0.4, 55);
    this.burst("lowpass", 1400 + power * 1500, 0.06, 0.25 + power * 0.25, 0.002);
  }

  pass(): void { this.kick(0.25); }

  post(): void {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    for (const [f, p] of [[520, 0.3], [1310, 0.18], [2260, 0.08]] as const) this.tone(f, "sine", t, 0.9, p);
    this.swell(0.7, 1.2);
  }

  save(): void {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.tone(95, "sine", t, 0.18, 0.4, 50);
    this.burst("lowpass", 500, 0.14, 0.3);
    this.swell(0.5, 1.0);
  }

  net(): void { this.burst("highpass", 2500, 0.35, 0.15, 0.02); }

  whistle(blasts = 1): void {
    if (!this.ctx || !this.master) return;
    for (let i = 0; i < blasts; i += 1) {
      const start = this.ctx.currentTime + i * 0.45;
      const dur = blasts > 1 && i === blasts - 1 ? 0.7 : 0.3;
      const osc = this.ctx.createOscillator(); osc.frequency.value = 2950;
      const lfo = this.ctx.createOscillator(); lfo.frequency.value = 28;
      const depth = this.ctx.createGain(); depth.gain.value = 140;
      lfo.connect(depth); depth.connect(osc.frequency);
      const gain = this.ctx.createGain(); gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.12, start + 0.02); gain.gain.setValueAtTime(0.12, start + dur - 0.05); gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
      osc.connect(gain); gain.connect(this.master);
      osc.start(start); lfo.start(start); osc.stop(start + dur + 0.05); lfo.stop(start + dur + 0.05);
    }
  }

  goal(): void {
    const s = this.source("bandpass", 500, 0.5); if (!s || !this.ctx) return;
    const t = this.ctx.currentTime;
    s.filter.frequency.setValueAtTime(400, t); s.filter.frequency.exponentialRampToValueAtTime(1100, t + 0.8);
    s.gain.gain.setValueAtTime(0.0001, t); s.gain.gain.exponentialRampToValueAtTime(0.5, t + 0.35); s.gain.gain.setTargetAtTime(0.0001, t + 1.6, 0.5);
    s.src.start(t); s.src.stop(t + 3.5);
    this.net();
  }

  tackle(): void { this.burst("lowpass", 700, 0.12, 0.25); }
}

export const matchSound = new MatchSound();
