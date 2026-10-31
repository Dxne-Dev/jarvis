import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { fakeEngine, renderScreen } from "../../test/render";
import { ShareBanner } from "./ShareBanner";

describe("Écran partagé en direct", () => {
  it("ne montre rien tant que l'écran n'est pas partagé", async () => {
    const { client, calls } = fakeEngine(() => [200, { active: false, frames: 0, since: null }]);
    renderScreen(<ShareBanner />, { client });
    await waitFor(() => {
      expect(calls.some((c) => c.path === "/v1/desktop/share")).toBe(true);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("le dit, et l'arrête d'un clic", async () => {
    const user = userEvent.setup();
    const { client, calls } = fakeEngine((method, path) => {
      if (method === "POST" && path === "/v1/desktop/share/stop")
        return [200, { active: false, frames: 12, since: null }];
      return [200, { active: true, frames: 12, since: 1761900000 }];
    });
    renderScreen(<ShareBanner />, { client });
    expect(await screen.findByText(/Ton écran est partagé avec Jarvis/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Arrêter le partage" }));
    await waitFor(() => {
      expect(screen.queryByText(/Ton écran est partagé avec Jarvis/)).not.toBeInTheDocument();
    });
    expect(calls.some((c) => c.method === "POST" && c.path === "/v1/desktop/share/stop")).toBe(
      true,
    );
  });
});
