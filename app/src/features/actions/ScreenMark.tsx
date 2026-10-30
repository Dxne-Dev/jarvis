import { useEngineImage } from "../../lib/engine/useEngineImage";
import styles from "./Actions.module.css";

/** Où Jarvis va cliquer (#48) : la capture de l'écran, l'élément trouvé par SAM 3.1 et
 * choisi par Muse Spark encadré en vert, le point du clic marqué. Montrée avant ta
 * validation. */
export function ScreenMark({ id, target }: { id: string; target: string }) {
  const image = useEngineImage(`/v1/desktop/marks/${encodeURIComponent(id)}`);
  return (
    <figure className={styles.live} aria-label="Où Jarvis va cliquer">
      {image ? (
        <img className={styles.liveImage} src={image} alt={`Où Jarvis va cliquer : ${target}`} />
      ) : (
        <p className={styles.liveWaiting}>Capture de l&apos;écran en chargement…</p>
      )}
    </figure>
  );
}
