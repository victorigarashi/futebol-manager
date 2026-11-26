import { CAMERA_LIMITS, PRESET_HINT, PRESET_LABEL, PRESET_ORDER, presetSettings, type CameraPreset, type CameraSettings } from "./render/cameraPresets";
import type { QualityChoice } from "./render/preference";

/**
 * In-match camera and graphics panel. Everything applies immediately (no reload, no restart
 * of the move) and is saved locally: it is one coach's own view, never shared with the rival
 * and never able to change the result.
 */
type Props = {
  value: CameraSettings;
  onChange: (next: CameraSettings) => void;
  quality: QualityChoice;
  onQuality: (quality: QualityChoice) => void;
  shadows: boolean;
  onShadows: (on: boolean) => void;
  fpsCap: number;
  onFpsCap: (fps: 0 | 30 | 60 | 120) => void;
  onClose: () => void;
};

const NUMBER = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

export function CameraPanel({ value, onChange, quality, onQuality, shadows, onShadows, fpsCap, onFpsCap, onClose }: Props) {
  // Any manual adjustment keeps the view but switches the preset to "Personalizada".
  const set = (patch: Partial<CameraSettings>) => onChange({ ...value, ...patch, preset: "custom" });
  const apply = (preset: CameraPreset) => onChange(presetSettings(preset));
  const slider = (
    key: "height" | "distance" | "zoom" | "fov" | "tilt" | "lateral" | "follow",
    label: string, unit: string, step: number,
  ) => (
    <label className="im-cam__row">
      <span>{label}</span>
      <output>{NUMBER.format(value[key])}{unit}</output>
      <input type="range" min={CAMERA_LIMITS[key][0]} max={CAMERA_LIMITS[key][1]} step={step}
        value={value[key]} aria-label={label}
        onChange={(event) => set({ [key]: Number(event.target.value) } as Partial<CameraSettings>)} />
    </label>
  );

  return <div className="im-cam" role="dialog" aria-label="Câmera e gráficos">
    <div className="im-cam__head"><h3>Câmera</h3><button type="button" onClick={onClose} aria-label="Fechar">✕</button></div>
    <div className="im-cam__presets" role="radiogroup" aria-label="Câmera da partida">
      {PRESET_ORDER.map((preset) => <button key={preset} type="button" role="radio" aria-checked={value.preset === preset}
        className={value.preset === preset ? "is-on" : ""} onClick={() => apply(preset)}>{PRESET_LABEL[preset]}</button>)}
    </div>
    <p>{PRESET_HINT[value.preset]}</p>
    {slider("height", "Altura", " m", 1)}
    {slider("distance", "Distância", " m", 1)}
    {slider("zoom", "Zoom", "×", 0.05)}
    {slider("fov", "Campo de visão", "°", 1)}
    {slider("tilt", "Ângulo vertical", "", 0.01)}
    {slider("lateral", "Deslocamento lateral", " m", 1)}
    {slider("follow", "Suavidade", "", 0.01)}
    <button type="button" className="im-cam__reset" onClick={() => onChange(presetSettings(value.preset))}>Restaurar esta câmera</button>

    <h3>Gráficos</h3>
    <label className="im-cam__row"><span>Qualidade</span>
      <select value={quality} onChange={(event) => onQuality(event.target.value as QualityChoice)}>
        <option value="auto">Automática</option><option value="low">Baixa</option><option value="medium">Média</option><option value="high">Alta</option>
      </select>
    </label>
    <label className="im-cam__check"><input type="checkbox" checked={shadows} onChange={(event) => onShadows(event.target.checked)} /> Sombras dos jogadores e do estádio</label>
    <label className="im-cam__row"><span>Limite de FPS</span>
      <select value={fpsCap} onChange={(event) => onFpsCap(Number(event.target.value) as 0 | 30 | 60 | 120)}>
        <option value={0}>Livre</option><option value={30}>30</option><option value={60}>60</option><option value={120}>120</option>
      </select>
    </label>
    <p>A qualidade se ajusta sozinha se o aparelho não segurar o ritmo. A troca 2D/3D continua no topo.</p>
  </div>;
}
