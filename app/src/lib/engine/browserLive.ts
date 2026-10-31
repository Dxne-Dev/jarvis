import { create } from "zustand";

/** La dernière image de la page de Jarvis (#34) : son numéro et son adresse. L'image
 * elle-même se lit sur le moteur (`/v1/browser/live`), sur cette machine. */
interface BrowserLiveState {
  seq: number;
  url: string;
  setFrame: (seq: number, url: string) => void;
}

export const useBrowserLive = create<BrowserLiveState>((set) => ({
  seq: 0,
  url: "",
  setFrame: (seq, url) => {
    set({ seq, url });
  },
}));
