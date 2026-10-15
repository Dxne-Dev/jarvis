import { createHashRouter } from "react-router";

import { ActionsScreen } from "../features/actions/ActionsScreen";
import { AutomationsScreen } from "../features/automations/AutomationsScreen";
import { HistoryScreen } from "../features/history/HistoryScreen";
import { HomeScreen } from "../features/home/HomeScreen";
import { JournalScreen } from "../features/journal/JournalScreen";
import { MemoryScreen } from "../features/memory/MemoryScreen";
import { SettingsScreen } from "../features/settings/SettingsScreen";
import { Shell } from "./Shell";

// Routeur à hachage : l'app de bureau n'a pas de serveur pour réécrire les URL.
export const router = createHashRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <HomeScreen /> },
      { path: "historique", element: <HistoryScreen /> },
      { path: "memoire", element: <MemoryScreen /> },
      { path: "actions", element: <ActionsScreen /> },
      { path: "automatisations", element: <AutomationsScreen /> },
      { path: "journal", element: <JournalScreen /> },
      { path: "reglages", element: <SettingsScreen /> },
    ],
  },
]);
