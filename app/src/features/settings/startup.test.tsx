import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const autostart = vi.hoisted(() => ({
  enabled: false,
  enable: vi.fn(() => {
    autostart.enabled = true;
    return Promise.resolve();
  }),
  disable: vi.fn(() => {
    autostart.enabled = false;
    return Promise.resolve();
  }),
}));

// Dans l'app installée : la coque Tauri et son greffon de démarrage automatique.
vi.mock("../../lib/engine/connection", async (original) => ({
  ...(await original<object>()),
  runtime: "tauri",
}));
vi.mock("@tauri-apps/plugin-autostart", () => ({
  isEnabled: () => Promise.resolve(autostart.enabled),
  enable: autostart.enable,
  disable: autostart.disable,
}));

const { StartupSection } = await import("./StartupSection");

describe("Démarrage", () => {
  it("active puis désactive le lancement à l'ouverture de session", async () => {
    const user = userEvent.setup();
    render(<StartupSection />);
    const toggle = await screen.findByRole("switch", { name: /ouverture de session/ });
    await waitFor(() => {
      expect(toggle).toBeEnabled();
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    await waitFor(() => {
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });
    expect(autostart.enable).toHaveBeenCalledOnce();
    await user.click(toggle);
    await waitFor(() => {
      expect(toggle).toHaveAttribute("aria-checked", "false");
    });
    expect(autostart.disable).toHaveBeenCalledOnce();
  });
});
