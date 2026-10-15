import { create } from "zustand";

import type { VoicePhase } from "./engine/types";

interface VoiceState {
  /** État du pipeline vocal, poussé par le moteur (événement `voice.state`). */
  phase: VoicePhase;
  /** Dernière phrase entendue, affichée pendant que Jarvis répond. */
  transcript: string | null;
  /** Ce que Jarvis est en train de dire (sous-titres), phrase après phrase. */
  reply: string;
  /** Conversation du dernier tour vocal, pour l'ouvrir à l'accueil. */
  conversationId: string | null;
  setPhase: (phase: VoicePhase) => void;
  setTranscript: (text: string | null) => void;
  addSentence: (text: string) => void;
  setConversation: (id: string | null) => void;
}

export const useVoiceStore = create<VoiceState>((set) => ({
  phase: "off",
  transcript: null,
  reply: "",
  conversationId: null,
  setPhase: (phase) => {
    set(phase === "idle" || phase === "off" ? { phase, transcript: null, reply: "" } : { phase });
  },
  setTranscript: (transcript) => {
    set({ transcript, reply: "" });
  },
  addSentence: (text) => {
    set((state) => ({ reply: state.reply ? `${state.reply} ${text}` : text }));
  },
  setConversation: (conversationId) => {
    set({ conversationId });
  },
}));

/*
 * Niveau audio (micro ou voix de Jarvis) : une douzaine de mesures par seconde.
 * Il vit hors de React pour ne pas redessiner l'écran à chaque mesure ; la sphère
 * le lit à chaque image et le lisse.
 */
const level = { target: 0, current: 0, at: 0 };

export function setVoiceLevel(value: number, now = performance.now()): void {
  level.target = Math.max(0, Math.min(1, value));
  level.at = now;
}

/** Niveau lissé, entre 0 et 1 ; retombe à zéro si plus rien n'arrive. */
export function voiceLevel(now = performance.now()): number {
  const stale = now - level.at > 250;
  const target = stale ? 0 : level.target;
  level.current += (target - level.current) * (target > level.current ? 0.45 : 0.18);
  return level.current;
}
