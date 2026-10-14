import { randomBytes } from "node:crypto";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * Tests de bout en bout : l'interface (Vite) branchée au vrai moteur Python.
 * Le moteur tourne dans un dossier temporaire, avec un trousseau en mémoire,
 * sans import de .env : aucun test ne touche aux vraies clés.
 */
const ENGINE_PORT = 18765;
const token = process.env.OJARVIS_E2E_TOKEN ?? randomBytes(32).toString("hex");
process.env.OJARVIS_E2E_TOKEN = token;

const home = process.env.OJARVIS_E2E_HOME ?? mkdtempSync(join(tmpdir(), "ojarvis-e2e-"));
process.env.OJARVIS_E2E_HOME = home;
const emptyEnv = join(home, "vide.env");
writeFileSync(emptyEnv, "");

const engineDir = resolve(import.meta.dirname, "../engine");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  outputDir: "../artefacts/e2e-results",
  use: {
    baseURL: "http://localhost:1420",
    trace: "retain-on-failure",
    ...(process.env.CI ? {} : { channel: "chrome" }),
  },
  projects: [
    {
      name: "chrome",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: [
    {
      command: `${engineDir}/.venv/bin/python -m ojarvis --dev --port ${ENGINE_PORT} --token-env OJARVIS_E2E_TOKEN`,
      url: `http://127.0.0.1:${ENGINE_PORT}/health`,
      cwd: engineDir,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        OJARVIS_E2E_TOKEN: token,
        OJARVIS_HOME: home,
        OJARVIS_MEMORY_KEYRING: "1",
        OJARVIS_DOTENV: emptyEnv,
      },
    },
    {
      command: "pnpm dev",
      url: "http://localhost:1420",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        VITE_OJARVIS_ENGINE_URL: `http://127.0.0.1:${ENGINE_PORT}`,
        VITE_OJARVIS_TOKEN: token,
      },
    },
  ],
});
