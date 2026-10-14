export type SphereState = "idle" | "listening" | "thinking" | "speaking" | "awaiting" | "error";

export const SPHERE_STATES: readonly SphereState[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "awaiting",
  "error",
];

/** Libellés lus par les lecteurs d'écran et affichés sous la sphère. */
export const STATE_LABELS: Record<SphereState, string> = {
  idle: "En veille",
  listening: "J'écoute",
  thinking: "Je réfléchis",
  speaking: "Je parle",
  awaiting: "Action en attente de ta validation",
  error: "Un problème est survenu",
};

export type ColorRole = "accent" | "accentStrong" | "warning" | "danger";

export interface SphereParams {
  /** Déformation de base de la surface. */
  amplitude: number;
  /** Réaction au niveau audio (micro ou voix). */
  audioGain: number;
  /** Finesse du relief. */
  frequency: number;
  /** Vitesse d'évolution du relief. */
  flow: number;
  /** Vitesse de rotation, en radians par seconde. */
  spin: number;
  core: number;
  halo: number;
  rings: number;
  ringSpeed: number;
  /** Pulsation lumineuse du cœur (Hz) et sa profondeur. */
  pulseRate: number;
  pulseDepth: number;
  /** Respiration lente (variation d'échelle). */
  breathe: number;
  jitter: number;
  pointSize: number;
  color: ColorRole;
}

export const STATE_PARAMS: Record<SphereState, SphereParams> = {
  idle: {
    amplitude: 0.045,
    audioGain: 0,
    frequency: 1.6,
    flow: 0.12,
    spin: 0.1,
    core: 0.32,
    halo: 0.24,
    rings: 0,
    ringSpeed: 0.2,
    pulseRate: 0,
    pulseDepth: 0,
    breathe: 0.02,
    jitter: 0,
    pointSize: 1,
    color: "accent",
  },
  listening: {
    amplitude: 0.05,
    audioGain: 0.34,
    frequency: 1.9,
    flow: 0.28,
    spin: 0.16,
    core: 0.44,
    halo: 0.34,
    rings: 0.15,
    ringSpeed: 0.35,
    pulseRate: 0,
    pulseDepth: 0,
    breathe: 0,
    jitter: 0,
    pointSize: 1.1,
    color: "accentStrong",
  },
  thinking: {
    amplitude: 0.07,
    audioGain: 0,
    frequency: 2.6,
    flow: 0.75,
    spin: 0.55,
    core: 0.4,
    halo: 0.28,
    rings: 0.85,
    ringSpeed: 1.4,
    pulseRate: 1.1,
    pulseDepth: 0.25,
    breathe: 0,
    jitter: 0,
    pointSize: 0.95,
    color: "accent",
  },
  speaking: {
    amplitude: 0.04,
    audioGain: 0.42,
    frequency: 1.5,
    flow: 0.35,
    spin: 0.18,
    core: 0.5,
    halo: 0.4,
    rings: 0.2,
    ringSpeed: 0.4,
    pulseRate: 0,
    pulseDepth: 0,
    breathe: 0,
    jitter: 0,
    pointSize: 1.1,
    color: "accentStrong",
  },
  awaiting: {
    amplitude: 0.04,
    audioGain: 0,
    frequency: 1.4,
    flow: 0.15,
    spin: 0.08,
    core: 0.38,
    halo: 0.3,
    rings: 0.65,
    ringSpeed: 0.25,
    pulseRate: 0.55,
    pulseDepth: 0.35,
    breathe: 0.012,
    jitter: 0,
    pointSize: 1,
    color: "warning",
  },
  error: {
    amplitude: 0.1,
    audioGain: 0,
    frequency: 3.2,
    flow: 0.5,
    spin: 0.04,
    core: 0.24,
    halo: 0.18,
    rings: 0,
    ringSpeed: 0,
    pulseRate: 0,
    pulseDepth: 0,
    breathe: 0,
    jitter: 0.6,
    pointSize: 0.9,
    color: "danger",
  },
};

/**
 * Animations réduites : le mouvement s'efface, l'information reste
 * (couleur, anneaux, luminosité du cœur liée au niveau audio, libellé).
 */
export function reduceMotion(params: SphereParams): SphereParams {
  return {
    ...params,
    spin: params.spin * 0.12,
    flow: params.flow * 0.15,
    ringSpeed: params.ringSpeed * 0.15,
    pulseRate: 0,
    pulseDepth: 0,
    breathe: 0,
    jitter: 0,
    amplitude: params.amplitude * 0.6,
    audioGain: 0,
  };
}

export type NumericParam = Exclude<keyof SphereParams, "color">;

export const NUMERIC_PARAMS: readonly NumericParam[] = [
  "amplitude",
  "audioGain",
  "frequency",
  "flow",
  "spin",
  "core",
  "halo",
  "rings",
  "ringSpeed",
  "pulseRate",
  "pulseDepth",
  "breathe",
  "jitter",
  "pointSize",
];
