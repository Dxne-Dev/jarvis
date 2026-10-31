import { MonitorUp } from "lucide-react";

import { Button } from "../../components/Button";
import { describeError } from "../../lib/engine/client";
import { useScreenShare, useToggleScreenShare } from "../../lib/engine/queries";
import { useScreenLive } from "../../lib/engine/screenLive";
import { useEngineImage } from "../../lib/engine/useEngineImage";
import styles from "./ShareBanner.module.css";

/** Tant que l'écran est partagé avec Jarvis : un bandeau, l'aperçu en direct, et « Arrêter ».
 * GNOME affiche aussi son propre indicateur de partage. */
export function ShareBanner() {
  const share = useScreenShare();
  const toggle = useToggleScreenShare();
  const seq = useScreenLive((s) => s.seq);
  const active = share.data?.active ?? false;
  const image = useEngineImage(active && seq > 0 ? "/v1/desktop/share/frame" : null, seq);
  if (!active) return null;
  return (
    <div className={styles.banner} role="status">
      <MonitorUp className={styles.icon} aria-hidden="true" />
      {image && (
        <img className={styles.preview} src={image} alt="Ton écran, tel que Jarvis le voit" />
      )}
      <p className={styles.text}>
        Ton écran est partagé avec Jarvis, en direct. Rien n&apos;est enregistré ; une image ne part
        chez un modèle que quand Jarvis regarde ou cherche un élément.
      </p>
      <Button
        size="sm"
        busy={toggle.isPending}
        onClick={() => {
          toggle.mutate(false);
        }}
      >
        Arrêter le partage
      </Button>
      {toggle.isError && (
        <p className={styles.error} role="alert">
          {describeError(toggle.error)}
        </p>
      )}
    </div>
  );
}
