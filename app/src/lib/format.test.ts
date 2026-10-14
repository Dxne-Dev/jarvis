import { describe, expect, it } from "vitest";

import { formatDuration, formatRelative } from "./format";

describe("format", () => {
  it("affiche les durées en ms puis en secondes, virgule française", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(340.4)).toBe("340 ms");
    expect(formatDuration(1234)).toBe("1,23 s");
    expect(formatDuration(65_000)).toBe("65,0 s");
  });

  it("donne des dates relatives en français", () => {
    const now = new Date("2026-10-14T20:00:00Z");
    expect(formatRelative("2026-10-14T19:59:30Z", now)).toMatch(/30 secondes/);
    expect(formatRelative("2026-10-14T19:40:00Z", now)).toMatch(/20 minutes/);
    expect(formatRelative("2026-10-14T17:00:00Z", now)).toMatch(/3 heures/);
    expect(formatRelative("2026-10-12T20:00:00Z", now)).toMatch(/avant-hier|2 jours/);
  });
});
