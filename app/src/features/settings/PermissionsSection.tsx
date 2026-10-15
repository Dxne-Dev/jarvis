import { ErrorState, LoadingState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import { usePreferences, useTools } from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import type { PermissionLevel } from "../../lib/engine/types";
import { LEVEL_HINT, LEVEL_NAME } from "../actions/levels";
import styles from "./SettingsScreen.module.css";

const LEVELS: PermissionLevel[] = [1, 2, 3];

/** Les trois niveaux, et le niveau de chaque outil (fixé par le moteur, pas modifiable ici). */
export function PermissionsSection() {
  const tools = useTools();
  const preferences = usePreferences();
  const online = useEngineOnline();
  const osControl = preferences.data?.os_control_enabled ?? false;
  if (!online && !tools.data)
    return <p className={styles.note}>Disponible dès que le moteur répondra.</p>;
  if (tools.isPending) return <LoadingState label="Lecture des outils…" />;
  if (tools.isError)
    return (
      <ErrorState
        message={describeError(tools.error)}
        onRetry={() => {
          void tools.refetch();
        }}
      />
    );
  return (
    <>
      {LEVELS.map((level) => (
        <div key={level} className={styles.group}>
          <div>
            <h3 className={styles.groupTitle}>
              Niveau {level} · {LEVEL_NAME[level]}
            </h3>
            <p className={styles.groupDescription}>{LEVEL_HINT[level]}</p>
          </div>
          <ul className={styles.secrets} aria-label={`Outils de niveau ${level}`}>
            {tools.data
              .filter((t) => t.level === level)
              .map((tool) => (
                <li key={tool.name} className={styles.toolRow}>
                  <code className={styles.code}>{tool.name}</code>
                  <span className={styles.secretHelp}>
                    {tool.description}
                    {tool.os_control && (
                      <span className={styles.toolTag}>
                        {osControl ? " Contrôle du PC" : " Contrôle du PC (désactivé)"}
                      </span>
                    )}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      ))}
      <p className={styles.groupDescription}>
        Ouvrir une page d&apos;un domaine où tu es connecté passe au niveau 2. Une automatisation ne
        déclenche jamais seule une action de niveau 2 ou 3.
      </p>
    </>
  );
}
