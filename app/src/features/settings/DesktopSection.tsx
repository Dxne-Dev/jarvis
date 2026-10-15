import { MonitorCog } from "lucide-react";

import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { describeError } from "../../lib/engine/client";
import { usePreferences, useUpdatePreferences } from "../../lib/engine/queries";
import { useEngineOnline } from "../../lib/engine/store";
import { Choice } from "./PreferenceControls";
import styles from "./SettingsScreen.module.css";

/** Contrôle du PC : désactivé par défaut ; l'activer demande une confirmation. */
export function DesktopSection() {
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const online = useEngineOnline();
  if (!online && !preferences.data)
    return <p className={styles.note}>Disponible dès que le moteur répondra.</p>;
  const enabled = preferences.data?.os_control_enabled ?? false;
  const disabled = !online || !preferences.data || update.isPending;
  return (
    <>
      <ul className={styles.secrets}>
        <li className={styles.secret}>
          <div className={styles.grantHead}>
            <MonitorCog className={styles.secretIcon} aria-hidden="true" />
            <div className={styles.secretText}>
              <p className={styles.secretLabel}>Applications, fichiers et écran</p>
              <p className={styles.secretHelp}>
                Ouvrir et fermer tes applications, déplacer, copier et créer des fichiers dans ton
                dossier personnel, regarder ton écran. Chaque action attend ta validation ; seule la
                lecture de l&apos;écran se fait sans demander.
              </p>
              <p className={styles.integrationStatus} data-tone={enabled ? "ok" : "idle"}>
                {enabled
                  ? "Activé : Jarvis peut te proposer ces actions."
                  : "Désactivé : Jarvis ne voit ni tes applications, ni tes fichiers, ni ton écran."}
              </p>
            </div>
            <div className={styles.actions}>
              {enabled ? (
                <Button
                  size="sm"
                  disabled={disabled}
                  onClick={() => {
                    update.mutate({ os_control_enabled: false });
                  }}
                >
                  Désactiver
                </Button>
              ) : (
                <ConfirmDialog
                  trigger={
                    <Button size="sm" disabled={disabled}>
                      Activer…
                    </Button>
                  }
                  title="Activer le contrôle du PC ?"
                  description="Jarvis pourra te proposer d'ouvrir ou de fermer une application, de ranger tes fichiers et de regarder ton écran. Rien ne se fait sans ta validation, sauf regarder l'écran. Tu peux le désactiver à tout moment."
                  confirmLabel="Activer"
                  onConfirm={() => {
                    update.mutate({ os_control_enabled: true });
                  }}
                />
              )}
            </div>
          </div>
          {update.isError && (
            <p className={styles.ko} role="alert">
              {describeError(update.error)}
            </p>
          )}
        </li>
      </ul>
      <Choice
        name="screen_vision"
        label="Lecture de l'écran"
        disabled={!enabled}
        options={[
          {
            value: "local",
            label: "Sur ce PC",
            hint: "Rien ne sort de ta machine. Lent : 30 s à 2 min selon l'écran.",
          },
          {
            value: "en_ligne",
            label: "En ligne",
            hint: "Rapide. La capture part chez OpenRouter ; s'il est saturé, lecture sur ce PC.",
          },
        ]}
      />
    </>
  );
}
