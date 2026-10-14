import "./styles/tokens.css";
import "./styles/base.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { installGlobalErrorLogging, uiLog } from "./lib/log";

installGlobalErrorLogging();
uiLog("info", `interface chargée (${navigator.userAgent})`);

const root = document.getElementById("root");
if (!root) throw new Error("élément #root introuvable");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
