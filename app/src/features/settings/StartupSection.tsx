import { Power } from "lucide-react";
import { Switch } from "radix-ui";
import { useEffect, useId, useState } from "react";

import { autostartEnabled, setAutostart } from "../../lib/desktop";
import { runtime } from "../../lib/engine/connection";
import styles from "./SettingsScreen.module.css";

/** Démarrer O-jarvis à l'ouverture de session : discret, dans la barre système. */
export function StartupSection() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = useId();

  useEffect(() => {
    let alive = true;
    void autostartEnabled().then((value) => {
      if (alive) setEnabled(value);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (runtime !== "tauri")
    return (
      <p className={styles.note}>Réglable dans l&apos;app installée, pas dans un navigateur.</p>
    );

  return (
    <ul className={styles.secrets} aria-label="Démarrage">
      <li className={styles.secret}>
        <div className={styles.grantHead}>
          <Power className={styles.secretIcon} aria-hidden="true" />
          <div className={styles.secretText}>
            <label htmlFor={id} className={styles.secretLabel}>
              Lancer O-jarvis à l&apos;ouverture de session
            </label>
            <p id={`${id}-aide`} className={styles.secretHelp}>
              Il démarre discrètement dans la barre système : « Hey Jarvis » est prêt, et le
              briefing du matin se joue à ta première session.
            </p>
          </div>
          <div className={styles.actions}>
            <Switch.Root
              id={id}
              className={styles.switch}
              checked={enabled ?? false}
              disabled={enabled === null || busy}
              aria-describedby={`${id}-aide`}
              onCheckedChange={(on) => {
                setBusy(true);
                setError(null);
                setAutostart(on)
                  .then(() => {
                    setEnabled(on);
                  })
                  .catch((reason: unknown) => {
                    setError(`Réglage impossible : ${String(reason)}`);
                  })
                  .finally(() => {
                    setBusy(false);
                  });
              }}
            >
              <Switch.Thumb className={styles.switchThumb} />
            </Switch.Root>
          </div>
        </div>
        {error && (
          <p className={styles.ko} role="alert">
            {error}
          </p>
        )}
      </li>
    </ul>
  );
}
