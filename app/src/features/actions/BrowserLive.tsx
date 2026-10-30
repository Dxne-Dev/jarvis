import { useEffect, useState } from "react";

import { useBrowserLive } from "../../lib/engine/browserLive";
import { useEngineStore } from "../../lib/engine/store";
import styles from "./Actions.module.css";

/** La page que Jarvis manipule, en direct (#34) : lue sur le moteur de cette machine,
 * jamais ailleurs. Une nouvelle image remplace la précédente dès qu'elle arrive. */
export function BrowserLive() {
  const client = useEngineStore((s) => s.client);
  const seq = useBrowserLive((s) => s.seq);
  const url = useBrowserLive((s) => s.url);
  const [image, setImage] = useState<string | null>(null);

  useEffect(() => {
    if (!client || seq === 0) return;
    let cancelled = false;
    void client
      .blob("/v1/browser/live")
      .then((blob) => {
        if (cancelled || !blob) return;
        const next = URL.createObjectURL(blob);
        setImage((previous) => {
          if (previous) URL.revokeObjectURL(previous);
          return next;
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true; // une image plus récente est déjà demandée
    };
  }, [client, seq]);

  useEffect(
    () => () => {
      setImage((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return null;
      });
    },
    [],
  );

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
