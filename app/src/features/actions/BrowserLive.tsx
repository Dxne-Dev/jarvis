import { useBrowserLive } from "../../lib/engine/browserLive";
import { useEngineImage } from "../../lib/engine/useEngineImage";
import styles from "./Actions.module.css";

/** La page que Jarvis manipule, en direct (#34) : lue sur le moteur de cette machine,
 * jamais ailleurs. Une nouvelle image remplace la précédente dès qu'elle arrive. */
export function BrowserLive() {
  const seq = useBrowserLive((s) => s.seq);
  const url = useBrowserLive((s) => s.url);
  const image = useEngineImage(seq === 0 ? null : "/v1/browser/live", seq);

  return (
    <figure className={styles.live} aria-label="Le navigateur de Jarvis, en direct">
      {image ? (
        <img className={styles.liveImage} src={image} alt="La page que Jarvis manipule" />
      ) : (
        <p className={styles.liveWaiting}>La page s&apos;affichera dès que Jarvis l&apos;ouvre.</p>
      )}
      {image && url && <figcaption className={styles.liveUrl}>{url}</figcaption>}
    </figure>
  );
}
