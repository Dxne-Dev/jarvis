import {
  NUMERIC_PARAMS,
  reduceMotion,
  STATE_PARAMS,
  type ColorRole,
  type NumericParam,
  type SphereState,
} from "./states";

export type RGB = [number, number, number];

export type Palette = Record<ColorRole, RGB>;

export interface FrameParams {
  values: Record<NumericParam, number>;
  color: RGB;
  colorHot: RGB;
  /** Niveau audio lissé, déjà multiplié par le gain de l'état. */
  audio: number;
  /** Intensité du cœur, pulsation et niveau audio compris. */
  coreNow: number;
  /** Échelle (respiration). */
  scale: number;
}

/** Temps de réponse des transitions entre états (constante de temps, en secondes). */
const TRANSITION_TAU_S = 0.16;
const AUDIO_ATTACK_TAU_S = 0.04;
const AUDIO_RELEASE_TAU_S = 0.22;

function approach(current: number, target: number, dt: number, tau: number): number {
  return current + (target - current) * (1 - Math.exp(-dt / tau));
}

function mixColor(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function lighten(color: RGB, amount: number): RGB {
  return mixColor(color, [1, 1, 1], amount);
}

/**
 * Logique de la sphère, sans WebGL : transitions douces entre états,
 * enveloppe du niveau audio, pulsation et respiration.
 */
export class SphereAnimator {
  private state: SphereState = "idle";
  private reduced = false;
  private values: Record<NumericParam, number>;
  private color: RGB;
  private level = 0;
  private time = 0;

  constructor(private palette: Palette) {
    this.values = { ...STATE_PARAMS.idle };
    this.color = palette[STATE_PARAMS.idle.color];
  }

  setState(state: SphereState): void {
    this.state = state;
  }

  setReducedMotion(reduced: boolean): void {
    this.reduced = reduced;
  }

  setPalette(palette: Palette): void {
    this.palette = palette;
  }

  get currentState(): SphereState {
    return this.state;
  }

  target(): Record<NumericParam, number> & { color: ColorRole } {
    const base = STATE_PARAMS[this.state];
    return this.reduced ? reduceMotion(base) : base;
  }

  step(dtSeconds: number, rawLevel: number): FrameParams {
    const dt = Math.min(Math.max(dtSeconds, 0), 0.1);
    this.time += dt;
    const target = this.target();
    for (const key of NUMERIC_PARAMS) {
      this.values[key] = approach(this.values[key], target[key], dt, TRANSITION_TAU_S);
    }
    const goal = this.palette[target.color];
    this.color = mixColor(this.color, goal, 1 - Math.exp(-dt / TRANSITION_TAU_S));

    const level = Math.min(Math.max(rawLevel, 0), 1);
    const tau = level > this.level ? AUDIO_ATTACK_TAU_S : AUDIO_RELEASE_TAU_S;
    this.level = approach(this.level, level, dt, tau);

    const v = this.values;
    const pulse = 1 + v.pulseDepth * Math.sin(2 * Math.PI * v.pulseRate * this.time);
    // En mouvement réduit, le niveau audio passe par la luminosité du cœur, pas par le relief.
    const audioLight = this.reduced ? this.level * 0.6 : this.level * 0.45;
    return {
      values: { ...v },
      color: this.color,
      colorHot: lighten(this.color, 0.55),
      audio: this.level * v.audioGain,
      coreNow: v.core * pulse + (target.audioGain > 0 || this.reduced ? audioLight : 0),
      scale: 1 + v.breathe * Math.sin(2 * Math.PI * 0.16 * this.time),
    };
  }
}

/** Lit une couleur CSS (#rrggbb, #rgb ou rgb(r g b / a)) en composantes 0..1. */
export function parseCssColor(value: string): RGB | null {
  const text = value.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(text);
  if (hex?.[1]) {
    const digits = hex[1];
    const full =
      digits.length === 3
        ? digits
            .split("")
            .map((c) => c + c)
            .join("")
        : digits;
    const n = Number.parseInt(full, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  const rgb = /^rgba?\(\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)/.exec(text);
  if (rgb?.[1] && rgb[2] && rgb[3]) {
    return [Number(rgb[1]) / 255, Number(rgb[2]) / 255, Number(rgb[3]) / 255];
  }
  return null;
}

const TOKEN_FOR_ROLE: Record<ColorRole, string> = {
  accent: "--color-accent",
  accentStrong: "--color-accent-strong",
  warning: "--color-warning",
  danger: "--color-danger",
};

/** Les couleurs de la sphère viennent des tokens CSS, jamais du code. */
export function readPalette(element: Element = document.documentElement): Palette {
  const style = getComputedStyle(element);
  const fallback: RGB = [0.5, 0.5, 0.5];
  const read = (role: ColorRole): RGB =>
    parseCssColor(style.getPropertyValue(TOKEN_FOR_ROLE[role])) ?? fallback;
  return {
    accent: read("accent"),
    accentStrong: read("accentStrong"),
    warning: read("warning"),
    danger: read("danger"),
  };
}
