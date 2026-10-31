import { create } from "zustand";

/** Le numéro de la dernière image de l'écran partagé : l'aperçu la relit quand il change. */
export const useScreenLive = create<{ seq: number; setSeq: (seq: number) => void }>((set) => ({
  seq: 0,
  setSeq: (seq) => {
    set({ seq });
  },
}));
