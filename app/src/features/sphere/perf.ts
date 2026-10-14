import type { PerfSample } from "../../lib/engine/types";

/** Une image est « longue » quand elle dépasse 1,5 intervalle à 60 i/s. */
export const LONG_FRAME_MS = 25;

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[index] ?? 0;
}

/** Statistiques d'une série d'intervalles entre images (en millisecondes). */
export function summarize(state: string, intervalsMs: number[], durationS: number): PerfSample {
  const sorted = [...intervalsMs].sort((a, b) => a - b);
  const round = (n: number) => Math.round(n * 100) / 100;
  return {
    state,
    duration_s: round(durationS),
    frames: intervalsMs.length,
    fps_mean: round(durationS > 0 ? intervalsMs.length / durationS : 0),
    frame_ms_p50: round(percentile(sorted, 50)),
    frame_ms_p95: round(percentile(sorted, 95)),
    frame_ms_p99: round(percentile(sorted, 99)),
    long_frames: intervalsMs.filter((ms) => ms > LONG_FRAME_MS).length,
  };
}

/** Collecte les intervalles entre images pendant une fenêtre de mesure. */
export class FrameRecorder {
  private intervals: number[] = [];
  private startedAt = 0;
  private recording = false;

  start(now: number): void {
    this.intervals = [];
    this.startedAt = now;
    this.recording = true;
  }

  record(dtMs: number): void {
    if (this.recording && dtMs > 0) this.intervals.push(dtMs);
  }

  stop(state: string, now: number): PerfSample {
    this.recording = false;
    return summarize(state, this.intervals, (now - this.startedAt) / 1000);
  }
}
