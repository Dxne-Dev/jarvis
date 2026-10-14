/**
 * Niveau audio synthétique, proche d'une voix (syllabes, respiration),
 * pour prévisualiser et mesurer les états « écoute » et « parole » sans micro.
 */
export function createDemoLevel(seed = 1): () => number {
  let phase = seed;
  let last = performance.now();
  return () => {
    const now = performance.now();
    phase += (now - last) / 1000;
    last = now;
    const syllables = Math.max(0, Math.sin(phase * 2 * Math.PI * 3.1));
    const words = 0.5 + 0.5 * Math.sin(phase * 2 * Math.PI * 0.45);
    const breath = Math.sin(phase * 2 * Math.PI * 0.12) > -0.6 ? 1 : 0.1;
    const grain = 0.85 + 0.15 * Math.sin(phase * 2 * Math.PI * 23.7);
    return Math.min(1, syllables * words * breath * grain * 1.1);
  };
}
