import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { LocalModel } from "../../lib/engine/types";
import { fakeEngine, renderScreen } from "../../test/render";
import { LocalModelsSection } from "./LocalModelsSection";

const MODEL_BIN = "https://huggingface.co/Systran/faster-whisper-base/resolve/abc/model.bin";

function models(ready: boolean): LocalModel[] {
  return [
    {
      key: "reveil",
      label: "Mot de réveil",
      folder: "/home/moi/.cache/o-jarvis/models/openwakeword",
      ready: true,
      state: "prêt",
      files: [],
    },
    {
      key: "transcription",
      label: "Transcription",
      folder: "/home/moi/.cache/o-jarvis/models/faster-whisper-base",
      ready,
      state: ready ? "prêt" : "absent",
      files: [
        {
          name: "model.bin",
          url: MODEL_BIN,
          sha256: "d0".repeat(32),
          size: 145_217_532,
          present: ready,
          partial: ready ? 0 : 45_000_000,
        },
      ],
    },
  ];
}

describe("Modèles locaux", () => {
  it("montre ce qui manque, les liens à la main, et importe un fichier", async () => {
    const user = userEvent.setup();
    let imported = false;
    const { client, calls } = fakeEngine((method, path) => {
      if (path === "/v1/local-models") return [200, models(imported)];
      if (path === "/v1/local-models/import" && method === "POST") {
        imported = true;
        return [
          200,
          { key: "transcription", label: "Transcription", file: "model.bin", ready: true },
        ];
      }
      if (path === "/v1/local-models/retry") return [202, null];
      return [404, {}];
    });
    renderScreen(<LocalModelsSection />, { client });

    expect(
      await screen.findByText("absent · 100 Mo à télécharger · 45 Mo déjà reçus"),
    ).toBeInTheDocument();
    await user.click(screen.getByText("Télécharger à la main (connexion faible)"));
    expect(screen.getByRole("link", { name: "model.bin" })).toHaveAttribute("href", MODEL_BIN);
    expect(
      screen.getByText("/home/moi/.cache/o-jarvis/models/faster-whisper-base"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    await waitFor(() => {
      expect(calls.some((c) => c.path === "/v1/local-models/retry")).toBe(true);
    });

    const file = new File(["contenu"], "model (1).bin");
    await user.upload(screen.getByLabelText("Fichiers de modèles à importer"), file);
    const result = await screen.findByRole("status");
    expect(
      within(result).getByText(/model \(1\)\.bin : rangé dans Transcription/),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/v1/local-models/import")?.body).toBe(file);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
    });
  });
});
