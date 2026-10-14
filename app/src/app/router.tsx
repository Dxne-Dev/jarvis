import { createHashRouter } from "react-router";

import { HomeScreen } from "../features/home/HomeScreen";
import { JournalScreen } from "../features/journal/JournalScreen";
import { SettingsScreen } from "../features/settings/SettingsScreen";
import { Shell } from "./Shell";

// Routeur à hachage : l'app de bureau n'a pas de serveur pour réécrire les URL.
export const router = createHashRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <HomeScreen /> },
      { path: "journal", element: <JournalScreen /> },
      { path: "reglages", element: <SettingsScreen /> },
    ],
  },
]);
